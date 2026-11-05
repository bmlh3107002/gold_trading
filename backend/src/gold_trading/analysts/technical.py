"""Technical analyst v1 — mô tả trạng thái giá bằng quy tắc xác định. Xem docs/thiet-ke/03.

KHÔNG dự báo xác suất, KHÔNG ra tín hiệu mua/bán. ``confidence`` chỉ đo chất lượng dữ liệu.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from gold_trading.analysts.indicators import atr, ema, rsi
from gold_trading.common.enums import SourceStatus
from gold_trading.contracts.analyst import AnalystOutput
from gold_trading.contracts.candle import Candle, DataSource
from gold_trading.market.quality import assess_window
from gold_trading.market.timeframes import Timeframe

VERSION = "technical-1.0.0"
ANALYST_ID = "technical"
WINDOW = 300
MIN_BARS = 250
SWING_K = 3
SLOPE_BARS = 10
SLOPE_MIN_ATR = 0.1
LEVEL_TOL_ATR = 0.5
LEVEL_MIN_TOUCHES = 2
VOL_LOOKBACK = 96
HIGH_VOL_RATIO = 2.0
EXPIRY_GRACE = timedelta(minutes=2)


@dataclass(frozen=True)
class Swing:
    kind: str  # HIGH | LOW
    open_time: datetime
    price: float
    confirmed_at: datetime  # close_time của nến thứ K sau swing


def input_hash(candles: list[Candle]) -> str:
    h = hashlib.sha256()
    for c in candles:
        h.update(
            f"{c.open_time.isoformat()}|{c.open!r}|{c.high!r}|{c.low!r}|{c.close!r}|{c.revision};".encode()
        )
    return h.hexdigest()


def find_swings(candles: list[Candle], k: int = SWING_K) -> list[Swing]:
    """Fractal k: chỉ xác nhận khi đã có đủ k nến ĐÃ ĐÓNG ở bên phải (không nhìn trước)."""
    out: list[Swing] = []
    for i in range(k, len(candles) - k):
        c = candles[i]
        left, right = candles[i - k : i], candles[i + 1 : i + 1 + k]
        confirmed_at = candles[i + k].close_time
        if all(c.high > x.high for x in left + right):
            out.append(Swing("HIGH", c.open_time, c.high, confirmed_at))
        if all(c.low < x.low for x in left + right):
            out.append(Swing("LOW", c.open_time, c.low, confirmed_at))
    return out


def cluster_levels(swings: list[Swing], tol: float) -> list[dict[str, Any]]:
    """Gom swing thành vùng giá trong dung sai ``tol``; giữ vùng chạm >= LEVEL_MIN_TOUCHES."""
    prices = sorted(s.price for s in swings)
    groups: list[list[float]] = []
    for p in prices:
        if groups and p - groups[-1][-1] <= tol:
            groups[-1].append(p)
        else:
            groups.append([p])
    return [
        {
            "price": round(sum(g) / len(g), 2),
            "low": round(g[0], 2),
            "high": round(g[-1], 2),
            "touches": len(g),
        }
        for g in groups
        if len(g) >= LEVEL_MIN_TOUCHES
    ]


def _structure(swings: list[Swing]) -> str:
    highs = [s.price for s in swings if s.kind == "HIGH"][-2:]
    lows = [s.price for s in swings if s.kind == "LOW"][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return "UNKNOWN"
    if highs[1] > highs[0] and lows[1] > lows[0]:
        return "BULLISH"
    if highs[1] < highs[0] and lows[1] < lows[0]:
        return "BEARISH"
    return "MIXED"


def analyze(
    rows: list[Candle],
    *,
    symbol: str,
    timeframe: Timeframe,
    source: DataSource,
    expected_last_close: datetime,
    correlation_id: str,
) -> AnalystOutput | None:
    """``rows``: nến point-in-time, đã gồm warm-up phía trước. None nếu không có nến nào."""
    if not rows:
        return None
    window = rows[-WINDOW:]
    last = window[-1]
    as_of = last.close_time
    q = assess_window(window, timeframe)
    quality_flags: set[str] = set()
    risk_flags: set[str] = set()
    status = SourceStatus.HEALTHY
    blocking: list[str] = []

    if len(window) < MIN_BARS:
        blocking.append("INSUFFICIENT_HISTORY")
    if q.low_coverage:
        blocking.append("LOW_COVERAGE")
    if last.close_time < expected_last_close:
        blocking.append("STALE_INPUT")
        status = SourceStatus.STALE
    if q.frozen_runs:
        blocking.append("FROZEN_FEED")
        status = SourceStatus.STALE
    if q.spikes:
        quality_flags.add("SPIKE_IN_WINDOW")
    if q.wide_spread_last:
        risk_flags.add("WIDE_SPREAD")
    if source.is_sample:
        quality_flags.add("SAMPLE_DATA")
    quality_flags.update(blocking)

    input_info = {
        "source": source.value,
        "bars": len(window),
        "first_open_time": window[0].open_time.isoformat(),
        "last_open_time": last.open_time.isoformat(),
        "max_revision": max(c.revision for c in window),
        "input_hash": input_hash(window),
        "coverage": round(q.coverage, 4),
        "missing_bars": len(q.missing),
        "spikes": [t.isoformat() for t in q.spikes],
    }
    base = dict(
        output_id=f"{ANALYST_ID}:{VERSION}:{source.value}:{symbol}:{timeframe.value}:{as_of.isoformat()}:{input_info['input_hash'][:16]}",
        analyst_id=ANALYST_ID,
        as_of=as_of,
        expires_at=as_of + timeframe.delta + EXPIRY_GRACE,
        version=VERSION,
        correlation_id=correlation_id,
        quality_flags=frozenset(quality_flags),
    )

    if blocking:
        if status is SourceStatus.HEALTHY:
            status = SourceStatus.INVALID
        return AnalystOutput(
            **base,
            confidence=0.0,
            features={"input": input_info},
            drivers=tuple(blocking),
            risk_flags=frozenset(risk_flags),
            source_status=status,
        )

    highs = [c.high for c in rows]
    lows = [c.low for c in rows]
    closes = [c.close for c in rows]
    atr_s = atr(highs, lows, closes, 14)
    e20, e50, r14 = ema(closes, 20), ema(closes, 50), rsi(closes, 14)
    a, c20, c50, rv = atr_s[-1], e20[-1], e50[-1], r14[-1]
    e50_prev = e50[-1 - SLOPE_BARS] if len(e50) > SLOPE_BARS else None
    if None in (a, c20, c50, rv, e50_prev) or not a:
        return AnalystOutput(
            **base,
            confidence=0.0,
            features={"input": input_info},
            drivers=("INSUFFICIENT_HISTORY",),
            risk_flags=frozenset(risk_flags),
            source_status=SourceStatus.INVALID,
        )
    close = last.close
    slope = (c50 - e50_prev) / a
    if c20 > c50 and close > c50 and slope > SLOPE_MIN_ATR:
        trend = "UP"
    elif c20 < c50 and close < c50 and slope < -SLOPE_MIN_ATR:
        trend = "DOWN"
    else:
        trend = "FLAT"

    recent_atr = [x for x in atr_s[-VOL_LOOKBACK:] if x is not None]
    vol_ratio = a / median(recent_atr) if recent_atr else None
    if vol_ratio is not None and vol_ratio > HIGH_VOL_RATIO:
        risk_flags.add("HIGH_VOLATILITY")

    swings = [s for s in find_swings(window) if s.confirmed_at <= as_of]
    levels = cluster_levels(swings, LEVEL_TOL_ATR * a)
    supports = [lv for lv in levels if lv["high"] < close]
    resistances = [lv for lv in levels if lv["low"] > close]
    sup = max(supports, key=lambda lv: lv["price"]) if supports else None
    res = min(resistances, key=lambda lv: lv["price"]) if resistances else None

    def lvl(v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is None:
            return None
        return v | {"distance_atr": round(abs(close - v["price"]) / a, 2)}

    features = {
        "close": close,
        "atr14": round(a, 4),
        "atr_pct": round(a / close, 6),
        "vol_ratio": round(vol_ratio, 3) if vol_ratio is not None else None,
        "ema20": round(c20, 4),
        "ema50": round(c50, 4),
        "ema50_slope_atr": round(slope, 3),
        "trend": trend,
        "trend_strength_atr": round((c20 - c50) / a, 3),
        "rsi14": round(rv, 2),
        "structure": _structure(swings),
        "swings": [
            {"kind": s.kind, "open_time": s.open_time.isoformat(), "price": s.price}
            for s in swings[-10:]
        ],
        "levels": levels,
        "nearest_support": lvl(sup),
        "nearest_resistance": lvl(res),
        "input": input_info,
    }
    drivers = [f"TREND_{trend}", f"STRUCTURE_{features['structure']}"]
    if rv >= 70:
        drivers.append("RSI_OVERBOUGHT")
    elif rv <= 30:
        drivers.append("RSI_OVERSOLD")
    # confidence = chất lượng dữ liệu, KHÔNG phải khả năng dự báo
    confidence = 1.0 if q.coverage >= 1.0 else 0.9
    if q.spikes:
        confidence *= 0.5
    return AnalystOutput(
        **base,
        confidence=round(confidence, 3),
        features=json.loads(json.dumps(features)),
        drivers=tuple(drivers),
        risk_flags=frozenset(risk_flags),
        source_status=SourceStatus.HEALTHY,
    )
