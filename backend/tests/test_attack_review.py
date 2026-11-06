"""Soát cuối GĐ0: kịch bản tấn công/thử lỗi nhắm vào chỗ dễ sai (ngoài các test theo case)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from gold_trading.auth.web import LOGIN_COOKIE, SESSION_COOKIE
from gold_trading.contracts.candle import DataSource
from gold_trading.storage.repository import InMemoryRepository
from tests.auth_helpers import PUBLIC_URL, client, make_app


def world():
    repo = InMemoryRepository()
    app, kc = make_app(repo, data_source=DataSource.MT5, run_analysts=False,
                       live_unlocked=True, auth_cfg={"multi_user_enabled": True})
    admin = client(app)
    kc.login(admin, "admin", admin=True)
    return repo, app, kc, admin


def test_path_tricks_on_account_id_do_not_bypass_guard():
    repo, app, kc, admin = world()
    admin.post("/api/accounts", json={"account_id": "acc_b", "name": "B"})
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


def test_live_request_id_from_other_account_cannot_be_approved():
    repo, app, kc, admin = world()
    admin.post("/api/accounts", json={"account_id": "acc_b", "name": "B"})
    admin.post("/api/accounts/acc_b/members", json={"user": "admin", "role": "OWNER"})
    o2 = client(app)
    kc.login(o2, "o2")
    admin.post("/api/accounts/default/members", json={"user": "o2", "role": "OWNER"})
    req = admin.post("/api/accounts/acc_b/mode/live-requests", json={"checklist": {}}).json()
    # o2 là OWNER của default, không phải acc_b: dùng request_id của acc_b qua đường default
    r = o2.post(f"/api/accounts/default/mode/live-requests/{req['request_id']}/approve")
    assert r.status_code == 409
    assert o2.post(
        f"/api/accounts/acc_b/mode/live-requests/{req['request_id']}/approve"
    ).status_code == 404


def test_owner_of_a_cannot_manage_members_or_tokens_of_b():
    repo, app, kc, admin = world()
    admin.post("/api/accounts", json={"account_id": "acc_b", "name": "B"})
    a = client(app)
    kc.login(a, "alice")
    admin.post("/api/accounts/default/members", json={"user": "alice", "role": "OWNER"})
    assert a.post("/api/accounts/acc_b/members",
                  json={"user": "alice", "role": "OWNER"}).status_code == 404
    assert a.post("/api/accounts/acc_b/gateway/token").status_code == 404
    assert a.post("/api/admin/kill-switch", json={"reason_code": "X"}).status_code == 403
    assert a.get("/api/admin/audit").status_code == 403


def test_bad_request_id_header_is_not_reflected():
    _, _, _, admin = world()
    r = admin.get("/api/auth/me", headers={"X-Request-ID": "x" * 65})
    assert r.headers["x-request-id"] != "x" * 65
    r = admin.get("/api/auth/me", headers={"X-Request-ID": "<script>"})
    assert "<" not in r.headers["x-request-id"]


def test_lowercase_bearer_and_token_whitespace_rejected():
    repo, app, kc, admin = world()
    tok = admin.post("/api/accounts/default/gateway/token").json()["token"]
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
