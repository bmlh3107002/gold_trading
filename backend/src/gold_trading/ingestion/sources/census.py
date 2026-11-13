"""Census: lịch + số actual doanh số bán lẻ (bước 8d — ING-09, ING-17, ING-19).

Điều khoản ``VERIFIED``. Thiết kế + lý do: ``docs/thiet-ke/14-census.md``. Hai nguồn, chung nhà
cung cấp ``census``:

1. ``census_schedule`` (lịch, không cần khóa) — lịch chỉ số kinh tế dạng danh sách
   (``/economic-indicators/calendar-listview*.html``: mỗi dòng có ngày + giờ chữ **và** mã ẩn
   ``AYYYYMMDDHHMM`` + kỳ ``AYYYYMM`` — hai cách ghi phải khớp), **đối chiếu** lịch riêng của
   khảo sát bán lẻ (``/retail/release_schedule.html``). Lệch → cờ ``CALENDAR_SOURCES_DISAGREE``,
   chặn cả ngày.
2. ``census_marts`` (số actual, khóa ``GT_CENSUS_API_KEY``) — API ``timeseries/eits/marts``:
   doanh số bán lẻ + ăn uống (đã điều chỉnh mùa vụ), mức (triệu USD) và % so tháng trước, cho
   tổng / trừ ô tô / trừ ô tô và xăng. Kiểm chéo: % Census công bố phải khớp % tự tính từ mức
   (lệch > 0,1 → INVALID).

Quy tắc an toàn giống ``bea.py``: định dạng lạ → INVALID, không ghi; "không có số" ≠ 0; khóa
không bao giờ nằm trong thứ được lưu; khóa sai/thiếu Census báo bằng **chuyển hướng** sang
``invalid_key.html`` / ``missing_key.html`` → không đi theo chuyển hướng, đổi thành
``AUTH_FAILED`` / ``KEY_MISSING``.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PROVIDER = "census"
SCHEDULE_SOURCE = "census_schedule"
VALUES_SOURCE = "census_marts"
BASE = "https://www.census.gov"
LISTVIEW_PATH = "/economic-indicators/calendar-listview.html"          # năm mới nhất
LISTVIEW_YEAR_PATH = "/economic-indicators/calendar-listview-{year}.html"
RETAIL_SCHEDULE_PATH = "/retail/release_schedule.html"
API_URL = "https://api.census.gov/data/timeseries/eits/marts"
ALLOWED_HOSTS = frozenset({"www.census.gov", "api.census.gov"})
SCHEDULE_PAYLOAD_VERSION = "census-schedule-1"
VALUES_PAYLOAD_VERSION = "census-marts-1"
MAX_BYTES = 5 * 1024 * 1024
INDICATOR = "Advance Monthly Sales for Retail and Food Services"
EVENT = "CENSUS_RETAIL"

MONTHS = {m: i for i, m in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August", "September",
     "October", "November", "December"), start=1)}


class CensusParseError(ValueError):
    """Nội dung Census không đúng định dạng đã biết — không đoán, cả lần tải bị coi INVALID."""


class FetchError(Exception):
    """Lỗi tải; ``code`` là mã ngắn an toàn (ING-30/31)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _text(fragment: str) -> str:
    t = html_lib.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", t).strip()


def _month_year(s: str) -> date:
    m = re.fullmatch(r"([A-Z][a-z]+) (\d{4})", s)
    if not m or m.group(1) not in MONTHS:
        raise CensusParseError(f"tháng lạ: {s[:40]!r}")
    return date(int(m.group(2)), MONTHS[m.group(1)], 1)


def _long_date(s: str) -> date:
    m = re.fullmatch(r"([A-Z][a-z]+) (\d{1,2}), (\d{4})", s)
    if not m or m.group(1) not in MONTHS:
        raise CensusParseError(f"ngày lạ: {s[:40]!r}")
    try:
        return date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
    except ValueError as e:
        raise CensusParseError(f"ngày không hợp lệ: {s[:40]!r}") from e


def _clock(s: str) -> time:
    m = re.fullmatch(r"(\d{1,2}):(\d{2}) ?([AaPp])\.?[Mm]\.?", s)
    if not m or not (1 <= int(m.group(1)) <= 12 and int(m.group(2)) <= 59):
        raise CensusParseError(f"giờ lạ: {s[:20]!r}")
    h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0)
    return time(h, int(m.group(2)))


# ---------------------------------------------------------------- 1. Lịch

@dataclass(frozen=True)
class Listed:
    period: date        # tháng số liệu (ngày 1)
    at: datetime        # giờ công bố, múi ET


_LV_YEAR = re.compile(r"US Census Bureau: (\d{4}) Economic Indicator Release Schedule")


def parse_listview(page: str) -> tuple[int, list[Listed]]:
    """(năm của trang, các lần công bố doanh số bán lẻ). Chữ và mã ẩn phải khớp nhau."""
    y = _LV_YEAR.search(page)
    if not y:
        raise CensusParseError("không thấy tiêu đề năm của lịch")
    start = page.find('id="calendar"')
    if start < 0:
        raise CensusParseError("không thấy bảng lịch")
    out: list[Listed] = []
    rows = 0
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", page[start:], re.S):
        cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        if not cells:
            continue
        rows += 1
        if cells[0] != INDICATOR:
            continue
        if len(cells) != 6:
            raise CensusParseError("dòng lịch bán lẻ sai số cột")
        d, t, period = _long_date(cells[1]), _clock(cells[2]), _month_year(cells[3])
        at = datetime.combine(d, t, tzinfo=ET)
        if cells[4] != "A" + at.strftime("%Y%m%d%H%M") or \
                cells[5] != "A" + period.strftime("%Y%m"):
            raise CensusParseError("ngày/giờ chữ lệch mã ẩn trong cùng dòng")
        out.append(Listed(period, at))
    if rows == 0 or not out:
        raise CensusParseError("lịch không có dòng doanh số bán lẻ nào")
    if len({x.period for x in out}) != len(out):
        raise CensusParseError("một kỳ có hai lần công bố")
    return int(y.group(1)), out


def parse_retail_schedule(page: str) -> dict[date, date]:
    """Lịch riêng của khảo sát bán lẻ: {tháng số liệu: ngày công bố} (giờ ghi ở tiêu đề: 8:30 am).
    "To be announced" → bỏ qua (chưa có ngày)."""
    i = page.find("Advance Monthly Retail Trade Report")
    j = page.find("<h2", i + 1) if i >= 0 else -1
    if i < 0 or j < 0:
        raise CensusParseError("không thấy bảng Advance Monthly Retail Trade Report")
    section = page[i:j]
    out: dict[date, date] = {}
    header = False
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", section, re.S):
        cells = [_text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
        if len(cells) != 2:
            raise CensusParseError("bảng lịch bán lẻ sai số cột")
        if cells[0] == "Data Month":
            if cells[1] != "Release Date at 8:30 am":
                raise CensusParseError("giờ công bố trong tiêu đề đã đổi")
            header = True
            continue
        if cells[1].startswith("To be announced"):
            continue
        p = _month_year(cells[0])
        if p in out:
            raise CensusParseError("tháng số liệu lặp lại")
        out[p] = _long_date(cells[1])
    if not header or not out:
        raise CensusParseError("bảng lịch bán lẻ rỗng")
    return out


@dataclass(frozen=True)
class CalendarEvent:
    logical_key: str
    event_time: datetime
    payload: dict = field(hash=False)


def build_schedule(listed: list[Listed], retail: dict[date, date], now: datetime,
                   keep_after: timedelta = timedelta(days=7)) -> list[CalendarEvent]:
    cutoff = now - keep_after
    events: list[CalendarEvent] = []
    for x in sorted(listed, key=lambda x: x.at):
        if x.at < cutoff:
            continue
        flags: list[str] = []
        other = retail.get(x.period)
        # Bảng bán lẻ chỉ có từ vài tháng trước tới năm sau: thiếu kỳ đã qua thì không coi là lệch.
        if other != x.at.date() or x.at.time() != time(8, 30):
            if other is not None or x.period >= min(retail):
                flags.append("CALENDAR_SOURCES_DISAGREE")
        confirmed = not flags
        at = x.at if confirmed else datetime.combine(x.at.date(), time(0, 0), tzinfo=ET)
        events.append(CalendarEvent(f"RETAIL:{x.period:%Y-%m}", at.astimezone(UTC), {
            "event": EVENT, "title": INDICATOR, "period": f"{x.period:%Y-%m}",
            "includes": ["RETAIL_SALES"], "time_confirmed": confirmed, "all_day": not confirmed,
            "release_local": x.at.strftime("%H:%M") if confirmed else None,
            "release_date_local": x.at.date().isoformat(), "tz": "America/New_York",
            "status": "SCHEDULED", "flags": flags}))
    have = {e.payload["period"] for e in events}
    for p, d in sorted(retail.items()):
        at = datetime.combine(d, time(0, 0), tzinfo=ET)
        if f"{p:%Y-%m}" in have or at + timedelta(days=1) < cutoff:
            continue
        # Chỉ có ở lịch bán lẻ → vẫn ghi, cả ngày + cờ (thêm sự kiện = chặn nhiều hơn).
        events.append(CalendarEvent(f"RETAIL:{p:%Y-%m}", at.astimezone(UTC), {
            "event": EVENT, "title": INDICATOR, "period": f"{p:%Y-%m}",
            "includes": ["RETAIL_SALES"], "time_confirmed": False, "all_day": True,
            "release_local": None, "release_date_local": d.isoformat(),
            "tz": "America/New_York", "status": "SCHEDULED",
            "flags": ["CALENDAR_SOURCES_DISAGREE"]}))
    if not any(e.event_time > now for e in events):
        raise CensusParseError("không còn lần công bố bán lẻ nào trong tương lai")
    return sorted(events, key=lambda e: (e.event_time, e.logical_key))


def collect_schedule(get, now: datetime) -> tuple[list[Listed], dict[date, date]]:
    """Trang lịch mặc định (năm mới nhất) + trang của năm hiện tại nếu khác."""
    year, listed = parse_listview(get(BASE + LISTVIEW_PATH))
    cur = now.astimezone(ET).year
    if cur != year:
        y2, more = parse_listview(get(BASE + LISTVIEW_YEAR_PATH.format(year=cur)))
        if y2 != cur:
            raise CensusParseError("trang lịch năm hiện tại ghi năm khác")
        seen = {x.period for x in listed}
        listed = listed + [x for x in more if x.period not in seen]
    return listed, parse_retail_schedule(get(BASE + RETAIL_SCHEDULE_PATH))


# ---------------------------------------------------------------- 2. Số actual

@dataclass(frozen=True)
class SeriesSpec:
    category: str
    data_type: str
    label: str
    unit: str


# Mã theo công cụ Time Series chính thức của Census (MARTS, kiểm 2026-11-13).
SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec("44X72", "SM", "Doanh số bán lẻ + ăn uống, tổng (đã điều chỉnh mùa vụ)",
               "USD_MILLIONS"),
    SeriesSpec("44X72", "MPCSM", "Doanh số bán lẻ + ăn uống, tổng, % so tháng trước", "PERCENT"),
    SeriesSpec("44Y72", "SM", "Doanh số bán lẻ + ăn uống trừ ô tô (đã điều chỉnh mùa vụ)",
               "USD_MILLIONS"),
    SeriesSpec("44Y72", "MPCSM", "Doanh số bán lẻ + ăn uống trừ ô tô, % so tháng trước", "PERCENT"),
    SeriesSpec("44W72", "SM", "Doanh số bán lẻ + ăn uống trừ ô tô và xăng (đã điều chỉnh mùa vụ)",
               "USD_MILLIONS"),
    SeriesSpec("44W72", "MPCSM", "Doanh số bán lẻ + ăn uống trừ ô tô và xăng, % so tháng trước",
               "PERCENT"),
)
_SPEC = {(s.category, s.data_type): s for s in SERIES}
_NA = frozenset({"(NA)", "NA", "(S)", "(X)", "(D)", "(Z)", "---"})
_NUM = re.compile(r"^-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$")
REQUIRED_COLS = ("cell_value", "data_type_code", "category_code", "seasonally_adj", "error_data",
                 "time")
PCT_TOLERANCE = Decimal("0.1")


@dataclass(frozen=True)
class Observation:
    category: str
    data_type: str
    period: str           # "2026-09"
    period_end: datetime
    value: str | None
    row: dict = field(hash=False)

    @property
    def key(self) -> str:
        return f"{self.category}:{self.data_type}:{self.period}"


def parse_value(raw: object) -> str | None:
    if not isinstance(raw, str):
        raise CensusParseError("cell_value không phải chuỗi")
    s = raw.strip()
    if s in _NA:
        return None
    if not _NUM.match(s):
        raise CensusParseError(f"cell_value lạ: {s[:20]!r}")
    return format(Decimal(s.replace(",", "")), "f")


def _period(raw: str) -> tuple[str, datetime]:
    m = re.fullmatch(r"(\d{4})-(\d{2})", raw)
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise CensusParseError(f"kỳ lạ: {raw!r}")
    y, mo = int(m.group(1)), int(m.group(2))
    nxt = date(y + (mo == 12), 1 if mo == 12 else mo + 1, 1)
    return f"{y}-{mo:02d}", datetime.combine(nxt, time(0, 0), tzinfo=ET).astimezone(UTC)


def parse_api(text: str) -> list[Observation]:
    """Phản hồi API (mảng 2 chiều, dòng đầu là tên cột) → quan sát của các series cấu hình.
    Chỉ lấy dòng đã điều chỉnh mùa vụ và không phải dòng sai số. Chuỗi rỗng (HTTP 204) → []."""
    if not text.strip():
        return []
    try:
        data = json.loads(text)
    except ValueError as e:
        raise CensusParseError("phản hồi không phải JSON") from e
    if not isinstance(data, list) or not data or not isinstance(data[0], list):
        raise CensusParseError("phản hồi sai cấu trúc")
    head = data[0]
    if any(c not in head for c in REQUIRED_COLS):
        raise CensusParseError("thiếu cột bắt buộc")
    idx = {c: head.index(c) for c in head}
    seen: dict[str, Observation] = {}
    for row in data[1:]:
        if not isinstance(row, list) or len(row) != len(head) or \
                not all(isinstance(v, str) for v in row):
            raise CensusParseError("dòng dữ liệu sai cấu trúc")
        g = {c: row[i] for c, i in idx.items()}
        if g["seasonally_adj"] not in ("yes", "no") or g["error_data"] not in ("yes", "no"):
            raise CensusParseError("giá trị cờ lạ")
        spec = _SPEC.get((g["category_code"], g["data_type_code"]))
        if spec is None or g["seasonally_adj"] != "yes" or g["error_data"] != "no":
            continue
        period, end = _period(g["time"])
        o = Observation(spec.category, spec.data_type, period, end, parse_value(g["cell_value"]),
                        {k: v for k, v in g.items() if k in REQUIRED_COLS})
        prev = seen.get(o.key)
        if prev is not None and prev.value != o.value:
            raise CensusParseError(f"{o.key} có hai giá trị khác nhau")
        seen[o.key] = o
    return sorted(seen.values(), key=lambda o: o.key)


def check_consistency(obs: list[Observation]) -> None:
    """% Census công bố phải khớp % tự tính từ mức (cùng phiên bản số liệu), lệch tối đa 0,1 điểm
    (Census tính từ số chưa làm tròn). Lệch hơn → nghi mã sai / dữ liệu hỏng → INVALID.
    Mỗi series cấu hình phải có ít nhất một quan sát."""
    by = {o.key: o for o in obs}
    for s in SERIES:
        if not any(o.category == s.category and o.data_type == s.data_type for o in obs):
            raise CensusParseError(f"thiếu series {s.category}/{s.data_type}")
    for o in obs:
        if o.data_type != "MPCSM" or o.value is None:
            continue
        y, m = map(int, o.period.split("-"))
        prev = f"{y - (m == 1)}-{12 if m == 1 else m - 1:02d}"
        cur = by.get(f"{o.category}:SM:{o.period}")
        before = by.get(f"{o.category}:SM:{prev}")
        if cur is None or before is None or cur.value is None or before.value is None:
            continue
        calc = (Decimal(cur.value) / Decimal(before.value) - 1) * 100
        if abs(calc - Decimal(o.value)) > PCT_TOLERANCE:
            raise CensusParseError(f"{o.key}: % công bố lệch % tự tính")


# ---------------------------------------------------------------- 3. Tải (HTTP)

def http_getter(client, timeout: float = 30.0):
    """``get(url, params=None) -> str``. **Không** đi theo chuyển hướng: Census báo khóa sai /
    thiếu bằng 302 sang ``invalid_key.html`` / ``missing_key.html``. HTTP 204 (không có dữ liệu)
    → ``""``."""
    import httpx

    from gold_trading.ingestion.api_keys import error_code_for_exception, error_code_for_http

    def get(url: str, params: dict | None = None) -> str:
        if not any(url.startswith(f"https://{h}/") for h in ALLOWED_HOSTS):
            raise FetchError("BAD_URL")
        try:
            r = client.get(url, params=params, timeout=timeout, follow_redirects=False)
        except httpx.HTTPError as e:
            raise FetchError(error_code_for_exception(e)) from None
        if r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("location", "")
            if "invalid_key" in loc:
                raise FetchError("AUTH_FAILED")
            if "missing_key" in loc:
                raise FetchError("KEY_MISSING")
            raise FetchError("UNEXPECTED_REDIRECT")
        if r.status_code == 204:
            return ""
        if r.status_code != 200:
            raise FetchError(error_code_for_http(r.status_code))
        if len(r.content) > MAX_BYTES:
            raise FetchError("RESPONSE_TOO_LARGE")
        return r.text

    return get


# ---------------------------------------------------------------- 4. Chạy một lần

SCHEDULE_FETCH_TTL = timedelta(hours=26)
VALUES_FETCH_TTL = timedelta(days=8)
# Số tháng mới nhất bình thường cũ nhất ~51 ngày tính từ cuối kỳ (vd. số tháng 3/2026 công bố 21/4;
# trước đó số mới nhất là tháng 2, hết kỳ 01/3). Quá 55 ngày → Census trễ lịch → STALE.
VALUES_DATA_TTL = timedelta(days=55)
RELEASE_MATCH_WINDOW = timedelta(days=3)


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


def run_schedule_once(*, store, log, get, now: datetime, registry=None):
    from gold_trading.ingestion.calendar_sync import EventIn, sync_calendar
    from gold_trading.ingestion.source_status import CheckOutcome, SourceCheck

    _enabled(registry, SCHEDULE_SOURCE)
    try:
        listed, retail = collect_schedule(get, now)
        events = build_schedule(listed, retail, now)
    except FetchError as e:
        check = SourceCheck(SCHEDULE_SOURCE, now, CheckOutcome.ERROR, e.code)
    except CensusParseError:
        check = SourceCheck(SCHEDULE_SOURCE, now, CheckOutcome.INVALID, "PARSE_ERROR")
    else:
        res = sync_calendar(store, source=SCHEDULE_SOURCE,
                            payload_version=SCHEDULE_PAYLOAD_VERSION,
                            raw_ref=f"{BASE}{LISTVIEW_PATH}@{now.isoformat()}",
                            events=[EventIn(e.logical_key, e.event_time, e.payload)
                                    for e in events], now=now)
        check = (SourceCheck(SCHEDULE_SOURCE, now, CheckOutcome.INVALID, res.error_code)
                 if res.error_code else SourceCheck.from_counts(SCHEDULE_SOURCE, now, res.counts))
    log.record(check)
    return check


def fetch_values(get, key, now: datetime) -> list[Observation]:
    """Hai yêu cầu (năm trước + năm nay theo giờ ET). Đầu năm, năm nay chưa có số → 204 → rỗng."""
    y = now.astimezone(ET).year
    obs: list[Observation] = []
    for year in (y - 1, y):
        obs.extend(parse_api(get(API_URL, {
            "get": "cell_value,data_type_code,time_slot_id,error_data,category_code,"
                   "seasonally_adj", "for": "us:*", "time": str(year), "key": key.reveal()})))
    check_consistency(obs)
    return obs


def release_for(store, now: datetime):
    cands = [r for r in store.as_of(now, source=SCHEDULE_SOURCE, kind="calendar",
                                    event_from=now - RELEASE_MATCH_WINDOW)
             if r.payload.get("event") == EVENT and r.payload.get("status") == "SCHEDULED"
             and r.event_time <= now]
    return max(cands, key=lambda r: r.event_time, default=None)


def sync_values(store, observations: list[Observation], now: datetime):
    """Như ``bea.sync_values``: mới → rev 0; đổi giá trị → rev mới + gắn lần công bố + độ trễ."""
    from gold_trading.common.enums import SourceStatus
    from gold_trading.contracts.records import NormalizedRecord
    from gold_trading.ingestion.point_in_time import AppendCounts

    known = {r.logical_key: r for r in store.as_of(now, source=VALUES_SOURCE, kind="macro")}
    initial = not known
    rel = release_for(store, now)
    counts = AppendCounts()
    for o in observations:
        prev = known.get(o.key)
        if prev is not None and prev.payload.get("value") == o.value:
            continue
        spec = _SPEC[(o.category, o.data_type)]
        flags: list[str] = []
        if rel is None:
            flags.append("INITIAL_LOAD" if initial else "UNSCHEDULED_CHANGE")
        if o.value is None:
            flags.append("VALUE_NOT_AVAILABLE")
        rev = 0 if prev is None else max(
            r.revision for r in store.history(VALUES_SOURCE, o.key, now)) + 1
        payload = {
            "category": o.category, "data_type": o.data_type, "label": spec.label,
            "unit": spec.unit, "period": o.period, "value": o.value,
            "value_status": "AVAILABLE" if o.value is not None else "NOT_AVAILABLE",
            "seasonally_adjusted": True,
            "release_ref": rel.logical_key if rel is not None else None,
            "latency_seconds": (int((now - rel.event_time).total_seconds())
                                if rel is not None else None),
            "flags": sorted(flags)}
        rec = NormalizedRecord(
            record_id=f"{VALUES_SOURCE}:{o.key}:r{rev}", source=VALUES_SOURCE, kind="macro",
            logical_key=o.key, revision=rev, event_time=o.period_end, ingested_at=now,
            available_at=max(rel.event_time, o.period_end) if rel is not None else None,
            source_status=SourceStatus.HEALTHY, payload_version=VALUES_PAYLOAD_VERSION,
            raw_ref=f"census:eits/marts@{now.isoformat()}", quality_flags=frozenset(flags),
            payload=payload)
        counts.add(store.append(rec, o.row))
    return counts


def run_values_once(*, store, log, get, key_lookup, now: datetime, registry=None):
    from gold_trading.ingestion.source_status import CheckOutcome, SourceCheck

    _enabled(registry, VALUES_SOURCE)
    if not key_lookup.ok:
        check = SourceCheck(VALUES_SOURCE, now, CheckOutcome.ERROR,
                            key_lookup.error_code or "KEY_MISSING")
    else:
        try:
            obs = fetch_values(get, key_lookup.key, now)
        except FetchError as e:
            check = SourceCheck(VALUES_SOURCE, now, CheckOutcome.ERROR, e.code)
        except CensusParseError:
            check = SourceCheck(VALUES_SOURCE, now, CheckOutcome.INVALID, "PARSE_ERROR")
        else:
            check = SourceCheck.from_counts(VALUES_SOURCE, now, sync_values(store, obs, now))
    log.record(check)
    return check


def values_due(now: datetime, store, last_ok_at: datetime | None,
               poll_window: timedelta = timedelta(minutes=90)) -> str | None:
    """Như ``bea.values_due``: 90 phút sau giờ công bố đã xác nhận, hoặc đối chiếu mỗi 7 ngày."""
    for r in store.as_of(now, source=SCHEDULE_SOURCE, kind="calendar",
                         event_from=now - poll_window):
        if (r.payload.get("event") == EVENT and r.payload.get("status") == "SCHEDULED"
                and r.payload.get("time_confirmed") and r.event_time <= now):
            return "RELEASE_WINDOW"
    if last_ok_at is None or now - last_ok_at > timedelta(days=7):
        return "RECONCILE"
    return None
