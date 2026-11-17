"""Census — lịch doanh số bán lẻ **chép tay** (GĐ1, DEC-01 / ING-09; người dùng chốt 2026-11-17).

Thiết kế: ``docs/thiet-ke/14-census.md`` mục "Lịch chép tay". Tóm tắt:

- Census chặn mọi truy cập từ Việt Nam (403, 2026-11-13) → nguồn tự động ``census_schedule``
  (``census.py``) không chạy được trên máy người dùng. Người dùng chọn **lịch chép tay có phiên
  bản** (không FRED, không bỏ): chỉ cần **giờ** công bố để chặn vào lệnh quanh tin; **không có số
  actual** (sự kiện không có ``actual_status``).
- Bảng chép từ hai trang chính thức của Census (đọc 2026-11-17 bằng bộ đọc đã có test của
  ``census.py``): lịch chỉ số kinh tế (``/economic-indicators/calendar-listview*.html``) và lịch
  riêng khảo sát bán lẻ (``/retail/release_schedule.html``). Chỉ chép các kỳ **cả hai trang khớp
  ngày** (2026-09 … 2027-11); mọi dòng 08:30 giờ New York.
- Cùng khóa sự kiện ``RETAIL:YYYY-MM`` + ``event = CENSUS_RETAIL`` như ``census.py``.
- Bảng sắp hết (lần công bố cuối < 45 ngày nữa) → lần kiểm ``INVALID`` (``SCHEDULE_TABLE_EXPIRING``)
  → nguồn lịch không khỏe → lịch hợp nhất không tin giờ (chặn cả ngày) + Risk từ chối
  (``CALENDAR_SOURCE_UNHEALTHY``) — hướng an toàn, buộc chép bảng mới. Không gọi mạng.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PROVIDER = "census"
SCHEDULE_SOURCE = "census_retail_schedule"
SCHEDULE_PAYLOAD_VERSION = "census-retail-schedule-1"
SCHEDULE_VERSION = "census-retail-2026.11.17"
SCHEDULE_SOURCE_NOTE = (
    "Chép từ www.census.gov/economic-indicators/calendar-listview{,-2026}.html và "
    "www.census.gov/retail/release_schedule.html (đọc 2026-11-17; hai trang khớp từng ngày)")
RELEASE_TIME = time(8, 30)             # mọi dòng của cả hai trang: 8:30 AM giờ New York
EXPIRY_WARNING = timedelta(days=45)    # bảng còn ít hơn chừng này → báo để chép bảng mới
# Công bố sau tháng số liệu ~2 tuần; chính phủ đóng cửa 2025 từng dời tới ~1 tháng → trần 75 ngày
# (ngoài khoảng này = gõ nhầm năm / tháng).
MAX_DELAY = timedelta(days=75)
EVENT = "CENSUS_RETAIL"
TITLE = "Advance Monthly Sales for Retail and Food Services"

# (tháng số liệu, ngày công bố) — nguyên văn, 08:30 AM giờ New York.
_TABLE: tuple[tuple[str, str], ...] = (
    ("2026-09", "2026-10-15"), ("2026-10", "2026-11-17"), ("2026-11", "2026-12-16"),
    ("2026-12", "2027-01-15"), ("2027-01", "2027-02-17"), ("2027-02", "2027-03-16"),
    ("2027-03", "2027-04-16"), ("2027-04", "2027-05-14"), ("2027-05", "2027-06-16"),
    ("2027-06", "2027-07-16"), ("2027-07", "2027-08-16"), ("2027-08", "2027-09-16"),
    ("2027-09", "2027-10-15"), ("2027-10", "2027-11-16"), ("2027-11", "2027-12-15"),
)


class ScheduleError(ValueError):
    pass


class ScheduleExpiring(ValueError):
    pass


@dataclass(frozen=True)
class CalendarEvent:
    logical_key: str
    event_time: datetime
    payload: dict


def release_at(d: date) -> datetime:
    """08:30 giờ New York của ngày ``d`` → UTC (13:30 mùa đông, 12:30 mùa hè)."""
    return datetime.combine(d, RELEASE_TIME, tzinfo=ET).astimezone(UTC)


def schedule_table() -> list[tuple[str, date]]:
    """``(tháng số liệu, ngày công bố)`` đã kiểm: tháng liên tiếp, ngày tăng dần, ngày công bố
    sau khi hết tháng số liệu và không quá ``MAX_DELAY``, ngày làm việc (thứ Hai–Sáu)."""
    out: list[tuple[str, date]] = []
    prev_p = prev_d = None
    for period, day in _TABLE:
        y, m = map(int, period.split("-"))
        d = date.fromisoformat(day)
        if prev_p is not None:
            py, pm = prev_p
            if (y, m) != (py + (pm == 12), pm % 12 + 1):
                raise ScheduleError(f"tháng số liệu không liên tiếp ở {period}")
            if d <= prev_d:
                raise ScheduleError(f"ngày công bố không tăng ở {day}")
        end = date(y + (m == 12), m % 12 + 1, 1)                 # ngày đầu tháng kế tiếp
        if not end <= d < end + MAX_DELAY or d.weekday() > 4:
            raise ScheduleError(f"ngày công bố lạ {day}")
        prev_p, prev_d = (y, m), d
        out.append((period, d))
    return out


def build_schedule(now: datetime, keep_after: timedelta = timedelta(days=7)
                   ) -> list[CalendarEvent]:
    """Sự kiện từ ``now - keep_after`` trở đi. Bảng sắp hết → ``ScheduleExpiring``."""
    cutoff = now - keep_after
    events: list[CalendarEvent] = []
    last: datetime | None = None
    for period, d in schedule_table():
        at = release_at(d)
        last = at if last is None else max(last, at)
        if at < cutoff:
            continue
        events.append(CalendarEvent(f"RETAIL:{period}", at, {
            "event": EVENT, "title": f"{TITLE} — {period}", "period": period,
            "includes": ["RETAIL_SALES"], "time_confirmed": True, "all_day": False,
            "release_local": "08:30", "release_date_local": d.isoformat(),
            "tz": "America/New_York", "status": "SCHEDULED", "basis": "OFFICIAL_TABLE_COPIED",
            "schedule_version": SCHEDULE_VERSION, "flags": []}))
    if last is None or last - now < EXPIRY_WARNING:
        raise ScheduleExpiring(SCHEDULE_VERSION)
    return events


SCHEDULE_FETCH_TTL = timedelta(hours=26)


def schedule_spec():
    from gold_trading.ingestion.source_status import SourceSpec
    return SourceSpec(SCHEDULE_SOURCE, "calendar", fetch_ttl=SCHEDULE_FETCH_TTL,
                      provider=PROVIDER)


def _enabled(registry, name: str) -> None:
    from gold_trading.ingestion.source_status import SourceRegistry
    registry = registry if registry is not None else SourceRegistry([schedule_spec()])
    spec = registry.get(name)
    if spec is None or not spec.enabled:
        raise ValueError(f"nguồn {name} chưa được bật")


def run_schedule_once(*, store, log, now: datetime, registry=None):
    """Ghi lịch từ bảng chép tay theo revision. Không gọi mạng."""
    from gold_trading.ingestion.calendar_sync import EventIn, sync_calendar
    from gold_trading.ingestion.source_status import CheckOutcome, SourceCheck

    _enabled(registry, SCHEDULE_SOURCE)
    try:
        events = build_schedule(now)
    except ScheduleExpiring:
        check = SourceCheck(SCHEDULE_SOURCE, now, CheckOutcome.INVALID, "SCHEDULE_TABLE_EXPIRING")
    except ScheduleError:
        check = SourceCheck(SCHEDULE_SOURCE, now, CheckOutcome.INVALID, "PARSE_ERROR")
    else:
        res = sync_calendar(store, source=SCHEDULE_SOURCE,
                            payload_version=SCHEDULE_PAYLOAD_VERSION,
                            raw_ref=f"table:{SCHEDULE_VERSION}",
                            events=[EventIn(e.logical_key, e.event_time, e.payload)
                                    for e in events], now=now)
        check = (SourceCheck(SCHEDULE_SOURCE, now, CheckOutcome.INVALID, res.error_code)
                 if res.error_code else SourceCheck.from_counts(SCHEDULE_SOURCE, now, res.counts))
    log.record(check)
    return check
