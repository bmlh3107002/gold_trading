"""Bảng lịch kinh tế hợp nhất tại một thời điểm (GĐ1 8g-2: ING-20, 1C-C07).

Gom sự kiện của mọi nguồn lịch (FOMC, BEA, DOL; sau này BLS…) **đã biết tại ``as_of``**
(point-in-time) thành một danh sách thống nhất, kèm:

- mức quan trọng + lý do + phiên bản chính sách (``event_importance``, ING-20);
- cửa sổ rủi ro cơ bản [``window_start``, ``window_end``): giờ đã xác nhận → quanh giờ công bố
  theo mức quan trọng; chưa chắc giờ / hai nguồn lệch → **cả ngày** giờ New York;
- forecast: **không có** (DEC-01) → ``forecast = None``, ``surprise_status =
  "INSUFFICIENT_DATA"`` — không bao giờ tính "bất ngờ" từ số khác (1C-C07); cửa sổ vẫn có.

8g-3 (1C-C05): mỗi sự kiện có số actual (GDP, PIO, trợ cấp thất nghiệp) mang
``actual_status``: ``NOT_DUE`` → ``AWAITING`` → ``RECEIVED``; tới giờ mà chưa có số và nguồn số
không khỏe (``UNKNOWN_SOURCE_DOWN``) hoặc trễ quá ``AWAIT_GRACE`` (``UNKNOWN_LATE``) → coi là
**chưa biết**: cửa sổ được **kéo dài** (luôn còn ít nhất ``RECHECK`` sau ``as_of``) tới khi có
số, tối đa hết ngày New York của lần công bố, kèm ghi chú cảnh báo. Nguồn lịch không khỏe →
sự kiện sắp tới không tin giờ → cả ngày.

Chỉ đọc; không ghi gì. Gộp các cửa sổ chồng nhau (2-C08) là việc của GĐ2.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from gold_trading.ingestion.event_importance import POLICY_VERSION, WINDOWS, rate

ET = ZoneInfo("America/New_York")
CALENDAR_SOURCES = ("fed_fomc", "bea_schedule", "dol_claims_schedule", "bls_schedule")
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
# Sự kiện có số actual → nguồn số. Sự kiện khác (FOMC): NOT_APPLICABLE.
ACTUAL_SOURCES = {"BEA_GDP": "bea_nipa", "BEA_PIO": "bea_nipa",
                  "DOL_JOBLESS_CLAIMS": "dol_claims",
                  "BLS_CPI": "bls_values", "BLS_EMPSIT": "bls_values", "BLS_PPI": "bls_values"}
# Chưa có số sau chừng này kể từ giờ công bố → coi là "chưa biết" dù nguồn còn khỏe.
AWAIT_GRACE = timedelta(minutes=15)
# Khi số chưa biết: cửa sổ luôn còn ít nhất chừng này sau as_of (người dùng đánh giá lại).
RECHECK = timedelta(minutes=5)
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
    match_ref: str | None = None             # BEA: khóa lần công bố; DOL: tuần kết thúc
    actual_status: str = "NOT_APPLICABLE"
    actual_received_at: datetime | None = None
    actuals: tuple[tuple[str, str | None], ...] = ()   # (series, giá trị chuỗi) đã nhận

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
        window_start=w_start, window_end=w_end, notes=tuple(notes),
        match_ref=p.get("week_ending") if event == "DOL_JOBLESS_CLAIMS" else r.logical_key)


def _matches(item: CalendarItem, v) -> bool:
    if item.event == "DOL_JOBLESS_CLAIMS":
        # Số của lần công bố = đơn lần đầu của tuần ghi trên lịch (các số khác là sửa tuần trước)
        return (v.payload.get("week_ending") == item.match_ref
                and v.payload.get("series") == "ICSA")
    return v.payload.get("release_ref") == item.match_ref


def _with_actual(it: CalendarItem, values: list, as_of: datetime,
                 values_healthy: bool | None) -> CalendarItem:
    """Gắn trạng thái số actual + kéo dài cửa sổ khi chưa biết số (1C-C05)."""
    if it.event not in ACTUAL_SOURCES or it.status == "REMOVED":
        return it
    got = [v for v in values if _matches(it, v)]
    notes = list(it.notes)
    due = it.window_start if it.all_day else it.release_at
    w_start, w_end = it.window_start, it.window_end
    day_end = _day_window(it.release_date_local)[1]
    if got:
        received = min(v.known_at for v in got)       # lúc hệ thống biết số
        published = min(v.available_at or v.known_at for v in got)  # lúc nguồn phát hành
        actuals = tuple(sorted((v.payload.get("series"), v.payload.get("value")) for v in got))
        if it.all_day and published < it.window_start:
            # Tuần lễ DOL: số đã phát hành ngày trước trong tuần → ngày này không có công bố.
            # Biết điều đó trước khi ngày bắt đầu → bỏ cửa sổ; biết giữa ngày → chặn tới lúc biết.
            notes.append("RELEASED_EARLIER_IN_WEEK")
            if received <= it.window_start:
                w_start = w_end = None
            else:
                w_end = min(received, w_end)
        elif received > w_end:
            notes.append("ACTUAL_LATE")
            # Đã chặn tới lúc biết số (chưa biết = chặn), nhưng không quá hết ngày New York.
            w_end = max(w_end, min(received, day_end))
        return replace(it, actual_status="RECEIVED", actual_received_at=received,
                       actuals=actuals, window_start=w_start, window_end=w_end,
                       notes=tuple(notes))
    if as_of < due:
        return replace(it, actual_status="NOT_DUE")
    if values_healthy is False:
        status = "UNKNOWN_SOURCE_DOWN"
    elif not it.all_day and as_of - it.release_at > AWAIT_GRACE:
        status = "UNKNOWN_LATE"
    else:
        status = "AWAITING"
    if status != "AWAITING":
        notes.append("ACTUAL_UNKNOWN")
    if not it.all_day:
        ext = min(as_of + RECHECK, day_end)
        if ext > w_end:
            w_end = ext
            notes.append("WINDOW_EXTENDED_ACTUAL_UNKNOWN")
        if as_of >= day_end:
            notes.append("ACTUAL_MISSING_END_OF_DAY")
    return replace(it, actual_status=status, window_end=w_end, notes=tuple(notes))


def _distrust_schedule(it: CalendarItem, as_of: datetime) -> CalendarItem:
    """Nguồn lịch không khỏe → sự kiện chưa tới không tin giờ → cả ngày (1C-C05)."""
    if it.status == "REMOVED" or it.release_at <= as_of:
        return it
    notes = tuple(it.notes) + ("SCHEDULE_SOURCE_UNHEALTHY",)
    if it.all_day:
        return replace(it, notes=notes)
    s, e = _day_window(it.release_at.astimezone(ET).date())
    return replace(it, all_day=True, time_confirmed=False, window_start=min(s, it.window_start),
                   window_end=max(e, it.window_end), notes=notes)


def health_details(check_log, store, as_of: datetime) -> dict:
    """Nguồn → ``SourceHealth`` (ING-30) cho các nguồn lịch + nguồn số đang chạy."""
    from gold_trading.ingestion.source_status import SourceRegistry, source_health
    from gold_trading.ingestion.sources import bea, bls, dol, fed_fomc

    reg = SourceRegistry([fed_fomc.fomc_spec(), bea.schedule_spec(), bea.values_spec(),
                          dol.schedule_spec(), dol.values_spec(), bls.schedule_spec(),
                          bls.values_spec()])
    return {h.source: h for h in source_health(reg, check_log, store, as_of)}


def health_map(check_log, store, as_of: datetime) -> dict[str, bool]:
    """Nguồn → HEALTHY hay không (ING-30), cho các nguồn lịch + nguồn số đang chạy."""
    from gold_trading.common.enums import SourceStatus

    return {src: h.status is SourceStatus.HEALTHY
            for src, h in health_details(check_log, store, as_of).items()}


def economic_calendar(store, as_of: datetime, *, start: datetime | None = None,
                      end: datetime | None = None, sources=CALENDAR_SOURCES,
                      include_removed: bool = False,
                      health: dict[str, bool] | None = None) -> list[CalendarItem]:
    """Sự kiện đã biết tại ``as_of`` có cửa sổ (hoặc giờ công bố) giao [start, end).
    Mặc định: từ ``as_of - 1 ngày`` tới ``as_of + 60 ngày``.

    ``health``: nguồn → khỏe hay không (``health_map``). Không truyền → chỉ xét số đến trễ
    (người gọi để chặn giao dịch — Safety ở GĐ2 — **phải** truyền)."""
    as_of = _require_utc(as_of)
    start = _require_utc(start) if start else as_of - timedelta(days=1)
    end = _require_utc(end) if end else as_of + timedelta(days=60)
    values: dict[str, list] = {}
    items: list[CalendarItem] = []
    for src in sources:
        # Lọc khoảng rộng hơn 2 ngày để không bỏ sót cửa sổ cả ngày lệch múi giờ.
        for r in store.as_of(as_of, source=src, kind="calendar",
                             event_from=start - timedelta(days=2),
                             event_to=end + timedelta(days=2)):
            it = to_item(r)
            if health is not None and health.get(src) is False:
                it = _distrust_schedule(it, as_of)
            vsrc = ACTUAL_SOURCES.get(it.event)
            if vsrc is not None:
                if vsrc not in values:
                    values[vsrc] = store.as_of(as_of, source=vsrc, kind="macro",
                                               event_from=start - timedelta(days=400))
                it = _with_actual(it, values[vsrc], as_of,
                                  None if health is None else health.get(vsrc))
            if it.status == "REMOVED":
                if include_removed and start <= it.release_at < end:
                    items.append(it)
                continue
            if it.window_start is None:
                continue  # đã ra số trước đó trong tuần
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
