"""Quản lý lệnh paper đang mở — GĐ5 bước 6d (H8, H7, LED-05 nhả giữ chỗ hết hạn, đỉnh H6).
Thiết kế 35 mục 12.6. Số hồ sơ / broker là **số giả chỉ để test**.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from gold_trading.market.hours import REFERENCE
from gold_trading.risk.blocks import ALL, Block, BlockKind
from gold_trading.risk.ledger import EventType
from gold_trading.risk.paper import PaperMonitor
from tests.test_paper_fill import Paper, q
from tests.test_paper_ledger import KINDS, make_ledger
from tests.test_risk_engine import ACC, FEED, TEST_PROFILE

D = Decimal
S = timedelta(seconds=1)


def _at(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def setup(t0, profile=None):
    p = Paper(t0)
    if profile is not None:
        p.w.profiles.append(ACC, profile, created_by="sub-u", reason="t",
                            at=t0 - timedelta(minutes=1))
    mon = PaperMonitor(p.broker, feed_for=lambda a: FEED,
                       risk_profile=lambda a, t: p.w.profiles.at(a, t),
                       entry_blocks=lambda a, t: p.w.blocks.active(t, FEED),
                       market_calendar=REFERENCE)
    return p, mon


def at(p, t, bid="2410", ask="2410.2"):
    p.at(t)
    p.w.quote = q(t - S, bid, ask)


# ---------------------------------------------------------------- H8 cuối tuần / lễ

@pytest.mark.parametrize("opened,tick,closes", [
    (_at(2026, 1, 9, 20, 0), _at(2026, 1, 9, 21, 29), False),   # thứ Sáu 16:29 NY: còn 31 phút
    (_at(2026, 1, 9, 20, 0), _at(2026, 1, 9, 21, 30), True),    # 16:30 NY (EST): đóng hết
    (_at(2026, 7, 10, 19, 0), _at(2026, 7, 10, 20, 29), False),  # mùa hè (EDT)
    (_at(2026, 7, 10, 19, 0), _at(2026, 7, 10, 20, 30), True),   # 16:30 NY = 20:30 UTC
    (_at(2026, 1, 8, 19, 0), _at(2026, 1, 8, 21, 45), False),   # thứ Năm: nghỉ hằng ngày
])
def test_weekend_closes_all_before_close(opened, tick, closes):              # H8, 5-C07
    p, mon = setup(opened)
    _, _, f = p.open()
    assert f.ok, f
    at(p, tick)
    rep = mon.tick(ACC)
    if closes:
        assert rep.closed == [(f.position_id, "WEEKEND_CLOSE")]
        ev = p.led.events(ACC, (EventType.CLOSE,))[0]
        # đóng chủ động ở bid − đệm = 2410 − 0,30 = 2409,70 → (2409,70 − 2400,50) × 4 = 36,80
        assert D(ev.data["exit_price"]) == D("2409.7") and ev.amount == D("36.8")
        assert p.led.open_positions(ACC, tick) == []
    else:
        assert rep.closed == [] and len(p.led.open_positions(ACC, tick)) == 1


def test_holiday_early_close_closes():
    p, mon = setup(_at(2026, 1, 19, 12, 0))                 # lễ MLK: đóng sớm
    _, _, f = p.open()
    for k in range(0, 600, 5):
        at(p, _at(2026, 1, 19, 12, 0) + timedelta(minutes=k))
        if mon.tick(ACC).closed:
            break
    else:
        raise AssertionError("ngày lễ đóng sớm không đóng lệnh")


def test_unknown_calendar_closes_all(t0):
    p, mon = setup(t0)
    _, _, f = p.open()
    mon.market_calendar = None
    at(p, t0 + minutes(1))
    rep = mon.tick(ACC)
    assert "MARKET_CALENDAR_UNKNOWN" in rep.status and rep.closed == [(f.position_id,
                                                                        "WEEKEND_CLOSE")]


def test_stale_feed_reports_and_keeps_open():
    p, mon = setup(_at(2026, 1, 9, 20, 0))
    p.open()
    p.at(_at(2026, 1, 9, 21, 40))
    p.w.quote = q(_at(2026, 1, 9, 21, 39), "2410", "2410.2")     # cũ 60 giây
    rep = mon.tick(ACC)
    assert rep.status[:2] == ["FEED_STALE", "WEEKEND_CLOSE_WINDOW"] and rep.closed == []
    assert len(p.led.open_positions(ACC, p.w.now)) == 1          # không bịa giá để đóng


# ---------------------------------------------------------------- H7 tin HIGH

def minutes(n):
    return timedelta(minutes=n)


def news(t, code="CALENDAR_HIGH", kind=BlockKind.RELEASE):
    return Block(kind, ALL, code, t, t + minutes(30), f"cal:{code}:{t.isoformat()}", t, "p0")


@pytest.mark.parametrize("code,kind,closes", [
    ("CALENDAR_HIGH", BlockKind.RELEASE, True),
    ("RELEASE_HIGH_RECEIVED", BlockKind.RELEASE, True),
    ("FED_UNSCHEDULED_POLICY", BlockKind.NEWS, True),
    ("CALENDAR_MEDIUM", BlockKind.RELEASE, False),
    ("WIDE_SPREAD", BlockKind.SPREAD, False),
])
def test_news_close_all_policy(t0, code, kind, closes):                    # H7 (CLOSE_ALL)
    p, mon = setup(t0)                                     # hồ sơ test: CLOSE_ALL
    _, _, f = p.open()
    p.w.blocks.add(news(t0 + minutes(1), code, kind))
    at(p, t0 + minutes(1))
    rep = mon.tick(ACC)
    assert (rep.closed == [(f.position_id, "NEWS_CLOSE")]) is closes, rep


@pytest.mark.parametrize("sl,kept", [("2400.8", True), ("2400.7", False), (None, False)])
def test_news_keep_safe_only(t0, sl, kept):                                 # H7 (người dùng chốt)
    p, mon = setup(t0, replace(TEST_PROFILE, news_hold_policy="KEEP_SAFE_ONLY"))
    _, _, f = p.open()
    # an toàn = SL ≥ giá vào 2400,50 + đệm 0,30 + phí 0 → 2400,80 (rủi ro còn lại ≤ 0)
    if sl is not None:
        at(p, t0 + minutes(1), "2405", "2405.2")
        assert p.broker.modify_sl(ACC, f.position_id, D(sl), actor="t", reason="hòa vốn")
    p.w.blocks.add(news(t0 + minutes(2)))
    at(p, t0 + minutes(2), "2405", "2405.2")
    rep = mon.tick(ACC)
    assert (rep.closed == []) is kept, rep


def test_profile_unreadable_uses_safest_policy(t0):
    p, mon = setup(t0, replace(TEST_PROFILE, news_hold_policy="KEEP_SAFE_ONLY"))
    _, _, f = p.open()
    at(p, t0 + minutes(1), "2405", "2405.2")
    p.broker.modify_sl(ACC, f.position_id, D("2401"), actor="t", reason="hòa vốn")

    def boom(a, t):
        raise OSError("db")
    mon.risk_profile = boom
    p.w.blocks.add(news(t0 + minutes(2)))
    at(p, t0 + minutes(2), "2405", "2405.2")
    rep = mon.tick(ACC)
    assert "RISK_PROFILE_UNKNOWN" in rep.status and rep.closed == [(f.position_id, "NEWS_CLOSE")]


def test_block_read_error_counts_as_news(t0):
    p, mon = setup(t0)
    _, _, f = p.open()

    def boom(a, t):
        raise OSError("db")
    mon.entry_blocks = boom
    at(p, t0 + minutes(1))
    rep = mon.tick(ACC)
    assert "NEWS_UNKNOWN" in rep.status and rep.closed == [(f.position_id, "NEWS_CLOSE")]


# ---------------------------------------------------------------- giữ chỗ hết hạn + đỉnh

def test_expired_reservation_released_with_compensating_event(t0):        # LED-05
    p, mon = setup(t0)
    d = p.w.evaluate()                                     # duyệt nhưng "crash" trước khi khớp
    assert p.led.reserved_total(ACC) == d.risk_amount
    at(p, t0 + 29 * S)
    assert mon.tick(ACC).released == []                    # còn hạn (30 giây)
    at(p, d.expires_at)
    rep = mon.tick(ACC)
    assert rep.released == [d.reservation_id] and p.led.reserved_total(ACC) == 0
    rel = p.led.events(ACC, (EventType.RELEASE,))[0]
    res = p.led.events(ACC, (EventType.RESERVE,))[0]
    assert (rel.reason, rel.actor, rel.links, rel.amount) == (
        "RESERVATION_EXPIRED", "system", res.event_id, -res.amount)
    assert mon.tick(ACC).released == []                    # một lần


def test_peak_marked_with_unrealized_gain(t0):
    p, mon = setup(t0)
    p.open()
    at(p, t0 + minutes(1), "2450", "2450.2")
    rep = mon.tick(ACC)
    # (2450 − 2400,50) × 100 × 0,04 = 198 → đỉnh 10.198
    assert rep.peak == D("10198")
    at(p, t0 + minutes(2), "2440", "2440.2")
    assert mon.tick(ACC).peak is None                      # thấp hơn đỉnh → không ghi
    assert p.led.equity_state(ACC, p.w.now).peak == D("10198")


def test_sl_tp_closed_in_tick(t0):
    p, mon = setup(t0)
    _, _, f = p.open()
    p.quotes = [q(t0 + 5 * S, "2390.5", "2390.7", bid_low="2389")]
    at(p, t0 + minutes(1))
    assert mon.tick(ACC).closed == [(f.position_id, "STOP_LOSS")]


@pytest.mark.parametrize("kind", [k for k in KINDS if k != "memory"])
def test_monitor_on_sql(kind, tmp_path):
    t = _at(2026, 1, 9, 20, 0)
    p = Paper(t, make_ledger(kind, tmp_path, "m.db"))
    mon = PaperMonitor(p.broker, feed_for=lambda a: FEED,
                       risk_profile=lambda a, x: p.w.profiles.at(a, x),
                       entry_blocks=lambda a, x: p.w.blocks.active(x, FEED),
                       market_calendar=REFERENCE)
    _, _, f = p.open()
    at(p, _at(2026, 1, 9, 21, 30))
    rep = mon.tick(ACC)
    assert (f.position_id, "WEEKEND_CLOSE") in rep.closed
    assert p.led.open_positions(ACC, p.w.now) == [] and p.led.reserved_total(ACC) == 0
    st = p.led.equity_state(ACC, p.w.now)
    assert st.realized == D("10036.8")                       # 10.000 + 36,80 (tính tay ở trên)
