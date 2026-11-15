"""ING-35 (KN-03, người dùng duyệt 2026-11-15): thống kê spread theo PHÚT, giữ vĩnh viễn.

Giá theo giây (``quote_seconds``, ING-08) chỉ giữ ``GT_QUOTE_RETENTION_DAYS`` (30 ngày). Backtest
GĐ6 cần phân bố spread **thật** theo giờ và quanh tin → mỗi phút của mỗi nguồn giá được tổng hợp
thành một dòng nhỏ, chỉ-thêm, giữ vĩnh viễn (thiết kế ``docs/thiet-ke/23-giu-du-lieu.md`` mục 6).

Quy tắc (không bịa, không nội suy):

- Chỉ tổng hợp phút đã **lắng** (``SETTLE`` sau khi phút kết thúc) từ đúng các giây đã lưu.
  Phút không có giây nào → không có dòng (không phải spread 0).
- Thống kê: spread cuối giây (nhỏ nhất, trung vị), spread lớn nhất trong giây (p95 theo hạng
  gần nhất, lớn nhất), bid đầu / cuối, bid thấp nhất, ask cao nhất, số giây, số tick, số giây có
  cờ ``WIDE_SPREAD`` / ``CALENDAR_CLOSED`` (để phía dùng lọc giờ đóng cửa). Đơn vị spread: point.
- Giây tới muộn sau khi đã tổng hợp → **revision mới** (không sửa dòng cũ), ``available_at`` = lúc
  ghi → đọc point-in-time được. Bản tính lại có **ít giây hơn** bản đã lưu (giây cũ đã bị xóa theo
  hạn giữ) → không ghi (không bao giờ thay số đầy đủ bằng số thiếu).
- Xóa giá theo giây chỉ tới mốc bộ tổng hợp đã chạy xong (``watermark``) → không mất phút chưa gộp.
"""

from __future__ import annotations

import logging
import math
import threading
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Protocol

from gold_trading.market.quotes import CALENDAR_CLOSED, WIDE_SPREAD, QuoteSecond

log = logging.getLogger("gold_trading.quotes")

VERSION = "quote-minutes-1"
MINUTE = timedelta(minutes=1)
SETTLE = timedelta(minutes=10)      # phút kết thúc ≥ 10 phút mới tổng hợp
REVISIT = timedelta(hours=2)        # mỗi lần chạy xét lại 2 giờ gần nhất (giây tới muộn)
EVERY = timedelta(minutes=5)
CHUNK = timedelta(hours=6)          # đọc giây theo từng đoạn (nạp bù 30 ngày không đầy bộ nhớ)
PURGE_MARGIN = timedelta(hours=2)   # lần đầu: bỏ 2 giờ cũ nhất (có thể đang bị xóa dở)


@dataclass(frozen=True)
class QuoteMinute:
    feed_id: str
    t: datetime                 # đầu phút, UTC
    seconds: int
    ticks: int
    bid_open: float
    bid_close: float
    ask_close: float
    bid_low: float
    ask_high: float
    spread_min: int
    spread_median: float
    spread_p95: int             # p95 (hạng gần nhất) của spread lớn nhất trong từng giây
    spread_max: int
    seconds_wide: int
    seconds_closed: int
    version: str = VERSION
    revision: int = 0
    computed_at: datetime | None = None
    available_at: datetime | None = None

    def values(self) -> tuple:
        return (self.seconds, self.ticks, self.bid_open, self.bid_close, self.ask_close,
                self.bid_low, self.ask_high, self.spread_min, self.spread_median,
                self.spread_p95, self.spread_max, self.seconds_wide, self.seconds_closed)


class QuoteMinuteStore(Protocol):
    def latest_revisions(self, feed: str, lo: datetime, hi: datetime
                         ) -> dict[datetime, QuoteMinute]: ...
    def append(self, rows: list[QuoteMinute]) -> int: ...
    def query(self, feed: str, lo: datetime, hi: datetime, *, as_of: datetime
              ) -> list[QuoteMinute]: ...


def floor_minute(t: datetime) -> datetime:
    if t.tzinfo is None:
        raise ValueError("thời điểm phải có múi giờ (UTC)")
    t = t.astimezone(UTC)
    return t.replace(second=0, microsecond=0)


def p_nearest_rank(values: list[int], p: float) -> int:
    """Phân vị theo hạng gần nhất (giá trị có thật trong mẫu, không nội suy)."""
    if not values or not 0 < p <= 1:
        raise ValueError("cần mẫu không rỗng và 0 < p ≤ 1")
    s = sorted(values)
    return s[max(math.ceil(p * len(s)) - 1, 0)]


def aggregate(feed: str, t: datetime, secs: list[QuoteSecond]) -> QuoteMinute:
    """Một phút từ các giây của đúng phút đó (đã lọc). Rỗng → lỗi lập trình."""
    if not secs:
        raise ValueError("phút không có giây nào — không tạo dòng")
    secs = sorted(secs, key=lambda r: r.t)
    if any(r.feed_id != feed or floor_minute(r.t) != t for r in secs):
        raise ValueError("giây không thuộc phút / nguồn này")
    ends = [r.spread_points for r in secs]
    # Spread lớn nhất trong giây không nhỏ hơn spread cuối giây (Gateway làm tròn lệch ≤ 1 point
    # được chấp nhận ở ING-08) → lấy số lớn hơn của hai, không bao giờ báo thấp hơn thực tế.
    maxes = [max(r.spread_max_points, r.spread_points) for r in secs]
    return QuoteMinute(
        feed_id=feed, t=t, seconds=len(secs), ticks=sum(r.ticks for r in secs),
        bid_open=secs[0].bid, bid_close=secs[-1].bid, ask_close=secs[-1].ask,
        bid_low=min(r.bid_low for r in secs), ask_high=max(r.ask_high for r in secs),
        spread_min=min(ends), spread_median=float(median(ends)),
        spread_p95=p_nearest_rank(maxes, 0.95), spread_max=max(maxes),
        seconds_wide=sum(WIDE_SPREAD in r.flags for r in secs),
        seconds_closed=sum(CALENDAR_CLOSED in r.flags for r in secs),
    )


def plan(feed: str, secs: Iterable[QuoteSecond], existing: dict[datetime, QuoteMinute],
         now: datetime, lo: datetime, hi: datetime) -> list[QuoteMinute]:
    """Dòng mới cần ghi cho các phút ``lo ≤ t < hi``: phút chưa có, hoặc có thêm giây (revision)."""
    by_min: dict[datetime, list[QuoteSecond]] = defaultdict(list)
    for r in secs:
        m = floor_minute(r.t)
        if lo <= m < hi:
            by_min[m].append(r)
    out = []
    for m in sorted(by_min):
        agg = aggregate(feed, m, by_min[m])
        old = existing.get(m)
        if old is not None:
            if agg.seconds <= old.seconds or agg.values() == old.values():
                continue        # không đổi, hoặc ít giây hơn (giây cũ đã bị xóa) → không ghi
            agg = replace(agg, revision=old.revision + 1)
        out.append(replace(agg, computed_at=now, available_at=now))
    return out


class QuoteMinuteRunner:
    """Chạy nền mỗi ``EVERY``: lần đầu nạp bù toàn bộ giây còn giữ, sau đó xét lại ``REVISIT``."""

    def __init__(self, quote_store, minute_store: QuoteMinuteStore, *,
                 retention: timedelta, now=None, every: timedelta = EVERY) -> None:
        from gold_trading.common.time import utcnow
        self.quotes = quote_store
        self.minutes = minute_store
        self.retention = retention
        self._now = now or utcnow
        self.every = every
        self.watermark: datetime | None = None   # mọi phút < watermark đã tổng hợp
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self, now: datetime | None = None) -> int:
        now = now or self._now()
        hi = floor_minute(now - SETTLE)
        if self.watermark is None:
            lo = floor_minute(now - self.retention + PURGE_MARGIN)
        else:
            lo = min(self.watermark, hi) - REVISIT
        written = 0
        for feed in self.quotes.feeds_between(lo, hi):
            a = lo
            while a < hi:
                b = min(a + CHUNK, hi)
                secs = self.quotes.window(feed, a, b)
                if secs:
                    rows = plan(feed, secs, self.minutes.latest_revisions(feed, a, b), now, a, b)
                    written += self.minutes.append(rows)
                a = b
        self.watermark = hi
        return written

    def purge_guard(self) -> datetime | None:
        """Mốc xóa giá theo giây an toàn (None = chưa chạy xong lần nào → chưa xóa)."""
        return self.watermark

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                n = self.run_once()
                if n:
                    log.info("Spread theo phút: ghi %d dòng (tới %s)", n, self.watermark)
            except Exception:
                log.exception("Tổng hợp spread theo phút lỗi, thử lại lần sau")
            if self._stop.wait(self.every.total_seconds()):
                return

    def start(self) -> None:
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="quote-minutes",
                                            daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None
