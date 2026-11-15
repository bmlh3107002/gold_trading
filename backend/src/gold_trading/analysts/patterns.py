"""Mẫu hình giá / nến bằng luật (GĐ3 bước 7b — TEC-06). Thiết kế: ``03-technical-analyst.md`` §10.

Chỉ **mô tả** — không phải tín hiệu, không có xác suất. Không nhìn trước:

- Mẫu nến trên nến ``i`` chỉ dùng nến ``i`` và các nến **trước** nó (đều đã đóng).
- Đỉnh đôi / đáy đôi chỉ từ swing **đã xác nhận** (``confirmed_at ≤ as_of`` — đủ K nến bên phải).
- Bỏ qua nến biên độ < ``MIN_RANGE_ATR`` × ATR (nhiễu) và nến cực đoan (lỗi feed, R3).

Ngưỡng là quy ước sách vở thường dùng, **chưa hiệu chỉnh** trên vàng M15.
Đổi → tăng VERSION Technical.
"""

from __future__ import annotations

from typing import Any

from gold_trading.contracts.candle import Candle

MIN_RANGE_ATR = 0.3        # nến nhỏ hơn 0,3 ATR → không xét mẫu
DOJI_BODY = 0.1            # thân ≤ 10 % biên độ
PIN_WICK = 2.0             # bóng chính ≥ 2 × thân
PIN_OTHER = 0.5            # bóng phụ ≤ 0,5 × thân (hoặc ≤ 10 % biên độ khi thân rất nhỏ)
PIN_BODY_MAX = 1 / 3       # thân ≤ 1/3 biên độ
RECENT_BARS = 8
DOUBLE_TOL_ATR = 0.25      # hai đỉnh / đáy cách nhau ≤ 0,25 ATR
DOUBLE_MIN_GAP = 10        # cách nhau ≥ 10 nến


def candle_patterns(prev: Candle | None, c: Candle, atr_value: float) -> list[str]:
    """Mẫu của nến ``c`` (dùng ``prev`` = nến ngay trước, nếu có)."""
    rng = c.high - c.low
    if atr_value <= 0 or rng < MIN_RANGE_ATR * atr_value:
        return []
    body = abs(c.close - c.open)
    upper = c.high - max(c.open, c.close)
    lower = min(c.open, c.close) - c.low
    out: list[str] = []
    if body <= DOJI_BODY * rng:
        out.append("DOJI")
    other_cap = max(PIN_OTHER * body, 0.1 * rng)
    if body <= PIN_BODY_MAX * rng and body > 0:
        if lower >= PIN_WICK * body and upper <= other_cap:
            out.append("HAMMER")            # bóng dưới dài (từ chối giá thấp)
        elif upper >= PIN_WICK * body and lower <= other_cap:
            out.append("SHOOTING_STAR")     # bóng trên dài (từ chối giá cao)
    if prev is not None:
        pb_lo, pb_hi = sorted((prev.open, prev.close))
        cb_lo, cb_hi = sorted((c.open, c.close))
        prev_bear, prev_bull = prev.close < prev.open, prev.close > prev.open
        bull, bear = c.close > c.open, c.close < c.open
        if bull and prev_bear and cb_lo <= pb_lo and cb_hi >= pb_hi and (cb_hi - cb_lo) > (
                pb_hi - pb_lo):
            out.append("BULLISH_ENGULFING")
        if bear and prev_bull and cb_lo <= pb_lo and cb_hi >= pb_hi and (cb_hi - cb_lo) > (
                pb_hi - pb_lo):
            out.append("BEARISH_ENGULFING")
        if c.high < prev.high and c.low > prev.low:
            out.append("INSIDE_BAR")
    return out


def recent_patterns(window: list[Candle], atr_series: list[float | None], skip: set,
                    n: int = RECENT_BARS) -> list[dict[str, Any]]:
    """Mẫu của ``n`` nến cuối (mới nhất cuối danh sách)."""
    out = []
    for i in range(max(1, len(window) - n), len(window)):
        # Thước đo "nến nhỏ" = ATR tới nến TRƯỚC (không để chính nến c thổi phồng thước đo)
        c, a = window[i], atr_series[i - 1]
        if a is None or c.open_time in skip or window[i - 1].open_time in skip:
            continue
        names = candle_patterns(window[i - 1], c, a)
        if names:
            out.append({"open_time": c.open_time.isoformat(), "patterns": names})
    return out


def double_patterns(swings, atr_value: float, index_of: dict) -> dict[str, Any]:
    """Đỉnh đôi / đáy đôi từ hai swing **đã xác nhận** gần nhất cùng loại."""
    res: dict[str, Any] = {"double_top": None, "double_bottom": None}
    for kind, key in (("HIGH", "double_top"), ("LOW", "double_bottom")):
        ss = [s for s in swings if s.kind == kind and s.open_time in index_of]
        if len(ss) < 2:
            continue
        a, b = ss[-2], ss[-1]
        gap = index_of[b.open_time] - index_of[a.open_time]
        if gap >= DOUBLE_MIN_GAP and abs(a.price - b.price) <= DOUBLE_TOL_ATR * atr_value:
            res[key] = {"first": a.open_time.isoformat(), "second": b.open_time.isoformat(),
                        "first_price": a.price, "second_price": b.price, "bars_apart": gap,
                        "confirmed_at": b.confirmed_at.isoformat()}
    return res
