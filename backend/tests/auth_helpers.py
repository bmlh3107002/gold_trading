"""Keycloak giả cho test: tự sinh khóa RSA, JWKS cục bộ, token endpoint qua httpx.MockTransport.

Không cần Keycloak thật. Dùng:
    kc = FakeKeycloak()
    app = create_app(repo, auth=kc.service(), ...)
    c = client(app); kc.login(c, "alice", admin=True)
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from gold_trading.auth.config import AuthConfig
from gold_trading.auth.oidc import OidcClient
from gold_trading.auth.web import AuthService

PUBLIC_URL = "https://testserver"
INTERNAL = "http://keycloak:8080/auth/realms/gold-trading"
CLIENT_ID = "gold-trading-dashboard"
CLIENT_SECRET = "test-client-secret-0123456789"
ORIGIN = {"Origin": PUBLIC_URL}


def make_config(**kw: Any) -> AuthConfig:
    base: dict[str, Any] = dict(
        public_url=PUBLIC_URL,
        internal_issuer_url=INTERNAL,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )
    base.update(kw)
    return AuthConfig(**base)


@dataclass
class User:
    sub: str
    username: str
    roles: list[str]
    email: str | None = None
    enabled: bool = True


@dataclass
class FakeKeycloak:
    key: Any = field(default_factory=lambda: rsa.generate_private_key(65537, 2048))
    kid: str = "k1"
    users: dict[str, User] = field(default_factory=dict)
    # code -> (sub, nonce, code_challenge)
    codes: dict[str, tuple[str, str, str]] = field(default_factory=dict)
    refresh_tokens: dict[str, str] = field(default_factory=dict)  # token -> sub
    down: bool = False
    clock_offset: int = 0
    issuer: str = PUBLIC_URL + "/auth/realms/gold-trading"
    audience: str = CLIENT_ID
    token_requests: list[dict[str, str]] = field(default_factory=list)

    # --- Token ---

    def id_token(self, user: User, nonce: str | None = None, **override: Any) -> str:
        now = int(time.time()) + self.clock_offset
        claims: dict[str, Any] = {
            "iss": self.issuer,
            "aud": self.audience,
            "azp": CLIENT_ID,
            "sub": user.sub,
            "iat": now,
            "exp": now + 300,
            "preferred_username": user.username,
            "gt_roles": list(user.roles),
        }
        if user.email:
            claims["email"] = user.email
        if nonce is not None:
            claims["nonce"] = nonce
        claims.update(override)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": self.kid})

    def jwks(self) -> dict[str, Any]:
        pub = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        pub.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return {"keys": [pub]}

    def _new_refresh(self, sub: str) -> str:
        t = "rt_" + secrets.token_urlsafe(16)
        self.refresh_tokens[t] = sub
        return t

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("keycloak down", request=request)
        url = str(request.url)
        if url == INTERNAL + "/protocol/openid-connect/certs":
            return httpx.Response(200, json=self.jwks())
        if url == INTERNAL + "/protocol/openid-connect/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_requests.append(form)
            if form.get("client_secret") != CLIENT_SECRET:
                return httpx.Response(401, json={"error": "invalid_client"})
            if form["grant_type"] == "authorization_code":
                entry = self.codes.pop(form.get("code", ""), None)
                if entry is None:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                sub, nonce, challenge = entry
                import base64
                import hashlib

                expect = base64.urlsafe_b64encode(
                    hashlib.sha256(form.get("code_verifier", "").encode()).digest()
                ).rstrip(b"=").decode()
                if expect != challenge:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                user = self.users[sub]
                return httpx.Response(200, json={
                    "id_token": self.id_token(user, nonce),
                    "refresh_token": self._new_refresh(sub),
                })
            if form["grant_type"] == "refresh_token":
                sub = self.refresh_tokens.pop(form.get("refresh_token", ""), None)
                if sub is None or not self.users[sub].enabled:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                user = self.users[sub]
                return httpx.Response(200, json={
                    "id_token": self.id_token(user),
                    "refresh_token": self._new_refresh(sub),
                })
        return httpx.Response(404)

    # --- Dựng service ---

    def oidc(self, config: AuthConfig) -> OidcClient:
        return OidcClient(config, httpx.Client(transport=httpx.MockTransport(self.handler)))

    def service(self, audit=None, **cfg: Any) -> AuthService:
        config = make_config(**cfg)
        return AuthService(config, self.oidc(config), audit=audit or (lambda *a: None))

    def app_kwargs(self, **cfg: Any) -> dict[str, Any]:
        """Tham số cho create_app: cấu hình đăng nhập test + OIDC client nối vào Keycloak giả."""
        config = make_config(**cfg)
        return {"auth": config, "oidc": self.oidc(config)}

    def add_user(self, username: str, *, admin: bool = False, email: str | None = None) -> User:
        sub = f"sub-{username}"
        u = User(sub, username, ["ADMIN"] if admin else [], email or f"{username}@example.com")
        self.users[sub] = u
        return u

    # --- Đăng nhập qua luồng thật (login → Keycloak → callback) ---

    def start_login(self, c: TestClient, next_path: str = "/") -> dict[str, str]:
        r = c.get("/api/auth/login", params={"next": next_path}, follow_redirects=False)
        assert r.status_code == 302, r.text
        q = {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}
        return q

    def login(self, c: TestClient, username: str, *, admin: bool = False) -> User:
        user = next((u for u in self.users.values() if u.username == username), None)
        if user is None:
            user = self.add_user(username, admin=admin)
        q = self.start_login(c)
        code = "code_" + secrets.token_urlsafe(8)
        self.codes[code] = (user.sub, q["nonce"], q["code_challenge"])
        r = c.get(
            "/api/auth/callback", params={"code": code, "state": q["state"]},
            follow_redirects=False,
        )
        assert r.status_code == 302 and "auth_error" not in r.headers["location"], r.headers
        return user


def client(app) -> TestClient:
    """Client HTTPS (cookie Secure chỉ gửi qua https), mặc định gửi Origin hợp lệ."""
    return TestClient(app, base_url=PUBLIC_URL, headers=ORIGIN)


def make_app(repo=None, kc: FakeKeycloak | None = None, **kw: Any):
    """create_app với Keycloak giả. Trả (app, kc)."""
    from gold_trading.api.app import create_app
    from gold_trading.storage.repository import InMemoryRepository

    kc = kc or FakeKeycloak()
    cfg = kw.pop("auth_cfg", {})
    return create_app(repo or InMemoryRepository(), **kc.app_kwargs(**cfg), **kw), kc


def admin_client(repo=None, username: str = "admin", **kw: Any) -> TestClient:
    """Client đã đăng nhập bằng người dùng ADMIN."""
    app, kc = make_app(repo, **kw)
    c = client(app)
    kc.login(c, username, admin=True)
    c.kc = kc  # type: ignore[attr-defined]
    return c
