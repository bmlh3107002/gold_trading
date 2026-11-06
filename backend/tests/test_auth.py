"""OPS-07: đăng nhập BFF (Keycloak giả). Case 0-C08, 0-C11, 0-C12, 0-C14, 0-C17."""

from __future__ import annotations

from datetime import timedelta
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from gold_trading.auth import web
from gold_trading.auth.config import AuthConfig, AuthConfigError
from gold_trading.auth.web import SESSION_COOKIE, is_public, safe_next
from gold_trading.common.time import utcnow
from gold_trading.storage.repository import InMemoryRepository
from tests.auth_helpers import (
    CLIENT_SECRET,
    INTERNAL,
    PUBLIC_URL,
    FakeKeycloak,
    client,
    make_app,
    make_config,
)


def setup(**kw):
    repo = InMemoryRepository()
    app, kc = make_app(repo, **kw)
    return app, kc, repo, client(app)


def audit_actions(repo):
    return [(e.action, e.outcome) for e in repo.audit(500)]


def set_cookie_headers(r):
    return [v for k, v in r.headers.multi_items() if k.lower() == "set-cookie"]


# ---------- Mọi route bắt buộc đăng nhập ----------


def test_every_non_public_route_requires_session():
    """Duyệt MỌI route trong OpenAPI (gồm router được include): không có phiên → 401."""
    app, _, _, _ = setup()
    anon = TestClient(app, base_url=PUBLIC_URL)
    checked = 0
    for path, ops in app.openapi()["paths"].items():
        if is_public(path):
            continue
        concrete = path
        for name in ("account_id", "user_sub", "request_id"):
            concrete = concrete.replace("{" + name + "}", "x")
        assert "{" not in concrete, f"tham số đường dẫn chưa xử lý: {path}"
        for method in ops:
            r = anon.request(method.upper(), concrete, json={}, headers={"Origin": PUBLIC_URL})
            assert r.status_code == 401, (method, path, r.status_code)
            checked += 1
    assert checked >= 10
    assert "/api/market/candles" in app.openapi()["paths"]


def test_public_paths_are_exactly_the_allowed_ones():
    assert web.PUBLIC_PATHS == {
        "/api/health", "/api/auth/login", "/api/auth/callback", "/api/auth/logout"
    }
    assert web.PUBLIC_PREFIXES == ("/api/ingest/mt5/",)
    assert not is_public("/api/ingest/other")
    assert not is_public("/api/auth/me")


def test_forged_cookie_is_rejected():
    _, _, _, c = setup()
    c.cookies.set(SESSION_COOKIE, "x" * 43)
    assert c.get("/api/auth/me").status_code == 401


# ---------- Luồng đăng nhập ----------


def test_login_redirect_has_pkce_state_nonce():
    _, kc, _, c = setup()
    r = c.get("/api/auth/login", params={"next": "/#market"}, follow_redirects=False)
    assert r.status_code == 302
    loc = urlsplit(r.headers["location"])
    assert f"{loc.scheme}://{loc.netloc}{loc.path}" == (
        PUBLIC_URL + "/auth/realms/gold-trading/protocol/openid-connect/auth"
    )
    q = {k: v[0] for k, v in parse_qs(loc.query).items()}
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) >= 43
    assert q["redirect_uri"] == PUBLIC_URL + "/api/auth/callback"
    assert len(q["state"]) >= 40 and len(q["nonce"]) >= 40
    (cookie,) = set_cookie_headers(r)
    assert cookie.startswith("__Host-gt_login=")
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    assert "Path=/" in cookie


def test_full_login_sets_strict_session_cookie_and_me():
    _, kc, repo, c = setup()
    user = kc.add_user("alice", admin=True)
    q = kc.start_login(c, "/#market")
    kc.codes["c1"] = (user.sub, q["nonce"], q["code_challenge"])
    r = c.get("/api/auth/callback", params={"code": "c1", "state": q["state"]},
              follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/#market"
    session_cookie = next(h for h in set_cookie_headers(r) if h.startswith(SESSION_COOKIE))
    morsel = SimpleCookie(session_cookie)[SESSION_COOKIE]
    assert morsel["httponly"] and morsel["secure"] and morsel["path"] == "/"
    assert morsel["samesite"].lower() == "strict"
    assert len(morsel.value) >= 40
    # Code được đổi kèm client secret và code_verifier
    form = kc.token_requests[-1]
    assert form["client_secret"] == CLIENT_SECRET and form["code_verifier"]
    me = c.get("/api/auth/me").json()
    assert me["username"] == "alice" and me["is_admin"] is True and me["sub"] == user.sub
    assert me["idle_timeout_seconds"] == 1800
    assert ("auth.login", "ACCEPTED") in audit_actions(repo)


def test_callback_state_mismatch_creates_no_session():
    _, kc, repo, c = setup()
    user = kc.add_user("bob")
    q = kc.start_login(c)
    kc.codes["c1"] = (user.sub, q["nonce"], q["code_challenge"])
    r = c.get("/api/auth/callback", params={"code": "c1", "state": "attacker"},
              follow_redirects=False)
    assert r.headers["location"] == "/?auth_error=state"
    assert c.get("/api/auth/me").status_code == 401
    assert ("auth.login", "REJECTED") in audit_actions(repo)


def test_callback_without_login_cookie_is_rejected():
    """Kẻ tấn công gửi link callback có state hợp lệ của chính hắn cho nạn nhân (login CSRF)."""
    app, kc, _, attacker = setup()
    user = kc.add_user("mallory")
    q = kc.start_login(attacker)
    kc.codes["c1"] = (user.sub, q["nonce"], q["code_challenge"])
    victim = client(app)
    r = victim.get("/api/auth/callback", params={"code": "c1", "state": q["state"]},
                   follow_redirects=False)
    assert r.headers["location"] == "/?auth_error=state"
    assert victim.get("/api/auth/me").status_code == 401


def test_state_cannot_be_replayed():
    _, kc, _, c = setup()
    user = kc.add_user("carol")
    q = kc.start_login(c)
    kc.codes["c1"] = (user.sub, q["nonce"], q["code_challenge"])
    c.get("/api/auth/callback", params={"code": "c1", "state": q["state"]},
          follow_redirects=False)
    c.cookies.set("__Host-gt_login", q["state"])
    r = c.get("/api/auth/callback", params={"code": "c1", "state": q["state"]},
              follow_redirects=False)
    assert r.headers["location"] == "/?auth_error=expired"


def test_keycloak_error_param_is_denied():
    _, _, _, c = setup()
    r = c.get("/api/auth/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert r.headers["location"] == "/?auth_error=denied"


def _callback_with(kc: FakeKeycloak, c, token_override=None, **id_claims):
    """Đăng nhập nhưng Keycloak giả trả ID token đã chỉnh sửa."""
    user = kc.add_user("eve")
    q = kc.start_login(c)
    kc.codes["c1"] = (user.sub, q["nonce"], q["code_challenge"])
    orig = kc.id_token

    def patched(u, nonce=None, **o):
        if token_override:
            return token_override(u, nonce)
        merged = {**o, **id_claims}
        return orig(u, merged.pop("nonce", nonce), **merged)

    kc.id_token = patched  # type: ignore[method-assign]
    r = c.get("/api/auth/callback", params={"code": "c1", "state": q["state"]},
              follow_redirects=False)
    kc.id_token = orig  # type: ignore[method-assign]
    return r.headers["location"]


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://evil.example/auth/realms/gold-trading"},
        {"aud": "other-client"},
        {"azp": "other-client"},
        {"nonce": "wrong-nonce"},
    ],
)
def test_invalid_id_token_claims_rejected(claims):
    _, kc, _, c = setup()
    assert _callback_with(kc, c, **claims) == "/?auth_error=invalid"
    assert c.get("/api/auth/me").status_code == 401


def test_token_signed_by_other_key_rejected():
    _, kc, _, c = setup()
    other = FakeKeycloak()

    def forged(u, nonce):
        return other.id_token(u, nonce)  # cùng kid "k1" nhưng khóa khác

    assert _callback_with(kc, c, token_override=forged) == "/?auth_error=invalid"


def test_alg_none_rejected():
    import jwt as pyjwt

    _, kc, _, c = setup()

    def none_alg(u, nonce):
        return pyjwt.encode({"sub": u.sub, "nonce": nonce}, None, algorithm="none",
                            headers={"kid": "k1"})

    assert _callback_with(kc, c, token_override=none_alg) == "/?auth_error=invalid"


def test_clock_skew_within_leeway_accepted_beyond_rejected():
    """0-C17: lệch ≤ 5 giây vẫn chấp nhận; quá thì từ chối và báo lỗi đồng hồ."""
    _, kc, _, c = setup()
    kc.clock_offset = 4  # Keycloak nhanh hơn 4 giây: iat ở tương lai 4 giây
    kc.login(c, "ok-user")
    assert c.get("/api/auth/me").status_code == 200

    _, kc2, _, c2 = setup()
    kc2.clock_offset = 60
    assert _callback_with(kc2, c2) == "/?auth_error=clock"
    _, kc3, _, c3 = setup()
    kc3.clock_offset = -400  # token đã hết hạn 100 giây theo đồng hồ backend
    assert _callback_with(kc3, c3) == "/?auth_error=clock"


def test_keycloak_down_during_login():
    _, kc, _, c = setup()
    user = kc.add_user("dan")
    q = kc.start_login(c)
    kc.codes["c1"] = (user.sub, q["nonce"], q["code_challenge"])
    kc.down = True
    r = c.get("/api/auth/callback", params={"code": "c1", "state": q["state"]},
              follow_redirects=False)
    assert r.headers["location"] == "/?auth_error=unavailable"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("/#market", "/#market"),
        ("//evil.com", "/"),
        ("https://evil.com", "/"),
        ("/\\evil.com", "/"),
        ("/ok\r\nSet-Cookie: x", "/"),
        (None, "/"),
    ],
)
def test_safe_next(raw, expected):
    assert safe_next(raw) == expected


# ---------- Hết hạn, làm mới, thu hồi ----------


def _shift_time(monkeypatch, delta: timedelta):
    base = utcnow()
    monkeypatch.setattr(web, "utcnow", lambda: base + delta)


def test_idle_timeout_and_max_lifetime(monkeypatch):
    _, kc, _, c = setup()
    kc.login(c, "idle")
    _shift_time(monkeypatch, timedelta(minutes=31))
    assert c.get("/api/auth/me").status_code == 401

    monkeypatch.undo()
    _, kc, _, c = setup()
    kc.login(c, "busy")
    base = utcnow()
    # Hoạt động đều đặn mỗi 20 phút vẫn bị đăng xuất khi quá 8 giờ.
    for i in range(1, 25):
        monkeypatch.setattr(web, "utcnow", lambda i=i: base + timedelta(minutes=20 * i))
        status = c.get("/api/auth/me").status_code
        if 20 * i < 8 * 60:
            assert status == 200, i
        else:
            assert status == 401, i
            break


def test_disabled_user_loses_access_at_next_refresh(monkeypatch):
    """0-C12: người dùng bị vô hiệu hóa trên Keycloak → làm mới thất bại → 401, có audit."""
    _, kc, repo, c = setup()
    user = kc.login(c, "frank")
    user.enabled = False
    assert c.get("/api/auth/me").status_code == 200  # chưa tới hạn làm mới
    _shift_time(monkeypatch, timedelta(seconds=61))
    assert c.get("/api/auth/me").status_code == 401
    assert ("auth.session_revoked", "ACCEPTED") in audit_actions(repo)
    assert c.get("/api/auth/me").status_code == 401


def test_keycloak_down_keeps_existing_session_until_expiry(monkeypatch):
    """0-C11: Keycloak chết → phiên đang có vẫn chạy tới hết hạn của chính nó."""
    _, kc, _, c = setup()
    kc.login(c, "gina")
    kc.down = True
    _shift_time(monkeypatch, timedelta(minutes=5))
    assert c.get("/api/auth/me").status_code == 200
    # Đăng nhập mới không được
    c2 = client(c.app)
    q = kc.start_login(c2)
    r = c2.get("/api/auth/callback", params={"code": "x", "state": q["state"]},
               follow_redirects=False)
    assert r.headers["location"] == "/?auth_error=unavailable"


def test_admin_role_removed_takes_effect_on_refresh(monkeypatch):
    _, kc, _, c = setup()
    user = kc.login(c, "hank", admin=True)
    assert c.get("/api/auth/me").json()["is_admin"] is True
    user.roles = []
    _shift_time(monkeypatch, timedelta(seconds=61))
    assert c.get("/api/auth/me").json()["is_admin"] is False


def test_refresh_happens_once_per_interval(monkeypatch):
    _, kc, _, c = setup()
    kc.login(c, "ivy")
    n = len(kc.token_requests)
    _shift_time(monkeypatch, timedelta(seconds=61))
    for _ in range(5):
        assert c.get("/api/auth/me").status_code == 200
    assert len(kc.token_requests) == n + 1


def test_logout_clears_session_and_returns_keycloak_url():
    _, kc, repo, c = setup()
    kc.login(c, "jack")
    r = c.post("/api/auth/logout")
    assert r.status_code == 200
    url = urlsplit(r.json()["logout_url"])
    q = parse_qs(url.query)
    assert url.path.endswith("/protocol/openid-connect/logout")
    assert q["post_logout_redirect_uri"] == [PUBLIC_URL + "/"]
    assert q["id_token_hint"]
    assert c.get("/api/auth/me").status_code == 401
    assert ("auth.logout", "ACCEPTED") in audit_actions(repo)


# ---------- CSRF, Origin, Host (0-C14) ----------


def test_write_from_other_origin_is_blocked_and_audited():
    _, kc, repo, c = setup()
    kc.login(c, "kate", admin=True)
    body = {"action": "halt", "reason_code": "X"}
    r = c.post("/api/accounts/default/safety", json=body, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = c.post("/api/accounts/default/safety", json=body, headers={"Origin": ""})
    assert r.status_code == 403
    assert ("access.csrf_blocked", "REJECTED") in audit_actions(repo)
    assert c.get("/api/accounts/default/status").json()["safety_state"] == "PAUSED"
    # Cùng origin thì được
    assert c.post("/api/accounts/default/safety", json=body).status_code == 200


def test_unknown_host_rejected_dns_rebinding():
    app, kc, _, c = setup()
    kc.login(c, "leo")
    r = c.get("/api/auth/me", headers={"Host": "attacker.example"})
    assert r.status_code == 400


def test_client_supplied_actor_is_rejected_and_audit_uses_session():
    _, kc, repo, c = setup()
    kc.login(c, "mia", admin=True)
    r = c.post("/api/accounts/default/safety",
               json={"action": "halt", "reason_code": "X", "actor": "someone"})
    assert r.status_code == 422
    r = c.post("/api/accounts/default/mode", json={"mode": "SHADOW", "approver": "x"})
    assert r.status_code == 422
    c.post("/api/accounts/default/safety", json={"action": "halt", "reason_code": "X"})
    halt = next(e for e in repo.audit(50) if e.action == "safety.halt")
    assert halt.actor == "mia"


# ---------- Cấu hình ----------


def test_config_rejects_unsafe_values():
    with pytest.raises(AuthConfigError):
        make_config(public_url="http://100.64.1.2:8080")  # http ngoài localhost
    with pytest.raises(AuthConfigError):
        make_config(client_secret="short")
    with pytest.raises(AuthConfigError):
        make_config(public_url="https://x.ts.net/path")
    assert make_config(public_url="http://localhost:8080").origin == "http://localhost:8080"


def test_config_from_env_requires_all(monkeypatch):
    monkeypatch.delenv("GT_OIDC_CLIENT_SECRET")
    with pytest.raises(AuthConfigError):
        AuthConfig.from_env()
    monkeypatch.setenv("GT_OIDC_CLIENT_SECRET", CLIENT_SECRET)
    cfg = AuthConfig.from_env()
    assert cfg.internal_issuer_url == INTERNAL
    assert CLIENT_SECRET not in repr(cfg)


def test_app_refuses_to_start_without_auth_config(monkeypatch):
    from gold_trading.api.app import create_app

    monkeypatch.delenv("GT_PUBLIC_URL")
    with pytest.raises(AuthConfigError):
        create_app(InMemoryRepository())
