"""DEC-17: trang Quản trị đơn giản — một USER một dòng; thêm, sửa, xóa, khóa; USER xin token,
ADMIN cấp (token hiện cho ADMIN) hoặc từ chối.

Trường hợp xấu: xin trùng, từ chối khi không có yêu cầu, USER bị khóa xin/được cấp, email trùng khi
sửa, Keycloak lỗi khi sửa/xóa, xóa USER đang cấp giá / đang LIVE / Gateway đang kết nối, dùng lại
tên đăng nhập sau khi xóa, USER đã xóa không đăng nhập lại được kể cả khi Keycloak chưa xóa.
"""

from __future__ import annotations

import json

import pytest

from gold_trading.common.enums import TradingMode
from gold_trading.common.time import utcnow
from gold_trading.storage.repository import (
    InMemoryRepository,
    Member,
    SqlRepository,
    TokenRequestEvent,
    TradingAccount,
    UserRecord,
)
from tests.auth_helpers import client
from tests.test_admin_users import PW, URL, body, create, issue, world
from tests.test_ingest_api import HB

HB_PATH = "/api/ingest/mt5/heartbeat"


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def row(admin, sub):
    found = [u for u in admin.get(URL).json() if u["sub"] == sub]
    return found[0] if found else None


def lan_world():
    repo, app, kc, admin = world()
    out = create(admin)
    me = client(app)
    kc.login(me, "lanng")
    return repo, app, kc, admin, me, out["sub"]


TOKEN_INFO = "/api/accounts/u-lanng/gateway/token"
TOKEN_REQ = "/api/accounts/u-lanng/gateway/token-request"


# ---------- Xin / cấp / từ chối token ----------


def test_user_requests_token_admin_issues_and_request_is_closed():
    repo, app, kc, admin, me, sub = lan_world()
    info = me.get(TOKEN_INFO).json()
    assert info["has_token"] is False and info["request_status"] == "NONE"

    r = me.post(TOKEN_REQ)
    assert r.status_code == 200 and r.json()["request_status"] == "PENDING"
    # Bấm lại: không tạo yêu cầu thứ hai
    assert me.post(TOKEN_REQ).json()["request_status"] == "PENDING"
    assert [e.event for e in repo._token_requests] == ["REQUESTED"]
    assert row(admin, sub)["token_requested_at"] is not None

    tok = issue(admin, sub)
    assert repo.account_for_token(tok) == "u-lanng"
    info = me.get(TOKEN_INFO).json()
    assert info["has_token"] is True and info["request_status"] == "NONE"
    assert tok not in json.dumps(info)  # USER không thấy token (DEC-17 lựa chọn B)
    assert row(admin, sub)["token_requested_at"] is None
    assert [e.event for e in repo._token_requests] == ["REQUESTED", "APPROVED"]
    assert client(app).post(HB_PATH, json=HB, headers=bearer(tok)).status_code == 200
    acts = [(e.action, e.outcome) for e in repo.audit(500)]
    assert ("gateway.token_request", "ACCEPTED") in acts
    assert ("gateway.token_request", "NOOP") in acts
    assert tok not in json.dumps([e.__dict__ for e in repo.audit(500)], default=str)


def test_reject_keeps_existing_token_and_user_can_ask_again():
    repo, app, kc, admin, me, sub = lan_world()
    old = issue(admin, sub)  # ADMIN cấp không cần yêu cầu (cấp lại khi mất)
    me.post(TOKEN_REQ)
    r = admin.post(f"{URL}/{sub}/gateway-token/reject")
    assert r.status_code == 204
    info = me.get(TOKEN_INFO).json()
    assert info["request_status"] == "REJECTED" and info["has_token"] is True
    assert repo.account_for_token(old) == "u-lanng"  # từ chối không đụng token đang dùng
    # Không còn yêu cầu nào chờ → từ chối lần nữa là 409
    assert admin.post(f"{URL}/{sub}/gateway-token/reject").status_code == 409
    # Xin lại được
    assert me.post(TOKEN_REQ).json()["request_status"] == "PENDING"


def test_locked_user_cannot_request_or_receive_token():
    repo, app, kc, admin, me, sub = lan_world()
    me.post(TOKEN_REQ)
    assert admin.post(f"{URL}/{sub}/lock").status_code == 200
    assert admin.post(f"{URL}/{sub}/gateway-token").status_code == 409
    assert not repo.has_gateway_tokens("u-lanng")
    me2 = client(app)  # phiên cũ đã bị thu hồi; đăng nhập lại cũng bị chặn
    assert me2.post(TOKEN_REQ).status_code == 401


def test_admin_cannot_request_token_and_user_cannot_answer():
    repo, app, kc, admin, me, sub = lan_world()
    assert admin.post(TOKEN_REQ).status_code == 404  # ADMIN không vào tài khoản giao dịch
    me.post(TOKEN_REQ)
    assert me.post(f"{URL}/{sub}/gateway-token").status_code == 403
    assert me.post(f"{URL}/{sub}/gateway-token/reject").status_code == 403
    assert not repo.has_gateway_tokens("u-lanng")
    assert admin.post(f"{URL}/ghost/gateway-token").status_code == 404


# ---------- Sửa ----------

EDIT = {"email": "lan.moi@example.com", "first_name": "Lan", "last_name": "Tran"}


def test_edit_updates_keycloak_and_list_without_losing_attributes():
    repo, app, kc, admin, me, sub = lan_world()
    kc.users[sub].attributes = {"locale": ["vi"]}
    r = admin.put(f"{URL}/{sub}", json=EDIT)
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "lan.moi@example.com" and r.json()["display_name"] == "Lan Tran"
    assert r.json()["username"] == "lanng"  # tên đăng nhập không đổi
    u = kc.users[sub]
    assert (u.email, u.first_name, u.last_name) == ("lan.moi@example.com", "Lan", "Tran")
    assert u.attributes == {"locale": ["vi"]} and u.enabled is True
    assert repo.user(sub).email == "lan.moi@example.com"
    assert ("user.update", "ACCEPTED") in [(e.action, e.outcome) for e in repo.audit(50)]


@pytest.mark.parametrize("bad", [
    {"email": "khong-phai-email"},
    {"first_name": ""},
    {"username": "doiten"},  # trường lạ: không cho đổi tên đăng nhập
    {"password": PW},
])
def test_edit_validation_before_keycloak(bad):
    repo, app, kc, admin, me, sub = lan_world()
    kc.admin_requests.clear()
    r = admin.put(f"{URL}/{sub}", json={**EDIT, **bad})
    assert r.status_code == 422
    assert kc.admin_requests == [] and PW not in r.text


def test_edit_email_clash_and_keycloak_down_change_nothing():
    repo, app, kc, admin, me, sub = lan_world()
    create(admin, username="minh", email="minh@example.com")
    r = admin.put(f"{URL}/{sub}", json={**EDIT, "email": "minh@example.com"})
    assert r.status_code == 409
    # Keycloak biết email trùng mà DB không biết (vd. người dùng tạo tay trên Keycloak)
    kc.add_user("ngoai", email="ngoai@example.com")
    r = admin.put(f"{URL}/{sub}", json={**EDIT, "email": "ngoai@example.com"})
    assert r.status_code == 409
    kc.down = True
    r = admin.put(f"{URL}/{sub}", json=EDIT)
    kc.down = False
    assert r.status_code == 503
    assert repo.user(sub).email == "lan@example.com" and kc.users[sub].email == "lan@example.com"


def test_edit_admin_or_unknown_is_404():
    repo, app, kc, admin, me, sub = lan_world()
    sub_admin = next(u.sub for u in kc.users.values() if u.username == "admin")
    assert admin.put(f"{URL}/{sub_admin}", json=EDIT).status_code == 404
    assert admin.put(f"{URL}/ghost", json=EDIT).status_code == 404


# ---------- Xóa ----------


def test_delete_blocks_everything_and_hides_user_but_keeps_history():
    repo, app, kc, admin, me, sub = lan_world()
    tok = issue(admin, sub)
    me.post(TOKEN_REQ)  # đang chờ một yêu cầu cấp lại
    r = admin.delete(f"{URL}/{sub}")
    assert r.status_code == 200, r.text
    assert r.json() == {"sub": sub, "sessions_revoked": 1, "tokens_revoked": 1,
                        "keycloak_synced": True}
    assert repo.user(sub).status == "DELETED"  # còn dòng để giữ lịch sử
    assert row(admin, sub) is None
    assert sub not in kc.users
    assert me.get("/api/accounts").status_code == 401
    assert client(app).post(HB_PATH, json=HB, headers=bearer(tok)).status_code == 401
    assert repo.last_token_request("u-lanng").event == "CANCELLED"
    assert repo.account("u-lanng") is not None and repo.audit(500, account_id="u-lanng")
    # Không thao tác tiếp được trên USER đã xóa
    for path in ("lock", "unlock", "reset-password", "gateway-token"):
        assert admin.post(f"{URL}/{sub}/{path}").status_code == 404
    assert admin.put(f"{URL}/{sub}", json=EDIT).status_code == 404


def test_cannot_delete_price_feed_user():
    repo, app, kc, admin = world()  # "trader" là chủ tài khoản cấp giá
    sub = "sub-trader"
    r = admin.delete(f"{URL}/{sub}")
    assert r.status_code == 409 and "tài khoản chính" in r.json()["detail"]
    assert repo.user(sub).status == "ACTIVE" and sub in kc.users


def test_cannot_delete_live_user():
    repo, app, kc, admin, me, sub = lan_world()
    rt = app.state.registry.get("u-lanng")
    rt.modes._mode = TradingMode.LIVE  # mô phỏng đã được duyệt LIVE
    r = admin.delete(f"{URL}/{sub}")
    assert r.status_code == 409 and "LIVE" in r.json()["detail"]
    assert repo.user(sub).status == "ACTIVE"


def test_cannot_delete_while_gateway_connected():
    repo, app, kc, admin, me, sub = lan_world()
    tok = issue(admin, sub)
    assert client(app).post(HB_PATH, json=HB, headers=bearer(tok)).status_code == 200
    r = admin.delete(f"{URL}/{sub}")
    assert r.status_code == 409 and "Gateway" in r.json()["detail"]
    assert repo.account_for_token(tok) == "u-lanng"


def test_delete_when_keycloak_fails_still_blocks_and_retry_completes():
    repo, app, kc, admin, me, sub = lan_world()
    kc.down = True
    r = admin.delete(f"{URL}/{sub}")
    kc.down = False
    assert r.status_code == 200 and r.json()["keycloak_synced"] is False
    assert repo.user(sub).status == "DELETED" and sub in kc.users
    # Còn trên Keycloak nhưng backend không cho đăng nhập
    c = client(app)
    q = kc.start_login(c)
    code = "code_x"
    kc.codes[code] = (sub, q["nonce"], q["code_challenge"])
    r = c.get("/api/auth/callback", params={"code": code, "state": q["state"]},
              follow_redirects=False)
    assert r.status_code == 302 and "auth_error" in r.headers["location"]
    # ADMIN bấm lại → xóa nốt trên Keycloak
    r = admin.delete(f"{URL}/{sub}")
    assert r.status_code == 200 and r.json()["keycloak_synced"] is True
    assert sub not in kc.users


def test_username_can_be_reused_after_delete_with_a_fresh_account():
    repo, app, kc, admin, me, sub = lan_world()
    assert admin.delete(f"{URL}/{sub}").status_code == 200
    out = create(admin)  # cùng tên đăng nhập + email
    assert out["sub"] != sub
    assert repo.role("u-lanng-2", out["sub"]) == "OWNER"
    assert repo.role("u-lanng", out["sub"]) is None  # không nhận lại tài khoản cũ
    assert [u["username"] for u in admin.get(URL).json()].count("lanng") == 1


def test_create_refuses_duplicate_username_of_active_user():
    repo, app, kc, admin, me, sub = lan_world()
    r = admin.post(URL, json=body(email="khac@example.com"))
    assert r.status_code == 409


# ---------- Repository SQL (SQLite) ----------


def test_sql_repository_dec17(tmp_path):
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'r.db'}")
    repo.create_all()
    now = utcnow()
    u = UserRecord("kc-1", "lan", "lan@example.com", "Lan", None, None)
    acc = TradingAccount("u-lan", "TK", now, "admin", False)
    assert repo.provision_user(u, acc, Member("u-lan", "kc-1", "OWNER", now, "admin"),
                               None, now) is None
    assert not repo.has_gateway_tokens("u-lan")
    assert repo.last_token_request("u-lan") is None
    repo.add_token_request_event(TokenRequestEvent("u-lan", "kc-1", "REQUESTED", now, "lan"))
    repo.add_token_request_event(TokenRequestEvent("u-lan", "kc-1", "APPROVED", now, "admin"))
    assert repo.last_token_request("u-lan").event == "APPROVED"
    with pytest.raises(ValueError):
        repo.add_token_request_event(TokenRequestEvent("u-lan", "kc-1", "XYZ", now, "x"))
    with pytest.raises(KeyError):
        repo.add_token_request_event(TokenRequestEvent("ghost", "kc-1", "REQUESTED", now, "x"))
    repo.rotate_gateway_token("u-lan", "tok-1", "admin", now)
    assert repo.has_active_gateway_token("u-lan")
    assert repo.revoke_gateway_tokens("u-lan", now) == 1
    assert repo.revoke_gateway_tokens("u-lan", now) == 0
    assert not repo.has_active_gateway_token("u-lan") and repo.has_gateway_tokens("u-lan")
    assert repo.account_for_token("tok-1") is None
    assert repo.update_user_profile("kc-1", "moi@example.com", "Lan Moi", now) is True
    assert repo.user("kc-1").email == "moi@example.com"
    assert repo.update_user_profile("ghost", "a@b.c", "x", now) is False
    assert repo.set_user_status("kc-1", "DELETED", now) is True
    assert repo.user("kc-1").status == "DELETED"


def test_memory_and_sql_agree_on_token_requests(tmp_path):
    sql = SqlRepository.from_url(f"sqlite:///{tmp_path / 'r.db'}")
    sql.create_all()
    for repo in (InMemoryRepository(), sql):
        now = utcnow()
        repo.provision_user(UserRecord("kc-1", "lan", None, None, None, None),
                            TradingAccount("u-lan", "TK", now, "a", False),
                            Member("u-lan", "kc-1", "OWNER", now, "a"), None, now)
        for ev in ("REQUESTED", "REJECTED", "REQUESTED"):
            repo.add_token_request_event(TokenRequestEvent("u-lan", "kc-1", ev, now, "x"))
        assert repo.last_token_request("u-lan").event == "REQUESTED"
