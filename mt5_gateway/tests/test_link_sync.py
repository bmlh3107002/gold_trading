"""MT-14 (Gateway 0.4.0): lô nến mang danh tính MT5 đọc trước + sau khi lấy nến; chờ liên kết
mà không thoát, nhịp tim vẫn gửi đều."""

from __future__ import annotations

from mt5_gateway import checks
from mt5_gateway.backend_client import BackendError
from mt5_gateway.sync import Syncer
from tests.fake_mt5 import FakeMt5
from tests.test_gateway import NOW_WINTER, FakeBackend, cfg

IDENT = {"mt5_login": 51234567, "mt5_server": "DemoBroker-Demo", "mt5_account_type": "DEMO",
         "broker_symbol": "XAUUSD"}


def world(be=None, **c):
    fake, be = FakeMt5(now_utc=NOW_WINTER), be or FakeBackend()
    conf = cfg(**c)
    rep = checks.run_checks(conf, fake, be, now=lambda: NOW_WINTER, tick_wait_s=1)
    be.posts.clear()
    t = [0.0]
    sleeps: list[float] = []

    def sleep(s):
        sleeps.append(s)
        t[0] += s

    s = Syncer(conf, rep.reader, be, rep, sleep=sleep, clock=lambda: t[0])
    return fake, be, s, rep, sleeps


def test_every_batch_carries_identity():
    fake, be, s, _, _ = world(timeframes=("M15", "H1"))
    s.backfill()
    s.push_recent()
    assert be.posts and all(p["identity"] == IDENT for p in be.posts)
    assert fake.order_send_called is False


def test_account_switch_during_read_drops_batch():
    fake, be, s, _, _ = world()
    real = fake.copy_rates_from_pos

    def switch_mid_read(*a):
        out = real(*a)
        fake.login = 999  # người dùng đổi tài khoản đúng lúc Gateway đang đọc nến
        return out

    fake.copy_rates_from_pos = switch_mid_read
    loops = iter([False, True])
    s.backfilled = True
    s.run_forever(stop=lambda: next(loops))
    assert be.posts == []  # không gửi nến không rõ thuộc MT5 nào
    assert be.heartbeats  # nhịp tim vẫn đi
    assert s.heartbeat_payload()["identity"]["login"] == 999  # nhịp tim sau báo MT5 mới


def test_logged_out_sends_no_candles_but_heartbeats():
    fake, be, s, _, _ = world()
    fake.account_none = True
    n = iter([False, False, False, True])
    s.run_forever(stop=lambda: next(n))
    assert be.posts == [] and s.backfilled is False
    assert len(be.heartbeats) >= 1 and be.heartbeats[0]["identity"] is None


class LinkGate(FakeBackend):
    """Từ chối nến (409 MT5_LINK_REQUIRED) cho tới khi ``open`` = True."""

    def __init__(self):
        super().__init__()
        self.open = False
        self.refused = 0

    def post_candles(self, **kw):
        if not kw.get("dry_run") and not self.open:
            self.refused += 1
            raise BackendError(409, "MT5_LINK_REQUIRED: Tài khoản chưa liên kết MT5")
        return super().post_candles(**kw)


def test_waits_for_link_without_exiting_and_keeps_heartbeating():
    be = LinkGate()
    _, be, s, _, sleeps = world(be)
    loops = {"n": 0}

    def stop():
        loops["n"] += 1
        if loops["n"] == 12:
            be.open = True  # chủ tài khoản vừa xác nhận trên web
        return loops["n"] > 30

    s.run_forever(stop=stop)
    assert be.refused >= 1
    assert s.backfilled is True  # nạp bù xong sau khi liên kết
    assert any(p["backfill"] for p in be.posts) and any(not p["backfill"] for p in be.posts)
    # nhịp tim vẫn đi trong lúc chờ (heartbeat_seconds = 10, poll = 5)
    assert len(be.heartbeats) >= 5
    assert max(sleeps) <= 5  # chờ liên kết không dồn backoff


def test_link_error_on_higher_tf_backfill_retries_instead_of_dropping_tf():
    class HigherGate(FakeBackend):
        def post_candles(self, **kw):
            if kw.get("timeframe") == "H1" and not kw.get("dry_run"):
                raise BackendError(409, "MT5_LINK_MISMATCH: MT5 khác")
            return super().post_candles(**kw)

    _, be, s, _, _ = world(HigherGate(), timeframes=("M15", "H1"))
    try:
        s.backfill()
        raised = False
    except BackendError:
        raised = True
    assert raised and "H1" in s.higher and s.backfilled is False


class LinkStatusBackend(FakeBackend):
    def __init__(self, status):
        super().__init__()
        self.status = status

    def post_candles(self, **kw):
        out = super().post_candles(**kw)
        if self.status is not None:
            out["link_status"] = self.status
        return out


def test_check_reports_link_status_as_warning_only():
    for status, want in (("ACTIVE", checks.PASS), ("NONE", checks.WARN),
                         ("PENDING_CONFIRM", checks.WARN), ("MISMATCH", checks.WARN)):
        _, _, _, rep, _ = world(LinkStatusBackend(status))
        step = next(x for x in rep.steps if x.name == "Liên kết MT5")
        assert step.status == want and rep.ok  # không chặn `run`: cần nhịp tim để liên kết
    _, _, _, rep, _ = world(LinkStatusBackend(None))  # backend cũ
    assert not any(x.name == "Liên kết MT5" for x in rep.steps)


def test_check_dry_run_sends_identity():
    fake, be2 = FakeMt5(now_utc=NOW_WINTER), FakeBackend()
    checks.run_checks(cfg(), fake, be2, now=lambda: NOW_WINTER, tick_wait_s=1)
    assert be2.posts and all(p["dry_run"] and p["identity"] == IDENT for p in be2.posts)


def test_after_link_block_gateway_backfills_again():
    """Bị chặn lâu (MISMATCH) rồi thông lại → nạp bù lại, không chỉ 20 nến gần nhất."""
    be = LinkGate()
    _, be, s, _, _ = world(be)
    be.open = True
    s.backfill()
    be.open = False  # MT5 bị chặn (vd. MISMATCH)
    k = {"n": 0}

    def stop():
        k["n"] += 1
        if k["n"] == 4:
            be.open = True
        return k["n"] > 20

    be.posts.clear()
    s.run_forever(stop=stop)
    assert any(p["backfill"] for p in be.posts) and s.backfilled


def test_broker_symbol_sent_is_configured_one():
    """MT-05: symbol broker gửi kèm = GT_BROKER_SYMBOL (vd. XAUUSD.r), không phải XAUUSD."""
    fake = FakeMt5(now_utc=NOW_WINTER, symbol="XAUUSD.r")
    be = FakeBackend()
    conf = cfg(broker_symbol="XAUUSD.r")
    rep = checks.run_checks(conf, fake, be, now=lambda: NOW_WINTER, tick_wait_s=1)
    assert rep.ok
    assert be.posts and {p["identity"]["broker_symbol"] for p in be.posts} == {"XAUUSD.r"}
    assert {p["symbol"] for p in be.posts} == {"XAUUSD"}
