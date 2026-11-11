"""Cửa nạp nến duy nhất cho mọi nguồn (SAMPLE, CSV, MT5).

Mọi nguồn đưa vào ``RawBar`` → ``CandleIngestor.ingest`` sẽ:
1. Kiểm tra (schema, OHLC, căn khung, nến đã đóng). Lỗi → quarantine kèm lý do, không bịa giá trị.
2. Khử trùng: cùng khóa + cùng giá trị → bỏ qua (idempotent).
3. Cùng khóa nhưng giá trị khác → revision mới (không ghi đè), available_at = lúc nhận.
4. Gắn cờ chất lượng: GAP_BEFORE, PRICE_JUMP, ZERO_RANGE (chỉ cờ, không sửa dữ liệu).

Khung H4/D1 (ING-14, 1A-C19) căn theo giờ server broker: bắt buộc truyền ``server_tz`` để kiểm
tra căn khung và tính ``close_time`` thật (ngày đổi DST dài 23/25 giờ). Không tự tổng hợp từ M15.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from gold_trading.contracts.candle import Candle, CandleFlag, DataSource
from gold_trading.market.hours import REFERENCE, MarketCalendar
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


def _ohlcv(b: RawBar) -> tuple[float, float, float, float, int]:
    return (b.open, b.high, b.low, b.close, b.tick_volume)


def _finite(*xs: float) -> bool:
    return all(isinstance(x, int | float) and math.isfinite(x) for x in xs)


class CandleIngestor:
    def __init__(self, store: CandleStore, calendar: MarketCalendar = REFERENCE) -> None:
        self.store = store
        # CAL-04: cờ GAP_BEFORE theo lịch đầy đủ (tham chiếu ∩ broker − ngày lễ + giờ đặc biệt)
        self.calendar = calendar

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
        server_tz: ZoneInfo | None = None,
        feed: str = "",
    ) -> IngestResult:
        """``backfill=True``: dữ liệu lịch sử, available_at = close_time (cờ BACKFILL).
        ``backfill=False``: dữ liệu realtime, available_at = ingested_at.
        ``server_tz``: múi giờ server broker, BẮT BUỘC với H4/D1.
        ``feed``: MT-05, nguồn giá; khử trùng / revision / GAP chỉ so với nến CÙNG feed."""
        if timeframe.server_aligned and server_tz is None:
            raise ValueError(f"Khung {timeframe} cần múi giờ server broker (server_tz)")
        result = IngestResult()
        quarantine: list[QuarantineEntry] = []
        # Dòng đã bị nguồn từ chối (ví dụ không đọc được thời gian) vẫn phải được ghi lại.
        for reason, raw in rejected:
            result._reject(reason)
            quarantine.append(
                QuarantineEntry(
                    source=source,
                    feed_id=feed,
                    symbol=symbol,
                    timeframe=timeframe,
                    received_at=ingested_at,
                    reason=reason,
                    raw=raw,
                )
            )
        # Cùng thời điểm xuất hiện nhiều lần trong một batch:
        # - giống hệt nhau  -> giữ một, đếm là trùng
        # - giá trị khác nhau -> không biết dòng nào đúng: cách ly tất cả, KHÔNG tạo revision giả
        groups: dict[datetime, list[RawBar]] = {}
        for b in bars:
            groups.setdefault(b.open_time, []).append(b)
        ordered: list[RawBar] = []
        for t in sorted(groups, key=lambda x: (x.tzinfo is None, x.replace(tzinfo=None))):
            items = groups[t]
            if len({_ohlcv(b) for b in items}) > 1:
                for b in items:
                    result._reject("CONFLICTING_DUPLICATE")
                    quarantine.append(
                        QuarantineEntry(
                            source=source,
                            feed_id=feed,
                            symbol=symbol,
                            timeframe=timeframe,
                            received_at=ingested_at,
                            reason="CONFLICTING_DUPLICATE",
                            raw=_raw_payload(b),
                        )
                    )
                continue
            result.duplicates += len(items) - 1
            ordered.append(items[0])
        if not ordered:
            self.store.append([], quarantine)
            return result

        lo, hi = ordered[0].open_time, ordered[-1].open_time
        existing = self.store.latest_by_open_time(symbol, timeframe, source, lo, hi, feed=feed)
        prev: Candle | None = self.store.last_before(symbol, timeframe, source, lo, feed=feed)
        accepted: list[Candle] = []

        for bar in ordered:
            reason = self._check(bar, timeframe, ingested_at, server_tz)
            if reason:
                result._reject(reason)
                quarantine.append(
                    QuarantineEntry(
                        source=source,
                        feed_id=feed,
                        symbol=symbol,
                        timeframe=timeframe,
                        received_at=ingested_at,
                        reason=reason,
                        raw=_raw_payload(bar),
                    )
                )
                continue

            current = existing.get(bar.open_time)
            if current is not None and current.ohlcv == _ohlcv(bar):
                result.duplicates += 1
                prev = current
                continue

            flags: set[CandleFlag] = set()
            revision = 0
            close_time = timeframe.close_time(bar.open_time, server_tz)
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
                if prev.close_time < bar.open_time and _gap_in_session(
                    prev.close_time, bar.open_time, timeframe, self.calendar, server_tz
                ):
                    flags.add(CandleFlag.GAP_BEFORE)
                if abs(bar.open / prev.close - 1) > PRICE_JUMP_THRESHOLD:
                    flags.add(CandleFlag.PRICE_JUMP)

            candle = Candle(
                symbol=symbol,
                timeframe=timeframe,
                source=source,
                feed_id=feed,
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
    def _check(
        bar: RawBar, tf: Timeframe, ingested_at: datetime, server_tz: ZoneInfo | None = None
    ) -> str | None:
        if bar.open_time.tzinfo is None:
            return "NAIVE_TIME"
        if not _finite(bar.open, bar.high, bar.low, bar.close):
            return "NON_FINITE_PRICE"
        if min(bar.open, bar.high, bar.low, bar.close) <= 0:
            return "NON_POSITIVE_PRICE"
        if bar.tick_volume < 0 or (bar.spread_points is not None and bar.spread_points < 0):
            return "NEGATIVE_VOLUME"
        if not tf.is_aligned_in(bar.open_time, server_tz):
            return "MISALIGNED_TIME"
        if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
            return "INVALID_OHLC"
        if tf.close_time(bar.open_time, server_tz) > ingested_at:
            return "BAR_NOT_CLOSED"
        return None


_GAP_SCAN_LIMIT = 10_000


def _gap_in_session(
    after: datetime,
    before: datetime,
    tf: Timeframe,
    calendar: MarketCalendar = REFERENCE,
    server_tz: ZoneInfo | None = None,
) -> bool:
    """Có nến nào "lẽ ra phải có" bị thiếu giữa ``after`` và ``before`` không.

    M1–H1: nến nằm trọn trong giờ mở cửa. H4/D1: nến dài, thường vắt qua giờ nghỉ hằng ngày nên
    chỉ cần thị trường mở ở BẤT KỲ lúc nào trong nến (MT5 tạo nến khi có tick)."""
    t = after
    for _ in range(_GAP_SCAN_LIMIT):
        if t >= before:
            return False
        end = tf.close_time(t, server_tz) if tf.server_aligned else t + tf.delta
        if tf.server_aligned:
            if _any_open(t, end, calendar):
                return True
        elif calendar.bar_in_session(t, end):
            return True
        t = end
    return True  # khoảng quá dài: coi là có thiếu (an toàn)


def _any_open(start: datetime, end: datetime, calendar: MarketCalendar) -> bool:
    step = timedelta(minutes=15)
    t = start
    while t < end:
        if calendar.is_open(t):
            return True
        t += step
    return False


# ---------------------------------------------------------------------------
# 1A-C21: nến cuối phiên (vị trí 0 của MT5) trước cuối tuần / ngày lễ / giờ nghỉ
# ---------------------------------------------------------------------------

# Chờ thêm sau giờ đóng nến để terminal nhận nốt tick cuối (an toàn hơn là nhanh).
TAIL_GRACE = timedelta(minutes=2)
# Thị trường không đóng liền quá 7 ngày; dài hơn thì không xác minh được → giữ lại.
TAIL_MAX_SPAN = timedelta(days=7)
_TAIL_STEP = timedelta(minutes=1)  # giờ lịch (broker, ngày lễ, giờ đặc biệt) đều theo phút


class TailStatus(StrEnum):
    NONE = "NONE"  # không gửi nến vị trí 0
    INCLUDED = "INCLUDED"  # coi là đã đóng, đưa vào lô như nến thường
    HELD_NOT_CLOSED = "HELD_NOT_CLOSED"  # chưa hết thời gian nến (+ TAIL_GRACE)
    HELD_MARKET_OPEN = "HELD_MARKET_OPEN"  # lịch báo mở cửa ở lúc nào đó từ khi nến đóng tới giờ
    HELD_NOT_LATEST = "HELD_NOT_LATEST"  # không mới hơn mọi nến đã đóng trong lô: dữ liệu lạ


def tail_status(
    tail_open: datetime,
    latest_closed_open: datetime | None,
    tf: Timeframe,
    now: datetime,
    calendar: MarketCalendar,
    server_tz: ZoneInfo | None = None,
) -> TailStatus:
    """Nến ở vị trí 0 của MT5 có được coi là ĐÃ ĐÓNG không (1A-C21).

    MT5 chỉ chuyển nến sang vị trí 1 khi có tick của nến kế tiếp, nên nến cuối trước cuối tuần /
    ngày lễ / giờ nghỉ nằm ở vị trí 0 tới khi thị trường mở lại. Chỉ coi là đã đóng khi CẢ HAI:

    1. hết thời gian nến theo đồng hồ backend: ``close_time + TAIL_GRACE <= now`` (H4/D1 tính
       ``close_time`` theo giờ server broker, ngày đổi DST dài/ngắn đúng thực tế);
    2. lịch đầy đủ (tham chiếu ∩ broker − ngày lễ + giờ đặc biệt) báo **đóng cửa suốt** từ
       ``close_time`` tới ``now``. Nếu lịch mở ở bất kỳ phút nào trong khoảng đó thì việc không có
       nến mới có thể do terminal mất kết nối / chậm → giữ lại (chờ MT5 chuyển nến sang vị trí 1).

    Lịch sai (thiếu ``GT_BROKER_SESSIONS``) chỉ làm nến bị giữ lâu hơn, không bao giờ nhận sớm.
    """
    if latest_closed_open is not None and tail_open <= latest_closed_open:
        return TailStatus.HELD_NOT_LATEST
    close = tf.close_time(tail_open, server_tz)
    if close + TAIL_GRACE > now:
        return TailStatus.HELD_NOT_CLOSED
    if now - close > TAIL_MAX_SPAN:
        return TailStatus.HELD_MARKET_OPEN
    t = close
    while t <= now:
        if calendar.is_open(t):
            return TailStatus.HELD_MARKET_OPEN
        t += _TAIL_STEP
    if calendar.is_open(now):
        return TailStatus.HELD_MARKET_OPEN
    return TailStatus.INCLUDED


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
