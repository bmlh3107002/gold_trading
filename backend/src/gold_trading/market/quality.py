"""Đánh giá chất lượng một cửa sổ nến trước khi phân tích (R2–R6, xem docs/thiet-ke/03).

Chỉ đánh giá, không sửa dữ liệu.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from statistics import median

from gold_trading.contracts.candle import Candle
from gold_trading.market.hours import REFERENCE, MarketCalendar
from gold_trading.market.timeframes import Timeframe

MIN_COVERAGE = 0.99
SPIKE_MULTIPLE = 8.0
FROZEN_RUN = 4
WIDE_SPREAD_MULTIPLE = 3.0


@dataclass(frozen=True)
class WindowQuality:
    bars: int
    expected_bars: int
    coverage: float
    missing: list[datetime] = field(default_factory=list)
    spikes: list[datetime] = field(default_factory=list)
    frozen_runs: list[datetime] = field(default_factory=list)  # open_time của nến đầu mỗi chuỗi
    # Nến có thật nhưng rơi vào lúc lịch nói là đóng cửa → lịch (hoặc múi giờ) đang sai
    outside_session: list[datetime] = field(default_factory=list)
    wide_spread_last: bool = False

    @property
    def low_coverage(self) -> bool:
        return self.coverage < MIN_COVERAGE


def expected_open_times(
    first: datetime, last: datetime, tf: Timeframe, calendar: MarketCalendar = REFERENCE
) -> list[datetime]:
    """Mọi open_time trong giờ mở cửa từ ``first`` tới ``last`` (bao gồm hai đầu)."""
    out = []
    t = first
    while t <= last:
        if calendar.bar_in_session(t, t + tf.delta):
            out.append(t)
        t += tf.delta
    return out


def assess_window(
    candles: list[Candle], tf: Timeframe, calendar: MarketCalendar = REFERENCE
) -> WindowQuality:
    if not candles:
        return WindowQuality(0, 0, 0.0)
    present = {c.open_time for c in candles}
    expected = expected_open_times(candles[0].open_time, candles[-1].open_time, tf, calendar)
    expected_set = set(expected)
    missing = [t for t in expected if t not in present]
    outside = [c.open_time for c in candles if c.open_time not in expected_set]
    # Độ phủ chỉ tính trên nến lẽ ra phải có; nến ngoài giờ được báo riêng, không bù cho nến thiếu
    coverage = (len(expected) - len(missing)) / len(expected) if expected else 0.0

    ranges = [c.high - c.low for c in candles]
    med_range = median(ranges) if ranges else 0.0
    spikes: list[datetime] = []
    if med_range > 0:
        for i, c in enumerate(candles):
            jump = abs(c.open - candles[i - 1].close) if i > 0 else 0.0
            if ranges[i] > SPIKE_MULTIPLE * med_range or jump > SPIKE_MULTIPLE * med_range:
                spikes.append(c.open_time)

    frozen: list[datetime] = []
    run = 1
    for i in range(1, len(candles)):
        same = candles[i].ohlcv[:4] == candles[i - 1].ohlcv[:4]
        run = run + 1 if same else 1
        if run == FROZEN_RUN:
            frozen.append(candles[i - FROZEN_RUN + 1].open_time)

    spreads = [c.spread_points for c in candles if c.spread_points is not None]
    last_spread = candles[-1].spread_points
    wide = bool(
        spreads
        and last_spread is not None
        and median(spreads) > 0
        and last_spread > WIDE_SPREAD_MULTIPLE * median(spreads)
    )
    return WindowQuality(
        bars=len(candles),
        expected_bars=len(expected),
        coverage=coverage,
        missing=missing,
        spikes=spikes,
        frozen_runs=frozen,
        wide_spread_last=wide,
        outside_session=outside,
    )
