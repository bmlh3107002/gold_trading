"""GĐ3 bước 7b — mẫu hình nến / giá (TEC-06), Technical 1.5.0."""

from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.analysts import patterns as P
from gold_trading.analysts import technical
from gold_trading.analysts.technical import Swing
from gold_trading.contracts.candle import Candle, DataSource
from gold_trading.market.timeframes import Timeframe

from .test_technical import NOW, run, sample_rows

T0 = datetime(2026, 1, 14, 10, 0, tzinfo=UTC)
M = timedelta(minutes=15)


def c(o, h, lo, cl, i=1):
    t = T0 + M * i
    return Candle(symbol="XAUUSD", timeframe=Timeframe.M15, source=DataSource.CSV, open_time=t,
                  close_time=t + M, open=o, high=h, low=lo, close=cl, ingested_at=t + M,
                  available_at=t + M)


ATR = 4.0


@pytest.mark.parametrize("prev,cur,want", [
    # nhấn chìm tăng: nến trước giảm, nến sau tăng bao trọn thân
    (c(102, 102.5, 100.5, 101, 0), c(100.8, 103.2, 100.5, 103, 1), {"BULLISH_ENGULFING"}),
    (c(101, 102.5, 100.5, 102, 0), c(102.2, 102.4, 99.8, 100.5, 1), {"BEARISH_ENGULFING"}),
    # búa: thân nhỏ ở trên, bóng dưới ≥ 2 × thân, bóng trên rất nhỏ
    (None, c(100.0, 100.6, 97.0, 100.5, 1), {"HAMMER"}),
    (None, c(100.5, 103.5, 99.9, 100.0, 1), {"SHOOTING_STAR"}),
    # doji: thân ≤ 10 % biên độ (bóng hai phía → không phải búa / sao băng)
    (None, c(100.0, 101.5, 98.5, 100.1, 1), {"DOJI"}),
    # inside bar
    (c(100, 104, 96, 103, 0), c(101, 103, 97, 102, 1), {"INSIDE_BAR"}),
])
def test_candle_patterns_hand_built(prev, cur, want):
    assert set(P.candle_patterns(prev, cur, ATR)) == want


def test_small_bar_ignored_and_no_false_engulfing():
    tiny = c(100.0, 100.5, 99.5, 100.05, 1)              # biên độ 1 < 0,3 × 4 → bỏ
    assert P.candle_patterns(None, tiny, ATR) == []
    same_color = (c(100, 101.5, 99.5, 101, 0), c(99.8, 102, 99.6, 101.8, 1))   # cùng màu tăng
    assert "BULLISH_ENGULFING" not in P.candle_patterns(*same_color, ATR)
    assert P.candle_patterns(None, c(100, 104, 96, 101, 1), 0.0) == []        # ATR 0 → không xét


def test_double_top_and_bottom_from_confirmed_swings():
    idx = {T0 + M * i: i for i in range(60)}
    sw = [Swing("HIGH", T0 + M * 10, 2410.0, T0 + M * 14),
          Swing("LOW", T0 + M * 20, 2390.0, T0 + M * 24),
          Swing("HIGH", T0 + M * 30, 2410.6, T0 + M * 34),
          Swing("LOW", T0 + M * 25, 2391.5, T0 + M * 29)]
    d = P.double_patterns(sorted(sw, key=lambda s: s.open_time), 4.0, idx)
    assert d["double_top"]["bars_apart"] == 20                       # |Δ| 0,6 ≤ 0,25 × 4 = 1
    assert d["double_bottom"] is None                                # cách nhau 5 nến < 10
    far = [Swing("HIGH", T0 + M * 10, 2410.0, T0 + M * 14),
           Swing("HIGH", T0 + M * 30, 2412.0, T0 + M * 34)]          # |Δ| 2 > 1
    assert P.double_patterns(far, 4.0, idx)["double_top"] is None


def test_technical_output_has_patterns_and_no_lookahead():
    rows = sample_rows(days=12, end=NOW + timedelta(hours=6))
    cut = [r for r in rows if r.close_time <= NOW]
    a = run(cut)
    b = run(rows[:len(cut)])                                         # cùng dữ liệu tới NOW
    assert a == b and a.version == technical.VERSION == "technical-1.5.0"
    p = a.features["patterns"]
    assert set(p) >= {"recent", "last_bar", "double_top", "double_bottom", "note"}
    assert "không phải tín hiệu" in p["note"]
    assert all(datetime.fromisoformat(x["open_time"]) < a.as_of for x in p["recent"])
    # Thêm nến tương lai: kết quả tại NOW không đổi (3-C06)
    assert run([r for r in rows if r.close_time <= NOW]) == a
    for d in (p["double_top"], p["double_bottom"]):
        if d:
            assert datetime.fromisoformat(d["confirmed_at"]) <= a.as_of


def test_spike_bar_never_forms_pattern():
    rows = sample_rows(days=10)
    s = rows[-1]
    rows[-1] = Candle(**{**s.model_dump(), "high": s.high + 300})    # nến lỗi feed (spike)
    o = run(rows)
    assert "SPIKE_IN_WINDOW" in o.quality_flags
    assert o.features["patterns"]["last_bar"] == []
