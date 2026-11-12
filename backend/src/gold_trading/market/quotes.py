"""ING-08: giá sống bid/ask/spread gom theo GIÂY, point-in-time. Xem docs/thiet-ke/09a mục 5e.

Gateway gom các tick của một giây ĐÃ TRỌN thành một bản ghi (giá cuối giây, bid thấp nhất, ask
cao nhất, spread cuối + lớn nhất, số tick). Backend kiểm lại TỪNG bản ghi (không tin Gateway):

- 1A-C13: giờ không tròn giây / ở tương lai / quá hạn giữ, bid ≥ ask đảo (bid > ask), giá ≤ 0,
  thấp/cao mâu thuẫn với giá cuối, spread khai không khớp bid/ask, trùng giây trong lô
  → BỎ bản ghi đó + đếm theo lý do. Không bao giờ sửa giá trị, không đổi thứ tự lịch sử
  (bản ghi đến muộn vẫn lưu đúng giây của nó, ``available_at`` = lúc nhận).
- 1A-C14: spread lớn nhất trong giây > ``WIDE_SPREAD_MULTIPLE`` × trung vị spread cuối giây của
  1 giờ trước (cùng nguồn, ≥ ``BASELINE_MIN`` mẫu) → cờ ``WIDE_SPREAD``; lưu đúng giá trị thật.
  Chưa đủ mẫu → ``SPREAD_UNRATED`` (không nói là bình thường).
- 1A-C15: giây mà lịch nói đóng cửa → cờ ``CALENDAR_CLOSED`` (vẫn lưu, không coi là thị trường
  mở); ≥ ``CLOSED_MISMATCH_MIN`` giây như vậy trong 10 phút của cùng nguồn → ``CALENDAR_MISMATCH``.
- Cùng giây đã có (Gateway gửi lại / hai tài khoản cùng broker) → giữ bản đầu, đếm ``duplicates``
  (khác giá trị thì đếm thêm ``conflicts``).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median
from typing import Protocol

from gold_trading.market.quality import WIDE_SPREAD_MULTIPLE

FUTURE_TOLERANCE = timedelta(seconds=2)
BASELINE_WINDOW = timedelta(hours=1)
BASELINE_MIN = 60
CLOSED_WINDOW = timedelta(minutes=10)
CLOSED_MISMATCH_MIN = 30
# Spread khai báo được lệch spread tính từ bid/ask tối đa 1 point (làm tròn).
SPREAD_TOLERANCE_POINTS = 1

WIDE_SPREAD = "WIDE_SPREAD"
SPREAD_UNRATED = "SPREAD_UNRATED"
CALENDAR_CLOSED = "CALENDAR_CLOSED"


@dataclass(frozen=True)
class QuoteIn:
    """Một giây do Gateway gửi (chưa kiểm)."""

    t: datetime
    bid: float
    ask: float
    bid_low: float
    ask_high: float
    spread_max_points: int
    ticks: int


@dataclass(frozen=True)
class QuoteSecond:
    feed_id: str
    t: datetime
    bid: float
    ask: float
    bid_low: float
    ask_high: float
    spread_points: int
    spread_max_points: int
    ticks: int
    flags: tuple[str, ...]
    ingested_at: datetime
    available_at: datetime

    def same_values(self, other: QuoteSecond) -> bool:
        return (self.bid, self.ask, self.bid_low, self.ask_high, self.spread_max_points,
                self.ticks) == (other.bid, other.ask, other.bid_low, other.ask_high,
                                other.spread_max_points, other.ticks)


class QuoteStore(Protocol):
    def window(self, feed: str, lo: datetime, hi: datetime) -> list[QuoteSecond]: ...
    def append(self, rows: list[QuoteSecond]) -> int: ...
    def latest(self, feed: str, as_of: datetime) -> QuoteSecond | None: ...
    def purge_before(self, cutoff: datetime) -> int: ...


class Calendar(Protocol):
    def is_open(self, t: datetime) -> bool: ...


@dataclass
class QuoteResult:
    received: int = 0
    accepted: int = 0
    duplicates: int = 0
    conflicts: int = 0
    dropped: dict[str, int] = field(default_factory=dict)
    wide_spread: int = 0
    calendar_closed: int = 0
    calendar_mismatch: bool = False

    def drop(self, reason: str) -> None:
        self.dropped[reason] = self.dropped.get(reason, 0) + 1


def spread_points(bid: float, ask: float, point: float) -> int:
    return int(round((ask - bid) / point))


def check_quote(q: QuoteIn, point: float, now: datetime, oldest: datetime) -> str | None:
    """Lý do bỏ bản ghi (1A-C13), hoặc None nếu hợp lệ."""
    if q.t.microsecond or q.t.tzinfo is None:
        return "NOT_WHOLE_SECOND"
    if q.t > now + FUTURE_TOLERANCE:
        return "FUTURE"
    if q.t < oldest:
        return "TOO_OLD"
    nums = (q.bid, q.ask, q.bid_low, q.ask_high)
    if not all(math.isfinite(x) and x > 0 for x in nums):
        return "NON_POSITIVE"
    if q.bid > q.ask:
        return "CROSSED"  # bid > ask: báo giá hỏng
    if q.bid_low > q.bid or q.ask_high < q.ask:
        return "INCONSISTENT"
    if q.ticks < 1 or q.spread_max_points < 0:
        return "INCONSISTENT"
    if q.spread_max_points + SPREAD_TOLERANCE_POINTS < spread_points(q.bid, q.ask, point):
        return "INCONSISTENT"  # spread lớn nhất nhỏ hơn spread cuối giây
    return None


class QuoteIngestor:
    def __init__(
        self,
        store: QuoteStore,
        calendar: Calendar,
        *,
        retention: timedelta = timedelta(days=30),
        purge_every: timedelta = timedelta(hours=1),
    ) -> None:
        self.store, self.calendar = store, calendar
        self.retention, self.purge_every = retention, purge_every
        self._next_purge: datetime | None = None

    def ingest(
        self, items: Iterable[QuoteIn], *, feed: str, point: float, now: datetime
    ) -> QuoteResult:
        if not (math.isfinite(point) and point > 0):
            raise ValueError("point phải > 0")
        res = QuoteResult()
        oldest = now - self.retention
        valid: list[QuoteIn] = []
        seen: set[datetime] = set()
        for q in items:
            res.received += 1
            reason = check_quote(q, point, now, oldest)
            if reason is None and q.t in seen:
                reason = "DUPLICATE_IN_BATCH"
            if reason:
                res.drop(reason)
                continue
            seen.add(q.t)
            valid.append(q)
        valid.sort(key=lambda q: q.t)
        if not valid:
            self._maybe_purge(now)
            return res

        # Cửa sổ đọc gồm mọi giây của lô → biết luôn giây nào đã có (khử trùng).
        lo = min(valid[0].t - BASELINE_WINDOW, now - CLOSED_WINDOW)
        hi = max(valid[-1].t, now) + FUTURE_TOLERANCE + timedelta(seconds=1)
        history = self.store.window(feed, lo, hi)
        known = {r.t: r for r in history}
        rows: list[QuoteSecond] = []
        context = sorted(history, key=lambda r: r.t)
        for q in valid:
            sp = spread_points(q.bid, q.ask, point)
            flags: list[str] = []
            base = [r.spread_points for r in context
                    if q.t - BASELINE_WINDOW <= r.t < q.t and CALENDAR_CLOSED not in r.flags]
            if len(base) >= BASELINE_MIN and median(base) > 0:
                if q.spread_max_points > WIDE_SPREAD_MULTIPLE * median(base):
                    flags.append(WIDE_SPREAD)
            else:
                flags.append(SPREAD_UNRATED)
            if not self.calendar.is_open(q.t):
                flags.append(CALENDAR_CLOSED)
            row = QuoteSecond(feed, q.t, q.bid, q.ask, q.bid_low, q.ask_high, sp,
                              q.spread_max_points, q.ticks, tuple(flags), now, now)
            old = known.get(q.t)
            if old is not None:
                res.duplicates += 1
                if not old.same_values(row):
                    res.conflicts += 1
                continue
            known[q.t] = row
            rows.append(row)
            context.append(row)
            res.wide_spread += WIDE_SPREAD in flags
            res.calendar_closed += CALENDAR_CLOSED in flags
        res.accepted = self.store.append(rows)
        # "Nhiều lần" = trong 10 phút gần nhất tính tới lúc nhận (cả giây đã lưu trước đó).
        closed = [r for r in known.values()
                  if now - CLOSED_WINDOW < r.t and CALENDAR_CLOSED in r.flags]
        res.calendar_mismatch = len(closed) >= CLOSED_MISMATCH_MIN
        self._maybe_purge(now)
        return res

    def _maybe_purge(self, now: datetime) -> None:
        """Xóa dữ liệu quá hạn giữ, tối đa mỗi ``purge_every`` một lần."""
        if self._next_purge is not None and now < self._next_purge:
            return
        self._next_purge = now + self.purge_every
        self.store.purge_before(now - self.retention)

