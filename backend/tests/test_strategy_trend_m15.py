"""Chiến lược v1 ``xu-huong-m15`` — STR-02/03/04, 5-C03/5-C04. Thiết kế 36 (người dùng duyệt 17/11).

Ví dụ tính tay = thiết kế 36 mục 6 (số **minh họa**): bid 2.600,00 / ask 2.600,30, EMA20 2.595,
ATR 13 → SL 2.580,50, TP 2.639,00.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from gold_trading.common.enums import Bias, Side
from gold_trading.contracts.market_view import SAMPLE_DATA, UNCALIBRATED, UNVALIDATED_RULES
from gold_trading.strategy.trend_m15 import STRATEGY_REF, V1, Inputs, decide, in_session
from tests.factories import market_view

D = Decimal
TUE = datetime(2026, 1, 6, 14, 15, tzinfo=UTC)          # thứ Ba 09:15 New York (EST)


def inp(now=TUE, **kw):
    base = dict(now=now, feed_id="f1",
                view=market_view(now - timedelta(minutes=1), confidence=0.72),
                technical={"atr14": 13.0, "ema20": 2595.0, "close": 2600.0},
                bid=D("2600.00"), ask=D("2600.30"), point=D("0.01"), open_count=0,
                last_closed_at=None, risk_per_trade=D("0.0025"))
    return Inputs(**(base | kw))


def test_long_hand_computed():
    o = decide(inp())
    i = o.intent
    assert o.reasons == () and i is not None
    assert (i.side, i.stop_loss, i.take_profit) == (Side.BUY, 2580.5, 2639.0)
    assert i.entry_reference == 2600.0 and i.entry_type == "MARKET"
    assert i.risk_budget_requested == 0.0025                       # đúng mức hồ sơ (H1)
    assert i.expiry == TUE + timedelta(seconds=60)                 # P11
    assert i.strategy_id == STRATEGY_REF == "xu-huong-m15@1.0.0" and i.policy_version == "1.0.0"
    assert o.details["ema_gap_atr"] == "0.3846"                    # 5 / 13


def test_short_hand_computed():
    v = market_view(TUE - timedelta(minutes=1), bias=Bias.SHORT, confidence=0.72)
    i = decide(inp(view=v, technical={"atr14": 13.0, "ema20": 2605.0})).intent
    assert (i.side, i.stop_loss, i.take_profit) == (Side.SELL, 2619.5, 2561.0)


def test_rounding_never_shrinks_stop_or_widens_target():
    # ATR 13,333 → 1,5 ATR = 19,9995: SL làm tròn ra xa (2.580,00), TP = 2 × 20,00 → 2.640,00
    i = decide(inp(technical={"atr14": "13.333", "ema20": 2600.0})).intent
    assert (i.stop_loss, i.take_profit) == (2580.0, 2640.0)
    v = market_view(TUE - timedelta(minutes=1), bias=Bias.SHORT, confidence=0.72)
    i = decide(inp(view=v, technical={"atr14": "13.333", "ema20": 2600.0})).intent
    assert (i.stop_loss, i.take_profit) == (2620.0, 2560.0)


def test_one_intent_per_market_view():                              # STR-04, 5-C04
    a, b = decide(inp()).intent, decide(inp()).intent
    assert a.intent_id != b.intent_id and a.idempotency_key == b.idempotency_key
    assert a.idempotency_key.startswith("xu-huong-m15@1.0.0:") and len(a.idempotency_key) <= 64
    long_id = "mv:fusion-rules-1.0.0:" + "x" * 230                  # mã MarketView dài
    v = market_view(TUE - timedelta(minutes=1), market_view_id=long_id, confidence=0.72)
    assert len(decide(inp(view=v)).intent.idempotency_key) <= 64
    v2 = market_view(TUE - timedelta(minutes=1), market_view_id="mv2", confidence=0.72)
    assert decide(inp(view=v2)).intent.idempotency_key != a.idempotency_key


# ---------------------------------------------------------------- điều kiện vào (V1–V8)

def test_no_or_expired_view():
    assert decide(inp(view=None)).reasons == ("NO_MARKET_VIEW",)
    old = market_view(TUE - timedelta(minutes=20), confidence=0.72)       # hết hạn sau 15 phút
    assert decide(inp(view=old)).reasons == ("NO_MARKET_VIEW",)
    fut = market_view(TUE + timedelta(seconds=1), confidence=0.72)       # chưa tới as_of
    assert decide(inp(view=fut)).reasons == ("NO_MARKET_VIEW",)
    other = market_view(TUE - timedelta(minutes=1), feed_id="f2", confidence=0.72)
    assert decide(inp(view=other)).reasons == ("MARKET_VIEW_FEED_MISMATCH",)


def test_neutral_never_trades():
    v = market_view(TUE - timedelta(minutes=1), bias=Bias.NEUTRAL, confidence=0.9)
    assert decide(inp(view=v)).reasons == ("BIAS_NEUTRAL",)


@pytest.mark.parametrize("c,ok", [(0.6, True), (0.5999, False), (0.3, False)])
def test_confidence_threshold(c, ok):                              # P1
    v = market_view(TUE - timedelta(minutes=1), confidence=c)
    assert (decide(inp(view=v)).intent is not None) is ok


@pytest.mark.parametrize("flag", sorted(V1.blocked_flags))
def test_each_blocked_flag(flag):                                  # V4
    v = market_view(TUE - timedelta(minutes=1), confidence=0.72, risk_flags=frozenset({flag}))
    assert decide(inp(view=v)).reasons == (f"RISK_FLAGS:{flag}",)


@pytest.mark.parametrize("now,ok", [
    (datetime(2026, 1, 6, 7, 59, tzinfo=UTC), False),   # 02:59 NY (EST)
    (datetime(2026, 1, 6, 8, 0, tzinfo=UTC), True),     # 03:00 NY
    (datetime(2026, 1, 6, 16, 59, tzinfo=UTC), True),   # 11:59 NY
    (datetime(2026, 1, 6, 17, 0, tzinfo=UTC), False),   # 12:00 NY
    (datetime(2026, 7, 7, 7, 0, tzinfo=UTC), True),     # mùa hè (EDT): 03:00 NY = 07:00 UTC
    (datetime(2026, 7, 7, 6, 59, tzinfo=UTC), False),
    (datetime(2026, 3, 9, 7, 0, tzinfo=UTC), True),     # thứ Hai ngay sau đổi giờ 8/3
    (datetime(2026, 3, 6, 7, 30, tzinfo=UTC), False),   # thứ Sáu trước đổi giờ: 02:30 EST
    (datetime(2026, 1, 9, 14, 59, tzinfo=UTC), True),   # thứ Sáu 09:59 NY
    (datetime(2026, 1, 9, 15, 0, tzinfo=UTC), False),   # thứ Sáu 10:00 NY (P3)
    (datetime(2026, 1, 10, 14, 0, tzinfo=UTC), False),  # thứ Bảy
    (datetime(2026, 1, 11, 23, 30, tzinfo=UTC), False),  # Chủ nhật 18:30 NY (mở cửa)
])
def test_session_follows_new_york_dst(now, ok):                     # V5
    assert in_session(now) is ok
    r = decide(inp(now=now))
    assert ("OUT_OF_SESSION" in r.reasons) is (not ok)


@pytest.mark.parametrize("ema,ok", [("2587", True), ("2586.99", False), ("2613", True),
                                    ("2613.01", False)])
def test_no_chasing_price(ema, ok):                                 # V6: ≤ 1 ATR = 13
    r = decide(inp(technical={"atr14": 13.0, "ema20": ema}))
    assert (r.intent is not None) is ok and (ok or r.reasons == ("PRICE_EXTENDED",))


def test_one_position_at_a_time():                                  # V7, 5-C03 / 5-C04
    assert decide(inp(open_count=1)).reasons == ("POSITION_OPEN",)
    # tín hiệu NGƯỢC chiều khi đang có lệnh: cũng chỉ bỏ qua (không đảo, không mở ngược)
    v = market_view(TUE - timedelta(minutes=1), bias=Bias.SHORT, confidence=0.72)
    r = decide(inp(view=v, open_count=1))
    assert r.intent is None and r.reasons == ("POSITION_OPEN",)


@pytest.mark.parametrize("ago,ok", [(29, False), (30, True)])
def test_cooldown_after_close(ago, ok):                             # V8
    r = decide(inp(last_closed_at=TUE - timedelta(minutes=ago)))
    assert (r.intent is not None) is ok


@pytest.mark.parametrize("kw,code", [
    (dict(technical=None), "MISSING_ATR"),
    (dict(technical={"ema20": 2595.0}), "MISSING_ATR"),
    (dict(technical={"atr14": 0, "ema20": 2595.0}), "MISSING_ATR"),
    (dict(technical={"atr14": "nan", "ema20": 2595.0}), "MISSING_ATR"),
    (dict(technical={"atr14": 13.0}), "MISSING_EMA20"),
    (dict(bid=None), "MISSING_QUOTE"),
    (dict(ask=None), "MISSING_QUOTE"),
    (dict(point=None), "MISSING_POINT"),
    (dict(risk_per_trade=None), "MISSING_RISK_PROFILE"),
])
def test_missing_data_never_guesses(kw, code):
    r = decide(inp(**kw))
    assert r.intent is None and code in r.reasons


def test_all_reasons_reported_together():
    v = market_view(TUE - timedelta(minutes=1), bias=Bias.NEUTRAL, confidence=0.1,
                    risk_flags=frozenset({"NEWS_SHOCK"}))
    r = decide(inp(view=v, now=TUE, open_count=1, technical=None))
    assert {"BIAS_NEUTRAL", "CONFIDENCE_LOW", "RISK_FLAGS:NEWS_SHOCK", "POSITION_OPEN",
            "MISSING_ATR"} <= set(r.reasons)


def test_sample_data_is_labelled():                                  # RPF-04
    v = market_view(TUE - timedelta(minutes=1), confidence=0.72, source="SAMPLE",
                    quality_flags=frozenset({UNCALIBRATED, UNVALIDATED_RULES, SAMPLE_DATA}))
    i = decide(inp(view=v)).intent
    assert i.reason.startswith("[SAMPLE_DATA]")


def test_params_are_the_approved_v1():                               # thiết kế 36 mục 7
    p = V1
    assert (p.min_confidence, p.max_ema_gap_atr, p.max_open, p.sl_atr, p.tp_r, p.be_at_r) == (
        0.6, 1, 1, D("1.5"), 2, 1)
    assert (p.session_start.hour, p.session_end.hour, p.friday_end.hour) == (3, 12, 10)
    assert (p.close_at.hour, p.close_at.minute) == (16, 45)
    assert p.cooldown == timedelta(minutes=30) and p.intent_ttl == timedelta(seconds=60)
    assert replace(p) == p
