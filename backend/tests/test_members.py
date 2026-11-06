"""MT-10: quản lý thành viên tài khoản (thêm theo username/email, đổi vai trò, gỡ), có audit.

DEC-12 chưa trả lời → mặc định KHÔNG nhận người dùng thứ hai.
"""

from __future__ import annotations

from gold_trading.contracts.candle import DataSource
from gold_trading.storage.repository import InMemoryRepository
from tests.auth_helpers import client, make_app

M = "/api/accounts/default/members"


def world(multi: bool = True):
    repo = InMemoryRepository()
    app, kc = make_app(repo, data_source=DataSource.MT5, run_analysts=False,
                       auth_cfg={"multi_user_enabled": multi})
    admin = client(app)
    kc.login(admin, "admin", admin=True)  # → OWNER của default
    clients = {}
    for name in ("bob", "carol"):
        clients[name] = client(app)
        kc.login(clients[name], name)  # đăng nhập một lần để có hồ sơ
    return repo, app, kc, admin, clients


def actions(repo):
    return [(e.action, e.outcome) for e in repo.audit(500) if e.action.startswith("members.")]


def test_second_user_refused_until_dec12_answered():
    repo, _, _, admin, clients = world(multi=False)
    r = admin.post(M, json={"user": "bob", "role": "VIEWER"})
    assert r.status_code == 409 and "DEC-12" in r.json()["detail"]
    assert ("members.add", "REJECTED") in actions(repo)
    assert clients["bob"].get("/api/accounts/default/status").status_code == 404
    # Tự thêm chính mình vào tài khoản khác (nhiều tài khoản MT5 của cùng người) vẫn được
    admin.post("/api/accounts", json={"account_id": "acc_two", "name": "MT5 thứ hai"})
    r = admin.post("/api/accounts/acc_two/members", json={"user": "admin", "role": "OWNER"})
    assert r.status_code == 201


def test_add_by_username_or_email_change_role_remove():
    repo, _, _, admin, clients = world()
    bob = clients["bob"]
    r = admin.post(M, json={"user": "BOB@example.com", "role": "VIEWER"})
    assert r.status_code == 201 and r.json()["username"] == "bob"
    assert bob.get("/api/accounts/default/status").status_code == 200
    assert bob.post("/api/accounts/default/safety",
                    json={"action": "halt", "reason_code": "X"}).status_code == 403
    assert admin.post(M, json={"user": "bob", "role": "OWNER"}).status_code == 409  # đã có
    r = admin.put(f"{M}/sub-bob", json={"role": "OPERATOR"})
    assert r.status_code == 200 and r.json()["role"] == "OPERATOR"
    assert bob.post("/api/accounts/default/safety",
                    json={"action": "halt", "reason_code": "X"}).status_code == 200
    assert admin.delete(f"{M}/sub-bob").status_code == 204
    assert bob.get("/api/accounts/default/status").status_code == 404
    assert [a for a, _ in actions(repo)] == [
        "members.remove", "members.change_role", "members.add"
    ]
    assert {m["username"] for m in admin.get(M).json()} == {"admin"}


def test_unknown_user_must_log_in_first():
    _, _, _, admin, _ = world()
    r = admin.post(M, json={"user": "never-logged-in", "role": "VIEWER"})
    assert r.status_code == 404 and "đăng nhập" in r.json()["detail"]


def test_only_owner_or_admin_manages_members():
    repo, _, _, admin, clients = world()
    admin.post(M, json={"user": "bob", "role": "OPERATOR"})
    bob = clients["bob"]
    assert bob.get(M).status_code == 200  # xem được
    assert bob.post(M, json={"user": "carol", "role": "VIEWER"}).status_code == 403
    assert bob.put(f"{M}/sub-bob", json={"role": "OWNER"}).status_code == 403  # tự nâng quyền
    assert bob.delete(f"{M}/sub-admin").status_code == 403
    carol = clients["carol"]
    assert carol.get(M).status_code == 404  # không thành viên


def test_last_owner_cannot_be_removed_or_demoted():
    _, _, _, admin, _ = world()
    assert admin.put(f"{M}/sub-admin", json={"role": "VIEWER"}).status_code == 409
    assert admin.delete(f"{M}/sub-admin").status_code == 409
    admin.post(M, json={"user": "bob", "role": "OWNER"})
    assert admin.put(f"{M}/sub-admin", json={"role": "VIEWER"}).status_code == 200


def test_invalid_role_rejected():
    _, _, _, admin, _ = world()
    assert admin.post(M, json={"user": "bob", "role": "ADMIN"}).status_code == 422
    assert admin.post(M, json={"user": "bob", "role": "VIEWER", "sub": "x"}).status_code == 422
