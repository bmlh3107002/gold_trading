"""BEA: lịch công bố + số actual GDP, PCE (bước 8c — ING-09, ING-17). Điều khoản ``VERIFIED``.

Thiết kế + lý do: ``docs/thiet-ke/13-bea.md``. Hai nguồn, chung nhà cung cấp ``bea``:

1. ``bea_schedule`` (lịch, không cần khóa) — file lịch chính thức của BEA
   (``www.bea.gov/news/schedule/ics/...``: tên từng lần công bố + giờ UTC), **đối chiếu** với file
   lịch máy đọc được mà trang lịch của BEA dẫn tới (``apps.bea.gov/API/signup/release_dates.json``).
   Hai file lệch nhau → cờ ``CALENDAR_SOURCES_DISAGREE``, giờ không được tin (``all_day``).
2. ``bea_nipa`` (số actual, khóa ``GT_BEA_API_KEY``) — API NIPA: GDP thực (% so quý trước, năm
   hóa), chỉ số giá PCE + PCE lõi (% so tháng trước và mức chỉ số). Mỗi lần BEA sửa số = một
   revision mới (ING-19), không ghi đè.

Quy tắc an toàn:
- Định dạng lạ → ``BeaParseError``: cả lần tải INVALID, không ghi gì. Không đoán.
- Giá trị BEA ghi "(NA)", "---"... → ``value = None``, ``value_status = NOT_AVAILABLE`` — **không**
  bao giờ thành 0 (1C-C01).
- Phản hồi API của BEA **chép lại khóa** (``Request.RequestParam`` có ``USERID``) → không bao giờ
  lưu nguyên phản hồi; chỉ lưu từng dòng số liệu (không chứa khóa).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PROVIDER = "bea"
SCHEDULE_SOURCE = "bea_schedule"
VALUES_SOURCE = "bea_nipa"
ICS_URL = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
DATES_URL = "https://apps.bea.gov/API/signup/release_dates.json"
API_URL = "https://apps.bea.gov/api/data"
ALLOWED_HOSTS = frozenset({"www.bea.gov", "apps.bea.gov"})
SCHEDULE_PAYLOAD_VERSION = "bea-schedule-1"
VALUES_PAYLOAD_VERSION = "bea-nipa-1"
MAX_BYTES = 5 * 1024 * 1024

# Tiêu đề nhóm trong file JSON của BEA ↔ loại công bố của hệ thống.
JSON_GROUPS = {"GDP": "Gross Domestic Product", "PIO": "Personal Income and Outlays"}

MONTHS = {m: i for i, m in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August", "September",
     "October", "November", "December"), start=1)}


class BeaParseError(ValueError):
    """Nội dung BEA không đúng định dạng đã biết — không đoán, cả lần tải bị coi INVALID."""


class FetchError(Exception):
    """Lỗi tải; ``code`` là mã ngắn an toàn (ING-30/31), không bao giờ kèm thông điệp gốc."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------- 1. Lịch (ICS + JSON)

@dataclass(frozen=True)
class IcsEvent:
    summary: str
    start: datetime          # UTC; ngày không giờ → 00:00 ET của ngày đó
    all_day: bool


def _ics_unescape(v: str) -> str:
    out, i = [], 0
    while i < len(v):
        c = v[i]
        if c == "\\" and i + 1 < len(v):
            n = v[i + 1]
            out.append("\n" if n in "nN" else n)
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out).strip()


_DT_UTC = re.compile(r"^(\d{8})T(\d{6})Z$")
_DT_LOCAL = re.compile(r"^(\d{8})T(\d{6})$")
_D_ONLY = re.compile(r"^(\d{8})$")


def _ics_start(name: str, value: str) -> tuple[datetime, bool]:
    params = dict(p.split("=", 1) for p in name.split(";")[1:] if "=" in p)
    try:
        if m := _DT_UTC.match(value):
            return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(
                tzinfo=UTC), False
        if (m := _D_ONLY.match(value)) and params.get("VALUE") == "DATE":
            d = datetime.strptime(m.group(1), "%Y%m%d").date()
            return datetime.combine(d, time(0, 0), tzinfo=ET).astimezone(UTC), True
        if (m := _DT_LOCAL.match(value)) and params.get("TZID") == "America/New_York":
            return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(
                tzinfo=ET).astimezone(UTC), False
    except ValueError as e:
        raise BeaParseError(f"giờ không hợp lệ: {value!r}") from e
    # Giờ "trôi" (không Z, không TZID biết được) → không đoán múi giờ.
    raise BeaParseError(f"DTSTART lạ: {name}:{value}")


def parse_ics(text: str) -> list[IcsEvent]:
    """Mọi sự kiện trong file lịch ICS của BEA (bỏ sự kiện ``STATUS:CANCELLED``)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]", "", text)  # nối dòng gập (RFC 5545)
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines or lines[0].strip() != "BEGIN:VCALENDAR" or "END:VCALENDAR" not in lines[-1]:
        raise BeaParseError("không phải file lịch ICS")
    out: list[IcsEvent] = []
    cur: dict[str, tuple[str, str]] | None = None
    for ln in lines:
        if ln == "BEGIN:VEVENT":
            if cur is not None:
                raise BeaParseError("VEVENT lồng nhau")
            cur = {}
            continue
        if ln == "END:VEVENT":
            if cur is None:
                raise BeaParseError("END:VEVENT thừa")
            if "SUMMARY" not in cur or "DTSTART" not in cur:
                raise BeaParseError("sự kiện thiếu SUMMARY / DTSTART")
            if cur.get("STATUS", ("", ""))[1].upper() != "CANCELLED":
                start, all_day = _ics_start(*cur["DTSTART"])
                out.append(IcsEvent(_ics_unescape(cur["SUMMARY"][1]), start, all_day))
            cur = None
            continue
        if cur is not None and ":" in ln:
            name, value = ln.split(":", 1)
            base = name.split(";", 1)[0].upper()
            if base in cur and base in ("SUMMARY", "DTSTART"):
                raise BeaParseError(f"sự kiện có hai {base}")
            cur[base] = (name, value.strip())
    if cur is not None:
        raise BeaParseError("VEVENT không đóng")
    if not out:
        raise BeaParseError("file lịch không có sự kiện nào")
    return out


@dataclass(frozen=True)
class Release:
    kind: str            # GDP | PIO
    period: str          # "2026Q3" | "2026-10" | "2025-10..2025-11"
    estimate: str | None  # GDP: ADVANCE / SECOND / THIRD / INITIAL / UPDATED
    logical_key: str


_GDP_HEAD = re.compile(r"^(?:GDP|Gross Domestic Product)(?: \(|,)")
_GDP_Q = re.compile(r"\b(1st|2nd|3rd|4th) [Qq]uarter(?: and Year)? (\d{4})\b")
_GDP_EST = re.compile(r"\((Advance|Second|Third|Initial|Updated) Estimate\)")
_PIO_HEAD = "Personal Income and Outlays"
_PIO = re.compile(r"^Personal Income and Outlays, ([A-Z][a-z]+)(?: and ([A-Z][a-z]+))? (\d{4})$")


def classify(summary: str) -> Release | None:
    """Tiêu đề lịch BEA → lần công bố GDP / Thu nhập–chi tiêu cá nhân (có PCE); khác → None.

    Tiêu đề **giống** GDP / PIO mà không đọc được kỳ → ``BeaParseError`` (không đoán)."""
    s = re.sub(r"\s+", " ", summary).strip()
    if _GDP_HEAD.match(s):
        q, est = _GDP_Q.findall(s), _GDP_EST.findall(s)
        if len(q) != 1 or len(est) != 1:
            raise BeaParseError(f"tiêu đề GDP lạ: {s[:120]!r}")
        period = f"{q[0][1]}Q{q[0][0][0]}"
        e = est[0].upper()
        return Release("GDP", period, e, f"GDP:{period}:{e}")
    if s.startswith(_PIO_HEAD):
        m = _PIO.match(s)
        if not m or m.group(1) not in MONTHS or (m.group(2) and m.group(2) not in MONTHS):
            raise BeaParseError(f"tiêu đề PIO lạ: {s[:120]!r}")
        y = int(m.group(3))
        m1 = MONTHS[m.group(1)]
        m2 = MONTHS[m.group(2)] if m.group(2) else m1
        if m2 < m1 or m2 - m1 > 2:
            raise BeaParseError(f"kỳ PIO lạ: {s[:120]!r}")
        period = f"{y}-{m1:02d}" + (f"..{y}-{m2:02d}" if m2 != m1 else "")
        return Release("PIO", period, None, f"PIO:{period}")
    return None


def parse_release_dates(text: str) -> dict[str, set[datetime]]:
    """File JSON lịch BEA → {GDP|PIO: tập giờ công bố UTC}."""
    try:
        d = json.loads(text)
    except ValueError as e:
        raise BeaParseError("file ngày công bố không phải JSON") from e
    if not isinstance(d, dict):
        raise BeaParseError("file ngày công bố sai cấu trúc")
    out: dict[str, set[datetime]] = {}
    for kind, title in JSON_GROUPS.items():
        g = d.get(title)
        lst = g.get("release_dates") if isinstance(g, dict) else None
        if not isinstance(lst, list) or not lst:
            raise BeaParseError(f"file ngày công bố thiếu nhóm {title!r}")
        times: set[datetime] = set()
        for s in lst:
            try:
                t = datetime.fromisoformat(s) if isinstance(s, str) else None
            except ValueError:
                t = None
            if t is None or t.tzinfo is None:
                raise BeaParseError(f"giờ lạ trong file ngày công bố: {str(s)[:40]!r}")
            times.add(t.astimezone(UTC))
        out[kind] = times
    return out


@dataclass(frozen=True)
class CalendarEvent:
    logical_key: str
    event_time: datetime      # UTC
    payload: dict = field(hash=False)


EVENT_NAME = {"GDP": "BEA_GDP", "PIO": "BEA_PIO"}
INCLUDES = {"GDP": ["REAL_GDP"], "PIO": ["PERSONAL_INCOME", "PCE", "PCE_PRICE_INDEX"]}


def build_schedule(ics: list[IcsEvent], dates: dict[str, set[datetime]], now: datetime,
                   keep_after: timedelta = timedelta(days=7)) -> list[CalendarEvent]:
    """Sự kiện GDP / PIO từ ``now - keep_after`` trở đi, có đối chiếu file JSON."""
    cutoff = now - keep_after
    events: list[CalendarEvent] = []
    matched: dict[str, set[datetime]] = {k: set() for k in JSON_GROUPS}
    ics_days: dict[str, set[date]] = {k: set() for k in JSON_GROUPS}
    for ev in ics:
        if ev.start < cutoff:
            continue  # không đọc tiêu đề cũ (định dạng cũ không làm hỏng lần tải)
        rel = classify(ev.summary)
        if rel is None:
            continue
        flags: list[str] = []
        confirmed = not ev.all_day and ev.start in dates[rel.kind]
        if not ev.all_day:
            if ev.start in dates[rel.kind]:
                matched[rel.kind].add(ev.start)
            else:
                flags.append("CALENDAR_SOURCES_DISAGREE")
        local = ev.start.astimezone(ET)
        ics_days[rel.kind].add(local.date())
        if confirmed and not (time(7, 0) <= local.time() <= time(18, 0)):
            flags.append("UNUSUAL_RELEASE_TIME")
        at = ev.start if confirmed else datetime.combine(
            local.date(), time(0, 0), tzinfo=ET).astimezone(UTC)
        events.append(CalendarEvent(rel.logical_key, at, {
            "event": EVENT_NAME[rel.kind], "title": ev.summary[:300], "period": rel.period,
            "estimate": rel.estimate, "includes": INCLUDES[rel.kind],
            "time_confirmed": confirmed, "all_day": not confirmed,
            "release_local": local.strftime("%H:%M") if confirmed else None,
            "release_date_local": local.date().isoformat(),
            "tz": "America/New_York", "status": "SCHEDULED", "flags": sorted(flags)}))
    # Giờ trong file JSON mà lịch ICS không có → vẫn ghi (thêm sự kiện = hướng chặn nhiều hơn),
    # cả ngày + cờ lệch nguồn. Ngày đó đã có sự kiện ICS cùng loại (đã gắn cờ, cả ngày) → bỏ qua.
    for kind, times in dates.items():
        for t in sorted(times - matched[kind]):
            local = t.astimezone(ET)
            if t < cutoff or local.date() in ics_days[kind]:
                continue
            events.append(CalendarEvent(
                f"{kind}:UNMATCHED:{local.date().isoformat()}",
                datetime.combine(local.date(), time(0, 0), tzinfo=ET).astimezone(UTC), {
                    "event": EVENT_NAME[kind], "title": None, "period": None, "estimate": None,
                    "includes": INCLUDES[kind], "time_confirmed": False, "all_day": True,
                    "release_local": None, "release_date_local": local.date().isoformat(),
                    "tz": "America/New_York", "status": "SCHEDULED",
                    "flags": ["CALENDAR_SOURCES_DISAGREE"]}))
    keys = [e.logical_key for e in events]
    if len(keys) != len(set(keys)):
        raise BeaParseError("hai sự kiện trùng khóa")
    for kind, name in EVENT_NAME.items():
        if not any(e.payload["event"] == name and e.event_time > now and e.payload["period"]
                   for e in events):
            raise BeaParseError(f"không còn lần công bố {kind} nào trong tương lai")
    return sorted(events, key=lambda e: (e.event_time, e.logical_key))


# ---------------------------------------------------------------- 2. Số actual (API NIPA)

@dataclass(frozen=True)
class SeriesSpec:
    code: str
    table: str
    line: str
    frequency: str        # Q | M
    release: str          # GDP | PIO
    label: str


# SeriesCode + dòng theo "SeriesRegister" chính thức của BEA (kiểm 2026-11-13).
SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec("A191RL", "T10101", "1", "Q", "GDP",
               "GDP thực, % thay đổi so với quý trước (năm hóa, đã điều chỉnh mùa vụ)"),
    SeriesSpec("DPCERGM", "T20807", "1", "M", "PIO", "Chỉ số giá PCE, % thay đổi so tháng trước"),
    SeriesSpec("DPCCRGM", "T20807", "25", "M", "PIO",
               "Chỉ số giá PCE lõi (trừ thực phẩm, năng lượng), % so tháng trước"),
    SeriesSpec("DPCERG", "T20804", "1", "M", "PIO", "Chỉ số giá PCE (mức, 2017=100)"),
    SeriesSpec("DPCCRG", "T20804", "25", "M", "PIO", "Chỉ số giá PCE lõi (mức, 2017=100)"),
)
TABLES: dict[str, str] = {s.table: s.frequency for s in SERIES}

_NA_VALUES = frozenset({"(NA)", "NA", "---", "--", "(D)", "(X)", "n.a.", "…", "..."})
_NUM = re.compile(r"^-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$")


@dataclass(frozen=True)
class Observation:
    series: str
    period: str            # "2026Q3" | "2026-09"
    period_end: datetime   # đầu kỳ kế tiếp (00:00 ET) → UTC
    value: str | None      # số thập phân dạng chuỗi (giữ đúng chữ số BEA công bố); None = không có
    row: dict = field(hash=False)


def _period(freq: str, raw: str) -> tuple[str, datetime]:
    if freq == "Q":
        m = re.match(r"^(\d{4})Q([1-4])$", raw)
        if not m:
            raise BeaParseError(f"kỳ quý lạ: {raw!r}")
        y, q = int(m.group(1)), int(m.group(2))
        nxt = date(y + (q == 4), 1 if q == 4 else 3 * q + 1, 1)
        label = f"{y}Q{q}"
    else:
        m = re.match(r"^(\d{4})M(\d{1,2})$", raw)
        if not m or not 1 <= int(m.group(2)) <= 12:
            raise BeaParseError(f"kỳ tháng lạ: {raw!r}")
        y, mo = int(m.group(1)), int(m.group(2))
        nxt = date(y + (mo == 12), 1 if mo == 12 else mo + 1, 1)
        label = f"{y}-{mo:02d}"
    return label, datetime.combine(nxt, time(0, 0), tzinfo=ET).astimezone(UTC)


def parse_value(raw: object) -> str | None:
    """Chuỗi DataValue của BEA → số dạng chuỗi chuẩn, hoặc None nếu BEA ghi "không có"."""
    if not isinstance(raw, str):
        raise BeaParseError("DataValue không phải chuỗi")
    s = raw.strip()
    if s in _NA_VALUES:
        return None
    if not _NUM.match(s):
        raise BeaParseError(f"DataValue lạ: {s[:20]!r}")
    try:
        d = Decimal(s.replace(",", ""))
    except InvalidOperation as e:  # pragma: no cover - regex đã chặn
        raise BeaParseError("DataValue lạ") from e
    return format(d, "f")


def api_error_code(body: object) -> str | None:
    """Lỗi BEA trả trong thân JSON (thường kèm HTTP 200) → mã ngắn; không đọc mô tả lỗi."""
    if not isinstance(body, dict):
        return None
    api = body.get("BEAAPI")
    if not isinstance(api, dict):
        return None
    res = api.get("Results")
    err = None
    for holder in (api, res if isinstance(res, dict) else None):
        if isinstance(holder, dict) and isinstance(holder.get("Error"), dict):
            err = holder["Error"]
    if err is None:
        return None
    code = str(err.get("APIErrorCode", "")).strip()
    if code == "1":
        return "AUTH_FAILED"  # "Invalid API UserId"
    if code == "7":
        return "RATE_LIMITED"
    return f"BEA_API_ERROR_{code}" if re.fullmatch(r"\d{1,6}", code) else "BEA_API_ERROR"


def parse_table(table: str, body: object) -> list[Observation]:
    """Các quan sát của những series cấu hình trong ``SERIES`` từ một phản hồi GetData."""
    freq = TABLES[table]
    api = body.get("BEAAPI") if isinstance(body, dict) else None
    res = api.get("Results") if isinstance(api, dict) else None
    if isinstance(res, list) and len(res) == 1:
        res = res[0]
    data = res.get("Data") if isinstance(res, dict) else None
    if not isinstance(data, list):
        raise BeaParseError(f"{table}: phản hồi không có Data")
    wanted = {s.code: s for s in SERIES if s.table == table}
    seen: dict[tuple[str, str], Observation] = {}
    for row in data:
        if not isinstance(row, dict):
            raise BeaParseError(f"{table}: dòng dữ liệu sai cấu trúc")
        code = row.get("SeriesCode")
        if code not in wanted:
            continue
        spec = wanted[code]
        if str(row.get("TableName", table)) != table:
            raise BeaParseError(f"{table}: dòng của bảng khác")
        if str(row.get("LineNumber", "")).strip() != spec.line:
            # Bảng bị sắp xếp lại → không chắc đúng series nữa.
            raise BeaParseError(f"{table}: {code} không còn ở dòng {spec.line}")
        period, end = _period(freq, str(row.get("TimePeriod", "")))
        value = parse_value(row.get("DataValue"))
        keep = {k: row.get(k) for k in ("TableName", "SeriesCode", "LineNumber",
                                         "LineDescription", "TimePeriod", "METRIC_NAME",
                                         "CL_UNIT", "UNIT_MULT", "DataValue", "NoteRef")
                if k in row}
        obs = Observation(code, period, end, value, keep)
        prev = seen.get((code, period))
        if prev is not None and prev.value != value:
            raise BeaParseError(f"{table}: {code} {period} có hai giá trị khác nhau")
        seen[(code, period)] = obs
    for code in wanted:
        if not any(k[0] == code for k in seen):
            raise BeaParseError(f"{table}: thiếu series {code}")
    return sorted(seen.values(), key=lambda o: (o.series, o.period))


# ---------------------------------------------------------------- 3. Tải (HTTP)

def http_getter(client, timeout: float = 30.0):
    """``get(url, params=None) -> str`` qua ``httpx.Client``: chỉ ``ALLOWED_HOSTS``, giới hạn cỡ,
    lỗi → ``FetchError`` với mã ngắn. Khóa đi trong ``params`` — không bao giờ ghép vào chuỗi để
    log hay báo lỗi."""
    import httpx

    from gold_trading.ingestion.api_keys import error_code_for_exception, error_code_for_http

    def get(url: str, params: dict | None = None) -> str:
        if not any(url.startswith(f"https://{h}/") for h in ALLOWED_HOSTS):
            raise FetchError("BAD_URL")
        try:
            r = client.get(url, params=params, timeout=timeout, follow_redirects=True)
        except httpx.HTTPError as e:
            raise FetchError(error_code_for_exception(e)) from None
        if r.url.scheme != "https" or r.url.host not in ALLOWED_HOSTS:
            raise FetchError("UNEXPECTED_REDIRECT")
        if r.status_code != 200:
            raise FetchError(error_code_for_http(r.status_code))
        if len(r.content) > MAX_BYTES:
            raise FetchError("RESPONSE_TOO_LARGE")
        return r.text

    return get


# ---------------------------------------------------------------- 4. Chạy một lần

SCHEDULE_FETCH_TTL = timedelta(hours=26)   # tải lịch mỗi ngày
VALUES_FETCH_TTL = timedelta(days=8)       # đối chiếu số ít nhất mỗi tuần (ngoài giờ công bố)
# Số mới nhất (PCE tháng) bình thường cũ nhất ~55 ngày tính từ cuối kỳ (vd. số tháng 10 công bố
# 25/11, số tháng 11 công bố 23/12). Quá 62 ngày → BEA trễ lịch → STALE.
VALUES_DATA_TTL = timedelta(days=62)
RELEASE_MATCH_WINDOW = timedelta(days=3)


def schedule_spec():
    from gold_trading.ingestion.source_status import SourceSpec
    return SourceSpec(SCHEDULE_SOURCE, "calendar", fetch_ttl=SCHEDULE_FETCH_TTL,
                      provider=PROVIDER)


def values_spec():
    from gold_trading.ingestion.source_status import SourceSpec
    return SourceSpec(VALUES_SOURCE, "macro", fetch_ttl=VALUES_FETCH_TTL,
                      data_ttl=VALUES_DATA_TTL, provider=PROVIDER)


def _enabled(registry, name: str):
    from gold_trading.ingestion.source_status import SourceRegistry
    registry = registry if registry is not None else SourceRegistry(
        [schedule_spec(), values_spec()])
    spec = registry.get(name)
    if spec is None or not spec.enabled:
        raise ValueError(f"nguồn {name} chưa được bật")


def run_schedule_once(*, store, log, get, now: datetime, registry=None):
    """Tải lịch BEA (ICS + JSON) → ghi sự kiện theo revision + nhật ký lần kiểm (ING-30)."""
    from gold_trading.ingestion.calendar_sync import EventIn, sync_calendar
    from gold_trading.ingestion.source_status import CheckOutcome, SourceCheck

    _enabled(registry, SCHEDULE_SOURCE)
    try:
        ics = parse_ics(get(ICS_URL))
        dates = parse_release_dates(get(DATES_URL))
        events = build_schedule(ics, dates, now)
    except FetchError as e:
        check = SourceCheck(SCHEDULE_SOURCE, now, CheckOutcome.ERROR, e.code)
    except BeaParseError:
        check = SourceCheck(SCHEDULE_SOURCE, now, CheckOutcome.INVALID, "PARSE_ERROR")
    else:
        res = sync_calendar(store, source=SCHEDULE_SOURCE,
                            payload_version=SCHEDULE_PAYLOAD_VERSION,
                            raw_ref=f"{ICS_URL}@{now.isoformat()}",
                            events=[EventIn(e.logical_key, e.event_time, e.payload)
                                    for e in events], now=now)
        if res.error_code:
            check = SourceCheck(SCHEDULE_SOURCE, now, CheckOutcome.INVALID, res.error_code)
        else:
            check = SourceCheck.from_counts(SCHEDULE_SOURCE, now, res.counts)
    log.record(check)
    return check


def release_for(store, release: str, now: datetime):
    """Lần công bố (lịch BEA đã biết tại ``now``) gần nhất đã tới giờ, trong 3 ngày qua."""
    name = EVENT_NAME[release]
    cands = [r for r in store.as_of(now, source=SCHEDULE_SOURCE, kind="calendar",
                                    event_from=now - RELEASE_MATCH_WINDOW)
             if r.payload.get("event") == name and r.payload.get("status") == "SCHEDULED"
             and r.event_time <= now]
    return max(cands, key=lambda r: r.event_time, default=None)


def fetch_values(get, key, now: datetime) -> list[Observation]:
    """Gọi API NIPA cho mỗi bảng (năm nay + năm trước theo giờ ET)."""
    y = now.astimezone(ET).year
    out: list[Observation] = []
    for table, freq in TABLES.items():
        text = get(API_URL, {"UserID": key.reveal(), "method": "GetData",
                             "DataSetName": "NIPA", "TableName": table, "Frequency": freq,
                             "Year": f"{y - 1},{y}", "ResultFormat": "JSON"})
        try:
            body = json.loads(text)
        except ValueError as e:
            raise BeaParseError(f"{table}: phản hồi không phải JSON") from e
        if code := api_error_code(body):
            raise FetchError(code)
        out.extend(parse_table(table, body))
    return out


def sync_values(store, observations: list[Observation], now: datetime):
    """Ghi số actual: mới → revision 0; BEA sửa số (hoặc đổi có/không có số) → revision mới.

    Gắn lần công bố: nếu lịch BEA có lần công bố cùng loại đã tới giờ trong 3 ngày qua →
    ``release_ref`` + ``available_at`` = giờ công bố + ``latency_seconds`` (ING-17: đo độ trễ).
    Không có → cờ ``UNSCHEDULED_CHANGE`` (lần nạp đầu: ``INITIAL_LOAD``)."""
    from gold_trading.common.enums import SourceStatus
    from gold_trading.contracts.records import NormalizedRecord
    from gold_trading.ingestion.point_in_time import AppendCounts

    known = {r.logical_key: r for r in store.as_of(now, source=VALUES_SOURCE, kind="macro")}
    initial = not known
    spec_by = {s.code: s for s in SERIES}
    rel_cache: dict[str, object] = {}
    counts, unchanged, revised = AppendCounts(), 0, 0
    for o in observations:
        key = f"{o.series}:{o.period}"
        prev = known.get(key)
        if prev is not None and prev.payload.get("value") == o.value:
            unchanged += 1
            continue
        spec = spec_by[o.series]
        if spec.release not in rel_cache:
            rel_cache[spec.release] = release_for(store, spec.release, now)
        rel = rel_cache[spec.release]
        flags: list[str] = []
        if rel is None:
            flags.append("INITIAL_LOAD" if initial else "UNSCHEDULED_CHANGE")
        if o.value is None:
            flags.append("VALUE_NOT_AVAILABLE")
        rev = 0 if prev is None else max(
            r.revision for r in store.history(VALUES_SOURCE, key, now)) + 1
        payload = {
            "series": o.series, "table": spec.table, "line": spec.line,
            "frequency": spec.frequency, "label": spec.label, "period": o.period,
            "value": o.value,
            "value_status": "AVAILABLE" if o.value is not None else "NOT_AVAILABLE",
            "unit": o.row.get("CL_UNIT"), "unit_mult": o.row.get("UNIT_MULT"),
            "metric": o.row.get("METRIC_NAME"),
            "release_ref": rel.logical_key if rel is not None else None,
            "latency_seconds": (int((now - rel.event_time).total_seconds())
                                if rel is not None else None),
            "flags": sorted(flags),
        }
        rec = NormalizedRecord(
            record_id=f"{VALUES_SOURCE}:{key}:r{rev}", source=VALUES_SOURCE, kind="macro",
            logical_key=key, revision=rev, event_time=o.period_end, ingested_at=now,
            available_at=max(rel.event_time, o.period_end) if rel is not None else None,
            source_status=SourceStatus.HEALTHY, payload_version=VALUES_PAYLOAD_VERSION,
            raw_ref=f"bea:NIPA:{spec.table}@{now.isoformat()}",
            quality_flags=frozenset(flags), payload=payload)
        counts.add(store.append(rec, o.row))
        if prev is not None:
            revised += 1
    return counts, unchanged, revised


def run_values_once(*, store, log, get, key_lookup, now: datetime, registry=None):
    """Một lần lấy số actual (cần khóa). Thiếu / sai khóa → ghi lỗi, **không** gọi BEA."""
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
        except BeaParseError:
            check = SourceCheck(VALUES_SOURCE, now, CheckOutcome.INVALID, "PARSE_ERROR")
        else:
            counts, _, _ = sync_values(store, obs, now)
            check = SourceCheck.from_counts(VALUES_SOURCE, now, counts)
    log.record(check)
    return check


def values_due(now: datetime, store, last_ok_at: datetime | None,
               poll_window: timedelta = timedelta(minutes=90)) -> str | None:
    """Có nên gọi API số liệu lúc ``now`` không (BEA không khuyến khích gọi khi chưa có số mới).

    - ``RELEASE_WINDOW``: trong 90 phút sau giờ công bố GDP / PIO đã xác nhận trên lịch.
    - ``RECONCILE``: chưa có lần OK nào, hoặc lần OK cuối cũ hơn 7 ngày (bắt sửa số ngoài lịch).
    - None: không cần gọi."""
    for name in EVENT_NAME.values():
        for r in store.as_of(now, source=SCHEDULE_SOURCE, kind="calendar",
                             event_from=now - poll_window):
            if (r.payload.get("event") == name and r.payload.get("status") == "SCHEDULED"
                    and r.payload.get("time_confirmed") and r.event_time <= now):
                return "RELEASE_WINDOW"
    if last_ok_at is None or now - last_ok_at > timedelta(days=7):
        return "RECONCILE"
    return None
