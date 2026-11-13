"""Lịch FOMC của Fed (ING-09, bước 8b). Điều khoản: ``VERIFIED`` (public domain, ghi nguồn Board).

Hai loại trang chính thức (thiết kế: ``docs/thiet-ke/12-lich-fomc.md``):

1. ``/monetarypolicy/fomccalendars.htm`` — **ngày họp** mọi năm (cả năm sau). Không có giờ.
2. Lịch tháng ``/newsevents/<tháng>.htm`` (đường dẫn lấy từ ``/newsevents/calendar.htm``) — **giờ
   công bố** (giờ miền Đông Mỹ): tuyên bố sau họp ("FOMC Meeting"), họp báo, biên bản.

Quy tắc an toàn:
- Gặp định dạng lạ → ``FomcParseError`` (cả lần tải bị coi INVALID, không ghi gì) — không đoán.
- Tuyên bố của cuộc họp chưa có giờ trên lịch tháng (lịch tháng chỉ có tới vài tháng tới) →
  ``time_confirmed = False``, ``event_time`` = 00:00 giờ miền Đông của ngày cuối họp, ``all_day``.
  Không tự gán "2 giờ chiều như mọi khi".
- Lịch tháng và trang lịch họp lệch nhau → ``time_confirmed = False`` + cờ
  ``CALENDAR_SOURCES_DISAGREE``.
- Fed ghi "mỗi ngày họp là dự kiến cho tới khi được xác nhận ở cuộc họp ngay trước" →
  ``tentative = True`` nếu cuộc họp trước đó chưa diễn ra tại lúc tải.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SOURCE = "fed_fomc"
PROVIDER = "fed"
BASE_URL = "https://www.federalreserve.gov"
MEETINGS_PATH = "/monetarypolicy/fomccalendars.htm"
CALENDAR_INDEX_PATH = "/newsevents/calendar.htm"
PAYLOAD_VERSION = "fomc-1"

MONTHS = {m: i for i, m in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August", "September",
     "October", "November", "December"), start=1)}
MONTH_ABBR = {m[:3]: i for m, i in MONTHS.items()}


class FomcParseError(ValueError):
    """Trang không đúng định dạng đã biết — không đoán, cả lần tải bị coi INVALID."""


def _text(fragment: str) -> str:
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", fragment)
    t = html_lib.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t).strip()


# --- 1. Trang lịch họp ---

@dataclass(frozen=True)
class Meeting:
    start: date
    end: date
    sep: bool                 # dấu * — có Tóm tắt dự báo kinh tế (SEP)
    note: str | None          # vd. "notation vote", "Monetary Policy Strategy Meeting"


_YEAR_RE = re.compile(r">\s*(\d{4}) FOMC Meetings\s*<")
_ROW_RE = re.compile(
    r'fomc-meeting__month[^"]*"[^>]*>\s*<strong>(?P<month>.*?)</strong>\s*</div>\s*'
    r'<div class="fomc-meeting__date[^"]*"[^>]*>(?P<date>.*?)</div>(?P<rest>.*?)'
    r'(?=fomc-meeting__month|<div class="panel-footer|\Z)', re.S)
_DATE_RE = re.compile(r"^(\d{1,2})(?:-(\d{1,2}))?(\*)?(?:\s*\(([^)]{1,60})\))?$")
_MONTH_LABEL_RE = re.compile(r"^([A-Z][a-z]+)(?:/([A-Z][a-z]+))?$")


def _month_no(label: str) -> int:
    if label in MONTHS:
        return MONTHS[label]
    if label in MONTH_ABBR:
        return MONTH_ABBR[label]
    raise FomcParseError(f"tháng lạ: {label!r}")


def parse_meetings(page: str) -> list[Meeting]:
    """Mọi cuộc họp trên trang lịch họp, theo thứ tự thời gian."""
    years = [(int(m.group(1)), m.start()) for m in _YEAR_RE.finditer(page)]
    if not years:
        raise FomcParseError("không thấy bảng 'YYYY FOMC Meetings'")
    years.sort(key=lambda x: x[1])
    out: list[Meeting] = []
    for k, (year, pos) in enumerate(years):
        end_pos = years[k + 1][1] if k + 1 < len(years) else len(page)
        seg = page[pos:end_pos]
        rows = list(_ROW_RE.finditer(seg))
        if not rows:
            raise FomcParseError(f"năm {year}: không đọc được dòng họp nào")
        for r in rows:
            label = _text(r.group("month"))
            date_txt = _text(r.group("date"))
            ml = _MONTH_LABEL_RE.match(label)
            dm = _DATE_RE.match(date_txt)
            if not ml or not dm:
                raise FomcParseError(f"năm {year}: dòng lạ {label!r} {date_txt!r}")
            m1 = _month_no(ml.group(1))
            m2 = _month_no(ml.group(2)) if ml.group(2) else m1
            d1 = int(dm.group(1))
            d2 = int(dm.group(2)) if dm.group(2) else d1
            try:
                start = date(year, m1, d1)
                end_year = year + 1 if m2 < m1 else year
                end = date(end_year, m2, d2)
            except ValueError as e:
                raise FomcParseError(f"năm {year}: ngày không hợp lệ {label} {date_txt}") from e
            if not (timedelta(0) <= end - start <= timedelta(days=3)):
                raise FomcParseError(f"năm {year}: khoảng họp lạ {label} {date_txt}")
            note = dm.group(4)
            rest = _text(r.group("rest"))
            if "Monetary Policy Strategy Meeting" in rest:
                note = "Monetary Policy Strategy Meeting"
            out.append(Meeting(start, end, bool(dm.group(3)), note))
    out.sort(key=lambda m: m.start)
    if len({m.end for m in out}) != len(out):
        raise FomcParseError("hai cuộc họp trùng ngày kết thúc")
    return out


# --- 2. Lịch tháng ---

@dataclass(frozen=True)
class ScheduledRelease:
    kind: str                 # FOMC_STATEMENT | FOMC_PRESS_CONFERENCE | FOMC_MINUTES
    at: datetime              # có múi giờ ET
    meeting_end: date | None  # cuộc họp liên quan (biên bản: "Meeting of ..."; tuyên bố: ngày cuối)
    raw: str


_MONTH_TITLE_RE = re.compile(r'<h4 class="text-center">\s*([A-Z][a-z]+) (\d{4})\s*</h4>')
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2}) ([ap])\.m\.$")
_CAL_ROW_RE = re.compile(
    r'<div class="col-xs-2">\s*<p>(?P<time>.*?)</p>\s*</div>\s*'
    r'<div class="col-xs-7">(?P<body>.*?)</div>\s*'
    r'<div class="col-xs-3">\s*<p>(?P<days>.*?)</p>', re.S)
_MEETING_OF_RE = re.compile(r"Meeting of ([A-Z][a-z]+) (\d{1,2})(?:-(?:([A-Z][a-z]+) )?(\d{1,2}))?")
_TWO_DAY_RE = re.compile(
    r"(?:Two|One)-day meeting, ([A-Z][a-z]+) (\d{1,2})(?: - (?:([A-Z][a-z]+) )?(\d{1,2}))?")


def _parse_time(s: str) -> time:
    m = _TIME_RE.match(s)
    if not m:
        raise FomcParseError(f"giờ lạ: {s!r}")
    h, mi = int(m.group(1)), int(m.group(2))
    if not (1 <= h <= 12 and 0 <= mi <= 59):
        raise FomcParseError(f"giờ lạ: {s!r}")
    h = h % 12 + (12 if m.group(3) == "p" else 0)
    return time(h, mi)


def _resolve_day(year: int, month: int, label: str | None, day: str, ref: date) -> date:
    """Ngày trong "Meeting of March 17-18": năm lấy gần ``ref`` nhất (biên bản tháng 1 có thể
    nói về họp tháng 12 năm trước)."""
    mo = _month_no(label) if label else month
    cands = [date(y, mo, int(day)) for y in (year - 1, year, year + 1)
             if _valid(y, mo, int(day))]
    if not cands:
        raise FomcParseError(f"ngày lạ: {label} {day}")
    return min(cands, key=lambda d: abs((d - ref).days))


def _valid(y: int, m: int, d: int) -> bool:
    try:
        date(y, m, d)
        return True
    except ValueError:
        return False


def parse_month_calendar(page: str) -> tuple[date, list[ScheduledRelease]]:
    """(ngày đầu tháng, các mốc FOMC có giờ) của một trang lịch tháng."""
    t = _MONTH_TITLE_RE.search(page)
    if not t:
        raise FomcParseError("không thấy tiêu đề tháng")
    month, year = _month_no(t.group(1)), int(t.group(2))
    start = page.find(">FOMC Meetings")
    if start < 0:
        return date(year, month, 1), []  # tháng không có mốc FOMC
    nxt = page.find("cal-nojs__rowTitle", start)
    section = page[start: nxt if nxt > 0 else len(page)]
    out: list[ScheduledRelease] = []
    for r in _CAL_ROW_RE.finditer(section):
        tm = _parse_time(_text(r.group("time")))
        body = _text(r.group("body"))
        days_txt = _text(r.group("days"))
        days = re.findall(r"\d{1,2}", days_txt)
        if not days or re.sub(r"[\d,\s]", "", days_txt):
            raise FomcParseError(f"ngày công bố lạ: {days_txt!r}")
        if body.startswith("FOMC Minutes"):
            kind = "FOMC_MINUTES"
        elif body.startswith("FOMC Press Conference"):
            kind = "FOMC_PRESS_CONFERENCE"
        elif body.startswith("FOMC Meeting"):
            kind = "FOMC_STATEMENT"
        else:
            raise FomcParseError(f"mục FOMC lạ: {body[:60]!r}")
        for d in days:
            if not _valid(year, month, int(d)):
                raise FomcParseError(f"ngày công bố không hợp lệ: {year}-{month}-{d}")
            day = date(year, month, int(d))
            at = datetime.combine(day, tm, tzinfo=ET)
            meeting_end: date | None = None
            if kind == "FOMC_MINUTES":
                m = _MEETING_OF_RE.search(body)
                if not m:
                    raise FomcParseError(f"biên bản không ghi cuộc họp: {body[:60]!r}")
                meeting_end = _resolve_day(year, month, m.group(3) or m.group(1),
                                           m.group(4) or m.group(2), day)
            elif kind == "FOMC_STATEMENT":
                m = _TWO_DAY_RE.search(body)
                if not m:
                    raise FomcParseError(f"tuyên bố không ghi ngày họp: {body[:60]!r}")
                meeting_end = _resolve_day(year, month, m.group(3) or m.group(1),
                                           m.group(4) or m.group(2), day)
            out.append(ScheduledRelease(kind, at, meeting_end, body[:200]))
    if not out:
        raise FomcParseError(f"{year}-{month:02d}: có mục FOMC nhưng không đọc được dòng nào")
    return date(year, month, 1), out


def month_links(index_page: str) -> list[str]:
    """Đường dẫn lịch tháng trên trang ``/newsevents/calendar.htm`` (không tự dựng địa chỉ:
    Fed đặt tên không đều, vd. ``2026-04.htm`` và ``2026-august.htm``)."""
    return sorted(set(re.findall(r'href="(/newsevents/\d{4}-[a-z0-9]+\.htm)"', index_page)))


# --- 3. Ghép thành sự kiện lịch ---

@dataclass(frozen=True)
class CalendarEvent:
    logical_key: str
    event_time: datetime      # UTC
    payload: dict = field(hash=False)


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(ZoneInfo("UTC")).isoformat()


def build_events(meetings: list[Meeting], releases: list[ScheduledRelease],
                 months_covered: set[date], now: datetime,
                 keep_after: timedelta = timedelta(days=7)) -> list[CalendarEvent]:
    """Sự kiện lịch từ ``now - keep_after`` trở đi. ``months_covered``: các tháng đã đọc
    được lịch tháng (tháng không có trong đó → giờ tuyên bố chưa xác nhận)."""
    cutoff = (now - keep_after).astimezone(ET).date()
    stmt_by_end: dict[date, list[ScheduledRelease]] = {}
    for r in releases:
        if r.kind == "FOMC_STATEMENT":
            stmt_by_end.setdefault(r.meeting_end, []).append(r)
    known_ends = {m.end for m in meetings}
    events: list[CalendarEvent] = []
    for i, m in enumerate(meetings):
        if m.end < cutoff:
            continue
        prev = meetings[i - 1] if i > 0 else None
        tentative = prev is not None and datetime.combine(
            prev.end, time(23, 59), tzinfo=ET) > now
        flags: list[str] = []
        cands = stmt_by_end.get(m.end, [])
        month_key = date(m.end.year, m.end.month, 1)
        confirmed = None
        if len(cands) == 1 and cands[0].at.date() == m.end:
            confirmed = cands[0].at
        elif cands or month_key in months_covered and m.note is None:
            # Lịch tháng có đọc được mà không có / lệch giờ tuyên bố của cuộc họp này.
            flags.append("CALENDAR_SOURCES_DISAGREE")
        at = confirmed or datetime.combine(m.end, time(0, 0), tzinfo=ET)
        events.append(CalendarEvent(
            f"FOMC_STATEMENT:{m.end.isoformat()}", at.astimezone(ZoneInfo("UTC")), {
                "event": "FOMC_STATEMENT",
                "meeting_start": m.start.isoformat(),
                "meeting_end": m.end.isoformat(),
                "sep": m.sep,
                "note": m.note,
                "tentative": tentative,
                "time_confirmed": confirmed is not None,
                "all_day": confirmed is None,
                "release_local": confirmed.strftime("%H:%M") if confirmed else None,
                "tz": "America/New_York",
                "status": "SCHEDULED",
                "flags": sorted(flags),
            }))
    for r in releases:
        if r.kind == "FOMC_STATEMENT" or r.at.date() < cutoff:
            continue
        if r.meeting_end is not None and r.meeting_end not in known_ends \
                and r.kind == "FOMC_MINUTES":
            flags = ["CALENDAR_SOURCES_DISAGREE"]
        else:
            flags = []
        key_day = r.at.date().isoformat()
        events.append(CalendarEvent(f"{r.kind}:{key_day}", r.at.astimezone(ZoneInfo("UTC")), {
            "event": r.kind,
            "meeting_end": r.meeting_end.isoformat() if r.meeting_end else None,
            "tentative": False,
            "time_confirmed": True,
            "all_day": False,
            "release_local": r.at.strftime("%H:%M"),
            "tz": "America/New_York",
            "status": "SCHEDULED",
            "flags": flags,
        }))
    # Tuyên bố có giờ trên lịch tháng nhưng không có trên trang lịch họp → vẫn ghi (an toàn:
    # thêm sự kiện), kèm cờ lệch nguồn.
    for end, cands in stmt_by_end.items():
        if end not in known_ends and end >= cutoff:
            for r in cands:
                events.append(CalendarEvent(
                    f"FOMC_STATEMENT:{end.isoformat()}", r.at.astimezone(ZoneInfo("UTC")), {
                        "event": "FOMC_STATEMENT", "meeting_start": None,
                        "meeting_end": end.isoformat(), "sep": None, "note": None,
                        "tentative": False, "time_confirmed": True, "all_day": False,
                        "release_local": r.at.strftime("%H:%M"), "tz": "America/New_York",
                        "status": "SCHEDULED", "flags": ["CALENDAR_SOURCES_DISAGREE"]}))
    keys = [e.logical_key for e in events]
    if len(keys) != len(set(keys)):
        raise FomcParseError("hai sự kiện trùng khóa")
    return sorted(events, key=lambda e: (e.event_time, e.logical_key))


# --- 4. Tải + ghi (một lần chạy) ---

def link_month(path: str) -> date | None:
    """``/newsevents/2026-04.htm`` hoặc ``/newsevents/2026-august.htm`` → ngày đầu tháng."""
    m = re.match(r"^/newsevents/(\d{4})-([a-z0-9]+)\.htm$", path)
    if not m:
        return None
    y, t = int(m.group(1)), m.group(2)
    if t.isdigit():
        mo = int(t)
    else:
        mo = next((i for name, i in MONTHS.items() if name.lower() == t), 0)
    return date(y, mo, 1) if 1 <= mo <= 12 else None


class FetchError(Exception):
    """Lỗi tải trang; ``code`` là mã ngắn an toàn (ING-30/31)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def collect(get, now: datetime) -> tuple[list[Meeting], list[ScheduledRelease], set[date]]:
    """Tải trang lịch họp + lịch tháng từ tháng trước tới hết các tháng Fed đã đăng.

    ``get(path) -> str`` ném ``FetchError`` khi lỗi mạng/HTTP."""
    meetings = parse_meetings(get(MEETINGS_PATH))
    this_month = date(now.astimezone(ET).year, now.astimezone(ET).month, 1)
    first = date(this_month.year - (this_month.month == 1), (this_month.month - 2) % 12 + 1, 1)
    releases: list[ScheduledRelease] = []
    covered: set[date] = set()
    links = [(link_month(p), p) for p in month_links(get(CALENDAR_INDEX_PATH))]
    if not links:
        raise FomcParseError("trang lịch không có đường dẫn lịch tháng")
    for mo, path in sorted(x for x in links if x[0] is not None):
        if mo < first:
            continue
        got_month, rel = parse_month_calendar(get(path))
        if got_month != mo:
            raise FomcParseError(f"{path}: tiêu đề tháng {got_month} không khớp đường dẫn")
        covered.add(mo)
        releases.extend(rel)
    return meetings, releases, covered


FETCH_TTL = timedelta(hours=26)  # tải mỗi ngày; quá 26 giờ không tải được → STALE
MAX_PAGE_BYTES = 5 * 1024 * 1024


def fomc_spec():
    from gold_trading.ingestion.source_status import SourceSpec
    return SourceSpec(SOURCE, "calendar", fetch_ttl=FETCH_TTL, provider=PROVIDER)


def http_getter(client, timeout: float = 20.0):
    """``get(path)`` dùng ``httpx.Client``: chỉ ``www.federalreserve.gov``, giới hạn cỡ trang,
    lỗi → ``FetchError`` với mã ngắn (không bao giờ kèm thông điệp gốc)."""
    import httpx

    from gold_trading.ingestion.api_keys import error_code_for_exception, error_code_for_http

    def get(path: str) -> str:
        if not path.startswith("/"):
            raise FetchError("BAD_PATH")
        try:
            r = client.get(BASE_URL + path, timeout=timeout, follow_redirects=True)
        except httpx.HTTPError as e:
            raise FetchError(error_code_for_exception(e)) from None
        if r.url.host != "www.federalreserve.gov":
            raise FetchError("UNEXPECTED_REDIRECT")
        if r.status_code != 200:
            raise FetchError(error_code_for_http(r.status_code))
        if len(r.content) > MAX_PAGE_BYTES:
            raise FetchError("RESPONSE_TOO_LARGE")
        return r.text

    return get


def run_once(*, store, log, get, now: datetime, registry=None):
    """Một lần tải lịch FOMC → ghi sự kiện (theo revision) + ghi nhật ký lần kiểm (ING-30).

    Nguồn phải được bật qua ``SourceRegistry`` (điều khoản Fed ``VERIFIED``, ING-32)."""
    from gold_trading.ingestion.calendar_sync import EventIn, sync_calendar
    from gold_trading.ingestion.source_status import CheckOutcome, SourceCheck, SourceRegistry

    registry = registry if registry is not None else SourceRegistry([fomc_spec()])
    spec = registry.get(SOURCE)
    if spec is None or not spec.enabled:
        raise ValueError("nguồn fed_fomc chưa được bật")
    try:
        meetings, releases, covered = collect(get, now)
        events = build_events(meetings, releases, covered, now)
        if not any(e.event_time > now and e.payload["event"] == "FOMC_STATEMENT"
                   for e in events):
            raise FomcParseError("không có cuộc họp nào trong tương lai")
    except FetchError as e:
        check = SourceCheck(SOURCE, now, CheckOutcome.ERROR, e.code)
    except FomcParseError:
        check = SourceCheck(SOURCE, now, CheckOutcome.INVALID, "PARSE_ERROR")
    else:
        res = sync_calendar(store, source=SOURCE, payload_version=PAYLOAD_VERSION,
                            raw_ref=f"{BASE_URL}{MEETINGS_PATH}@{now.isoformat()}",
                            events=[EventIn(e.logical_key, e.event_time, e.payload)
                                    for e in events], now=now)
        if res.error_code:
            check = SourceCheck(SOURCE, now, CheckOutcome.INVALID, res.error_code)
        else:
            check = SourceCheck.from_counts(SOURCE, now, res.counts)
    log.record(check)
    return check
