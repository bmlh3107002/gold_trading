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
from gold_trading.auth.kc_admin import KeycloakAdmin
from gold_trading.auth.oidc import OidcClient
from gold_trading.auth.web import AuthService

PUBLIC_URL = "https://testserver"
INTERNAL = "http://keycloak:8080/auth/realms/gold-trading"
ADMIN_API = "http://keycloak:8080/auth/admin/realms/gold-trading"
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
    first_name: str = ""
    last_name: str = ""
    attributes: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class FakeKeycloak:
    key: Any = field(default_factory=lambda: rsa.generate_private_key(65537, 2048))
    kid: str = "k1"
    users: dict[str, User] = field(default_factory=dict)
    # code -> (sub, nonce, code_challenge)
    codes: dict[str, tuple[str, str, str]] = field(default_factory=dict)
    refresh_tokens: dict[str, str] = field(default_factory=dict)  # token -> sub
    # Admin API (MT-20): bật service account chưa, mật khẩu đã đặt, lượt gọi admin
    service_account: bool = True
    passwords: dict[str, tuple[str, bool]] = field(default_factory=dict)  # sub -> (pw, temporary)
    admin_requests: list[tuple[str, str]] = field(default_factory=list)
    admin_tokens: set[str] = field(default_factory=set)
    fail_admin_create: int | None = None  # ép mã lỗi khi tạo người dùng
    fail_admin_ops: int | None = None  # ép mã lỗi cho bật/tắt, đăng xuất, đặt lại mật khẩu
    logouts: list[str] = field(default_factory=list)
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
            if form["grant_type"] == "client_credentials":
                if not self.service_account:
                    return httpx.Response(400, json={"error": "unauthorized_client"})
                if "kc-admin-api" not in form.get("scope", "").split():
                    return httpx.Response(200, json={"access_token": "no-admin-aud"})
                t = "at_" + secrets.token_urlsafe(16)
                self.admin_tokens.add(t)
                return httpx.Response(200, json={"access_token": t, "token_type": "Bearer"})
            if form["grant_type"] == "refresh_token":
                sub = self.refresh_tokens.pop(form.get("refresh_token", ""), None)
                if sub is None or not self.users[sub].enabled:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                user = self.users[sub]
                return httpx.Response(200, json={
                    "id_token": self.id_token(user),
                    "refresh_token": self._new_refresh(sub),
                })
        if url.startswith(ADMIN_API + "/users"):
            return self._admin(request, url)
        return httpx.Response(404)

    def _admin(self, request: httpx.Request, url: str) -> httpx.Response:
        self.admin_requests.append((request.method, url))
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] not in self.admin_tokens:
            return httpx.Response(401)
        if request.method == "POST" and url == ADMIN_API + "/users":
            if self.fail_admin_create:
                return httpx.Response(self.fail_admin_create, json={"errorMessage": "forced"})
            body = json.loads(request.content)
            name = body["username"]
            if any(u.username == name or (u.email and u.email == body.get("email"))
                   for u in self.users.values()):
                return httpx.Response(409, json={"errorMessage": "User exists"})
            cred = body["credentials"][0]
            if len(cred["value"]) < 12:
                return httpx.Response(400, json={"error": "invalidPasswordMinLengthMessage",
                                                 "errorMessage": "Invalid password: min length."})
            sub = "kc-" + secrets.token_hex(8)
            self.users[sub] = User(sub, name, [], body.get("email"))
            self.passwords[sub] = (cred["value"], bool(cred["temporary"]))
            return httpx.Response(201, headers={"Location": f"{ADMIN_API}/users/{sub}"})
        rest = url[len(ADMIN_API + "/users/"):].split("/")
        sub = rest[0]
        if request.method in ("PUT", "POST") and self.fail_admin_ops:
            return httpx.Response(self.fail_admin_ops, json={"errorMessage": "forced"})
        if request.method == "GET" and len(rest) == 1:
            u = self.users.get(sub)
            if u is None:
                return httpx.Response(404)
            return httpx.Response(200, json={
                "id": u.sub, "username": u.username, "email": u.email, "enabled": u.enabled,
                "firstName": u.first_name, "lastName": u.last_name, "attributes": u.attributes})
        if request.method == "PUT" and len(rest) == 1:
            if sub not in self.users:
                return httpx.Response(404)
            body = json.loads(request.content)
            u = self.users[sub]
            if set(body) == {"enabled"}:
                u.enabled = bool(body["enabled"])
                return httpx.Response(204)
            # Sửa hồ sơ (DEC-17): giống Keycloak ≥ 24, thuộc tính không gửi kèm bị mất
            if "credentials" in body or body.get("username") != u.username:
                return httpx.Response(400, json={"errorMessage": "unexpected fields"})
            if any(o.sub != sub and o.email and o.email == body.get("email")
                   for o in self.users.values()):
                return httpx.Response(409, json={"errorMessage": "User exists with same email"})
            u.email = body.get("email")
            u.first_name = body.get("firstName") or ""
            u.last_name = body.get("lastName") or ""
            u.attributes = body.get("attributes") or {}
            u.enabled = bool(body.get("enabled", u.enabled))
            return httpx.Response(204)
        if request.method == "POST" and rest[1:] == ["logout"]:
            if sub not in self.users:
                return httpx.Response(404)
            self.logouts.append(sub)
            for t, s in list(self.refresh_tokens.items()):
                if s == sub:
                    del self.refresh_tokens[t]
            return httpx.Response(204)
        if request.method == "PUT" and rest[1:] == ["reset-password"]:
            if sub not in self.users:
                return httpx.Response(404)
            body = json.loads(request.content)
            if len(body["value"]) < 12:
                return httpx.Response(400, json={"errorMessage": "Invalid password: min length."})
            self.passwords[sub] = (body["value"], bool(body["temporary"]))
            return httpx.Response(204)
        if request.method == "DELETE":
            sub = url.rsplit("/", 1)[-1]
            if self.users.pop(sub, None) is None:
                return httpx.Response(404)
            self.passwords.pop(sub, None)
            return httpx.Response(204)
        return httpx.Response(405)

    # --- Dựng service ---

    def oidc(self, config: AuthConfig) -> OidcClient:
        return OidcClient(config, httpx.Client(transport=httpx.MockTransport(self.handler)))

    def service(self, audit=None, **cfg: Any) -> AuthService:
        config = make_config(**cfg)
        return AuthService(config, self.oidc(config), audit=audit or (lambda *a: None))

    def app_kwargs(self, **cfg: Any) -> dict[str, Any]:
        """Tham số cho create_app: cấu hình đăng nhập test + OIDC client nối vào Keycloak giả."""
        config = make_config(**cfg)
        http = httpx.Client(transport=httpx.MockTransport(self.handler))
        return {"auth": config, "oidc": self.oidc(config), "kc_admin": KeycloakAdmin(config, http)}

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


def login_owner(app, kc: FakeKeycloak, repo, username: str = "trader",
                account: str = "default") -> TestClient:
    """DEC-16: USER đăng nhập + là chủ ``account`` (thay cho admin-làm-chủ trước đây)."""
    from gold_trading.common.time import utcnow
    from gold_trading.storage.repository import Member

    c = client(app)
    u = kc.login(c, username)
    if repo.account(account) is None:
        from gold_trading.storage.repository import TradingAccount

        repo.create_account(TradingAccount(account, account, utcnow(), "test", price_feed=False))
        app.state.registry.add(account)
    repo.set_member(Member(account, u.sub, "OWNER", utcnow(), "test"))
    c.kc = kc  # type: ignore[attr-defined]
    c.sub = u.sub  # type: ignore[attr-defined]
    return c


def user_client(repo=None, username: str = "trader", **kw: Any) -> TestClient:
    """Client đã đăng nhập bằng USER là chủ tài khoản ``default``."""
    from gold_trading.storage.repository import InMemoryRepository

    repo = repo if repo is not None else InMemoryRepository()
    app, kc = make_app(repo, **kw)
    return login_owner(app, kc, repo, username)


def admin_client(repo=None, username: str = "admin", **kw: Any) -> TestClient:
    """Client đã đăng nhập bằng người dùng ADMIN."""
    app, kc = make_app(repo, **kw)
    c = client(app)
    kc.login(c, username, admin=True)
    c.kc = kc  # type: ignore[attr-defined]
    return c
