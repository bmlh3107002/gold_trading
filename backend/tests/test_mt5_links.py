"""MT-13: liên kết tài khoản giao dịch ↔ MT5 ``(login, server)`` + case MT-C11.

Luồng: Gateway báo danh tính → PENDING_CONFIRM → USER gõ lại login → ACTIVE. Trường hợp xấu:
gõ sai login/server, terminal đổi MT5 / đăng xuất / mất nhịp tim trước khi xác nhận, MT5 đã liên
kết ở tài khoản khác (MT-C11, kể cả qua index DB), REAL không đánh dấu, tài khoản UNKNOWN, gửi
trường lạ, USER khác / ADMIN / ẩn danh, gỡ khi LIVE, xóa USER trả MT5 về chưa liên kết. Chạy với
cả kho bộ nhớ và SQL (SQLite).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from gold_trading.common.enums import TradingMode
from gold_trading.common.time import utcnow
from gold_trading.contracts.candle import DataSource
from gold_trading.storage.repository import (
    InMemoryRepository,
    Mt5Link,
    Mt5LinkError,
    SqlRepository,
    TradingAccount,
)
from gold_trading.storage.schema import mt5_links
from tests.auth_helpers import client, login_owner, make_app
from tests.test_ingest_api import HB

HB_PATH = "/api/ingest/mt5/heartbeat"
TOK_A = "gtk_" + "a" * 40
TOK_B = "gtk_" + "b" * 40


def ident(login=51234567, server="Broker-Demo", account_type="DEMO"):
    return {"login": login, "server": server, "company": "Demo Broker Ltd",
            "account_type": account_type, "terminal_name": "MetaTrader 5",
            "terminal_path": r"C:\MT5"}


def hb(login=51234567, server="Broker-Demo", account_type="DEMO", gateway_id="win-1"):
    return HB | {"gateway_version": "0.3.0", "gateway_id": gateway_id, "server": server,
                 "account_type": account_type,
                 "identity": ident(login, server, account_type)}


@pytest.fixture(params=["memory", "sqlite"])
def repo(request, tmp_path):
    if request.param == "memory":
        return InMemoryRepository()
    r = SqlRepository.from_url(f"sqlite:///{tmp_path / 'gt.db'}")
    r.create_all()
    return r


class World:
    def __init__(self, repo):
        self.repo = repo
        self.app, self.kc = make_app(repo, data_source=DataSource.MT5, run_analysts=False,
                                     run_sample_feed=False)
        self.a = login_owner(self.app, self.kc, repo, "alice", "acc_a")
        self.b = login_owner(self.app, self.kc, repo, "bob", "acc_b")
        self.tok_a = repo.rotate_gateway_token("acc_a", TOK_A, "t", utcnow())
        repo.rotate_gateway_token("acc_b", TOK_B, "t", utcnow())

    def beat(self, tok=TOK_A, **kw):
        r = client(self.app).post(HB_PATH, json=hb(**kw), headers={"Authorization":
                                                                   f"Bearer {tok}"})
        assert r.status_code == 200, r.text
        return r

    def state(self, c=None, acc="acc_a"):
        r = (c or self.a).get(f"/api/accounts/{acc}/mt5-link")
        assert r.status_code == 200, r.text
        return r.json()

    def confirm(self, c=None, acc="acc_a", **body):
        st = self.state(c, acc)
        base = {"link_id": st["pending"]["link_id"], "login": st["pending"]["login"],
                "server": st["pending"]["server"]}
        return (c or self.a).post(f"/api/accounts/{acc}/mt5-link/confirm", json=base | body)


@pytest.fixture
def w(repo):
    return World(repo)


def actions(repo, acc):
    return [(e.action, e.outcome) for e in repo.audit(500, account_id=acc)]


# ---------- Luồng chuẩn ----------


def test_no_identity_no_link(w):
    st = w.state()
    assert st == {"current": None, "pending": None, "terminal_matches_pending": False,
                  "history": [], "current_effective": None, "terminal": None,
                  "terminal_matches_current": False}
    # Gateway cũ (không có identity) và terminal chưa đăng nhập → không tạo gì
    client(w.app).post(HB_PATH, json=HB, headers={"Authorization": f"Bearer {TOK_A}"})
    assert w.state()["pending"] is None


def test_heartbeat_creates_one_pending_then_owner_confirms(w):
    for _ in range(3):  # nhịp tim lặp lại không tạo thêm liên kết chờ
        w.beat()
    st = w.state()
    p = st["pending"]
    assert st["current"] is None and st["terminal_matches_pending"] is True
    assert (p["login"], p["server"], p["company"], p["trade_mode"], p["status"],
            p["gateway_id"]) == (51234567, "Broker-Demo", "Demo Broker Ltd", "DEMO",
                                 "PENDING_CONFIRM", "win-1")
    assert len(w.repo.mt5_links("acc_a")) == 1
    assert w.repo.mt5_links("acc_a")[0].token_id == w.tok_a  # gắn đúng token đã gửi
    assert actions(w.repo, "acc_a").count(("mt5_link.pending", "ACCEPTED")) == 1

    r = w.confirm()
    assert r.status_code == 200, r.text
    cur = r.json()["current"]
    assert cur["status"] == "ACTIVE" and cur["verified_by"] == "alice"
    assert cur["verified_at"] is not None and r.json()["pending"] is None
    assert ("mt5_link.confirm", "ACCEPTED") in actions(w.repo, "acc_a")
    # Đã ACTIVE: nhịp tim cùng MT5 không tạo liên kết chờ
    w.beat()
    assert w.state()["pending"] is None and len(w.repo.mt5_links("acc_a")) == 1


def test_link_only_for_token_account(w):
    """Token của B chỉ tạo liên kết cho B, dù A đang xem."""
    w.beat(tok=TOK_B, login=777)
    assert w.state()["pending"] is None
    assert w.state(w.b, "acc_b")["pending"]["login"] == 777


# ---------- Xác nhận: trường hợp xấu ----------


@pytest.mark.parametrize("body", [{"login": 51234568}, {"server": "Broker-Live"},
                                  {"login": 1, "server": "x"}])
def test_typed_login_or_server_mismatch_rejected(w, body):
    w.beat()
    r = w.confirm(**body)
    assert r.status_code == 409 and "không khớp" in r.json()["detail"]
    assert w.state()["current"] is None
    assert ("mt5_link.confirm", "REJECTED") in actions(w.repo, "acc_a")


def test_terminal_switched_before_confirm_replaces_pending(w):
    w.beat()
    old = w.state()["pending"]["link_id"]
    w.beat(login=999)  # người dùng đổi tài khoản trong terminal trước khi xác nhận
    st = w.state()
    assert st["pending"]["login"] == 999 and st["pending"]["link_id"] != old
    assert st["history"][0]["link_id"] == old and st["history"][0]["status"] == "CANCELLED"
    assert st["history"][0]["end_reason"] == "REPLACED"
    # Xác nhận liên kết cũ (đã hủy) → từ chối
    r = w.a.post("/api/accounts/acc_a/mt5-link/confirm",
                 json={"link_id": old, "login": 51234567, "server": "Broker-Demo"})
    assert r.status_code == 409


def test_terminal_logged_out_or_stale_cannot_confirm(w, monkeypatch):
    w.beat()
    # Đăng xuất: nhịp tim không còn identity
    client(w.app).post(HB_PATH, json=HB | {"account_type": "UNKNOWN", "server": None},
                       headers={"Authorization": f"Bearer {TOK_A}"})
    assert w.state()["terminal_matches_pending"] is False
    r = w.confirm()
    assert r.status_code == 409 and "Terminal" in r.json()["detail"]
    # Đăng nhập lại đúng MT5 → được; nhưng nếu nhịp tim quá hạn (Gateway tắt) → không
    w.beat()
    import gold_trading.api.accounts as accounts_mod

    later = utcnow() + timedelta(seconds=31)
    monkeypatch.setattr(accounts_mod, "utcnow", lambda: later)
    assert w.state()["terminal_matches_pending"] is False
    assert w.confirm().status_code == 409
    assert w.state()["current"] is None


def test_real_account_needs_explicit_acknowledgement(w):
    w.beat(account_type="REAL", server="Broker-Live")
    r = w.confirm()
    assert r.status_code == 409 and "TIỀN THẬT" in r.json()["detail"]
    assert w.state()["current"] is None
    r = w.confirm(acknowledge_real=True)
    assert r.status_code == 200 and r.json()["current"]["trade_mode"] == "REAL"


def test_unknown_account_type_never_linked(w):
    """Danh tính có nhưng loại tài khoản không rõ → không tạo liên kết (không đoán DEMO/REAL)."""
    w.beat(account_type="UNKNOWN")
    assert w.state()["pending"] is None


def test_extra_fields_and_bad_values_rejected(w):
    w.beat()
    assert w.confirm(verified_by="mallory").status_code == 422
    assert w.confirm(login=0).status_code == 422
    assert w.confirm(login=-5).status_code == 422
    assert w.confirm(server="").status_code == 422
    assert w.state()["current"] is None


def test_unknown_link_id_404(w):
    w.beat()
    r = w.a.post("/api/accounts/acc_a/mt5-link/confirm",
                 json={"link_id": "mtl_nope", "login": 51234567, "server": "Broker-Demo"})
    assert r.status_code == 404


# ---------- MT-C11: cùng (login, server) ở tài khoản thứ hai ----------


def test_same_mt5_cannot_be_active_in_two_accounts(w):
    w.beat()
    assert w.confirm().status_code == 200
    # B chạy Gateway trên cùng MT5 (cùng login + server)
    w.beat(tok=TOK_B)
    assert w.state(w.b, "acc_b")["pending"]["login"] == 51234567
    r = w.confirm(w.b, "acc_b")
    assert r.status_code == 409 and "tài khoản giao dịch khác" in r.json()["detail"]
    assert "acc_a" not in r.text and "alice" not in r.text  # không lộ tài khoản kia
    assert w.state(w.b, "acc_b")["current"] is None
    # Cùng login nhưng KHÁC server = MT5 khác → được
    w.beat(tok=TOK_B, server="Other-Demo")
    assert w.confirm(w.b, "acc_b").status_code == 200
    # A gỡ liên kết → MT5 đó liên kết được ở tài khoản khác (liên kết MỚI, cần xác nhận lại)
    cur = w.state()["current"]
    assert w.a.post("/api/accounts/acc_a/mt5-link/revoke",
                    json={"link_id": cur["link_id"]}).status_code == 200


def test_db_index_blocks_second_held_link_even_bypassing_checks(repo):
    """Lớp phòng thủ cuối: dù code kiểm tra có lỗi, DB không cho hai liên kết giữ cùng MT5."""
    if not isinstance(repo, SqlRepository):
        pytest.skip("chỉ kho SQL có index")
    now = utcnow()
    repo.create_account(TradingAccount("acc_x", "X", now, "t", price_feed=False))
    repo.create_account(TradingAccount("acc_y", "Y", now, "t", price_feed=False))
    row = dict(mt5_login=1, mt5_server="S", mt5_company=None, trade_mode="DEMO",
               gateway_id="g", token_id=None, status="ACTIVE", created_at=now)
    with repo.engine.begin() as conn:
        conn.execute(insert(mt5_links).values(link_id="l1", account_id="acc_x", **row))
    with pytest.raises(IntegrityError), repo.engine.begin() as conn:
        conn.execute(insert(mt5_links).values(link_id="l2", account_id="acc_y", **row))
    with pytest.raises(IntegrityError), repo.engine.begin() as conn:  # 2 liên kết giữ / tài khoản
        conn.execute(insert(mt5_links).values(link_id="l3", account_id="acc_x",
                                              **(row | {"mt5_login": 2})))
    pend = row | {"status": "PENDING_CONFIRM", "mt5_login": 5}
    with repo.engine.begin() as conn:
        conn.execute(insert(mt5_links).values(link_id="l4", account_id="acc_y", **pend))
    with pytest.raises(IntegrityError), repo.engine.begin() as conn:  # 2 liên kết chờ / tài khoản
        conn.execute(insert(mt5_links).values(link_id="l5", account_id="acc_y",
                                              **(pend | {"mt5_login": 6})))
    with pytest.raises(IntegrityError), repo.engine.begin() as conn:  # login phải > 0
        conn.execute(insert(mt5_links).values(link_id="l6", account_id="acc_y",
                                              **(row | {"mt5_login": 0, "status": "REVOKED"})))
    with pytest.raises(IntegrityError), repo.engine.begin() as conn:  # trạng thái lạ
        conn.execute(insert(mt5_links).values(link_id="l7", account_id="acc_y",
                                              **(row | {"mt5_login": 7, "status": "WHATEVER"})))


def test_repo_confirm_conflicts(repo):
    now = utcnow()
    for a in ("acc_x", "acc_y"):
        repo.create_account(TradingAccount(a, a, now, "t", price_feed=False))

    def pending(acc, login=1, server="S"):
        link = Mt5Link(f"l-{acc}-{login}-{server}", acc, login, server, None, "DEMO", "g", None,
                       "PENDING_CONFIRM", now)
        assert repo.add_pending_link(link)
        return link

    lx, ly = pending("acc_x"), pending("acc_y")
    repo.confirm_link("acc_x", lx.link_id, "u", now)
    with pytest.raises(Mt5LinkError) as e:
        repo.confirm_link("acc_y", ly.link_id, "u", now)
    assert e.value.code == "IDENTITY_HELD"
    with pytest.raises(Mt5LinkError) as e:  # link của tài khoản khác → như không tồn tại
        repo.confirm_link("acc_y", lx.link_id, "u", now)
    assert e.value.code == "NOT_FOUND"
    with pytest.raises(Mt5LinkError) as e:
        repo.confirm_link("acc_x", lx.link_id, "u", now)
    assert e.value.code == "NOT_PENDING"
    # Đang giữ liên kết → không tạo liên kết chờ (MT5 khác: MT-14 xử lý)
    assert not repo.add_pending_link(Mt5Link("l-z", "acc_x", 9, "S", None, "DEMO", "g", None,
                                             "PENDING_CONFIRM", now))
    with pytest.raises(ValueError):
        repo.add_pending_link(Mt5Link("l-bad", "acc_y", 0, "S", None, "DEMO", "g", None,
                                      "PENDING_CONFIRM", now))
    with pytest.raises(ValueError):
        repo.add_pending_link(Mt5Link("l-bad2", "acc_y", 5, "S", None, "UNKNOWN", "g", None,
                                      "PENDING_CONFIRM", now))
    with pytest.raises(ValueError):
        repo.add_pending_link(Mt5Link("l-bad3", "acc_y", 5, "S", None, "DEMO", "g", None,
                                      "ACTIVE", now))
    with pytest.raises(KeyError):
        repo.add_pending_link(Mt5Link("l-bad4", "acc_nope", 5, "S", None, "DEMO", "g", None,
                                      "PENDING_CONFIRM", now))
    # Kết thúc liên kết đã kết thúc → NOT_OPEN
    repo.end_link("acc_x", lx.link_id, "REVOKED", "u", now, "OWNER_REVOKED")
    with pytest.raises(Mt5LinkError) as e:
        repo.end_link("acc_x", lx.link_id, "REVOKED", "u", now, "again")
    assert e.value.code == "NOT_OPEN"
    # Sau khi gỡ: tài khoản y xác nhận được (giữ nguyên lịch sử của x)
    assert repo.confirm_link("acc_y", ly.link_id, "u", now).status == "ACTIVE"
    assert [x.status for x in repo.mt5_links("acc_x")] == ["REVOKED"]


# ---------- Gỡ liên kết ----------


def test_revoke_and_relink_creates_new_link(w):
    w.beat()
    w.confirm()
    cur = w.state()["current"]
    r = w.a.post("/api/accounts/acc_a/mt5-link/revoke", json={"link_id": cur["link_id"]})
    assert r.status_code == 200
    st = r.json()
    assert st["current"] is None and st["history"][0]["status"] == "REVOKED"
    assert st["history"][0]["end_reason"] == "OWNER_REVOKED"
    # Gỡ lần hai → 409
    assert w.a.post("/api/accounts/acc_a/mt5-link/revoke",
                    json={"link_id": cur["link_id"]}).status_code == 409
    # Nhịp tim kế tiếp → liên kết MỚI (link_id khác), phải xác nhận lại (MT-C14 phần dữ liệu)
    w.beat()
    st = w.state()
    assert st["current"] is None and st["pending"]["link_id"] != cur["link_id"]
    assert w.confirm().status_code == 200
    assert len(w.repo.mt5_links("acc_a")) == 2


def test_decline_pending(w):
    w.beat()
    p = w.state()["pending"]
    r = w.a.post("/api/accounts/acc_a/mt5-link/revoke", json={"link_id": p["link_id"]})
    assert r.status_code == 200 and r.json()["history"][0]["status"] == "CANCELLED"
    assert r.json()["history"][0]["end_reason"] == "OWNER_DECLINED"


def test_revoke_blocked_while_live(w):
    w.beat()
    w.confirm()
    rt = w.app.state.registry.get("acc_a")
    rt.modes._mode = TradingMode.LIVE  # mô phỏng đang LIVE (bật LIVE thật cần ADMIN duyệt)
    cur = w.state()["current"]
    r = w.a.post("/api/accounts/acc_a/mt5-link/revoke", json={"link_id": cur["link_id"]})
    assert r.status_code == 409 and "LIVE" in r.json()["detail"]
    assert w.state()["current"]["status"] == "ACTIVE"


# ---------- Quyền ----------


def test_other_user_admin_anonymous_cannot_touch_link(w):
    w.beat()
    p = w.state()["pending"]
    body = {"link_id": p["link_id"], "login": p["login"], "server": p["server"]}
    admin = client(w.app)
    w.kc.login(admin, "root", admin=True)
    for c, code in ((w.b, 404), (admin, 404), (client(w.app), 401)):
        assert c.get("/api/accounts/acc_a/mt5-link").status_code == code
        assert c.post("/api/accounts/acc_a/mt5-link/confirm", json=body).status_code == code
        assert c.post("/api/accounts/acc_a/mt5-link/revoke",
                      json={"link_id": p["link_id"]}).status_code == code
    # B dùng link_id của A trên tài khoản của mình → không tìm thấy
    assert w.b.post("/api/accounts/acc_b/mt5-link/confirm", json=body).status_code == 404
    assert w.state()["pending"]["status"] == "PENDING_CONFIRM"


def test_locked_user_gateway_cannot_create_pending(w):
    w.repo.set_user_status(w.a.sub, "LOCKED", utcnow())
    r = client(w.app).post(HB_PATH, json=hb(), headers={"Authorization": f"Bearer {TOK_A}"})
    assert r.status_code == 403
    assert w.repo.mt5_links("acc_a") == []


def test_delete_user_releases_mt5(w):
    w.beat()
    w.confirm()
    admin = client(w.app)
    w.kc.login(admin, "root", admin=True)
    # Gateway phải tắt trước khi xóa: cho nhịp tim quá hạn
    import gold_trading.api.users as users_mod

    real = users_mod.utcnow
    later = real() + timedelta(minutes=2)
    users_mod.utcnow = lambda: later
    try:
        r = admin.delete(f"/api/admin/users/{w.a.sub}")
    finally:
        users_mod.utcnow = real
    assert r.status_code == 200, r.text
    assert [x.status for x in w.repo.mt5_links("acc_a")] == ["REVOKED"]
    # MT5 đó giờ liên kết được ở tài khoản B
    w.beat(tok=TOK_B)
    assert w.confirm(w.b, "acc_b").status_code == 200


def test_db_error_while_creating_pending_does_not_break_heartbeat(w, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def boom(link):
        raise OperationalError("x", {}, Exception("disk full"))

    monkeypatch.setattr(w.repo, "add_pending_link", boom)
    w.beat()  # vẫn 200
    monkeypatch.undo()
    assert w.repo.mt5_links("acc_a") == []


# ---------- Lách MT-C11 bằng tên server (tìm được khi soát lại) ----------


@pytest.mark.parametrize("server", [" Broker-Demo", "Broker-Demo ", "Broker\tDemo",
                                    "Broker-Demo\n", "Broker​-Demo"])
def test_non_canonical_server_never_linked(w, server):
    w.beat(server=server)
    assert w.state()["pending"] is None and w.repo.mt5_links("acc_a") == []


def test_server_case_variant_is_same_mt5(w):
    w.beat()
    assert w.confirm().status_code == 200
    w.beat(tok=TOK_B, server="BROKER-demo")
    r = w.confirm(w.b, "acc_b")
    assert r.status_code == 409 and "tài khoản giao dịch khác" in r.json()["detail"]


def test_db_index_case_insensitive(repo):
    if not isinstance(repo, SqlRepository):
        pytest.skip("chỉ kho SQL có index")
    now = utcnow()
    for a in ("acc_x", "acc_y"):
        repo.create_account(TradingAccount(a, a, now, "t", price_feed=False))
    row = dict(mt5_login=1, mt5_company=None, trade_mode="DEMO", gateway_id="g", token_id=None,
               status="ACTIVE", created_at=now)
    with repo.engine.begin() as conn:
        conn.execute(insert(mt5_links).values(link_id="l1", account_id="acc_x",
                                              mt5_server="Srv", **row))
    with pytest.raises(IntegrityError), repo.engine.begin() as conn:
        conn.execute(insert(mt5_links).values(link_id="l2", account_id="acc_y",
                                              mt5_server="sRV", **row))
