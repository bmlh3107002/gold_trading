"""GĐ6 bước 6 — chỉ số một lần mô phỏng + mốc so sánh (protocol-1 mục 5–6)."""

from __future__ import annotations

import random
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest

from gold_trading.backtest import baselines as B
from gold_trading.backtest.metrics import session_of, summarize, trades_of
from gold_trading.backtest.simulate import Bars, HistoricalView, HistoricalViews, simulate
from gold_trading.common.enums import Bias
from gold_trading.strategy.trend_m15 import V1, Inputs, decide
from tests.factories import market_view
from tests.test_backtest_simulate import (
    FEED,
    NY,
    SCOPE,
    START,
    T_SIG,
    TECH,
    bar,
    cfg,
    run,
    view_at,
    world,
)

D = Decimal


def test_session_boundaries_new_york():
    def ny(h, m=0):
        return datetime(2025, 3, 11, h, m, tzinfo=NY)
    assert session_of(ny(2, 59)) == "ASIA" and session_of(ny(3)) == "LONDON"
    assert session_of(ny(7, 59)) == "LONDON" and session_of(ny(8)) == "US"
    assert session_of(ny(16, 59)) == "US" and session_of(ny(18)) == "ASIA"


def test_summary_hand_values_single_take_profit():
    bars = world()
    bars[T_SIG] = bar(T_SIG, "2400", "2418.5", "2399.6", "2417")
    res = run(bars, [view_at(T_SIG)])
    tr = trades_of(res, {"mv1": "TREND"})
    assert len(tr) == 1
    t = tr[0]
    assert (t.pnl, t.risk, t.reason, t.regime, t.side) == (D("35.20"), D("18.80"),
                                                           "TAKE_PROFIT", "TREND", "BUY")
    assert t.r == pytest.approx(35.20 / 18.80)
    assert t.session == "US" and t.year == 2025
    assert t.trade_day.isoformat() == "2025-03-11"            # đóng 09:15 NY → ngày giao dịch 11/3
    s = summarize(res, {"mv1": "TREND"})
    assert s.n == 1 and s.win_rate == 1.0 and s.profit_factor is None      # không có lệnh lỗ
    assert s.expectancy_r == pytest.approx(35.20 / 18.80) and s.expectancy_usd == 35.20
    assert s.total_pnl == D("35.20") and s.avg_hold_minutes == 15
    assert s.max_drawdown == 0 and s.h4_count == 0 and s.h6_count == 0
    assert s.by_regime["TREND"].n == 1 and s.by_side["BUY"].pnl == D("35.20")
    assert s.by_year[2025].n == 1 and set(s.by_session) == {"US"}


def test_summary_loss_then_win_drawdown_and_streak():
    bars = world()
    bars[T_SIG] = bar(T_SIG, "2400", "2400.5", "2390", "2392")             # SL −19,20
    t2 = T_SIG + timedelta(hours=1)                                         # sau nghỉ 30 phút
    bars[t2] = bar(t2, "2400", "2418.5", "2399.6", "2417")                 # TP +35,20
    res = run(bars, [view_at(T_SIG), view_at(t2, mid="mv2")])
    s = summarize(res)
    assert s.n == 2 and s.win_rate == 0.5
    assert s.profit_factor == pytest.approx(35.20 / 19.20)
    assert s.longest_losing_streak == 1
    assert s.expectancy_usd == pytest.approx((35.20 - 19.20) / 2)
    assert s.by_regime["UNKNOWN"].n == 2                    # không có bảng regime → UNKNOWN


def test_trade_day_after_17_new_york_is_next_day():
    from gold_trading.backtest.metrics import Trade
    t = Trade("p", "BUY", datetime(2025, 3, 11, 17, 30, tzinfo=NY),
              datetime(2025, 3, 11, 18, 0, tzinfo=NY), D(1), D(1), "TP", None, None)
    assert t.trade_day.isoformat() == "2025-03-12"


# ---------------------------------------------------------------------- mốc


def test_no_filter_params_drops_v3_v6_keeps_exits():
    p = B.no_filter_params(V1)
    assert (p.sl_atr, p.tp_r, p.be_at_r, p.close_at, p.max_open, p.cooldown) == \
        (V1.sl_atr, V1.tp_r, V1.be_at_r, V1.close_at, V1.max_open, V1.cooldown)
    evening = datetime(2025, 3, 11, 14, 0, tzinfo=NY).astimezone(UTC)
    v = market_view(evening, bias=Bias.LONG, confidence=0.1, feed_id=FEED,
                    risk_flags=frozenset({"CROWDING_RISK"}))
    inp = Inputs(evening, FEED, v, {"atr14": 6.0, "ema20": 2300.0}, D(2400), D("2400.2"),
                 D("0.01"), 0, None, D("0.0025"))
    assert decide(inp, V1).intent is None
    assert decide(inp, p).intent is not None
    neutral = Inputs(evening, FEED, v.model_copy(update={"bias": Bias.NEUTRAL}),
                     {"atr14": 6.0, "ema20": 2400.0}, D(2400), D("2400.2"), D("0.01"), 0, None,
                     D("0.0025"))
    assert decide(neutral, p).intent is None                 # V2 vẫn cần có hướng
    r = B.random_entry_params(V1)
    assert (r.session_start, r.session_end, r.friday_end) == \
        (V1.session_start, V1.session_end, V1.friday_end)    # mốc ngẫu nhiên giữ giờ phiên


def test_run_seed_stable_and_distinct():
    assert B.run_seed(7, 0) == B.run_seed(7, 0)
    assert len({B.run_seed(7, i) for i in range(1000)}) == 1000
    assert B.run_seed(7, 1) != B.run_seed(8, 1)


def _chain(n_days=1):
    """MarketView tầng 1 giả mỗi 15 phút trong ngày tín hiệu (cùng ATR thật = 6)."""
    out = []
    t = T_SIG - timedelta(hours=6)
    while t < T_SIG + timedelta(hours=4):
        v = market_view(t, market_view_id=f"c{t:%H%M}", bias=Bias.NEUTRAL, confidence=0.2,
                        feed_id=FEED)
        out.append(HistoricalView(v, t, TECH))
        t += timedelta(minutes=15)
    return out


def test_eligible_times_and_random_views():
    bars = Bars(world().values())
    chain = _chain()
    pool = B.eligible_times(bars, chain, B.random_entry_params(V1), START,
                            T_SIG + timedelta(hours=12))
    assert pool and all(V1.session_start <= v.computed_at.astimezone(NY).time() < time(12, 0)
                        for v in pool)
    a = B.random_views(pool, 10, 0.3, random.Random(5))
    b = B.random_views(pool, 10, 0.3, random.Random(5))
    assert [(v.view.market_view_id, v.view.bias) for v in a] == \
        [(v.view.market_view_id, v.view.bias) for v in b]
    assert len(a) == 10 and sum(v.view.bias is Bias.LONG for v in a) == 3
    assert len({v.computed_at for v in a}) == 10 and all(v.view.confidence == 1.0 for v in a)
    assert all(v.technical == TECH for v in a)
    assert B.random_views(pool, 0, 0.5, random.Random(1)) == []
    assert len(B.random_views(pool, 10_000, 0.5, random.Random(1))) == len(pool)


def test_random_baseline_deterministic_serial_equals_parallel():
    bars = Bars(world().values())
    chain = _chain()
    end = T_SIG + timedelta(hours=12)
    kw = dict(n_trades=3, long_share=0.5, runs=6, root_seed=42)
    a = B.random_baseline(bars, chain, cfg(), START, end, **kw)
    b = B.random_baseline(bars, chain, cfg(), START, end, **kw, workers=2)
    assert a == b
    # Một ngày chỉ khớp được 1 lệnh → hiệu chỉnh tăng số lần bốc tới hết kho rồi dừng (không lặp).
    pool = B.eligible_times(bars, chain, B.random_entry_params(V1), START, end)
    assert a.target_trades == 3 and a.draws == len(pool)
    assert len(a.runs) == 6 and all(r.drawn == len(pool) for r in a.runs)
    # Giá đi ngang: lệnh giữ tới 16:45 → các lần bốc sau bị "đang có lệnh" chặn → 1 lệnh / lần.
    vals = [r.expectancy_r for r in a.runs if r.expectancy_r is not None]
    assert len(vals) == 6 and all(r.trades == 1 for r in a.runs)
    assert min(vals) <= a.p95_expectancy_r <= max(vals)
    c = B.random_baseline(bars, chain, cfg(), START, end, **(kw | {"root_seed": 43}))
    assert [r.seed for r in c.runs] != [r.seed for r in a.runs]


def test_random_baseline_empty_pool_is_none():
    bars = Bars(world().values())
    r = B.random_baseline(bars, [], cfg(), START, T_SIG, n_trades=5, long_share=0.5, runs=3,
                          root_seed=1)
    assert r.runs == () and r.p95_expectancy_r is None


def test_buy_and_hold_hand():
    bars = world()
    bars[T_SIG] = bar(T_SIG, "2400", "2410", "2399", "2412")
    bs = Bars(bars.values())
    assert B.buy_and_hold_pct(bs, T_SIG, T_SIG + timedelta(minutes=15)) == pytest.approx(12 / 2400)
    assert B.buy_and_hold_pct(bs, T_SIG, T_SIG) is None


def test_no_filter_baseline_trades_where_strategy_would_not():
    bars = world()
    evening = datetime(2025, 3, 11, 13, 0, tzinfo=NY).astimezone(UTC)        # ngoài giờ V5
    views = HistoricalViews([view_at(evening)], SCOPE)
    end = T_SIG + timedelta(hours=10)
    assert simulate(list(bars.values()), views, cfg(), START, end).trades == []
    r = simulate(list(bars.values()), views, cfg(params=B.no_filter_params(V1)), START, end)
    assert len(r.trades) == 1


def test_calibration_reaches_target_trade_count_on_longer_data():
    # 3 tuần giá đi ngẫu nhiên, MarketView mỗi 15 phút: bốc đúng n thời điểm chỉ khớp được ít hơn
    # (đang có lệnh / nghỉ / 4 lệnh ngày); sau hiệu chỉnh trung vị số lệnh khớp ≈ n.
    from gold_trading.backtest.simulate import SimBar
    from gold_trading.market.hours import is_open
    rng = random.Random(3)
    t, p, bl = START, 2400.0, []
    while t < START + timedelta(days=24):
        if is_open(t) and is_open(t + timedelta(minutes=14)):
            o = round(p, 2)
            c = round(o + rng.gauss(0, 2.5), 2)
            bl.append(SimBar(t, D(str(o)), D(str(max(o, c) + 0.5)), D(str(min(o, c) - 0.5)),
                             D(str(c)), 20))
            p = c
        t += timedelta(minutes=15)
    bars = Bars(bl)
    chain = [HistoricalView(market_view(b.close_time, market_view_id=f"x{i}", bias=Bias.NEUTRAL,
                                        feed_id=FEED), b.close_time, {"atr14": 5.0, "ema20": 1.0})
             for i, b in enumerate(bl)]
    end = START + timedelta(days=24)
    r = B.random_baseline(bars, chain, cfg(), START, end, n_trades=20, long_share=0.5, runs=8,
                          root_seed=9)
    assert r.draws > 20                                     # cần bốc nhiều hơn n
    assert abs(r.median_trades - 20) <= 3
