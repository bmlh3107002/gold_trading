"""Phần mở rộng Technical (GĐ3 bước 7a — TEC-07, TEC-09). Thiết kế: ``03-technical-analyst.md`` §8.

- **TEC-07 ``vol_forecast``** — EWMA λ = 0,94 (RiskMetrics) trên lợi suất log M15: σ nến kế tiếp,
  σ một ngày giao dịch (× √96). **Luật cố định, không phải mô hình đã kiểm định**; không xác suất.
- **TEC-09 bối cảnh đa khung** — H1 / H4 / D1 của **cùng nguồn giá**, chỉ nến **đã đóng** trước
  ``as_of`` của M15: xu hướng theo **đúng luật xu hướng của M15** (EMA20 / EMA50 + độ dốc EMA50 theo
  ATR). Khung cũ (quá một nến + 30 phút **thị trường mở** — cuối tuần không tính) → không dùng.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from gold_trading.analysts.indicators import atr, ema
from gold_trading.contracts.candle import Candle
from gold_trading.market.hours import MarketCalendar
from gold_trading.market.timeframes import Timeframe

EWMA_LAMBDA = 0.94
EWMA_SEED = 30            # phương sai khởi đầu = trung bình bình phương 30 lợi suất đầu
EWMA_MIN_RETURNS = 60
DAY_BARS_M15 = 96
HIGHER = (Timeframe.H1, Timeframe.H4, Timeframe.D1)
MTF_MIN_BARS = 70         # EMA50 + 10 nến độ dốc + đệm
MTF_LIMIT = 200
STALE_GRACE = timedelta(minutes=30)
SLOPE_BARS = 10
SLOPE_MIN_ATR = 0.1


def ewma_vol(closes: list[float]) -> dict[str, Any] | None:
    """σ dự báo nến kế tiếp theo EWMA. None nếu chưa đủ lợi suất."""
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:], strict=False) if a > 0 and b > 0]
    if len(rets) < EWMA_MIN_RETURNS:
        return None
    var = sum(r * r for r in rets[:EWMA_SEED]) / EWMA_SEED
    for r in rets[EWMA_SEED:]:
        var = EWMA_LAMBDA * var + (1 - EWMA_LAMBDA) * r * r
    s_bar = math.sqrt(var)
    return {"sigma_bar_pct": round(s_bar * 100, 5),
            "sigma_day_pct": round(s_bar * math.sqrt(DAY_BARS_M15) * 100, 4),
            "returns_used": len(rets),
            "method": "EWMA λ=0,94 (RiskMetrics) trên lợi suất log M15 — luật cố định, "
                      "không phải mô hình đã kiểm định"}


def trend_of(candles: list[Candle]) -> dict[str, Any] | None:
    if len(candles) < MTF_MIN_BARS:
        return None
    closes = [c.close for c in candles]
    a = atr([c.high for c in candles], [c.low for c in candles], closes, 14)[-1]
    e20, e50 = ema(closes, 20), ema(closes, 50)
    c20, c50, prev = e20[-1], e50[-1], e50[-1 - SLOPE_BARS]
    if None in (a, c20, c50, prev) or not a:
        return None
    slope = (c50 - prev) / a
    close = closes[-1]
    if c20 > c50 and close > c50 and slope > SLOPE_MIN_ATR:
        t = "UP"
    elif c20 < c50 and close < c50 and slope < -SLOPE_MIN_ATR:
        t = "DOWN"
    else:
        t = "FLAT"
    return {"trend": t, "ema20": round(c20, 4), "ema50": round(c50, 4),
            "ema50_slope_atr": round(slope, 3)}


def open_minutes(start: datetime, end: datetime, calendar: MarketCalendar,
                 cap: int) -> int:
    """Số phút thị trường mở trong ``[start, end)`` (dừng đếm khi vượt ``cap``)."""
    n, t = 0, start
    while t < end and n <= cap:
        if calendar.is_open(t):
            n += 1
        t += timedelta(minutes=1)
    return n


def mtf_context(higher: dict[Timeframe, list[Candle]] | None, as_of: datetime,
                calendar: MarketCalendar) -> dict[str, Any]:
    """Bối cảnh từng khung lớn. ``higher=None`` → chưa đánh giá (vd. nguồn không có khung lớn)."""
    out: dict[str, Any] = {}
    for tf in HIGHER:
        rows = [c for c in (higher or {}).get(tf, []) if c.close_time <= as_of]
        if higher is None or tf not in higher:
            out[tf.value] = {"status": "NOT_EVALUATED"}
            continue
        if not rows:
            out[tf.value] = {"status": "MISSING"}
            continue
        last = rows[-1]
        limit = int((tf.delta + STALE_GRACE).total_seconds() // 60)
        if open_minutes(last.close_time, as_of, calendar, limit) > limit:
            out[tf.value] = {"status": "STALE", "last_close": last.close_time.isoformat()}
            continue
        t = trend_of(rows)
        if t is None:
            out[tf.value] = {"status": "INSUFFICIENT_HISTORY", "bars": len(rows)}
            continue
        out[tf.value] = {"status": "OK", "last_close": last.close_time.isoformat(),
                         "bars": len(rows), **t}
    return out


def alignment(m15_trend: str, mtf: dict[str, Any]) -> str:
    """ALIGNED_UP / ALIGNED_DOWN (mọi khung có đánh giá cùng chiều M15), CONFLICT (có khung ngược
    chiều), MIXED (còn lại), NOT_EVALUATED (không khung lớn nào dùng được)."""
    trends = [v["trend"] for v in mtf.values() if v.get("status") == "OK"]
    if not trends:
        return "NOT_EVALUATED"
    opposite = {"UP": "DOWN", "DOWN": "UP"}.get(m15_trend)
    if opposite and opposite in trends:
        return "CONFLICT"
    if m15_trend in ("UP", "DOWN") and all(t == m15_trend for t in trends):
        return f"ALIGNED_{m15_trend}"
    return "MIXED"
