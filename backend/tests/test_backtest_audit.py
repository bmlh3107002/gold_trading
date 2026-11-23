"""GĐ6 bước 9 — soát riêng nhắm chỗ dễ sai (6-C01 phần mô phỏng; công thức lãi / lỗ).

1. Rò rỉ tương lai: thêm nến / MarketView **sau** T không đổi bất cứ gì đã xảy ra tới T.
2. Lãi / lỗ: viết lại độc lập bằng ``Fraction`` (phân số chính xác) cho mọi lệnh của một lần
   mô phỏng nhiều lệnh (có phí, có khoảng trống giá) → lệch 0; giá vào / ra đúng luật nến.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction as F

import pytest

from gold_trading.backtest.simulate import Bars, HistoricalView, HistoricalViews, SimBar, simulate
from gold_trading.common.enums import Bias
from gold_trading.market.hours import is_open
from tests.factories import market_view
from tests.test_backtest_simulate import FEED, SCOPE, START, cfg

D = Decimal


def random_world(seed: int, days: int, *, gap_p=0.004, view_p=0.3):
    rng = random.Random(seed)
    t, p, bl, views = START, 2400.0, [], []
    while t < START + timedelta(days=days):
        if is_open(t) and is_open(t + timedelta(minutes=14)):
            o = round(p, 2)
            if rng.random() < gap_p:
                o = round(o + rng.choice([-15, -8, 8, 15]), 2)
            c = round(o + rng.gauss(0, 2.5), 2)
            hi = round(max(o, c) + abs(rng.gauss(0, 0.6)), 2)
            lo = round(min(o, c) - abs(rng.gauss(0, 0.6)), 2)
            bl.append(SimBar(t, D(str(o)), D(str(hi)), D(str(lo)), D(str(c)),
                             rng.choice([12, 18, 20, 25, 40])))
            p = c
            if rng.random() < view_p:
                tc = t + timedelta(minutes=15)
                v = market_view(tc, market_view_id=f"a{seed}-{len(views)}", feed_id=FEED,
                                bias=rng.choice([Bias.LONG, Bias.SHORT, Bias.NEUTRAL]),
                                confidence=round(rng.uniform(0.4, 0.95), 2))
                views.append(HistoricalView(v, tc, {"atr14": round(rng.uniform(3, 7), 2),
                                                    "ema20": round(c + rng.gauss(0, 2), 2)}))
        t += timedelta(minutes=15)
    return bl, views


# ---------------------------------------------------------------------- 1. rò rỉ tương lai


@pytest.mark.parametrize("seed", [1, 2])
def test_future_data_does_not_change_the_past(seed):                            # 6-C01
    bl, views = random_world(seed, 60)
    cut_t = START + timedelta(days=30, hours=21)                 # giữa chừng, có lệnh trước đó
    past_bars = [b for b in bl if b.close_time <= cut_t]
    past_views = [v for v in views if v.computed_at <= cut_t]
    a = simulate(past_bars, HistoricalViews(past_views, SCOPE), cfg(), START, cut_t)
    b = simulate(bl, HistoricalViews(views, SCOPE), cfg(), START, START + timedelta(days=60))

    def closed_by(r, t):
        return [(e.amount, e.at, e.reason, e.data["entry_price"], e.data["exit_price"])
                for e in r.trades if e.at <= t]
    assert len(a.trades) > 10
    # Mọi lệnh đã đóng tới T, mọi quyết định Risk tới T, mọi lần dừng tới T: giống hệt.
    assert closed_by(a, cut_t) == closed_by(b, cut_t)
    assert [(d.decided_at, d.outcome, d.reason_codes, d.volume) for d in a.decisions] == \
        [(d.decided_at, d.outcome, d.reason_codes, d.volume) for d in b.decisions
         if d.decided_at <= cut_t]
    assert [(p.code, p.at) for p in a.pauses] == [(p.code, p.at) for p in b.pauses
                                                  if p.at <= cut_t]
    assert a.equity_by_day == [x for x in b.equity_by_day if x[0] <= cut_t]


def test_late_or_out_of_order_market_view_is_refused():
    bl, views = random_world(3, 10)
    late = views[5]
    bad = HistoricalView(late.view, views[-1].computed_at + timedelta(minutes=15),
                         late.technical)
    with pytest.raises(ValueError):                 # as_of lùi về trước → không âm thầm nhận
        HistoricalViews([*views, bad], SCOPE)


# ---------------------------------------------------------------------- 2. lãi / lỗ độc lập


def floor8(x: F) -> F:
    return F((x.numerator * 10**8) // x.denominator, 10**8)


@pytest.mark.parametrize("seed", [4, 5])
def test_pnl_and_fill_prices_independent_rewrite(seed):
    bl, views = random_world(seed, 120, gap_p=0.01)
    c = cfg(commission_per_lot=D("7"))
    res = simulate(bl, HistoricalViews(views, SCOPE), c, START, START + timedelta(days=120))
    bars = Bars(bl)
    opens = {e.ref_id: e for e in res.opens}
    point = F("0.01")
    assert len(res.trades) > 100
    reasons = set()
    for cl in res.trades:
        o = opens[cl.ref_id]
        d = o.data
        side = 1 if d["side"] == "BUY" else -1
        entry, exit_ = F(d["entry_price"]), F(cl.data["exit_price"])
        vol, cs, slip = F(d["volume"]), F(d["contract_size"]), F(d["slippage"])
        comm = F(d["commission_per_lot"])
        assert comm == 7
        # Giá vào = giá mở nến bắt đầu lúc khớp (BUY + spread) ± đệm.
        b = bars.starting_at(o.at)
        sp = b.spread_points * point
        assert entry == (F(str(b.open)) + sp + slip if side == 1 else F(str(b.open)) - slip)
        # Lãi / lỗ ròng = sàn 8 chữ số của (chênh giá × cỡ HĐ × lot − phí × lot − swap).
        nights = int(cl.data["swap_nights"])
        assert nights == 0                                  # v1 không giữ qua đêm
        want = floor8((exit_ - entry) * side * cs * vol - comm * vol)
        assert F(str(cl.amount)) == want, (cl.ref_id, cl.amount, want)
        # Giá ra đúng luật nến (thiết kế 39 mục 6), viết lại độc lập.
        reasons.add(cl.reason)
        orig_sl = F(d["stop_loss"])
        if cl.reason == "TAKE_PROFIT":
            assert exit_ == F(d["take_profit"])
        elif cl.reason == "STOP_LOSS":
            tb = bars.starting_at(datetime.fromisoformat(cl.data["trigger_t"]))
            tsp = tb.spread_points * point
            op, hi, lo = F(str(tb.open)), F(str(tb.high)), F(str(tb.low))
            if side == 1:                       # BUY đóng ở bid: x = SL hiện hành hoặc giá mở
                x = exit_ + slip
                assert x <= op and (x == op or (lo <= x and x >= orig_sl))
            else:                               # SELL đóng ở ask = bid + spread nến
                y = exit_ - slip
                assert y >= op + tsp and (y == op + tsp or (hi + tsp >= y and y <= orig_sl))
        else:                                   # đóng chủ động: giá mở nến lúc đóng ± đệm
            qb = bars.starting_at(cl.at)
            q_bid = F(str(qb.open))
            want_x = q_bid - slip if side == 1 else q_bid + qb.spread_points * point + slip
            assert exit_ == want_x, (cl.reason, exit_, want_x)
    assert {"STOP_LOSS", "TAKE_PROFIT"} <= reasons
    # Sổ tiền: vốn + tổng lãi / lỗ = equity cuối đã chốt (nếu ngày cuối sau lệnh cuối).
    last_day, eq = res.equity_by_day[-1]
    assert eq == c.capital + sum(e.amount for e in res.trades if e.at <= last_day)
