"""Quản lý lệnh của chiến lược v1 — thiết kế 36 mục 5 (dời hòa vốn P9, đóng 16:45 NY P10).

Số broker / hồ sơ GIẢ chỉ để test (``test_risk_engine``): khớp BUY 0,04 lot ở 2.400,50
(ask 2.400,20 + đệm 0,30), SL 2.390 → khoảng SL ban đầu R = 10,50.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from gold_trading.market.hours import REFERENCE
from gold_trading.risk.paper import PaperMonitor
from gold_trading.strategy.trend_m15 import STRATEGY_REF, Manager, time_stop_at
from tests.factories import intent
from tests.test_paper_fill import Paper, q
from tests.test_paper_monitor import news
from tests.test_risk_engine import ACC, FEED, TEST_PROFILE

D = Decimal
S = timedelta(seconds=1)


def setup(t0, profile=None, strategy=STRATEGY_REF):
    p = Paper(t0)
    if profile is not None:
        p.w.profiles.append(ACC, profile, created_by="sub-u", reason="t",
                            at=t0 - timedelta(minutes=1))
    mon = PaperMonitor(p.broker, feed_for=lambda a: FEED,
                       risk_profile=lambda a, t: p.w.profiles.at(a, t),
                       entry_blocks=lambda a, t: p.w.blocks.active(t, FEED),
                       market_calendar=REFERENCE, managers=(Manager(),))
    _, _, f = p.open(intent(t0 - timedelta(seconds=30), strategy_id=strategy))
    assert f.ok, f
    return p, mon, f.position_id


def _u(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def at(p, t, bid, ask=None):
    p.at(t)
    p.w.quote = q(t - S, bid, ask or str(D(bid) + D("0.2")))


@pytest.mark.parametrize("bid,moved", [("2410.99", False), ("2411.00", True)])
def test_break_even_after_one_r(t0, bid, moved):                      # P9
    p, mon, pid = setup(t0)
    at(p, t0 + timedelta(minutes=15), bid)
    rep = mon.tick(ACC)
    # 1 R = 10,50 → kích hoạt khi bid ≥ 2.411,00; SL mới = 2.400,50 + 0,30 + 0 = 2.400,80
    assert rep.moved == ([(pid, D("2400.80"))] if moved else [])
    sl = p.led.open_positions(ACC, p.w.now)[0].stop_loss
    assert sl == (D("2400.80") if moved else D("2390.0"))
    at(p, t0 + timedelta(minutes=16), "2420")
    again = mon.tick(ACC).moved
    if moved:
        assert again == []                                     # một lần, không trailing
    else:
        assert again == [(pid, D("2400.80"))]                  # tới 1 R mới dời


def test_break_even_includes_commission(t0):
    p = Paper(t0)
    p.w.commission = replace(p.w.commission, per_lot=D(7))
    mon = PaperMonitor(p.broker, feed_for=lambda a: FEED, risk_profile=lambda a, t: None,
                       entry_blocks=lambda a, t: [], market_calendar=REFERENCE,
                       managers=(Manager(),))
    d = p.w.evaluate(intent(t0 - timedelta(seconds=30), strategy_id=STRATEGY_REF), keep_key=True)
    f = p.broker.fill(d, intent(t0 - timedelta(seconds=30), strategy_id=STRATEGY_REF,
                                intent_id=d.intent_id), FEED)
    assert f.ok, f
    at(p, t0 + timedelta(minutes=15), "2412")
    # 2.400,50 + 0,30 + 7 / 100 = 2.400,87
    assert mon.tick(ACC).moved == [(f.position_id, D("2400.87"))]


def test_be_makes_position_safe_for_high_news(t0):                    # P9 + H7
    p, mon, pid = setup(t0, replace(TEST_PROFILE, news_hold_policy="KEEP_SAFE_ONLY"))
    at(p, t0 + timedelta(minutes=15), "2412")
    mon.tick(ACC)
    p.w.blocks.add(news(t0 + timedelta(minutes=20)))
    at(p, t0 + timedelta(minutes=20), "2412")
    assert mon.tick(ACC).closed == []                            # đã an toàn → giữ qua tin


@pytest.mark.parametrize("opened,stop", [
    (_u(2026, 1, 5, 14, 0), _u(2026, 1, 5, 21, 45)),      # EST
    (_u(2026, 7, 6, 13, 0), _u(2026, 7, 6, 20, 45)),      # EDT
    (_u(2026, 3, 9, 12, 0), _u(2026, 3, 9, 20, 45)),      # ngay sau đổi giờ 8/3
    (_u(2026, 1, 5, 22, 0), _u(2026, 1, 6, 21, 45)),      # mở sau 16:45 → hôm sau
])
def test_time_stop_at_follows_dst(opened, stop):                      # P10
    assert time_stop_at(opened) == stop


@pytest.mark.parametrize("minute,closes", [(44, False), (45, True)])
def test_time_stop_closes_at_1645_new_york(t0, minute, closes):       # P10
    p, mon, pid = setup(t0)                                      # mở thứ Hai 09:00 NY
    at(p, datetime(2026, 1, 5, 21, minute, tzinfo=UTC), "2405")
    rep = mon.tick(ACC)
    assert (rep.closed == [(pid, "TIME_STOP")]) is closes
    if closes:
        # đóng chủ động ở bid − đệm: (2.404,70 − 2.400,50) × 100 × 0,04 = 16,80
        assert p.led.closed_trades(ACC, t0, p.w.now)[0].net_pnl == D("16.8")


def test_other_strategy_positions_untouched(t0):
    p, mon, pid = setup(t0, strategy="tay-test")
    at(p, datetime(2026, 1, 5, 21, 50, tzinfo=UTC), "2415")
    rep = mon.tick(ACC)
    assert rep.closed == [] and rep.moved == []


def test_stale_quote_no_management(t0):
    p, mon, pid = setup(t0)
    p.at(datetime(2026, 1, 5, 21, 50, tzinfo=UTC))
    p.w.quote = q(p.w.now - timedelta(seconds=30), "2415", "2415.2")
    rep = mon.tick(ACC)
    assert "FEED_STALE" in rep.status and rep.closed == [] and rep.moved == []


def test_manager_error_keeps_position_and_reports(t0):
    p, mon, pid = setup(t0)

    class Boom:
        def action(self, *a):
            raise RuntimeError("x")
    mon.managers = (Boom(),)
    at(p, t0 + timedelta(minutes=15), "2412")
    rep = mon.tick(ACC)
    assert "MANAGER_ERROR" in rep.status and rep.closed == []
    assert len(p.led.open_positions(ACC, p.w.now)) == 1


def test_sell_break_even(t0):
    p = Paper(t0)
    p.w.profiles.append(ACC, replace(TEST_PROFILE, pyramiding_policy="NONE"), created_by="u",
                        reason="t", at=t0 - timedelta(minutes=1))
    from gold_trading.common.enums import Bias, Side
    from tests.factories import market_view
    p.w.views.append(market_view(t0 - timedelta(minutes=1), market_view_id="mvS",
                                 bias=Bias.SHORT), report_id="r2",
                  computed_at=t0 - timedelta(minutes=1))
    i = intent(t0 - timedelta(seconds=30), strategy_id=STRATEGY_REF, side=Side.SELL,
               market_view_id="mvS", stop_loss=2410.0, take_profit=2380.0)
    d = p.w.evaluate(i, keep_key=True)
    f = p.broker.fill(d, i, FEED)
    assert f.ok, (d.reason_codes, f)
    # khớp SELL = bid 2.400,00 − 0,30 = 2.399,70; R = 10,30 → kích hoạt khi ask ≤ 2.389,40
    mon = PaperMonitor(p.broker, feed_for=lambda a: FEED, risk_profile=lambda a, t: None,
                       entry_blocks=lambda a, t: [], market_calendar=REFERENCE,
                       managers=(Manager(),))
    at(p, t0 + timedelta(minutes=15), "2389.2", "2389.4")
    assert mon.tick(ACC).moved == [(f.position_id, D("2399.40"))]   # 2.399,70 − 0,30
