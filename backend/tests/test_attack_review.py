"""Soát cuối GĐ0: kịch bản tấn công/thử lỗi nhắm vào chỗ dễ sai (ngoài các test theo case)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from gold_trading.auth.web import LOGIN_COOKIE, SESSION_COOKIE
from gold_trading.contracts.candle import DataSource
from gold_trading.storage.repository import InMemoryRepository
from tests.auth_helpers import PUBLIC_URL, client, login_owner, make_app


def world():
    repo = InMemoryRepository()
    app, kc = make_app(repo, data_source=DataSource.MT5, run_analysts=False,
                       live_unlocked=True, auth_cfg={"multi_user_enabled": True})
    admin = client(app)
    kc.login(admin, "admin", admin=True)
    return repo, app, kc, admin


def test_path_tricks_on_account_id_do_not_bypass_guard():
    repo, app, kc, admin = world()
    login_owner(app, kc, repo, "bob", account="acc_b")
    eve = client(app)
    kc.login(eve, "eve")
    for path in ("/api/accounts/acc_b%2F..%2Fdefault/status", "/api/accounts/ACC_B/status",
                 "/api/accounts/acc_b%00/status", "/api/accounts/%20acc_b/status",
                 "/api/accounts/default/../acc_b/status"):
        r = eve.get(path)
        assert r.status_code in (404, 400), (path, r.status_code)


def test_login_cookie_cannot_be_used_as_session():
    _, app, kc, _ = world()
    c = client(app)
    q = kc.start_login(c)
    c.cookies.set(SESSION_COOKIE, q["state"])
    assert c.get("/api/auth/me").status_code == 401
    c.cookies.delete(SESSION_COOKIE)
    c.cookies.set(LOGIN_COOKIE, q["state"])
    assert c.get("/api/auth/me").status_code == 401


def test_session_fixation_new_id_on_login():
    _, app, kc, _ = world()
    c = client(app)
    c.cookies.set(SESSION_COOKIE, "attacker-chosen-session-id-0123456789abcdef")
    kc.login(c, "victim")
    from gold_trading.common.time import utcnow

    store = app.state.auth.store
    assert store.get("attacker-chosen-session-id-0123456789abcdef", utcnow()) is None
    assert store.count() == 2  # admin (world) + victim: đều do backend tạo, id ngẫu nhiên


def test_logout_csrf_and_odd_origins_blocked():
    _, _, _, admin = world()
    for origin in ("https://evil.example", "null", PUBLIC_URL + ".evil.example",
                   "http://testserver", "https://testserver:8443"):
        r = admin.post("/api/auth/logout", headers={"Origin": origin})
        assert r.status_code == 403, origin
    assert admin.get("/api/auth/me").status_code == 200  # vẫn đăng nhập
    r = admin.post("/api/auth/logout", headers={"Origin": PUBLIC_URL + "/"})
    assert r.status_code == 200  # dấu / cuối được chuẩn hóa


def test_host_header_variants():
    _, app, _, admin = world()
    assert admin.get("/api/auth/me", headers={"Host": "testserver.evil.com"}).status_code == 400
    assert admin.get("/api/auth/me", headers={"Host": "evil.com:443"}).status_code == 400
    assert admin.get("/api/auth/me", headers={"Host": "localhost:8080"}).status_code == 200


def test_open_redirect_variants():
    _, app, kc, _ = world()
    c = client(app)
    user = kc.add_user("rob")
    for nxt in ("//evil.com", "/\\evil.com", "https:/evil.com", "/%2F%2Fevil.com".replace(
            "%2F", "/"), "\t//evil.com", " //evil.com"):
        r = c.get("/api/auth/login", params={"next": nxt}, follow_redirects=False)
        q = {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}
        kc.codes["c"] = (user.sub, q["nonce"], q["code_challenge"])
        r = c.get("/api/auth/callback", params={"code": "c", "state": q["state"]},
                  follow_redirects=False)
        loc = r.headers["location"]
        assert loc.startswith("/") and not loc.startswith("//") and "evil" not in loc, (nxt, loc)


def test_live_request_of_other_account_cannot_be_reached_by_a_user():
    """USER A không xem/duyệt được yêu cầu LIVE của tài khoản B; chỉ ADMIN duyệt."""
    repo, app, kc, admin = world()
    a = login_owner(app, kc, repo, "alice")
    b = login_owner(app, kc, repo, "bob", account="acc_b")
    req = b.post("/api/accounts/acc_b/mode/live-requests", json={"checklist": {}}).json()
    assert a.get("/api/accounts/acc_b/mode/live-requests").status_code == 404
    assert a.post(f"/api/admin/live-requests/{req['request_id']}/approve").status_code == 403
    assert a.post(f"/api/admin/live-requests/{req['request_id']}/reject").status_code == 403
    assert [x["request_id"] for x in admin.get("/api/admin/live-requests").json()] == [
        req["request_id"]]


def test_user_cannot_use_any_admin_endpoint():
    repo, app, kc, admin = world()
    a = login_owner(app, kc, repo, "alice")
    login_owner(app, kc, repo, "bob", account="acc_b")
    for method, path in [
        ("GET", "/api/admin/users"),
        ("POST", "/api/admin/users/sub-bob/lock"),
        ("POST", "/api/admin/users/sub-bob/unlock"),
        ("POST", "/api/admin/users/sub-bob/reset-password"),
        ("POST", "/api/admin/users/sub-bob/accounts/acc_b/gateway-token"),
        ("GET", "/api/admin/live-requests"),
    ]:
        assert a.request(method, path, json={}).status_code == 403, path
    assert a.post("/api/accounts/acc_b/gateway/token").status_code == 405
    assert repo.user("sub-bob").status == "ACTIVE"
    assert not repo.has_gateway_tokens("acc_b")


def test_bad_request_id_header_is_not_reflected():
    _, _, _, admin = world()
    r = admin.get("/api/auth/me", headers={"X-Request-ID": "x" * 65})
    assert r.headers["x-request-id"] != "x" * 65
    r = admin.get("/api/auth/me", headers={"X-Request-ID": "<script>"})
    assert "<" not in r.headers["x-request-id"]


def test_lowercase_bearer_and_token_whitespace_rejected():
    repo, app, kc, admin = world()
    login_owner(app, kc, repo, "trader")
    tok = admin.post("/api/admin/users/sub-trader/accounts/default/gateway-token").json()["token"]
    hb = {"gateway_id": "g", "gateway_version": "1", "read_only": True,
          "terminal_connected": True, "account_type": "DEMO", "server_tz": "Europe/Athens"}
    anon = TestClient(app, base_url=PUBLIC_URL)
    for h in (f"bearer {tok}", f"Bearer  {tok}", f"Bearer {tok} ", tok):
        assert anon.post("/api/ingest/mt5/heartbeat", json=hb,
                         headers={"Authorization": h}).status_code == 401, h
    assert anon.post("/api/ingest/mt5/heartbeat", json=hb,
                     headers={"Authorization": f"Bearer {tok}"}).status_code == 200


def test_session_cookie_from_ingest_paths_gives_no_extra_power():
    """Cổng Gateway không xét cookie: có phiên ADMIN mà không có token vẫn 401."""
    _, _, _, admin = world()
    hb = {"gateway_id": "g", "gateway_version": "1", "read_only": True,
          "terminal_connected": True, "account_type": "DEMO", "server_tz": "Europe/Athens"}
    assert admin.post("/api/ingest/mt5/heartbeat", json=hb).status_code in (401, 503)
