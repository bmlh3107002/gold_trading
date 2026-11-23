"""GĐ6 bước 5 — mô phỏng giao dịch theo nến (BT-02, MOD-03; 6-C02, 6-C03 phần mô phỏng).

Số broker / phí là số GIẢ chỉ để test (như ``test_risk_engine``): 1 lot = 100 oz, point 0,01,
spread nến 20 point (0,20), phí 0. Hồ sơ rủi ro = hồ sơ người dùng chốt 16/11 (H1–H11).

Tính tay ca chuẩn (09:00 NY thứ Ba 11/03/2025, nến bắt đầu lúc đó mở 2.400,00):
- ``decide``: bid 2.400, ATR 6, EMA20 2.398 → SL = 2.400 − 1,5 × 6 = 2.391;
  TP = 2.400 + 2 × 9 = 2.418.
- Risk: đệm trượt giá = p95 spread nến 30 ngày = 0,20; rủi ro / lot = (9 + 0,20 + 0,20) × 100 = 940;
  vốn 10.000 × 0,25 % = 25 → 25 / 940 = 0,0265 → **0,02 lot**, rủi ro **18,80**.
- Khớp: ask + đệm = 2.400,20 + 0,20 = **2.400,40**.
- TP: (2.418 − 2.400,40) × 100 × 0,02 = **+35,20**.
- SL: giá đóng = min(2.391, mở) − 0,20 = 2.390,80 → (2.390,80 − 2.400,40) × 2 = **−19,20**.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from gold_trading.analysts.framework import Scope
from gold_trading.backtest.simulate import (
    BarBroker,
    Bars,
    HistoricalView,
    HistoricalViews,
    SimBar,
    SimConfig,
    simulate,
)
from gold_trading.common.enums import Bias, Side, TradingMode
from gold_trading.market.hours import REFERENCE, is_open
from gold_trading.risk.blocks import Block, BlockKind
from gold_trading.strategy.runner import StrategyRunner
from tests.factories import market_view
from tests.test_risk_profiles import USER_V1

D = Decimal
NY = ZoneInfo("America/New_York")
FEED = "f1"
SCOPE = Scope.of_feed("XAUUSD", "M15", "MT5", FEED)
SPEC = dict(digits=2, point=0.01, contract_size=100.0, volume_min=0.01, volume_max=50.0,
            volume_step=0.01, currency_profit="USD", stops_level=20, freeze_level=10,
            swap_mode=1, swap_long=0.0, swap_short=0.4, swap_rollover3days=3, leverage=100,
            account_currency="USD")
TECH = {"atr14": 6.0, "ema20": 2398.0}
START = datetime(2025, 2, 28, 0, 0, tzinfo=UTC)
T_SIG = datetime(2025, 3, 11, 9, 0, tzinfo=NY).astimezone(UTC)        # thứ Ba, sau đổi giờ Mỹ


def flat_bars(start: datetime, end: datetime, price="2400", spread=20) -> dict[datetime, SimBar]:
    out = {}
    t = start
    p = D(price)
    while t < end:
        if is_open(t) and is_open(t + timedelta(minutes=14)):
            out[t] = SimBar(t, p, p + D("0.5"), p - D("0.5"), p, spread)
        t += timedelta(minutes=15)
    return out


def cfg(**kw) -> SimConfig:
    base = dict(feed_id=FEED, symbol="XAUUSD", spec=SPEC, commission_per_lot=D(0),
                profile=USER_V1, capital=D(10_000), market_calendar=REFERENCE)
    return SimConfig(**(base | kw))


def view_at(t: datetime, bias=Bias.LONG, conf=0.7, mid="mv1", **kw) -> HistoricalView:
    v = market_view(t, market_view_id=mid, bias=bias, confidence=conf, feed_id=FEED, **kw)
    return HistoricalView(v, t, TECH)


def run(bars: dict, views, end=None, **kw):
    return simulate(list(bars.values()), HistoricalViews(views, SCOPE), cfg(**kw), START,
                    end or T_SIG + timedelta(hours=10))


def world(**bar_overrides):
    bars = flat_bars(START, T_SIG + timedelta(hours=12))
    for t, b in bar_overrides.items():
        bars[t] = b
    return bars


def bar(t, o, h, lo, c, spread=20):
    return SimBar(t, D(o), D(h), D(lo), D(c), spread)


# ---------------------------------------------------------------------- dò trong nến (thuần)


@pytest.mark.parametrize("side,sl,tp,b,exp", [
    ("BUY", D(2391), D(2418), ("2400", "2405", "2390", "2401"), ("STOP_LOSS", D("2390.80"))),
    ("BUY", D(2391), D(2418), ("2385", "2386", "2380", "2381"), ("STOP_LOSS", D("2384.80"))),
    ("BUY", D(2391), D(2418), ("2400", "2418", "2399", "2410"), ("TAKE_PROFIT", D(2418))),
    ("BUY", D(2391), D(2418), ("2400", "2420", "2390", "2400"), ("STOP_LOSS", D("2390.80"))),
    ("BUY", D(2391), D(2418), ("2400", "2417.99", "2391.01", "2400"), None),
    # SELL: giá ask = bid + 0,20
    ("SELL", D(2409), D(2382), ("2400", "2408.80", "2395", "2400"), ("STOP_LOSS", D("2409.20"))),
    ("SELL", D(2409), D(2382), ("2400", "2408.79", "2395", "2400"), None),
    ("SELL", D(2409), D(2382), ("2412", "2413", "2411", "2412"), ("STOP_LOSS", D("2412.40"))),
    ("SELL", D(2409), D(2382), ("2400", "2401", "2381.80", "2390"), ("TAKE_PROFIT", D(2382))),
    ("SELL", D(2409), D(2382), ("2400", "2401", "2381.81", "2390"), None),
    ("SELL", D(2409), D(2382), ("2400", "2410", "2380", "2400"), ("STOP_LOSS", D("2409.20"))),
])
def test_bar_hit_rules_hand_values(side, sl, tp, b, exp):
    sb = bar(T_SIG, *b)
    assert BarBroker.bar_hit(side, sl, tp, sb, D("0.01"), D("0.20")) == exp


# ---------------------------------------------------------------------- chạy đầy đủ


def test_take_profit_hand_computed():
    bars = world(**{})
    bars[T_SIG] = bar(T_SIG, "2400", "2418.5", "2399.6", "2417")
    r = run(bars, [view_at(T_SIG)])
    assert len(r.trades) == 1
    tr = r.trades[0]
    assert tr.reason == "TAKE_PROFIT" and tr.amount == D("35.20")
    assert tr.data["entry_price"] == "2400.40" and tr.data["volume"] == "0.02"
    d = [x for x in r.decisions if x.outcome.value != "REJECTED"]
    assert len(d) == 1 and d[0].risk_amount == D("18.80")
    assert r.pauses == [] and r.capital == D(10_000)


def test_stop_loss_with_exit_slippage_hand_computed():
    bars = world()
    bars[T_SIG] = bar(T_SIG, "2400", "2400.5", "2399.6", "2400")
    nxt = T_SIG + timedelta(minutes=15)
    bars[nxt] = bar(nxt, "2400", "2400.5", "2390", "2392")
    r = run(bars, [view_at(T_SIG)])
    assert [(t.reason, t.amount) for t in r.trades] == [("STOP_LOSS", D("-19.20"))]


def test_same_bar_hits_both_counts_as_stop_loss():
    bars = world()
    bars[T_SIG] = bar(T_SIG, "2400", "2419", "2390", "2400")
    r = run(bars, [view_at(T_SIG)])
    assert [(t.reason, t.amount) for t in r.trades] == [("STOP_LOSS", D("-19.20"))]


def test_gap_through_stop_closes_at_open_worse():
    bars = world()
    bars[T_SIG] = bar(T_SIG, "2400", "2400.5", "2399.6", "2400")
    nxt = T_SIG + timedelta(minutes=15)
    bars[nxt] = bar(nxt, "2385", "2386", "2380", "2381")
    r = run(bars, [view_at(T_SIG)])
    # (2.384,80 − 2.400,40) × 100 × 0,02 = −31,20 (khoảng trống giá: lỗ hơn rủi ro đã duyệt)
    assert [(t.reason, t.amount) for t in r.trades] == [("STOP_LOSS", D("-31.20"))]


def test_time_stop_at_1645_new_york():
    bars = world()
    r = run(bars, [view_at(T_SIG)], end=T_SIG + timedelta(hours=12))
    assert len(r.trades) == 1 and r.trades[0].reason == "TIME_STOP"
    closed = r.trades[0].at.astimezone(NY)
    assert (closed.hour, closed.minute) == (16, 45)
    # đóng ở bid − đệm = 2.400 − 0,20; vào 2.400,40 → (−0,60) × 2 = −1,20
    assert r.trades[0].amount == D("-1.20")


def test_break_even_moves_then_stop_at_break_even():
    # Vào 2.400,40, khoảng SL ban đầu |2.400,40 − 2.391| = 9,40 → dời hòa vốn khi bid ≥ 2.409,80.
    bars = world()
    bars[T_SIG] = bar(T_SIG, "2400", "2400.5", "2399.6", "2400")
    t1 = T_SIG + timedelta(minutes=15)
    bars[t1] = bar(t1, "2409.60", "2410", "2409", "2409.7")
    t2 = t1 + timedelta(minutes=15)
    t3 = t2 + timedelta(minutes=15)
    bars[t3] = bar(t3, "2405", "2406", "2400", "2401")
    # (a) giá mở nến t2 = 2.409,79 (thiếu 0,01) → không dời → nến t3 (low 2.400) chưa chạm SL gốc.
    bars[t2] = bar(t2, "2409.79", "2410", "2409.6", "2409.8")
    r = run(bars, [view_at(T_SIG)])
    assert [t.reason for t in r.trades] == ["TIME_STOP"]
    # (b) giá mở nến t2 = 2.409,80 → SL dời = vào + đệm + phí / cỡ HĐ = 2.400,60; nến t3 chạm
    # → đóng ở min(2.400,60, mở 2.405) − 0,20 = 2.400,40 → hòa vốn đúng 0.
    bars[t2] = bar(t2, "2409.80", "2410", "2409.6", "2409.9")
    r = run(bars, [view_at(T_SIG)])
    assert [(t.reason, t.amount) for t in r.trades] == [("STOP_LOSS", D("0.00"))]


def test_friday_weekend_close_30_minutes_before():                              # 6-C02 / H8
    fri = datetime(2025, 3, 14, 9, 0, tzinfo=NY).astimezone(UTC)
    bars = flat_bars(START, fri + timedelta(hours=12))
    r = simulate(list(bars.values()), HistoricalViews([view_at(fri)], SCOPE), cfg(), START,
                 fri + timedelta(hours=12))
    assert len(r.trades) == 1 and r.trades[0].reason == "WEEKEND_CLOSE"
    c = r.trades[0].at.astimezone(NY)
    assert (c.weekday(), c.hour, c.minute) == (4, 16, 30)


def test_dst_gap_week_session_hours_follow_new_york():                          # 6-C02
    # 11/03/2025: Mỹ đã đổi giờ (09/03), châu Âu chưa (30/03). 03:00 NY = 07:00 UTC (không phải
    # 08:00): nhận định lúc 07:00 UTC phải được xét (trong giờ), lúc 06:45 UTC thì không.
    inside = datetime(2025, 3, 11, 7, 0, tzinfo=UTC)
    outside = datetime(2025, 3, 11, 6, 45, tzinfo=UTC)
    bars = world()
    assert len(run(bars, [view_at(inside)]).trades) == 1
    assert run(bars, [view_at(outside)]).trades == []


def test_pause_and_resume_next_trading_day_rule():
    from gold_trading.backtest.simulate import BacktestAccounts
    from gold_trading.risk.ledger import RiskLedger
    now = [T_SIG]
    acc = BacktestAccounts(cfg(), START, lambda: now[0])
    assert acc.entry_denials("x", T_SIG) == [] and acc.mode("x") is TradingMode.BACKTEST
    assert acc.request_pause("x", "DRAWDOWN_HALT") is True
    assert acc.request_pause("x", "DAILY_LOSS_LIMIT") is False            # đã dừng → không chồng
    assert acc.entry_denials("x", T_SIG) == ["SAFETY_PAUSED:DRAWDOWN_HALT"]
    led = RiskLedger(clock=lambda: now[0])
    led.start("backtest", D(10_000), actor="t", reason="t", at=START)
    nxt = datetime(2025, 3, 11, 17, 0, tzinfo=NY).astimezone(UTC)
    acc.maybe_resume(nxt - timedelta(minutes=15), led, D(9_400))
    assert acc.paused is not None                                 # chưa tới mốc ngày
    now[0] = nxt
    acc.maybe_resume(nxt, led, D(9_400))
    assert acc.paused is None and acc.active_since("x") == nxt
    assert acc.pauses[0].resumed_at == nxt
    assert led.equity_state("backtest", nxt).peak == D(9_400)            # H6: đặt lại đỉnh


def test_no_trade_without_view_or_outside_session_or_with_block():
    bars = world()
    assert run(bars, []).trades == []
    evening = datetime(2025, 3, 11, 13, 0, tzinfo=NY).astimezone(UTC)    # sau 12:00 NY
    assert run(bars, [view_at(evening)]).trades == []
    blk = Block(BlockKind.NEWS, FEED, "CALENDAR_HIGH", T_SIG - timedelta(minutes=5),
                T_SIG + timedelta(minutes=30), "cpi", T_SIG - timedelta(days=1), "p0")
    r = run(bars, [view_at(T_SIG)],
            entry_blocks=lambda t: [blk] if blk.start_at <= t < blk.end_at else [])
    assert r.trades == []
    rej = [d for d in r.decisions if "ENTRY_BLOCK:CALENDAR_HIGH" in d.reason_codes]
    assert len(rej) == 1


def test_missing_bar_at_signal_means_no_quote_no_trade():                      # 6-C03
    bars = world()
    del bars[T_SIG]                     # hở dữ liệu đúng nến sẽ khớp lệnh (nến bắt đầu lúc T_SIG)
    r = run(bars, [view_at(T_SIG)])
    assert r.trades == [] and r.no_quote_ticks >= 1
    ev = [e for e in r.evaluations if e.market_view_id == "mv1"]
    assert len(ev) == 1 and "MISSING_QUOTE" in ev[0].reasons


def test_unhealthy_calendar_rejects():
    bars = world()
    r = run(bars, [view_at(T_SIG)], calendar_health=lambda t: ["CALENDAR_SOURCE_UNHEALTHY:x"])
    assert r.trades == []
    assert any("CALENDAR_SOURCE_UNHEALTHY:x" in d.reason_codes for d in r.decisions)


def test_spread_baseline_needs_history():
    # Chỉ 3 ngày dữ liệu trước tín hiệu → < 6.900 "phút" → Risk từ chối, không đoán.
    bars = {t: b for t, b in world().items() if t >= T_SIG - timedelta(days=3)}
    r = simulate(list(bars.values()), HistoricalViews([view_at(T_SIG)], SCOPE), cfg(),
                 T_SIG - timedelta(days=3), T_SIG + timedelta(hours=2))
    assert r.trades == []
    assert any("SPREAD_BASELINE_MISSING" in d.reason_codes for d in r.decisions)


def test_short_side_take_profit_hand_computed():
    # SELL: bid 2.400, EMA20 2.402 → SL = 2.409, TP = 2.382; vào = bid − đệm = 2.399,80.
    # Rủi ro / lot = (9 + 0,20 + 0,20) × 100 = 940 → 0,02 lot.
    # TP: ask ≤ 2.382 khi low + 0,20 ≤ 2.382.
    bars = world()
    bars[T_SIG] = bar(T_SIG, "2400", "2400.5", "2381.5", "2383")
    v = market_view(T_SIG, market_view_id="mvs", bias=Bias.SHORT, confidence=0.7, feed_id=FEED)
    r = run(bars, [HistoricalView(v, T_SIG, {"atr14": 6.0, "ema20": 2402.0})])
    assert [(t.reason, t.amount) for t in r.trades] == [("TAKE_PROFIT", D("35.60"))]
    assert r.trades[0].data["side"] == Side.SELL.value


def test_deterministic_and_equity_days():
    bars = world()
    bars[T_SIG] = bar(T_SIG, "2400", "2418.5", "2399.6", "2417")
    a = run(bars, [view_at(T_SIG)])
    b = run(bars, [view_at(T_SIG)])
    assert [(t.reason, t.amount, t.at) for t in a.trades] == \
        [(t.reason, t.amount, t.at) for t in b.trades]
    assert a.equity_by_day[-1][1] == D("10035.20")
    for t, _ in a.equity_by_day:
        assert t.astimezone(NY).hour == 17


def test_backtest_mode_allowed_by_strategy_runner():
    assert TradingMode.BACKTEST.value == "BACKTEST"
    src = pathlib.Path(StrategyRunner.run_account.__code__.co_filename).read_text()
    assert "TradingMode.BACKTEST" in src


PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "gold_trading" / "backtest"
FORBIDDEN = ("gold_trading.api", "gold_trading.accounts.mt5_link", "httpx", "requests",
             "urllib", "socket", "gold_trading.storage.repository")


# Chỉ lệnh CLI được mở kho SQL — và chỉ bằng URL đã qua ``resolve_url`` (DB riêng, test ở
# ``test_backtest_data.py``); mọi mô-đun khác không chạm cơ sở dữ liệu nào.
DB_OK = {"cli.py"}


@pytest.mark.parametrize("mod", sorted(p.name for p in PKG.glob("*.py")))
def test_backtest_has_no_path_to_gateway_network_or_live_db(mod):
    tree = ast.parse((PKG / mod).read_text())
    names = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    names += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    bad = [x for x in names if x.startswith(FORBIDDEN)]
    if mod in DB_OK:
        bad = [x for x in bad if x != "gold_trading.storage.repository"]
    assert not bad


def test_spread_baseline_rows_are_point_in_time():
    from gold_trading.backtest.simulate import _SpreadMinutes
    b1 = bar(T_SIG, "2400", "2401", "2399", "2400", spread=20)
    b2 = bar(T_SIG + timedelta(minutes=15), "2400", "2401", "2399", "2400", spread=90)
    sm = _SpreadMinutes(Bars([b1, b2]))
    lo, hi = T_SIG, T_SIG + timedelta(hours=1)
    # Lúc nến 2 chưa đóng: chỉ 15 "phút" của nến 1 — spread 90 của nến 2 chưa được biết.
    rows = sm.query(lo, hi, as_of=T_SIG + timedelta(minutes=20))
    assert len(rows) == 15 and {r.spread_p95 for r in rows} == {20}
    rows = sm.query(lo, hi, as_of=T_SIG + timedelta(minutes=30))
    assert len(rows) == 30 and {r.spread_p95 for r in rows} == {20, 90}


def test_below_min_lot_capital_never_trades():                                  # 5-C01
    # Vốn 3.000: 0,25 % = 7,50 < rủi ro 0,01 lot = 9,40 → Risk từ chối, không làm tròn lên.
    bars = world()
    bars[T_SIG] = bar(T_SIG, "2400", "2418.5", "2399.6", "2417")
    r = run(bars, [view_at(T_SIG)], capital=D(3_000))
    assert r.trades == []
    assert any("BELOW_MIN_VOLUME" in d.reason_codes for d in r.decisions)


def test_fast_ledger_gives_identical_results_to_reference_ledger(monkeypatch):
    """Sổ có chỉ mục (hiệu năng) phải cho đúng từng lệnh như sổ tham chiếu của GĐ5."""
    import random

    import gold_trading.backtest.simulate as SM
    from gold_trading.risk.ledger import RiskLedger
    rng = random.Random(11)
    t, p, bl, views = START, 2400.0, [], []
    while t < START + timedelta(days=40):
        if is_open(t) and is_open(t + timedelta(minutes=14)):
            o = round(p, 2)
            c = round(o + rng.gauss(0, 2.5), 2)
            if rng.random() < 0.004:
                o = round(o + rng.choice([-12, 12]), 2)              # khoảng trống giá
            bl.append(SimBar(t, D(str(o)), D(str(round(max(o, c) + 0.4, 2))),
                             D(str(round(min(o, c) - 0.4, 2))), D(str(c)),
                             rng.choice([15, 20, 40])))
            p = c
            if rng.random() < 0.3:
                tc = t + timedelta(minutes=15)
                v = market_view(tc, market_view_id=f"r{len(views)}", feed_id=FEED,
                                bias=rng.choice([Bias.LONG, Bias.SHORT]), confidence=0.8)
                views.append(HistoricalView(v, tc, {"atr14": 4.0, "ema20": c}))
        t += timedelta(minutes=15)
    end = START + timedelta(days=40)

    def sig(r):
        return [(e.type, e.ref_id[:0], e.amount, e.at, e.reason, e.data.get("exit_price"))
                for e in r.trades], [(p.code, p.at) for p in r.pauses], r.equity_by_day
    fast = simulate(bl, HistoricalViews(views, SCOPE), cfg(), START, end)
    monkeypatch.setattr(SM, "FastLedger", RiskLedger)
    ref = simulate(bl, HistoricalViews(views, SCOPE), cfg(), START, end)
    assert len(fast.trades) > 20
    assert sig(fast) == sig(ref)
