"""Cửa nạp nến duy nhất cho mọi nguồn (SAMPLE, CSV, MT5).

Mọi nguồn đưa vào ``RawBar`` → ``CandleIngestor.ingest`` sẽ:
1. Kiểm tra (schema, OHLC, căn khung, nến đã đóng). Lỗi → quarantine kèm lý do, không bịa giá trị.
2. Khử trùng: cùng khóa + cùng giá trị → bỏ qua (idempotent).
3. Cùng khóa nhưng giá trị khác → revision mới (không ghi đè), available_at = lúc nhận.
4. Gắn cờ chất lượng: GAP_BEFORE, PRICE_JUMP, ZERO_RANGE (chỉ cờ, không sửa dữ liệu).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from gold_trading.contracts.candle import Candle, CandleFlag, DataSource
from gold_trading.market.hours import bar_in_session
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.candles import CandleStore, QuarantineEntry

# Biến động 1 nến M15 của vàng hiếm khi vượt ~2%; vượt ngưỡng thì gắn cờ để người xem kiểm tra.
PRICE_JUMP_THRESHOLD = 0.03


@dataclass(frozen=True)
class RawBar:
    """Nến thô từ nguồn, thời gian đã đổi về UTC (có tzinfo)."""

    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int = 0
    spread_points: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestResult:
    accepted: int = 0
    duplicates: int = 0
    revised: int = 0
    quarantined: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    def _reject(self, reason: str) -> None:
        self.quarantined += 1
        self.reasons[reason] = self.reasons.get(reason, 0) + 1


def _finite(*xs: float) -> bool:
    return all(isinstance(x, int | float) and math.isfinite(x) for x in xs)


class CandleIngestor:
    def __init__(self, store: CandleStore) -> None:
        self.store = store

    def ingest(
        self,
        bars: Iterable[RawBar],
        *,
        symbol: str,
        timeframe: Timeframe,
        source: DataSource,
        ingested_at: datetime,
        backfill: bool,
        rejected: Iterable[tuple[str, dict[str, Any]]] = (),
    ) -> IngestResult:
        """``backfill=True``: dữ liệu lịch sử, available_at = close_time (cờ BACKFILL).
        ``backfill=False``: dữ liệu realtime, available_at = ingested_at."""
        result = IngestResult()
        quarantine: list[QuarantineEntry] = []
        # Dòng đã bị nguồn từ chối (ví dụ không đọc được thời gian) vẫn phải được ghi lại.
        for reason, raw in rejected:
            result._reject(reason)
            quarantine.append(
                QuarantineEntry(
                    source=source,
                    symbol=symbol,
                    timeframe=timeframe,
                    received_at=ingested_at,
                    reason=reason,
                    raw=raw,
                )
            )
        ordered = sorted(bars, key=lambda b: b.open_time)
        if not ordered:
            self.store.append([], quarantine)
            return result

        lo, hi = ordered[0].open_time, ordered[-1].open_time
        existing = self.store.latest_by_open_time(symbol, timeframe, source, lo, hi)
        prev: Candle | None = self.store.last_before(symbol, timeframe, source, lo)
        accepted: list[Candle] = []

        for bar in ordered:
            reason = self._check(bar, timeframe, ingested_at)
            if reason:
                result._reject(reason)
                quarantine.append(
                    QuarantineEntry(
                        source=source,
                        symbol=symbol,
                        timeframe=timeframe,
                        received_at=ingested_at,
                        reason=reason,
                        raw=_raw_payload(bar),
                    )
                )
                continue

            current = existing.get(bar.open_time)
            ohlcv = (bar.open, bar.high, bar.low, bar.close, bar.tick_volume)
            if current is not None and current.ohlcv == ohlcv:
                result.duplicates += 1
                prev = current
                continue

            flags: set[CandleFlag] = set()
            revision = 0
            close_time = bar.open_time + timeframe.delta
            available_at = ingested_at
            if current is not None:
                revision = current.revision + 1
                flags.add(CandleFlag.REVISED)
                result.revised += 1
            elif backfill:
                flags.add(CandleFlag.BACKFILL)
                available_at = close_time
            if bar.high == bar.low:
                flags.add(CandleFlag.ZERO_RANGE)
            if prev is not None:
                if prev.open_time + timeframe.delta < bar.open_time and _gap_in_session(
                    prev.close_time, bar.open_time, timeframe
                ):
                    flags.add(CandleFlag.GAP_BEFORE)
                if abs(bar.open / prev.close - 1) > PRICE_JUMP_THRESHOLD:
                    flags.add(CandleFlag.PRICE_JUMP)

            candle = Candle(
                symbol=symbol,
                timeframe=timeframe,
                source=source,
                open_time=bar.open_time,
                close_time=close_time,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                tick_volume=bar.tick_volume,
                spread_points=bar.spread_points,
                revision=revision,
                ingested_at=ingested_at,
                available_at=available_at,
                flags=frozenset(flags),
            )
            accepted.append(candle)
            existing[bar.open_time] = candle
            prev = candle
            if current is None:
                result.accepted += 1

        self.store.append(accepted, quarantine)
        return result

    @staticmethod
    def _check(bar: RawBar, tf: Timeframe, ingested_at: datetime) -> str | None:
        if bar.open_time.tzinfo is None:
            return "NAIVE_TIME"
        if not _finite(bar.open, bar.high, bar.low, bar.close):
            return "NON_FINITE_PRICE"
        if min(bar.open, bar.high, bar.low, bar.close) <= 0:
            return "NON_POSITIVE_PRICE"
        if bar.tick_volume < 0 or (bar.spread_points is not None and bar.spread_points < 0):
            return "NEGATIVE_VOLUME"
        if not tf.is_aligned(bar.open_time):
            return "MISALIGNED_TIME"
        if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
            return "INVALID_OHLC"
        if bar.open_time + tf.delta > ingested_at:
            return "BAR_NOT_CLOSED"
        return None


def _gap_in_session(after: datetime, before: datetime, tf: Timeframe) -> bool:
    """Có nến nào trong giờ mở cửa bị thiếu giữa ``after`` và ``before`` không."""
    t = after
    while t < before:
        if bar_in_session(t, t + tf.delta):
            return True
        t += tf.delta
    return False


def _raw_payload(bar: RawBar) -> dict[str, Any]:
    def clean(v: Any) -> Any:
        if isinstance(v, float) and not math.isfinite(v):
            return str(v)
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    base = {
        "open_time": bar.open_time.isoformat(),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "tick_volume": bar.tick_volume,
        "spread_points": bar.spread_points,
    }
    return {k: clean(v) for k, v in (base | bar.raw).items()}
