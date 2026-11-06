"""OIDC client cho BFF: tạo URL đăng nhập, đổi code lấy token, làm mới, xác minh ID token.

- Đổi code và làm mới đi qua mạng nội bộ tới Keycloak (``internal_issuer_url``).
- ID token được xác minh chữ ký (JWKS, RS256), ``iss``, ``aud``, ``azp``, ``nonce``, thời hạn
  với độ lệch đồng hồ cho phép ``clock_leeway_s`` giây.
- Phân biệt rõ: Keycloak từ chối (``InvalidGrant`` → hủy phiên) và Keycloak không truy cập được
  (``ProviderUnavailable`` → giữ phiên tới hết hạn của chính nó).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from gold_trading.auth.config import AuthConfig

log = logging.getLogger("gold_trading.auth")

ALGORITHMS = ["RS256"]
JWKS_MIN_REFRESH_S = 30.0


class OidcError(Exception):
    """Lỗi xác thực: không tin được kết quả đăng nhập."""


class InvalidGrant(OidcError):
    """Keycloak từ chối code/refresh token (người dùng bị vô hiệu hóa, phiên bị thu hồi...)."""


class ProviderUnavailable(OidcError):
    """Không kết nối được Keycloak hoặc Keycloak lỗi 5xx."""


class ClockSkewError(OidcError):
    """Token chưa có hiệu lực / đã hết hạn quá độ lệch cho phép: có thể do đồng hồ lệch."""


@dataclass(frozen=True)
class TokenSet:
    id_token: str = field(repr=False)
    refresh_token: str | None = field(repr=False)
    claims: dict[str, Any] = field(repr=False)


def new_state() -> str:
    return secrets.token_urlsafe(32)


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


class OidcClient:
    def __init__(self, config: AuthConfig, http: httpx.Client | None = None) -> None:
        self.config = config
        self._http = http or httpx.Client(timeout=5.0)
        self._jwks: dict[str, Any] = {}
        self._jwks_fetched_at = 0.0
        self._lock = threading.Lock()

    # --- URL ---

    def authorize_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        q = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.config.authorize_endpoint}?{urlencode(q)}"

    def end_session_url(self, id_token: str | None) -> str:
        q = {
            "client_id": self.config.client_id,
            "post_logout_redirect_uri": f"{self.config.origin}/",
        }
        if id_token:
            q["id_token_hint"] = id_token
        return f"{self.config.end_session_endpoint}?{urlencode(q)}"

    # --- Token endpoint ---

    def _token_request(self, data: dict[str, str]) -> dict[str, Any]:
        data = {
            **data,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
        }
        try:
            resp = self._http.post(self.config.token_endpoint, data=data)
        except httpx.HTTPError as e:
            raise ProviderUnavailable(f"Không kết nối được Keycloak: {type(e).__name__}") from e
        if resp.status_code >= 500:
            raise ProviderUnavailable(f"Keycloak lỗi {resp.status_code}")
        try:
            body = resp.json()
        except ValueError as e:
            raise ProviderUnavailable("Keycloak trả về dữ liệu không phải JSON") from e
        if resp.status_code != 200:
            # Không ghi chi tiết body (có thể chứa thông tin nhạy cảm), chỉ mã lỗi chuẩn OAuth.
            err = str(body.get("error", "unknown")) if isinstance(body, dict) else "unknown"
            if err in ("invalid_grant", "unauthorized_client", "invalid_client"):
                raise InvalidGrant(err)
            raise OidcError(f"Token endpoint từ chối: {err}")
        if not isinstance(body, dict) or "id_token" not in body:
            raise OidcError("Thiếu id_token trong phản hồi")
        return body

    def exchange_code(self, *, code: str, code_verifier: str, nonce: str) -> TokenSet:
        body = self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.config.redirect_uri,
                "code_verifier": code_verifier,
            }
        )
        claims = self.verify_id_token(body["id_token"], nonce=nonce)
        return TokenSet(body["id_token"], body.get("refresh_token"), claims)

    def refresh(self, refresh_token: str, *, expected_sub: str) -> TokenSet:
        body = self._token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token, "scope": "openid"}
        )
        claims = self.verify_id_token(body["id_token"], nonce=None)
        if claims.get("sub") != expected_sub:
            raise InvalidGrant("sub thay đổi khi làm mới")
        return TokenSet(body["id_token"], body.get("refresh_token", refresh_token), claims)

    # --- Xác minh ID token ---

    def _fetch_jwks(self, force: bool) -> None:
        with self._lock:
            now = time.monotonic()
            if self._jwks and not force:
                return
            if force and now - self._jwks_fetched_at < JWKS_MIN_REFRESH_S and self._jwks:
                return  # Chống bị ép tải JWKS liên tục bằng kid lạ.
            try:
                resp = self._http.get(self.config.jwks_endpoint)
                resp.raise_for_status()
                keys = resp.json().get("keys", [])
            except (httpx.HTTPError, ValueError) as e:
                raise ProviderUnavailable(f"Không tải được JWKS: {type(e).__name__}") from e
            self._jwks = {
                k["kid"]: k
                for k in keys
                if k.get("kid") and k.get("kty") == "RSA" and k.get("use", "sig") == "sig"
            }
            self._jwks_fetched_at = now

    def _key_for(self, kid: str | None):
        if not kid:
            raise OidcError("Token thiếu kid")
        self._fetch_jwks(force=False)
        if kid not in self._jwks:
            self._fetch_jwks(force=True)
        jwk = self._jwks.get(kid)
        if jwk is None:
            raise OidcError("Không tìm thấy khóa ký của token")
        return jwt.PyJWK(jwk).key

    def verify_id_token(self, token: str, *, nonce: str | None) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as e:
            raise OidcError("ID token không đúng định dạng") from e
        if header.get("alg") not in ALGORITHMS:
            raise OidcError("Thuật toán ký không được phép")
        key = self._key_for(header.get("kid"))
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=ALGORITHMS,
                audience=self.config.client_id,
                issuer=self.config.issuer,
                leeway=self.config.clock_leeway_s,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except (jwt.ExpiredSignatureError, jwt.ImmatureSignatureError) as e:
            log.warning("ID token ngoài thời hạn (độ lệch > %ss): kiểm tra đồng hồ máy chủ",
                        self.config.clock_leeway_s)
            raise ClockSkewError(str(e)) from e
        except jwt.PyJWTError as e:
            raise OidcError(f"ID token không hợp lệ: {type(e).__name__}") from e
        iat = claims.get("iat")
        if isinstance(iat, (int, float)) and iat > time.time() + self.config.clock_leeway_s:
            log.warning("ID token phát hành trong tương lai: đồng hồ máy chủ có thể lệch")
            raise ClockSkewError("iat ở tương lai")
        azp = claims.get("azp")
        if azp is not None and azp != self.config.client_id:
            raise OidcError("azp không khớp client")
        if nonce is not None and not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise OidcError("nonce không khớp")
        return claims


def roles_from_claims(claims: dict[str, Any]) -> frozenset[str]:
    raw = claims.get("gt_roles", [])
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(r for r in raw if isinstance(r, str))
