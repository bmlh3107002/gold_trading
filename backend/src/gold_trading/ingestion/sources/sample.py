"""Bộ sinh dữ liệu MẪU cho XAUUSD — KHÔNG phải giá thị trường thật.

Chỉ dùng để dựng giao diện, pipeline và test. Mô hình: random walk log-normal,
biến động theo phiên (Á thấp, London/NY cao), chỉ sinh nến trong giờ mở cửa.

Tất định: cùng seed + cùng giá khởi đầu → cùng chuỗi nến, nên restart không tạo dữ liệu khác.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator
from datetime import UTC, datetime

from gold_trading.ingestion.candles import RawBar
from gold_trading.market.hours import REFERENCE
from gold_trading.market.timeframes import Timeframe

# Biến động năm ~15% → độ lệch chuẩn log-return cho 1 phút giao dịch
_ANNUAL_VOL = 0.15
_MINUTES_PER_YEAR = 252 * 23 * 60


def _session_factor(t: datetime) -> float:
    h = t.astimezone(UTC).hour
    if 7 <= h < 12:  # London
        return 1.2
    if 12 <= h < 17:  # London + New York
        return 1.6
    if 17 <= h < 21:  # New York chiều
        return 1.0
    return 0.6  # phiên Á


def _bar(prev_close: float, open_time: datetime, tf: Timeframe, seed: int, gap: bool) -> RawBar:
    rng = random.Random(f"{seed}:{int(open_time.timestamp())}")
    minutes = tf.delta.total_seconds() / 60
    sigma = _ANNUAL_VOL * math.sqrt(minutes / _MINUTES_PER_YEAR) * _session_factor(open_time)
    # Gap mở cửa đầu tuần/sau nghỉ: lệch nhẹ so với giá đóng trước đó
    o = prev_close * math.exp(rng.gauss(0, sigma * 2)) if gap else prev_close
    c = o * math.exp(rng.gauss(0, sigma))
    wick_up = abs(rng.gauss(0, sigma * 0.6))
    wick_dn = abs(rng.gauss(0, sigma * 0.6))
    o, c = round(o, 2), round(c, 2)
    h = max(round(max(o, c) * math.exp(wick_up), 2), o, c)
    lo = min(round(min(o, c) * math.exp(-wick_dn), 2), o, c)
    vol = int(rng.uniform(400, 1400) * _session_factor(open_time) * minutes / 15)
    spread = int(rng.uniform(15, 30) / _session_factor(open_time))
    return RawBar(
        open_time=open_time, open=o, high=h, low=lo, close=c, tick_volume=vol, spread_points=spread
    )


def generate(
    *,
    start: datetime,
    end: datetime,
    tf: Timeframe,
    prev_close: float,
    seed: int,
) -> Iterator[RawBar]:
    """Sinh nến đã đóng có open_time trong [start, end - tf], chỉ trong giờ mở cửa."""
    t = tf.floor(start)
    if t < start:
        t += tf.delta
    last_close = prev_close
    pending_gap = False
    while t + tf.delta <= end:
        if REFERENCE.bar_in_session(t, t + tf.delta):
            bar = _bar(last_close, t, tf, seed, pending_gap)
            last_close = bar.close
            pending_gap = False
            yield bar
        else:
            pending_gap = True
        t += tf.delta
