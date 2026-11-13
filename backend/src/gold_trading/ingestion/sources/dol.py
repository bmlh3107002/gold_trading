"""DOL: lịch + số đơn xin trợ cấp thất nghiệp hằng tuần (bước 8f — ING-09, ING-17, ING-19).

Thiết kế + lý do: ``docs/thiet-ke/15-dol.md``. Hai nguồn, chung nhà cung cấp ``dol``:

1. ``dol_claims_schedule`` (lịch) — DOL **không** đăng lịch dạng đọc được; lịch **sinh theo quy
   tắc** DOL công bố (thứ Năm 8:30 sáng giờ miền Đông), ghi rõ ``basis = "RULE"``,
   ``time_confirmed = False``. Tuần có ngày lễ liên bang (``market.federal_holidays``) → **không
   đoán** ngày mới: chặn cả ngày thứ Tư, thứ Năm, thứ Sáu (người dùng chọn 2026-11-13).
2. ``dol_claims`` (số actual) — bản tin PDF chính thức ``www.dol.gov/ui/data.pdf`` (không cần khóa):
   giờ phát hành ("EMBARGOED UNTIL 8:30 A.M. (Eastern) Thursday, …") + câu tiêu đề. Kiểm số học:
   số tuần này = số tuần trước (đã sửa) ± mức thay đổi DOL ghi; lệch → INVALID cả lần tải.

Quy tắc an toàn: định dạng lạ → INVALID, không ghi gì; giờ phát hành lệch lịch theo quy tắc → cờ
``RELEASE_OFF_SCHEDULE`` (cảnh báo); bản tin cũ hơn số đã có không viết lại gì.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PROVIDER = "dol"
SCHEDULE_SOURCE = "dol_claims_schedule"
VALUES_SOURCE = "dol_claims"
PDF_URL = "https://www.dol.gov/ui/data.pdf"
ALLOWED_HOSTS = frozenset({"www.dol.gov"})
SCHEDULE_PAYLOAD_VERSION = "dol-schedule-1"
VALUES_PAYLOAD_VERSION = "dol-claims-1"
MAX_BYTES = 10 * 1024 * 1024
EVENT = "DOL_JOBLESS_CLAIMS"
RULE_TIME = time(8, 30)
HORIZON_WEEKS = 8

MONTHS = {m: i for i, m in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August", "September",
     "October", "November", "December"), start=1)}
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class DolParseError(ValueError):
    """Bản tin không đúng định dạng đã biết — không đoán, cả lần tải bị coi INVALID."""


class FetchError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------- 1. Lịch theo quy tắc

@dataclass(frozen=True)
class CalendarEvent:
    logical_key: str
    event_time: datetime
    payload: dict = field(hash=False)


def build_schedule(now: datetime, weeks: int = HORIZON_WEEKS,
                   keep_after: timedelta = timedelta(days=7)) -> list[CalendarEvent]:
    """Mỗi tuần một lần công bố dự kiến (thứ Năm 8:30 ET). Tuần có ngày lễ liên bang (thứ Hai–Sáu)
    → ba sự kiện cả ngày thứ Tư / thứ Năm / thứ Sáu thay cho giờ 8:30."""
    from gold_trading.market.federal_holidays import FEDERAL_HOLIDAYS_VERSION, holidays_between

    today = now.astimezone(ET).date()
    cutoff = (now - keep_after).astimezone(ET).date()
    monday = cutoff - timedelta(days=cutoff.weekday())
    events: list[CalendarEvent] = []
    for w in range(weeks + 2):
        mon = monday + timedelta(weeks=w)
        thu = mon + timedelta(days=3)
        if thu > today + timedelta(weeks=weeks):
            break
        hol = holidays_between(mon, mon + timedelta(days=4))
        base = {"event": EVENT, "title": "Unemployment Insurance Weekly Claims",
                "week_ending": (thu - timedelta(days=5)).isoformat(), "basis": "RULE",
                "time_confirmed": False, "tz": "America/New_York", "status": "SCHEDULED",
                "rule_version": FEDERAL_HOLIDAYS_VERSION, "includes": ["INITIAL_CLAIMS"]}
        if not hol:
            at = datetime.combine(thu, RULE_TIME, tzinfo=ET)
            if thu >= cutoff:
                events.append(CalendarEvent(f"CLAIMS:{thu.isoformat()}", at.astimezone(UTC), {
                    **base, "all_day": False, "release_local": "08:30",
                    "release_date_local": thu.isoformat(), "holidays": [], "flags": []}))
            continue
        names = [f"{d.isoformat()} {n}" for d, n in sorted(hol.items())]
        for off, tag in ((2, "WED"), (3, "THU"), (4, "FRI")):
            d = mon + timedelta(days=off)
            if d < cutoff:
                continue
            key = f"CLAIMS:{thu.isoformat()}" + ("" if tag == "THU" else f":{tag}")
            events.append(CalendarEvent(
                key, datetime.combine(d, time(0, 0), tzinfo=ET).astimezone(UTC), {
                    **base, "all_day": True, "release_local": None,
                    "release_date_local": d.isoformat(), "holidays": names,
                    "flags": ["HOLIDAY_WEEK"]}))
    if not any(e.event_time > now for e in events):  # pragma: no cover - luôn có tuần sau
        raise DolParseError("không sinh được lần công bố tương lai")
    return sorted(events, key=lambda e: (e.event_time, e.logical_key))


# ---------------------------------------------------------------- 2. Bản tin PDF

@dataclass(frozen=True)
class Release:
    released_at: datetime        # giờ ET trong dòng "EMBARGOED UNTIL"
    values: dict                 # logical_key → (week_ending, giá trị int, nhãn)


def pdf_text(data: bytes, pages: int = 2) -> str:
    """Chữ của vài trang đầu (đủ phần tóm tắt). Lỗi đọc PDF → ``DolParseError``."""
    try:
        from pypdf import PdfReader
        r = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in r.pages[:pages])
    except Exception as e:  # noqa: BLE001 - mọi lỗi đọc PDF đều là "định dạng lạ"
        raise DolParseError("không đọc được PDF") from e


def _n(s: str) -> int:
    if not re.fullmatch(r"\d{1,3}(?:,\d{3})*", s):
        raise DolParseError(f"số lạ: {s[:20]!r}")
    return int(s.replace(",", ""))


_EMBARGO = re.compile(
    r"EMBARGOED UNTIL\s+(\d{1,2}):(\d{2}) ([AP])\.M\. \(Eastern\) ([A-Z][a-z]+), "
    r"([A-Z][a-z]+) (\d{1,2}), (\d{4})")
_NUM = r"(\d{1,3}(?:,\d{3})*)"
_CHANGE = (r"(?:an increase of " + _NUM + r"|a decrease of " + _NUM + r"|unchanged) from the "
           r"previous week's (?:revised|unrevised) (?:level|average)")
_PREV = (r"The previous week's (?:level|average) was (?:revised (up|down) by " + _NUM + r" from "
         + _NUM + r" to " + _NUM + r"|unrevised at " + _NUM + r")")
_ICSA = re.compile(r"In the week ending ([A-Z][a-z]+) (\d{1,2}), the advance figure for seasonally "
                   r"adjusted initial claims was " + _NUM + ", " + _CHANGE + r"\. " + _PREV + r"\.")
_IC4W = re.compile(r"The 4-week moving average was " + _NUM + ", " + _CHANGE + r"\. " + _PREV
                   + r"\.")
_CCSA = re.compile(r"The advance number for seasonally adjusted insured unemployment during the "
                   r"week ending ([A-Z][a-z]+) (\d{1,2}) was " + _NUM + ", " + _CHANGE + r"\. "
                   + _PREV + r"\.")


def _week(month: str, day: str, released: date) -> date:
    if month not in MONTHS:
        raise DolParseError(f"tháng lạ: {month!r}")
    for y in (released.year, released.year - 1):
        try:
            d = date(y, MONTHS[month], int(day))
        except ValueError:
            continue
        if d.weekday() == 5 and timedelta(0) < released - d <= timedelta(days=20):
            return d
    raise DolParseError(f"tuần kết thúc lạ: {month} {day}")


def _checked(cur: str, groups: tuple) -> tuple[int, int]:
    """(giá trị tuần này, giá trị tuần trước đã sửa), sau khi kiểm số học."""
    inc, dec, updown, by, frm, to, unrev = groups
    value = _n(cur)
    prev = _n(to) if to else _n(unrev)
    if to:
        delta = _n(by) * (1 if updown == "up" else -1)
        if _n(frm) + delta != prev:
            raise DolParseError("số sửa của tuần trước không khớp")
    change = _n(inc) if inc else -_n(dec) if dec else 0
    if prev + change != value:
        raise DolParseError("số tuần này ≠ số tuần trước ± mức thay đổi")
    return value, prev


def parse_release(text: str) -> Release:
    t = re.sub(r"\s+", " ", text)
    m = _EMBARGO.search(t)
    if not m:
        raise DolParseError("không thấy dòng EMBARGOED UNTIL")
    h, mi = int(m.group(1)), int(m.group(2))
    if not (1 <= h <= 12 and mi <= 59) or m.group(5) not in MONTHS:
        raise DolParseError("giờ phát hành lạ")
    try:
        d = date(int(m.group(7)), MONTHS[m.group(5)], int(m.group(6)))
    except ValueError as e:
        raise DolParseError("ngày phát hành lạ") from e
    if WEEKDAYS[d.weekday()] != m.group(4):
        raise DolParseError("thứ trong tuần không khớp ngày phát hành")
    released = datetime.combine(d, time(h % 12 + (12 if m.group(3) == "P" else 0), mi),
                                tzinfo=ET)
    values: dict[str, tuple[date, int, str]] = {}
    ic = _ICSA.search(t)
    if not ic:
        raise DolParseError("không đọc được câu số đơn lần đầu")
    wk = _week(ic.group(1), ic.group(2), d)
    v, p = _checked(ic.group(3), ic.groups()[3:])
    values[f"ICSA:{wk}"] = (wk, v, "Đơn xin trợ cấp lần đầu, đã điều chỉnh mùa vụ (ước tính sớm)")
    values[f"ICSA:{wk - timedelta(weeks=1)}"] = (
        wk - timedelta(weeks=1), p, "Đơn xin trợ cấp lần đầu, đã điều chỉnh mùa vụ")
    a = _IC4W.search(t, ic.end())
    if not a:
        raise DolParseError("không đọc được trung bình 4 tuần")
    v4, p4 = _checked(a.group(1), a.groups()[1:])
    values[f"IC4WSA:{wk}"] = (wk, v4, "Trung bình 4 tuần đơn lần đầu, đã điều chỉnh mùa vụ")
    values[f"IC4WSA:{wk - timedelta(weeks=1)}"] = (
        wk - timedelta(weeks=1), p4, "Trung bình 4 tuần đơn lần đầu, đã điều chỉnh mùa vụ")
    cc = _CCSA.search(t)
    if not cc:
        raise DolParseError("không đọc được câu số đơn tiếp tục")
    cw = _week(cc.group(1), cc.group(2), d)
    if wk - cw != timedelta(weeks=1):
        raise DolParseError("tuần của đơn tiếp tục phải trước tuần đơn lần đầu một tuần")
    vc, pc = _checked(cc.group(3), cc.groups()[3:])
    values[f"CCSA:{cw}"] = (cw, vc, "Đơn tiếp tục (người đang nhận trợ cấp), đã điều chỉnh "
                                    "mùa vụ (ước tính sớm)")
    values[f"CCSA:{cw - timedelta(weeks=1)}"] = (
        cw - timedelta(weeks=1), pc, "Đơn tiếp tục, đã điều chỉnh mùa vụ")
    return Release(released, values)


def http_getter(client, timeout: float = 30.0):
    """``get(url) -> bytes`` (PDF). Chỉ ``www.dol.gov``; chuyển hướng sang nơi khác → lỗi."""
    import httpx

    from gold_trading.ingestion.api_keys import error_code_for_exception, error_code_for_http

    def get(url: str) -> bytes:
        if not any(url.startswith(f"https://{h}/") for h in ALLOWED_HOSTS):
            raise FetchError("BAD_URL")
        try:
            r = client.get(url, timeout=timeout, follow_redirects=True)
        except httpx.HTTPError as e:
            raise FetchError(error_code_for_exception(e)) from None
        if r.url.scheme != "https" or r.url.host not in ALLOWED_HOSTS:
            raise FetchError("UNEXPECTED_REDIRECT")
        if r.status_code != 200:
            raise FetchError(error_code_for_http(r.status_code))
        if len(r.content) > MAX_BYTES:
            raise FetchError("RESPONSE_TOO_LARGE")
        if not r.content.startswith(b"%PDF"):
            raise FetchError("NOT_PDF")
        return r.content

    return get


# ---------------------------------------------------------------- 3. Chạy một lần

SCHEDULE_FETCH_TTL = timedelta(hours=26)
VALUES_FETCH_TTL = timedelta(days=8)
# Tuần mới nhất (kết thúc thứ Bảy) được công bố thứ Năm kế tiếp (5 ngày sau); thêm tuần lễ dời
# ngày + một lần lỡ → 16 ngày. Quá → DOL ngừng / đổi định dạng → STALE.
VALUES_DATA_TTL = timedelta(days=16)


def schedule_spec():
    from gold_trading.ingestion.source_status import SourceSpec
    return SourceSpec(SCHEDULE_SOURCE, "calendar", fetch_ttl=SCHEDULE_FETCH_TTL,
                      provider=PROVIDER)


def values_spec():
    from gold_trading.ingestion.source_status import SourceSpec
    return SourceSpec(VALUES_SOURCE, "macro", fetch_ttl=VALUES_FETCH_TTL,
                      data_ttl=VALUES_DATA_TTL, provider=PROVIDER)


def _enabled(registry, name: str) -> None:
    from gold_trading.ingestion.source_status import SourceRegistry
    registry = registry if registry is not None else SourceRegistry(
        [schedule_spec(), values_spec()])
    spec = registry.get(name)
    if spec is None or not spec.enabled:
        raise ValueError(f"nguồn {name} chưa được bật")


def run_schedule_once(*, store, log, now: datetime, registry=None):
    """Sinh lịch theo quy tắc + ghi theo revision (đổi bảng ngày lễ → revision)."""
    from gold_trading.ingestion.calendar_sync import EventIn, sync_calendar
    from gold_trading.ingestion.source_status import CheckOutcome, SourceCheck

    _enabled(registry, SCHEDULE_SOURCE)
    events = build_schedule(now)
    res = sync_calendar(store, source=SCHEDULE_SOURCE, payload_version=SCHEDULE_PAYLOAD_VERSION,
                        raw_ref=f"rule:thursday-0830-et@{now.isoformat()}",
                        events=[EventIn(e.logical_key, e.event_time, e.payload) for e in events],
                        now=now)
    check = (SourceCheck(SCHEDULE_SOURCE, now, CheckOutcome.INVALID, res.error_code)
             if res.error_code else SourceCheck.from_counts(SCHEDULE_SOURCE, now, res.counts))
    log.record(check)
    return check


def scheduled_match(store, released_at: datetime, now: datetime) -> bool:
    """Giờ phát hành có khớp lịch theo quy tắc (đã biết tại ``now``) không: đúng giờ 8:30 của
    tuần thường, hoặc trong ba ngày chặn cả ngày của tuần lễ."""
    r_utc = released_at.astimezone(UTC)
    for r in store.as_of(now, source=SCHEDULE_SOURCE, kind="calendar",
                         event_from=r_utc - timedelta(days=1),
                         event_to=r_utc + timedelta(seconds=1)):
        p = r.payload
        if p.get("status") != "SCHEDULED":
            continue
        if not p.get("all_day") and r.event_time == r_utc:
            return True
        if p.get("all_day") and p.get("release_date_local") == released_at.date().isoformat():
            return True
    return False


def sync_values(store, rel: Release, now: datetime):
    from gold_trading.common.enums import SourceStatus
    from gold_trading.contracts.records import NormalizedRecord
    from gold_trading.ingestion.point_in_time import AppendCounts

    known = {r.logical_key: r for r in store.as_of(now, source=VALUES_SOURCE, kind="macro")}
    on_schedule = scheduled_match(store, rel.released_at, now)
    counts = AppendCounts()
    released_utc = rel.released_at.astimezone(UTC)
    for key, (wk, value, label) in sorted(rel.values.items()):
        prev = known.get(key)
        if prev is not None and prev.payload.get("value") == str(value):
            continue
        if prev is not None and prev.available_at is not None \
                and prev.available_at >= released_utc:
            continue  # bản tin cũ hơn số đã có → không viết lại
        flags = [] if on_schedule else ["RELEASE_OFF_SCHEDULE"]
        rev = 0 if prev is None else max(
            r.revision for r in store.history(VALUES_SOURCE, key, now)) + 1
        week_end = datetime.combine(wk + timedelta(days=1), time(0, 0), tzinfo=ET).astimezone(UTC)
        rec = NormalizedRecord(
            record_id=f"{VALUES_SOURCE}:{key}:r{rev}", source=VALUES_SOURCE, kind="macro",
            logical_key=key, revision=rev, event_time=week_end, ingested_at=now,
            available_at=released_utc, source_status=SourceStatus.HEALTHY,
            payload_version=VALUES_PAYLOAD_VERSION,
            raw_ref=f"{PDF_URL}@{rel.released_at.isoformat()}", quality_flags=frozenset(flags),
            payload={"series": key.split(":")[0], "week_ending": wk.isoformat(),
                     "value": str(value), "value_status": "AVAILABLE", "unit": "PERSONS",
                     "seasonally_adjusted": True, "label": label,
                     "released_at": released_utc.isoformat(),
                     "latency_seconds": max(0, int((now - released_utc).total_seconds())),
                     "flags": flags})
        counts.add(store.append(rec, {"released_at": rel.released_at.isoformat(),
                                      "key": key, "value": value}))
    return counts


def run_values_once(*, store, log, get, now: datetime, registry=None):
    from gold_trading.ingestion.source_status import CheckOutcome, SourceCheck

    _enabled(registry, VALUES_SOURCE)
    try:
        rel = parse_release(pdf_text(get(PDF_URL)))
        if rel.released_at.astimezone(UTC) > now:
            raise DolParseError("bản tin ghi giờ phát hành ở tương lai")
    except FetchError as e:
        check = SourceCheck(VALUES_SOURCE, now, CheckOutcome.ERROR, e.code)
    except DolParseError:
        check = SourceCheck(VALUES_SOURCE, now, CheckOutcome.INVALID, "PARSE_ERROR")
    else:
        check = SourceCheck.from_counts(VALUES_SOURCE, now, sync_values(store, rel, now))
    log.record(check)
    return check


def values_due(now: datetime, store, last_ok_at: datetime | None,
               poll_window: timedelta = timedelta(minutes=90)) -> str | None:
    """Trong 90 phút sau 8:30 ET thứ Năm (hoặc cả ngày thứ Tư–Sáu tuần lễ), hoặc đối chiếu khi
    lần OK cuối > 7 ngày."""
    local = now.astimezone(ET)
    for r in store.as_of(now, source=SCHEDULE_SOURCE, kind="calendar",
                         event_from=now - timedelta(days=1)):
        p = r.payload
        if p.get("status") != "SCHEDULED" or r.event_time > now:
            continue
        if not p.get("all_day") and now - r.event_time <= poll_window:
            return "RELEASE_WINDOW"
        if p.get("all_day") and p.get("release_date_local") == local.date().isoformat() \
                and time(8, 0) <= local.time() <= time(18, 0):
            return "RELEASE_WINDOW"
    if last_ok_at is None or now - last_ok_at > timedelta(days=7):
        return "RECONCILE"
    return None
