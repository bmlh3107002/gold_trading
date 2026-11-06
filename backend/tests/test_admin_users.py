"""MT-20: ADMIN tạo người dùng trên Dashboard → Keycloak + tài khoản giao dịch riêng (OWNER)."""

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
from tests.auth_helpers import client, make_app

URL = "/api/admin/users"
PW = "TamThoi12345xyz"


def body(**kw):
    b = {"username": "lanng", "email": "lan@example.com", "first_name": "Lan",
         "last_name": "Nguyen", "password": PW}
    b.update(kw)
    return b


def world(multi: bool = True, repo=None):
    repo = repo or InMemoryRepository()
    app, kc = make_app(repo, data_source=DataSource.MT5, run_analysts=False,
                       auth_cfg={"multi_user_enabled": multi})
    admin = client(app)
    kc.login(admin, "admin", admin=True)
    return repo, app, kc, admin


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
    # Keycloak: có người dùng, mật khẩu tạm (bắt đổi ở lần đăng nhập đầu)
    assert kc.users[sub].username == "lanng"
    assert kc.passwords[sub] == (PW, True)
    # DB: hồ sơ chưa đăng nhập, tài khoản riêng không ghi nến dùng chung, OWNER
    u = repo.user(sub)
    assert u is not None and u.first_login_at is None and u.last_login_at is None
    acc = repo.account("u-lanng")
    assert acc is not None and acc.price_feed is False
    assert repo.role("u-lanng", sub) == "OWNER"
    assert app.state.registry.get("u-lanng") is not None
    [e] = user_audit(repo)
    assert e.outcome == "ACCEPTED" and e.account_id == "u-lanng" and e.actor == "admin"
    assert "password" not in e.payload
    no_password_anywhere(repo, r.text)


def test_new_user_logs_in_and_only_sees_own_account():
    repo, app, kc, admin = world()
    sub = admin.post(URL, json=body()).json()["sub"]
    me = client(app)
    kc.login(me, "lanng")
    u = repo.user(sub)
    assert u is not None and u.first_login_at is not None  # lần đăng nhập đầu được ghi
    accs = me.get("/api/accounts").json()
    assert [(a["account_id"], a["role"]) for a in accs] == [("u-lanng", "OWNER")]
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
    repo.provision_user(u, acc, Member("u-lanng", "kc-1", "OWNER", now, "admin"))
    assert repo.user("kc-1").first_login_at is None
    assert repo.role("u-lanng", "kc-1") == "OWNER"
    # Trùng: không để lại gì dở dang
    from gold_trading.storage.repository import ConflictError

    u2 = UserRecord("kc-2", "x", None, None, None, None)
    with pytest.raises(ConflictError):
        repo.provision_user(u2, acc, Member("u-lanng", "kc-2", "OWNER", now, "admin"))
    assert repo.user("kc-2") is None
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
