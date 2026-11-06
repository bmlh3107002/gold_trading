"""Đăng nhập BFF trên FastAPI: /api/auth/*, kiểm tra phiên cho MỌI route, chống CSRF.

Mọi route mặc định bắt buộc đăng nhập (dependency toàn cục). Ngoại lệ duy nhất là
``PUBLIC_PATHS`` + cổng Gateway (``PUBLIC_PREFIXES``, xác thực bằng token riêng).
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from gold_trading.auth.config import AuthConfig
from gold_trading.auth.oidc import (
    ClockSkewError,
    InvalidGrant,
    OidcClient,
    OidcError,
    ProviderUnavailable,
    new_state,
    pkce_pair,
    roles_from_claims,
)
from gold_trading.auth.sessions import Session, SessionStore
from gold_trading.common.time import utcnow

log = logging.getLogger("gold_trading.auth")

SESSION_COOKIE = "__Host-gt_session"
LOGIN_COOKIE = "__Host-gt_login"
PUBLIC_PATHS = frozenset(
    {"/api/health", "/api/auth/login", "/api/auth/callback", "/api/auth/logout"}
)
PUBLIC_PREFIXES = ("/api/ingest/mt5/",)
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Mã lỗi đăng nhập hiển thị trên giao diện (không đưa chi tiết kỹ thuật ra URL).
AUTH_ERRORS = ("denied", "state", "expired", "clock", "unavailable", "invalid", "locked")


@dataclass(frozen=True)
class Principal:
    """Người đang đăng nhập, lấy từ phiên đã xác thực (không bao giờ từ body request)."""

    sub: str
    username: str
    email: str | None
    display_name: str | None
    is_admin: bool


class Me(BaseModel):
    sub: str
    username: str
    email: str | None
    display_name: str | None
    is_admin: bool
    session_expires_at: datetime
    idle_timeout_seconds: int


class LogoutResult(BaseModel):
    logout_url: str


AuditFn = Callable[[str, str | None, str, str, dict[str, Any], str | None], None]
LoginHook = Callable[[Principal], None]
# DEC-16: True = người dùng bị ADMIN khóa (đọc DB mỗi request). Lỗi đọc DB → ném lỗi (chặn).
LockedFn = Callable[[str], bool]


def is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES)


def safe_next(raw: str | None) -> str:
    """Chỉ cho đường dẫn tương đối trong cùng site (chống open redirect)."""
    if not raw or not raw.startswith("/") or raw.startswith("//") or "\\" in raw:
        return "/"
    if any(ord(c) < 0x20 for c in raw):
        return "/"
    return raw


class AuthService:
    def __init__(
        self,
        config: AuthConfig,
        oidc: OidcClient,
        *,
        audit: AuditFn,
        on_login: LoginHook | None = None,
        is_locked: LockedFn | None = None,
        store: SessionStore | None = None,
    ) -> None:
        self.config = config
        self.oidc = oidc
        self.store = store or SessionStore(max_age=config.session_max, idle=config.session_idle)
        self._audit = audit
        self._on_login = on_login
        self._is_locked = is_locked

    # --- Kiểm tra mỗi request ---

    def check_origin(self, request: Request) -> None:
        if request.method not in UNSAFE_METHODS:
            return
        origin = request.headers.get("origin")
        if origin is None or origin.rstrip("/") not in self.config.allowed_origins:
            self._audit(
                "anonymous", None, "access.csrf_blocked", "REJECTED",
                {"path": request.url.path, "origin": (origin or "")[:200]}, "Origin không hợp lệ",
            )
            raise HTTPException(403, "Origin không hợp lệ")

    def authenticate(self, request: Request) -> Principal:
        now = utcnow()
        session = self.store.get(request.cookies.get(SESSION_COOKIE), now)
        if session is None:
            raise HTTPException(401, "Chưa đăng nhập hoặc phiên đã hết hạn")
        if self._is_locked and self._is_locked(session.sub):
            # Khóa có hiệu lực ở request kế tiếp, không chờ Keycloak.
            self._revoke(session, "tài khoản bị khóa")
        self._maybe_refresh(session, now)
        return Principal(
            sub=session.sub,
            username=session.username,
            email=session.email,
            display_name=session.display_name,
            is_admin=session.is_admin,
        )

    def _maybe_refresh(self, s: Session, now: datetime) -> None:
        if now - s.last_refresh < self.config.refresh_interval:
            return
        with s.lock:  # Một lần làm mới mỗi phiên: refresh token chỉ dùng được một lần.
            if now - s.last_refresh < self.config.refresh_interval:
                return
            if not s.refresh_token:
                self._revoke(s, "không có refresh token")
            try:
                ts = self.oidc.refresh(s.refresh_token or "", expected_sub=s.sub)
            except ProviderUnavailable as e:
                # 0-C11: Keycloak chết → giữ phiên tới hết hạn của chính nó, thử lại sau.
                log.warning("Không làm mới được phiên với Keycloak: %s", e)
                s.last_refresh = now - self.config.refresh_interval / 2
                return
            except OidcError as e:
                # 0-C12: bị vô hiệu hóa / phiên bị thu hồi / token sai → kết thúc phiên.
                self._revoke(s, type(e).__name__)
            s.refresh_token = ts.refresh_token
            s.id_token = ts.id_token
            s.roles = roles_from_claims(ts.claims)
            s.last_refresh = now

    def _revoke(self, s: Session, reason: str) -> None:
        self.store.delete_session(s)
        self._audit(s.username, s.sub, "auth.session_revoked", "ACCEPTED", {}, reason)
        raise HTTPException(401, "Phiên đã bị thu hồi, vui lòng đăng nhập lại")

    # --- Cookie ---

    def _set_cookie(self, resp, name: str, value: str, *, max_age: int, samesite: str) -> None:
        resp.set_cookie(
            name, value, max_age=max_age, path="/", secure=True, httponly=True, samesite=samesite
        )

    def _clear_cookie(self, resp, name: str, samesite: str) -> None:
        resp.delete_cookie(name, path="/", secure=True, httponly=True, samesite=samesite)

    def _fail(self, code: str, detail: str) -> RedirectResponse:
        assert code in AUTH_ERRORS
        self._audit("anonymous", None, "auth.login", "REJECTED", {"reason": code}, detail)
        resp = RedirectResponse(f"/?auth_error={code}", status_code=302)
        self._clear_cookie(resp, LOGIN_COOKIE, "lax")
        return resp

    # --- Router ---

    def router(self) -> APIRouter:
        r = APIRouter(prefix="/api/auth", tags=["auth"])

        @r.get("/login", include_in_schema=False)
        def login(next: str | None = None) -> RedirectResponse:  # noqa: A002
            now = utcnow()
            state, nonce = new_state(), new_state()
            verifier, challenge = pkce_pair()
            self.store.put_login(
                state, code_verifier=verifier, nonce=nonce, next_path=safe_next(next), now=now
            )
            resp = RedirectResponse(
                self.oidc.authorize_url(state=state, nonce=nonce, code_challenge=challenge),
                status_code=302,
            )
            self._set_cookie(resp, LOGIN_COOKIE, state, max_age=600, samesite="lax")
            return resp

        @r.get("/callback", include_in_schema=False)
        def callback(
            request: Request,
            code: str | None = None,
            state: str | None = None,
            error: str | None = None,
        ) -> RedirectResponse:
            now = utcnow()
            if error:
                return self._fail("denied", f"Keycloak trả lỗi: {error[:64]}")
            cookie_state = request.cookies.get(LOGIN_COOKIE)
            if (
                not code
                or not state
                or not cookie_state
                or not secrets.compare_digest(state, cookie_state)
            ):
                return self._fail("state", "state thiếu hoặc không khớp cookie")
            tx = self.store.pop_login(state, now)
            if tx is None:
                return self._fail("expired", "Giao dịch đăng nhập hết hạn hoặc đã dùng")
            try:
                ts = self.oidc.exchange_code(code=code, code_verifier=tx.code_verifier,
                                             nonce=tx.nonce)
            except ClockSkewError as e:
                return self._fail("clock", str(e)[:200])
            except ProviderUnavailable as e:
                return self._fail("unavailable", str(e)[:200])
            except (InvalidGrant, OidcError) as e:
                return self._fail("invalid", f"{type(e).__name__}: {str(e)[:150]}")
            c = ts.claims
            username = str(c.get("preferred_username") or c["sub"])[:128]
            session = Session(
                sub=str(c["sub"]),
                username=username,
                email=(str(c["email"])[:256] if c.get("email") else None),
                display_name=(str(c["name"])[:256] if c.get("name") else None),
                roles=roles_from_claims(c),
                created_at=now,
                last_seen=now,
                last_refresh=now,
                refresh_token=ts.refresh_token,
                id_token=ts.id_token,
            )
            principal = Principal(session.sub, session.username, session.email,
                                  session.display_name, session.is_admin)
            if self._on_login:
                self._on_login(principal)
            if self._is_locked and self._is_locked(session.sub):
                return self._fail("locked", f"Tài khoản bị khóa: {username}")
            raw = self.store.create(session)
            self._audit(username, session.sub, "auth.login", "ACCEPTED",
                        {"admin": session.is_admin}, None)
            resp = RedirectResponse(tx.next_path, status_code=302)
            self._set_cookie(
                resp, SESSION_COOKIE, raw,
                max_age=int(self.config.session_max.total_seconds()), samesite="strict",
            )
            self._clear_cookie(resp, LOGIN_COOKIE, "lax")
            return resp

        @r.get("/me", response_model=Me)
        def me(request: Request) -> Me:
            p: Principal = request.state.principal
            s = self.store.get(request.cookies.get(SESSION_COOKIE), utcnow())
            assert s is not None
            return Me(
                sub=p.sub,
                username=p.username,
                email=p.email,
                display_name=p.display_name,
                is_admin=p.is_admin,
                session_expires_at=s.created_at + self.config.session_max,
                idle_timeout_seconds=int(self.config.session_idle.total_seconds()),
            )

        @r.post("/logout", response_model=LogoutResult)
        def logout(request: Request):
            self.check_origin(request)
            s = self.store.delete(request.cookies.get(SESSION_COOKIE))
            if s is not None:
                self._audit(s.username, s.sub, "auth.logout", "ACCEPTED", {}, None)
            body = LogoutResult(logout_url=self.oidc.end_session_url(s.id_token if s else None))
            from fastapi.responses import JSONResponse

            resp = JSONResponse(body.model_dump())
            self._clear_cookie(resp, SESSION_COOKIE, "strict")
            return resp

        return r

    def dependency(self) -> Callable[[Request], None]:
        """Dependency toàn cục: mọi route (trừ PUBLIC) phải có phiên; route ghi phải đúng Origin."""

        def require(request: Request) -> None:
            if is_public(request.url.path):
                return
            request.state.principal = self.authenticate(request)
            self.check_origin(request)

        return require


def principal(request: Request) -> Principal:
    """Dùng trong endpoint: ``p: Principal = Depends(principal)``."""
    p = getattr(request.state, "principal", None)
    if p is None:  # Không bao giờ xảy ra nếu dependency toàn cục đã chạy.
        raise HTTPException(401, "Chưa đăng nhập")
    return p


CurrentUser = Annotated[Principal, Depends(principal)]
