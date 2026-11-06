"""MT-20 + DEC-16: ADMIN quản lý USER trên Dashboard.

Tạo (Keycloak + tài khoản giao dịch riêng + token Gateway trong một giao dịch), danh sách, khóa,
mở khóa, đặt lại mật khẩu, cấp lại token.
"""

from __future__ import annotations

import json

import pytest

from gold_trading.contracts.candle import DataSource
from gold_trading.storage.repository import (
    InMemoryRepository,
    Member,
    SqlRepository,
    TradingAccount,
    UserRecord,
)
from tests.auth_helpers import client, login_owner, make_app
from tests.test_ingest_api import HB

URL = "/api/admin/users"
PW = "TamThoi12345xyz"


def body(**kw):
    b = {"username": "lanng", "email": "lan@example.com", "first_name": "Lan",
         "last_name": "Nguyen", "password": PW}
    b.update(kw)
    return b


def world(multi: bool = True, repo=None, seed_owner: bool = True):
    """``seed_owner``: tài khoản nguồn giá ``default`` đã có chủ (như máy đang chạy), để USER
    mới nhận tài khoản riêng ``u-<username>``."""
    repo = repo or InMemoryRepository()
    app, kc = make_app(repo, data_source=DataSource.MT5, run_analysts=False,
                       auth_cfg={"multi_user_enabled": multi})
    admin = client(app)
    kc.login(admin, "admin", admin=True)
    if seed_owner:
        login_owner(app, kc, repo, "trader")
    return repo, app, kc, admin


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def user_audit(repo):
    return [e for e in repo.audit(500) if e.action == "user.create"]


def no_password_anywhere(repo, *texts: str) -> None:
    dump = json.dumps([e.payload for e in repo.audit(500)], default=str)
    dump += json.dumps([e.detail for e in repo.audit(500)], default=str)
    assert PW not in dump
    for t in texts:
        assert PW not in t


def test_admin_creates_user_with_own_account_and_temporary_password():
    repo, app, kc, admin = world()
    r = admin.post(URL, json=body())
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["username"] == "lanng" and out["account_id"] == "u-lanng"
    assert out["account_name"] == "Tài khoản của Lan Nguyen"
    sub = out["sub"]
    assert out["status"] == "ACTIVE" and out["temporary_password"] is None  # admin tự đặt
    assert r.headers["cache-control"] == "no-store"
    # Token Gateway sinh tự động, gắn đúng tài khoản, đã đăng ký ở backend (chờ Gateway)
    tok = out["gateway"]["token"]
    assert tok.startswith("gtk_") and len(tok) >= 40
    assert out["gateway"]["account_id"] == "u-lanng" and out["gateway_status"] == "WAITING"
    assert repo.account_for_token(tok) == "u-lanng"
    assert tok not in json.dumps(repo._tokens, default=str)  # chỉ lưu băm
    # Keycloak: có người dùng, mật khẩu tạm (bắt đổi ở lần đăng nhập đầu)
    assert kc.users[sub].username == "lanng"
    assert kc.passwords[sub] == (PW, True)
    # DB: hồ sơ chưa đăng nhập, tài khoản riêng không ghi nến dùng chung, OWNER
    u = repo.user(sub)
    assert u is not None and u.first_login_at is None and u.last_login_at is None
    assert u.role == "USER" and u.status == "ACTIVE"
    acc = repo.account("u-lanng")
    assert acc is not None and acc.price_feed is False
    assert repo.role("u-lanng", sub) == "OWNER"
    assert app.state.registry.get("u-lanng") is not None
    [e] = user_audit(repo)
    assert e.outcome == "ACCEPTED" and e.account_id == "u-lanng" and e.actor == "admin"
    assert "password" not in e.payload and e.payload["token_id"] == out["gateway"]["token_id"]
    assert tok not in json.dumps([x.__dict__ for x in repo.audit(500)], default=str)
    no_password_anywhere(repo, r.text)


def test_new_user_logs_in_and_only_sees_own_account():
    repo, app, kc, admin = world()
    sub = admin.post(URL, json=body()).json()["sub"]
    me = client(app)
    kc.login(me, "lanng")
    u = repo.user(sub)
    assert u is not None and u.first_login_at is not None  # lần đăng nhập đầu được ghi
    accs = me.get("/api/accounts").json()
    assert [a["account_id"] for a in accs] == ["u-lanng"]
    assert me.get("/api/accounts/default/status").status_code == 404
    assert me.get("/api/accounts/u-lanng/status").status_code == 200
    # Người mới (không phải ADMIN) không tạo được người dùng
    r = me.post(URL, json=body(username="khac", email="khac@example.com"))
    assert r.status_code == 403


def test_non_admin_refused_without_calling_keycloak():
    repo, app, kc, admin = world()
    bob = client(app)
    kc.login(bob, "bob")
    kc.admin_requests.clear()
    r = bob.post(URL, json=body())
    assert r.status_code == 403
    assert kc.admin_requests == []
    assert [e.outcome for e in user_audit(repo)] == ["REJECTED"]
    no_password_anywhere(repo, r.text)


def test_dec12_off_refuses():
    repo, _, kc, admin = world(multi=False)
    r = admin.post(URL, json=body())
    assert r.status_code == 409 and "DEC-12" in r.json()["detail"]
    assert kc.admin_requests == []


def test_unlimited_number_of_users():
    repo, app, kc, admin = world()
    for i in range(12):
        r = admin.post(URL, json=body(username=f"user{i:02d}", email=f"u{i}@example.com"))
        assert r.status_code == 201, r.text
    assert len([a for a in repo.accounts() if a.account_id.startswith("u-")]) == 12
    tokens = {t["token_sha256"] for t in repo._tokens}
    assert len(tokens) == 12  # không dùng chung token giữa các USER


def test_duplicate_username_or_email():
    repo, _, kc, admin = world()
    assert admin.post(URL, json=body()).status_code == 201
    r = admin.post(URL, json=body())  # cùng username → mã tài khoản đã có
    assert r.status_code == 409
    r = admin.post(URL, json=body(username="lanng2"))  # cùng email → Keycloak 409
    assert r.status_code == 409
    assert "lanng2" not in [u.username for u in kc.users.values()]
    assert repo.account("u-lanng2") is None


@pytest.mark.parametrize("bad", [
    {"password": "Zq9w"},
    {"username": "Có Dấu"},
    {"username": "ab"},
    {"email": "khong-phai-email"},
    {"first_name": ""},
    {"actor": "x"},  # trường lạ
])
def test_validation_rejected_before_keycloak_and_password_not_echoed(bad):
    repo, _, kc, admin = world()
    kc.admin_requests.clear()
    r = admin.post(URL, json=body(**bad))
    assert r.status_code == 422
    assert kc.admin_requests == []
    assert PW not in r.text and "Zq9w" not in r.text
    assert "input" not in r.json()["detail"][0]


def test_password_equal_to_username_refused():
    _, _, kc, admin = world()
    r = admin.post(URL, json=body(username="matkhau12345", password="matkhau12345"))
    assert r.status_code == 422
    assert not any(u.username == "matkhau12345" for u in kc.users.values())


def test_keycloak_password_policy_maps_to_422():
    _, _, kc, admin = world()
    kc.fail_admin_create = 400
    r = admin.post(URL, json=body())
    assert r.status_code == 422


def test_service_account_not_enabled_tells_to_run_sync():
    repo, _, kc, admin = world()
    kc.service_account = False
    r = admin.post(URL, json=body())
    assert r.status_code == 503 and "sync-client.sh" in r.json()["detail"]
    assert repo.account("u-lanng") is None


def test_keycloak_down_is_503_and_nothing_saved():
    repo, _, kc, admin = world()
    kc.down = True
    r = admin.post(URL, json=body())
    kc.down = False
    assert r.status_code == 503
    assert repo.account("u-lanng") is None


def test_db_failure_deletes_user_from_keycloak(monkeypatch):
    repo, _, kc, admin = world()

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(repo, "provision_user", boom)
    r = admin.post(URL, json=body())
    assert r.status_code == 500
    assert not any(u.username == "lanng" for u in kc.users.values())  # đã bù trừ
    assert any(m == "DELETE" for m, _ in kc.admin_requests)
    [e] = user_audit(repo)
    assert e.outcome == "REJECTED" and "True" in (e.detail or "")


def test_dotted_username_gets_valid_account_id():
    repo, _, _, admin = world()
    r = admin.post(URL, json=body(username="lan.nguyen", email="lan.nguyen@example.com"))
    assert r.status_code == 201 and r.json()["account_id"] == "u-lan-nguyen"


# --- Repository SQL (SQLite) ---


def sql_repo(tmp_path):
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'u.db'}")
    repo.create_all()
    return repo


def test_sql_provision_is_atomic_and_login_sets_first_login(tmp_path):
    from gold_trading.common.time import utcnow

    repo = sql_repo(tmp_path)
    now = utcnow()
    u = UserRecord("kc-1", "me", "me@example.com", "Lan", None, None)
    acc = TradingAccount("u-lanng", "TK", now, "admin", False)
    repo.provision_user(u, acc, Member("u-lanng", "kc-1", "OWNER", now, "admin"), "tok-1", now)
    assert repo.user("kc-1").first_login_at is None
    assert repo.user("kc-1").status == "ACTIVE" and repo.user("kc-1").role == "USER"
    assert repo.role("u-lanng", "kc-1") == "OWNER"
    assert repo.account_for_token("tok-1") == "u-lanng"
    # Trùng: không để lại gì dở dang (không người dùng, không token mồ côi)
    from gold_trading.storage.repository import ConflictError

    u2 = UserRecord("kc-2", "x", None, None, None, None)
    with pytest.raises(ConflictError):
        repo.provision_user(u2, acc, Member("u-lanng", "kc-2", "OWNER", now, "admin"),
                            "tok-2", now)
    assert repo.user("kc-2") is None
    assert repo.account_for_token("tok-2") is None
    assert repo.account_for_token("tok-1") == "u-lanng"  # token cũ không bị thu hồi oan
    # Nhận tài khoản có sẵn đã có chủ → từ chối, không đổi gì
    with pytest.raises(ConflictError):
        repo.provision_user(UserRecord("kc-3", "y", None, None, None, None), None,
                            Member("u-lanng", "kc-3", "OWNER", now, "admin"), "tok-3", now)
    assert repo.user("kc-3") is None and repo.account_for_token("tok-1") == "u-lanng"
    # Trạng thái + vai trò
    assert repo.set_user_status("kc-1", "LOCKED", now) is True
    assert repo.user("kc-1").status == "LOCKED"
    assert repo.set_user_status("ghost", "LOCKED", now) is False
    with pytest.raises(ValueError):
        repo.set_user_status("kc-1", "OWNER", now)
    repo.upsert_user("kc-1", "me", "me@example.com", "Lan", now)
    assert repo.user("kc-1").status == "LOCKED"  # đăng nhập không tự mở khóa
    # Đăng nhập lần đầu: điền first_login_at, lần sau giữ nguyên
    repo.upsert_user("kc-1", "me", "me@example.com", "Lan", now)
    first = repo.user("kc-1").first_login_at
    assert first is not None
    later = utcnow()
    repo.upsert_user("kc-1", "me", "me@example.com", "Lan", later)
    assert repo.user("kc-1").first_login_at == first


def test_sql_end_to_end_through_api(tmp_path):
    repo = sql_repo(tmp_path)
    repo2, app, kc, admin = world(repo=repo)
    r = admin.post(URL, json=body())
    assert r.status_code == 201, r.text
    me = client(app)
    kc.login(me, "lanng")
    assert [a["account_id"] for a in me.get("/api/accounts").json()] == ["u-lanng"]


# --- DEC-16: USER đầu tiên nhận tài khoản nguồn giá; danh sách; khóa / mở khóa; mật khẩu ---


def create(admin, **kw):
    r = admin.post(URL, json=body(**kw))
    assert r.status_code == 201, r.text
    return r.json()


def test_first_user_on_fresh_install_gets_price_feed_account_and_generated_password():
    repo, app, kc, admin = world(seed_owner=False, repo=InMemoryRepository())
    out = admin.post(URL, json={k: v for k, v in body().items() if k != "password"}).json()
    assert out["account_id"] == "default" and out["account_name"] == "Tài khoản chính"
    pw = out["temporary_password"]
    assert pw and len(pw) >= 12 and kc.passwords[out["sub"]] == (pw, True)
    assert pw not in json.dumps([e.__dict__ for e in repo.audit(500)], default=str)
    # Gateway của USER này ghi được nến dùng chung (price_feed)
    me = client(app)
    r = me.post("/api/ingest/mt5/heartbeat", json=HB, headers=bearer(out["gateway"]["token"]))
    assert r.status_code == 200
    # USER thứ hai: tài khoản riêng
    assert create(admin, username="minh", email="m@example.com")["account_id"] == "u-minh"


def test_list_users_shows_status_and_gateway_but_never_secrets():
    repo, app, kc, admin = world()
    out = create(admin)
    rows = admin.get(URL).json()
    assert [u["username"] for u in rows] == ["lanng", "trader"]  # ADMIN không nằm trong danh sách
    lan = rows[0]
    assert lan["status"] == "ACTIVE" and lan["first_login_at"] is None
    assert [(a["account_id"], a["gateway_status"]) for a in lan["accounts"]] == [
        ("u-lanng", "WAITING")]
    assert rows[1]["accounts"][0]["gateway_status"] == "NO_TOKEN"
    text = json.dumps(rows)
    assert out["gateway"]["token"] not in text and PW not in text and "token" not in lan
    # Gateway gửi nhịp tim → CONNECTED
    gw = client(app)
    gw.post("/api/ingest/mt5/heartbeat", json=HB, headers=bearer(out["gateway"]["token"]))
    assert admin.get(URL).json()[0]["accounts"][0]["gateway_status"] == "CONNECTED"
    # USER không xem được danh sách
    me = client(app)
    kc.login(me, "lanng")
    assert me.get(URL).status_code == 403


def test_lock_blocks_login_session_gateway_and_orders_without_touching_safety():
    repo, app, kc, admin = world()
    out = create(admin)
    sub, tok = out["sub"], out["gateway"]["token"]
    me = client(app)
    kc.login(me, "lanng")
    assert me.post("/api/accounts/u-lanng/safety",
                   json={"action": "resume", "reason_code": "OK"}).status_code == 200
    reg = app.state.registry
    assert reg.allows_new_orders("u-lanng") is True
    gw = client(app)
    assert gw.post("/api/ingest/mt5/heartbeat", json=HB, headers=bearer(tok)).status_code == 200

    r = admin.post(f"{URL}/{sub}/lock")
    assert r.status_code == 200
    assert r.json() == {"sub": sub, "status": "LOCKED", "sessions_revoked": 1,
                        "keycloak_synced": True}
    assert repo.user(sub).status == "LOCKED"
    assert kc.users[sub].enabled is False and sub in kc.logouts
    assert me.get("/api/accounts").status_code == 401  # phiên đã thu hồi
    assert gw.post("/api/ingest/mt5/heartbeat", json=HB, headers=bearer(tok)).status_code == 403
    assert reg.allows_new_orders("u-lanng") is False
    assert reg.get("u-lanng").safety.state.value == "ACTIVE"  # không đổi Safety / không đóng lệnh
    assert admin.get(URL).json()[0]["accounts"][0]["gateway_status"] == "BLOCKED"
    # Khóa lại lần nữa: idempotent
    assert admin.post(f"{URL}/{sub}/lock").json()["status"] == "LOCKED"

    r = admin.post(f"{URL}/{sub}/unlock")
    assert r.status_code == 200 and r.json()["status"] == "ACTIVE"
    assert kc.users[sub].enabled is True and repo.user(sub).status == "ACTIVE"
    # Token cũ dùng lại được; bot không tự đổi gì
    assert gw.post("/api/ingest/mt5/heartbeat", json=HB, headers=bearer(tok)).status_code == 200
    assert reg.get("u-lanng").modes.mode.value == "PAPER"
    actions = [(e.action, e.outcome) for e in repo.audit(500) if e.action.startswith("user.")]
    assert ("user.lock", "ACCEPTED") in actions and ("user.unlock", "ACCEPTED") in actions


def test_lock_still_effective_when_keycloak_fails_and_retry_syncs():
    repo, app, kc, admin = world()
    sub = create(admin)["sub"]
    kc.fail_admin_ops = 500
    r = admin.post(f"{URL}/{sub}/lock")
    assert r.status_code == 200 and r.json()["keycloak_synced"] is False
    assert repo.user(sub).status == "LOCKED"  # backend đã chặn
    assert kc.users[sub].enabled is True
    kc.fail_admin_ops = None
    assert admin.post(f"{URL}/{sub}/lock").json()["keycloak_synced"] is True
    assert kc.users[sub].enabled is False


def test_unlock_keeps_user_locked_when_keycloak_fails():
    repo, app, kc, admin = world()
    sub = create(admin)["sub"]
    admin.post(f"{URL}/{sub}/lock")
    kc.down = True
    r = admin.post(f"{URL}/{sub}/unlock")
    kc.down = False
    assert r.status_code == 503
    assert repo.user(sub).status == "LOCKED"


def test_reset_password_revokes_sessions_and_keeps_gateway_token():
    repo, app, kc, admin = world()
    out = create(admin)
    sub, tok = out["sub"], out["gateway"]["token"]
    me = client(app)
    kc.login(me, "lanng")
    r = admin.post(f"{URL}/{sub}/reset-password")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    pw = r.json()["temporary_password"]
    assert len(pw) >= 12 and pw != PW
    assert kc.passwords[sub] == (pw, True)  # tạm thời → bắt đổi khi đăng nhập
    assert r.json()["sessions_revoked"] == 1 and sub in kc.logouts
    assert me.get("/api/accounts").status_code == 401
    assert repo.account_for_token(tok) == "u-lanng"  # token không đổi
    assert pw not in json.dumps([e.__dict__ for e in repo.audit(500)], default=str)


def test_admin_cannot_lock_or_reset_admin_and_unknown_user_is_404():
    repo, app, kc, admin = world()
    sub_admin = next(u.sub for u in kc.users.values() if u.username == "admin")
    for action in ("lock", "unlock", "reset-password"):
        assert admin.post(f"{URL}/{sub_admin}/{action}").status_code == 404
        assert admin.post(f"{URL}/ghost/{action}").status_code == 404
    assert kc.users[sub_admin].enabled is True
    # Ngay sau migration 0006 dòng của ADMIN còn ghi USER (chưa đăng nhập lại): vẫn không tự khóa
    u = repo.user(sub_admin)
    repo._users[sub_admin] = u.__class__(**{**u.__dict__, "role": "USER"})
    assert "admin" not in [x["username"] for x in admin.get(URL).json()]
    assert admin.post(f"{URL}/{sub_admin}/lock").status_code == 404
    assert repo.user(sub_admin).status == "ACTIVE"


def test_reissue_token_revokes_old_one():
    repo, app, kc, admin = world()
    out = create(admin)
    old = out["gateway"]["token"]
    r = admin.post(f"{URL}/{out['sub']}/accounts/u-lanng/gateway-token")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    new = r.json()["token"]
    assert new != old
    assert repo.account_for_token(old) is None and repo.account_for_token(new) == "u-lanng"
