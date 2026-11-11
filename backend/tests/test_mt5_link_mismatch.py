"""MT-14 + MT-C08 + 1A-C11: terminal đổi MT5 / đăng xuất khi đã liên kết → MISMATCH /
DISCONNECTED, chặn ghi nến, không tự chuyển sang MT5 mới; xác minh lại hoặc liên kết lại.

Chạy với cả kho bộ nhớ và SQL (SQLite).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.exc import OperationalError

import gold_trading.api.accounts as accounts_mod
from gold_trading.common.time import utcnow
from gold_trading.contracts.candle import DataSource
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.candles import InMemoryCandleStore
from gold_trading.storage.repository import InMemoryRepository, SqlRepository
from tests.auth_helpers import client, login_owner, make_app
from tests.mt5_helpers import FEED, IDENT_FIELDS, LOGIN, SERVER, link_active
from tests.test_ingest_api import AUTH, HB, TOKEN, bars, batch

HB_PATH = "/api/ingest/mt5/heartbeat"
CANDLES = "/api/ingest/mt5/candles"
LINK = "/api/accounts/default/mt5-link"


def ident(login=LOGIN, server=SERVER, account_type="DEMO"):
    return {"login": login, "server": server, "company": "Demo Broker Ltd",
            "account_type": account_type, "terminal_name": "MetaTrader 5",
            "terminal_path": r"C:\MT5"}


def hb(login=LOGIN, server=SERVER, account_type="DEMO"):
    return HB | {"gateway_version": "0.4.0", "server": server, "account_type": account_type,
                 "identity": ident(login, server, account_type)}


HB_LOGGED_OUT = HB | {"gateway_version": "0.4.0", "account_type": "UNKNOWN", "server": None}


@pytest.fixture(params=["memory", "sqlite"])
def repo(request, tmp_path):
    if request.param == "memory":
        return InMemoryRepository()
    r = SqlRepository.from_url(f"sqlite:///{tmp_path / 'gt.db'}")
    r.create_all()
    return r


class World:
    def __init__(self, repo, linked=True):
        self.repo = repo
        self.store = InMemoryCandleStore()
        self.app, self.kc = make_app(repo, candle_store=self.store, data_source=DataSource.MT5,
                                     run_analysts=False, run_sample_feed=False,
                                     ingest_token=TOKEN)
        self.u = login_owner(self.app, self.kc, repo, "trader")
        self.gw = client(self.app)
        self.link = link_active(repo) if linked else None

    def beat(self, body=None):
        r = self.gw.post(HB_PATH, json=body if body is not None else hb(), headers=AUTH)
        assert r.status_code == 200, r.text

    def candles(self, n=5, dry=False, **ident_over):
        body = batch(bars(n), backfill=False) | ident_over
        return self.gw.post(CANDLES + ("?dry_run=true" if dry else ""), json=body, headers=AUTH)

    def state(self):
        r = self.u.get(LINK)
        assert r.status_code == 200, r.text
        return r.json()

    def status(self):
        return self.repo.mt5_links("default")[-1].status

    def count(self):
        return self.store.stats("XAUUSD", Timeframe.M15, DataSource.MT5, feed=FEED).count

    def reverify(self, **over):
        cur = self.state()["current"]
        body = {"link_id": cur["link_id"], "login": cur["login"], "server": cur["server"]}
        return self.u.post(f"{LINK}/reverify", json=body | over)

    def actions(self):
        return [e.action for e in self.repo.audit(500, account_id="default")]


@pytest.fixture
def w(repo):
    return World(repo)


# ---------- Ghi nến chỉ khi khớp liên kết ACTIVE ----------


def test_active_link_matching_candles_accepted(w):
    w.beat()
    r = w.candles()
    assert r.status_code == 200 and r.json()["accepted"] == 5
    assert r.json()["link_status"] == "ACTIVE"


@pytest.mark.parametrize("linked_state", ["none", "pending"])
def test_no_active_link_candles_rejected(repo, linked_state):
    w = World(repo, linked=False)
    if linked_state == "pending":
        w.beat()  # tạo liên kết chờ, chưa xác nhận
        assert w.state()["pending"] is not None
    r = w.candles()
    assert r.status_code == 409 and r.json()["detail"].startswith("MT5_LINK_REQUIRED")
    assert w.count() == 0


def test_candles_without_identity_rejected_partial_identity_422(w):
    body = batch(bars(5), backfill=False)
    for k in IDENT_FIELDS:
        body.pop(k)
    r = w.gw.post(CANDLES, json=body, headers=AUTH)  # Gateway cũ
    assert r.status_code == 409 and r.json()["detail"].startswith("MT5_LINK_REQUIRED")
    assert "0.5.0" in r.json()["detail"]
    r = w.gw.post(CANDLES, json=body | {"mt5_login": LOGIN}, headers=AUTH)
    assert r.status_code == 422
    assert w.count() == 0 and w.status() == "ACTIVE"


def test_dry_run_reports_link_status_without_blocking_or_changing(repo):
    w = World(repo, linked=False)
    r = w.candles(dry=True)
    assert r.status_code == 200 and r.json()["link_status"] == "NONE"
    w.beat()
    assert w.candles(dry=True).json()["link_status"] == "PENDING_CONFIRM"
    assert w.count() == 0


def test_dry_run_mismatch_is_reported_not_persisted(w):
    r = w.candles(dry=True, mt5_login=999)
    assert r.status_code == 200 and r.json()["link_status"] == "MISMATCH"
    assert w.status() == "ACTIVE" and w.count() == 0


# ---------- MT-C08: đổi sang MT5 khác ----------


def test_heartbeat_other_mt5_moves_to_mismatch_and_blocks_candles(w):
    w.beat(hb(login=999))
    assert w.status() == "MISMATCH"
    assert "mt5_link.mismatch" in w.actions()
    st = w.state()
    assert st["current"]["login"] == LOGIN  # KHÔNG tự đổi sang MT5 mới
    assert st["current_effective"] == "MISMATCH" and st["pending"] is None
    assert st["terminal"] == {"login": 999, "server": SERVER, "trade_mode": "DEMO"}
    assert st["terminal_matches_current"] is False
    # Nến từ MT5 mới → chặn
    r = w.candles(mt5_login=999)
    assert r.status_code == 409 and r.json()["detail"].startswith("MT5_LINK_MISMATCH")
    # Nến khai danh tính cũ cũng bị chặn cho tới khi xác minh lại
    r = w.candles()
    assert r.status_code == 409 and r.json()["detail"].startswith("MT5_LINK_MISMATCH")
    assert w.count() == 0
    # Nhịp tim lặp lại không ghi thêm sự kiện
    w.beat(hb(login=999))
    assert w.actions().count("mt5_link.mismatch") == 1


def test_candles_from_other_mt5_before_heartbeat_also_trip_mismatch(w):
    w.beat()
    r = w.candles(mt5_login=999)
    assert r.status_code == 409 and w.status() == "MISMATCH" and w.count() == 0


@pytest.mark.parametrize("change", [{"server": "Other-Live"}, {"account_type": "REAL"},
                                    {"login": LOGIN + 1}])
def test_any_identity_part_change_is_mismatch(w, change):
    """1A-C11: đổi broker / demo → thật / login khác đều là MT5 khác."""
    w.beat(hb(**change))
    assert w.status() == "MISMATCH"


def test_server_case_change_is_same_mt5(w):
    w.beat(hb(server=SERVER.upper()))
    assert w.status() == "ACTIVE"
    assert w.candles(mt5_server=SERVER.lower()).status_code == 200


def test_back_to_old_mt5_still_needs_reverify(w):
    w.beat(hb(login=999))
    w.beat()  # quay về đúng MT5 cũ
    st = w.state()
    assert w.status() == "MISMATCH" and st["terminal_matches_current"] is True
    assert w.candles().status_code == 409
    # Gõ sai login → từ chối
    r = w.reverify(login=LOGIN + 1)
    assert r.status_code == 409 and w.status() == "MISMATCH"
    r = w.reverify()
    assert r.status_code == 200, r.text
    assert r.json()["current"]["status"] == "ACTIVE"
    assert r.json()["current"]["verified_by"] == "trader"
    assert "mt5_link.reverify" in w.actions()
    assert w.candles().status_code == 200 and w.count() == 5


def test_reverify_refused_while_terminal_on_other_mt5_or_stale(w, monkeypatch):
    w.beat(hb(login=999))
    r = w.reverify()
    assert r.status_code == 409 and "Terminal chưa đăng nhập lại" in r.json()["detail"]
    w.beat()
    later = utcnow() + timedelta(seconds=31)
    monkeypatch.setattr(accounts_mod, "utcnow", lambda: later)
    assert w.reverify().status_code == 409  # nhịp tim quá hạn
    assert w.status() == "MISMATCH"


def test_reverify_only_from_mismatch_and_only_owner(w):
    w.beat()
    assert w.reverify().status_code == 409  # đang ACTIVE
    w.beat(hb(login=999))
    w.beat()
    other = login_owner(w.app, w.kc, w.repo, "mallory", "acc_m")
    cur = w.state()["current"]
    body = {"link_id": cur["link_id"], "login": cur["login"], "server": cur["server"]}
    assert other.post(f"{LINK}/reverify", json=body).status_code == 404
    assert other.post("/api/accounts/acc_m/mt5-link/reverify", json=body).status_code == 404
    assert client(w.app).post(f"{LINK}/reverify", json=body).status_code == 401
    assert w.u.post(f"{LINK}/reverify", json=body | {"extra": 1}).status_code == 422
    assert w.status() == "MISMATCH"


def test_reverify_real_needs_acknowledgement(repo):
    w = World(repo, linked=False)
    link_active(repo, trade_mode="REAL")
    w.beat(hb(login=999, account_type="REAL"))
    w.beat(hb(account_type="REAL"))
    assert w.reverify().status_code == 409
    assert w.reverify(acknowledge_real=True).status_code == 200


def test_mt5_c14_relink_to_new_mt5_is_new_link(w):
    """Muốn dùng MT5 mới: gỡ liên kết cũ → liên kết MỚI cần xác nhận; lịch sử cũ giữ riêng."""
    w.beat(hb(login=999))
    old = w.state()["current"]["link_id"]
    r = w.u.post(f"{LINK}/revoke", json={"link_id": old})
    assert r.status_code == 200 and r.json()["history"][0]["status"] == "REVOKED"
    w.beat(hb(login=999))
    p = w.state()["pending"]
    assert p["login"] == 999 and p["link_id"] != old
    assert w.candles(mt5_login=999).status_code == 409  # chưa xác nhận
    r = w.u.post(f"{LINK}/confirm", json={"link_id": p["link_id"], "login": 999,
                                           "server": SERVER})
    assert r.status_code == 200
    assert w.candles(mt5_login=999).status_code == 200
    assert w.candles().status_code == 409  # MT5 cũ giờ là MT5 khác
    assert [x.status for x in w.repo.mt5_links("default")] == ["REVOKED", "MISMATCH"]


def test_mismatched_link_still_holds_mt5_against_other_accounts(w):
    """Đang MISMATCH vẫn giữ MT5 cũ: tài khoản khác không lấy được (MT-C11)."""
    w.beat(hb(login=999))
    bob = login_owner(w.app, w.kc, w.repo, "bob", "acc_b")
    tok = "gtk_" + "b" * 40
    w.repo.rotate_gateway_token("acc_b", tok, "t", utcnow())
    r = w.gw.post(HB_PATH, json=hb(), headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    p = bob.get("/api/accounts/acc_b/mt5-link").json()["pending"]
    r = bob.post("/api/accounts/acc_b/mt5-link/confirm",
                 json={"link_id": p["link_id"], "login": LOGIN, "server": SERVER})
    assert r.status_code == 409


# ---------- Đăng xuất / mất kết nối ----------


def test_logout_disconnected_then_same_mt5_reconnects(w):
    w.beat()
    w.beat(HB_LOGGED_OUT)
    assert w.status() == "DISCONNECTED" and "mt5_link.disconnected" in w.actions()
    assert w.state()["current_effective"] == "DISCONNECTED"
    w.beat(HB_LOGGED_OUT)
    assert w.actions().count("mt5_link.disconnected") == 1
    w.beat()  # đăng nhập lại đúng MT5
    assert w.status() == "ACTIVE" and "mt5_link.reconnected" in w.actions()


def test_disconnected_then_matching_candles_reconnect(w):
    w.beat(HB_LOGGED_OUT)
    r = w.candles()
    assert r.status_code == 200 and w.status() == "ACTIVE"


def test_disconnected_then_other_mt5_is_mismatch(w):
    w.beat(HB_LOGGED_OUT)
    w.beat(hb(login=999))
    assert w.status() == "MISMATCH"


def test_stale_heartbeat_shows_disconnected_without_db_change(w, monkeypatch):
    w.beat()
    assert w.state()["current_effective"] == "ACTIVE"
    later = utcnow() + timedelta(seconds=31)
    monkeypatch.setattr(accounts_mod, "utcnow", lambda: later)
    st = w.state()
    assert st["current_effective"] == "DISCONNECTED" and st["terminal"] is None
    assert w.status() == "ACTIVE"


# ---------- Kho + lỗi ----------


def test_repo_transition_rules(repo):
    link = link_active(repo)
    with pytest.raises(ValueError):
        repo.transition_link("default", link.link_id, "ACTIVE", "REVOKED", utcnow())
    with pytest.raises(ValueError):
        repo.transition_link("default", link.link_id, "ACTIVE", "PENDING_CONFIRM", utcnow())
    assert repo.transition_link("default", link.link_id, "ACTIVE", "MISMATCH", utcnow())
    with pytest.raises(ValueError):  # thoát MISMATCH bắt buộc có người xác minh
        repo.transition_link("default", link.link_id, "MISMATCH", "ACTIVE", utcnow())
    # Kiểm lạc quan: trạng thái đã khác expected → False, không đổi gì
    assert not repo.transition_link("default", link.link_id, "ACTIVE", "DISCONNECTED", utcnow())
    assert not repo.transition_link("acc_nope", link.link_id, "MISMATCH", "ACTIVE", utcnow(),
                                    verified_by="u")
    assert repo.mt5_links("default")[-1].status == "MISMATCH"


def test_db_error_on_link_check_blocks_candles_503(w, monkeypatch):
    def boom(account_id, limit=50):
        raise OperationalError("SELECT", {}, Exception("db down"))

    monkeypatch.setattr(w.repo, "mt5_links", boom)
    r = w.candles()
    assert r.status_code == 503
    monkeypatch.undo()
    assert w.count() == 0
