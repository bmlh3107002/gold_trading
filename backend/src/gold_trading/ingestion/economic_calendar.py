"""Bảng lịch kinh tế hợp nhất tại một thời điểm (GĐ1 8g-2: ING-20, 1C-C07).

Gom sự kiện của mọi nguồn lịch (FOMC, BEA, DOL; sau này BLS…) **đã biết tại ``as_of``**
(point-in-time) thành một danh sách thống nhất, kèm:

- mức quan trọng + lý do + phiên bản chính sách (``event_importance``, ING-20);
- cửa sổ rủi ro cơ bản [``window_start``, ``window_end``): giờ đã xác nhận → quanh giờ công bố
  theo mức quan trọng; chưa chắc giờ / hai nguồn lệch → **cả ngày** giờ New York;
- forecast: **không có** (DEC-01) → ``forecast = None``, ``surprise_status =
  "INSUFFICIENT_DATA"`` — không bao giờ tính "bất ngờ" từ số khác (1C-C07); cửa sổ vẫn có.

Chỉ đọc; không ghi gì. Gộp các cửa sổ chồng nhau (2-C08) là việc của GĐ2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from gold_trading.ingestion.event_importance import POLICY_VERSION, WINDOWS, rate

ET = ZoneInfo("America/New_York")
CALENDAR_SOURCES = ("fed_fomc", "bea_schedule", "dol_claims_schedule")
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
# Cờ khiến không tin giờ đã ghi → chặn cả ngày.
DISTRUST_TIME_FLAGS = frozenset({"CALENDAR_SOURCES_DISAGREE", "UNUSUAL_RELEASE_TIME"})


def _require_utc(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("thời điểm phải có múi giờ (UTC)")
    return v.astimezone(UTC)


@dataclass(frozen=True)
class CalendarItem:
    source: str
    logical_key: str
    revision: int
    event: str
    variant: str | None
    title: str | None
    release_at: datetime                 # giờ công bố (UTC); chưa chắc giờ = 0:00 ET ngày đó
    release_date_local: date
    time_confirmed: bool
    all_day: bool                        # cửa sổ cả ngày (chưa chắc giờ hoặc không tin giờ)
    status: str                          # SCHEDULED / REMOVED
    tentative: bool
    flags: tuple[str, ...]
    importance: str
    importance_reason: str
    importance_known: bool
    policy_version: str
    window_start: datetime | None        # None khi REMOVED
    window_end: datetime | None
    forecast: None = None
    forecast_status: str = INSUFFICIENT_DATA
    surprise_status: str = INSUFFICIENT_DATA
    notes: tuple[str, ...] = field(default=())

    def window_contains(self, t: datetime) -> bool:
        return (self.window_start is not None and self.window_start <= t < self.window_end)


def _local_day(p: dict, event_time: datetime) -> date:
    raw = p.get("release_date_local") or p.get("meeting_end")
    if raw and p.get("all_day"):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return event_time.astimezone(ET).date()


def _day_window(d: date) -> tuple[datetime, datetime]:
    """[0:00, 24:00) giờ New York của ngày ``d`` (đúng cả ngày đổi giờ DST: 23 / 25 giờ)."""
    start = datetime.combine(d, time(0, 0), tzinfo=ET).astimezone(UTC)
    end = datetime.combine(d + timedelta(days=1), time(0, 0), tzinfo=ET).astimezone(UTC)
    return start, end


def to_item(r) -> CalendarItem:
    p = r.payload
    event = p.get("event") or "UNKNOWN"
    variant = p.get("estimate")
    rating = rate(event, variant)
    flags = tuple(sorted(p.get("flags") or ()))
    confirmed = bool(p.get("time_confirmed"))
    distrust = bool(DISTRUST_TIME_FLAGS & set(flags))
    # Giờ theo quy tắc (DOL thứ Năm 8:30 ET, người dùng chọn ở 8f) → cửa sổ quanh giờ đó, ghi chú.
    by_rule = p.get("basis") == "RULE" and not p.get("all_day")
    all_day = bool(p.get("all_day")) or (not confirmed and not by_rule) or distrust
    day = _local_day(p, r.event_time)
    status = p.get("status") or "SCHEDULED"
    notes: list[str] = []
    if status == "REMOVED":
        w_start = w_end = None
    elif all_day:
        w_start, w_end = _day_window(day)
        if confirmed and distrust:
            notes.append("TIME_DISTRUSTED_WHOLE_DAY")
    else:
        w = WINDOWS[rating.importance]
        w_start, w_end = r.event_time - w.before, r.event_time + w.after
    if by_rule and not all_day:
        notes.append("TIME_BY_RULE")
    if not rating.known:
        notes.append("IMPORTANCE_UNKNOWN_EVENT")
    return CalendarItem(
        source=r.source, logical_key=r.logical_key, revision=r.revision, event=event,
        variant=variant, title=p.get("title"), release_at=r.event_time,
        release_date_local=day, time_confirmed=confirmed and not distrust, all_day=all_day,
        status=status, tentative=bool(p.get("tentative")), flags=flags,
        importance=rating.importance.value, importance_reason=rating.reason,
        importance_known=rating.known, policy_version=POLICY_VERSION,
        window_start=w_start, window_end=w_end, notes=tuple(notes))


def economic_calendar(store, as_of: datetime, *, start: datetime | None = None,
                      end: datetime | None = None, sources=CALENDAR_SOURCES,
                      include_removed: bool = False) -> list[CalendarItem]:
    """Sự kiện đã biết tại ``as_of`` có cửa sổ (hoặc giờ công bố) giao [start, end).
    Mặc định: từ ``as_of - 1 ngày`` tới ``as_of + 60 ngày``."""
    as_of = _require_utc(as_of)
    start = _require_utc(start) if start else as_of - timedelta(days=1)
    end = _require_utc(end) if end else as_of + timedelta(days=60)
    items: list[CalendarItem] = []
    for src in sources:
        # Lọc khoảng rộng hơn 2 ngày để không bỏ sót cửa sổ cả ngày lệch múi giờ.
        for r in store.as_of(as_of, source=src, kind="calendar",
                             event_from=start - timedelta(days=2),
                             event_to=end + timedelta(days=2)):
            it = to_item(r)
            if it.status == "REMOVED":
                if include_removed and start <= it.release_at < end:
                    items.append(it)
                continue
            if it.window_start < end and it.window_end > start:
                items.append(it)
    return sorted(items, key=lambda i: (i.window_start or i.release_at, i.source,
                                        i.logical_key))


def active_windows(store, as_of: datetime, **kw) -> list[CalendarItem]:
    """Sự kiện có cửa sổ rủi ro chứa ``as_of`` (dùng cho Safety / làn nhanh ở GĐ2)."""
    as_of = _require_utc(as_of)
    return [i for i in economic_calendar(store, as_of, start=as_of,
                                         end=as_of + timedelta(seconds=1), **kw)
            if i.window_contains(as_of)]
