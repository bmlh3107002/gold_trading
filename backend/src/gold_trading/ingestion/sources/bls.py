"""BLS — lịch + số actual CPI, việc làm (NFP), PPI (GĐ1 bước 8e; ING-09, ING-17, ING-19).

Thiết kế + lý do: ``docs/thiet-ke/24-bls.md``. Tóm tắt:

- **Lịch:** trang lịch BLS chặn chương trình tự động (403 với máy chủ lẫn ``curl`` trên máy người
  dùng; trình duyệt xem được) → **chép tay** bảng lịch chính thức (người dùng chép từ trình duyệt
  2026-11-13) thành bảng có phiên bản ``SCHEDULE_VERSION``. Không giả trình duyệt để lách.
  Bảng sắp hết (lần công bố cuối < 45 ngày nữa) → lần kiểm lịch ``INVALID``
  (``SCHEDULE_TABLE_EXPIRING``) → nguồn lịch "Hỏng" trên trang Nguồn dữ liệu → bảng lịch hợp nhất
  không tin giờ (chặn cả ngày) — hướng an toàn, buộc chép bảng mới.
- **Số:** API v2 ``api.bls.gov`` (POST JSON, khóa ``GT_BLS_API_KEY`` trong thân yêu cầu — không
  bao giờ trong URL / log). Mỗi (series, tháng) là một dữ kiện; BLS sửa số / bỏ chữ "sơ bộ" →
  revision mới. Số mới trong 3 ngày sau một lần công bố cùng loại trên lịch → gắn ``release_ref``
  + ``available_at`` = giờ công bố (ING-17 đo độ trễ).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PROVIDER = "bls"
SCHEDULE_SOURCE = "bls_schedule"
VALUES_SOURCE = "bls_values"
API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
ALLOWED_HOSTS = frozenset({"api.bls.gov"})
SCHEDULE_PAYLOAD_VERSION = "bls-schedule-1"
VALUES_PAYLOAD_VERSION = "bls-values-1"
MAX_BYTES = 5 * 1024 * 1024

# ---------------------------------------------------------------- 1. Lịch (chép tay, có phiên bản)

SCHEDULE_VERSION = "bls-schedule-2026.11.13"
SCHEDULE_SOURCE_NOTE = ("Chép tay từ www.bls.gov/schedule/news_release/{cpi,empsit,ppi}.htm "
                        "(người dùng mở bằng trình duyệt, 2026-11-13)")
RELEASE_TIME = time(8, 30)            # mọi dòng trong 3 bảng đều "08:30 AM" (giờ New York)
EXPIRY_WARNING = timedelta(days=45)    # bảng còn ít hơn chừng này → báo để chép bảng mới
EVENT_NAME = {"CPI": "BLS_CPI", "EMPSIT": "BLS_EMPSIT", "PPI": "BLS_PPI"}
TITLES = {"CPI": "Consumer Price Index", "EMPSIT": "The Employment Situation",
          "PPI": "Producer Price Index"}
INCLUDES = {"CPI": ["CPI", "CORE_CPI"],
            "EMPSIT": ["NONFARM_PAYROLLS", "UNEMPLOYMENT_RATE", "AVG_HOURLY_EARNINGS"],
            "PPI": ["PPI_FINAL_DEMAND"]}

# (tháng số liệu, ngày công bố) — nguyên văn 3 bảng "Schedule of Releases for …" (giờ 08:30 AM).
_TABLE: dict[str, tuple[tuple[str, str], ...]] = {
    "CPI": (
        ("2026-10", "2026-11-10"), ("2026-11", "2026-12-10"), ("2026-12", "2027-01-13"),
        ("2027-01", "2027-02-11"), ("2027-02", "2027-03-10"), ("2027-03", "2027-04-13"),
        ("2027-04", "2027-05-12"), ("2027-05", "2027-06-10"), ("2027-06", "2027-07-14"),
        ("2027-07", "2027-08-11"), ("2027-08", "2027-09-14"), ("2027-09", "2027-10-14"),
        ("2027-10", "2027-11-10"), ("2027-11", "2027-12-10")),
    "EMPSIT": (
        ("2026-10", "2026-11-06"), ("2026-11", "2026-12-04"), ("2026-12", "2027-01-08"),
        ("2027-01", "2027-02-05"), ("2027-02", "2027-03-05"), ("2027-03", "2027-04-02"),
        ("2027-04", "2027-05-07"), ("2027-05", "2027-06-04"), ("2027-06", "2027-07-02"),
        ("2027-07", "2027-08-06"), ("2027-08", "2027-09-03"), ("2027-09", "2027-10-08"),
        ("2027-10", "2027-11-05"), ("2027-11", "2027-12-03")),
    "PPI": (
        ("2026-10", "2026-11-13"), ("2026-11", "2026-12-15"), ("2026-12", "2027-01-14"),
        ("2027-01", "2027-02-12"), ("2027-02", "2027-03-12"), ("2027-03", "2027-04-14"),
        ("2027-04", "2027-05-13"), ("2027-05", "2027-06-11"), ("2027-06", "2027-07-15"),
        ("2027-07", "2027-08-10"), ("2027-08", "2027-09-10"), ("2027-09", "2027-10-15"),
        ("2027-10", "2027-11-12"), ("2027-11", "2027-12-15")),
}


class BlsParseError(ValueError):
    pass


class ScheduleExpiring(ValueError):
    pass


class FetchError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CalendarEvent:
    logical_key: str
    event_time: datetime
    payload: dict


def release_at(d: date) -> datetime:
    """08:30 giờ New York của ngày ``d`` → UTC (13:30 mùa đông, 12:30 mùa hè)."""
    return datetime.combine(d, RELEASE_TIME, tzinfo=ET).astimezone(UTC)


def schedule_table() -> list[tuple[str, str, date]]:
    """``(loại, tháng số liệu, ngày công bố)`` đã kiểm: tháng liên tiếp, ngày tăng dần, ngày
    công bố sau tháng số liệu, ngày làm việc (thứ Hai–Sáu)."""
    out = []
    for kind, rows in _TABLE.items():
        prev_p = prev_d = None
        for period, day in rows:
            y, m = map(int, period.split("-"))
            d = date.fromisoformat(day)
            if prev_p is not None:
                py, pm = prev_p
                if (y, m) != ((py + (pm == 12)), pm % 12 + 1):
                    raise BlsParseError(f"{kind}: tháng số liệu không liên tiếp ở {period}")
                if d <= prev_d:
                    raise BlsParseError(f"{kind}: ngày công bố không tăng ở {day}")
            if d <= date(y, m, 28) or d.weekday() > 4:
                raise BlsParseError(f"{kind}: ngày công bố lạ {day}")
            prev_p, prev_d = (y, m), d
            out.append((kind, period, d))
    return out


def build_schedule(now: datetime, keep_after: timedelta = timedelta(days=7)
                   ) -> list[CalendarEvent]:
    """Sự kiện từ ``now - keep_after`` trở đi. Bảng sắp hết → ``ScheduleExpiring``."""
    cutoff = now - keep_after
    events: list[CalendarEvent] = []
    last: dict[str, datetime] = {}
    for kind, period, d in schedule_table():
        at = release_at(d)
        last[kind] = max(last.get(kind, at), at)
        if at < cutoff:
            continue
        events.append(CalendarEvent(f"{kind}:{period}", at, {
            "event": EVENT_NAME[kind], "title": f"{TITLES[kind]} — {period}",
            "period": period, "estimate": None, "includes": INCLUDES[kind],
            "time_confirmed": True, "all_day": False, "release_local": "08:30",
            "release_date_local": d.isoformat(), "tz": "America/New_York",
            "status": "SCHEDULED", "basis": "OFFICIAL_TABLE_COPIED",
            "schedule_version": SCHEDULE_VERSION, "flags": []}))
    for kind, t in last.items():
        if t - now < EXPIRY_WARNING:
            raise ScheduleExpiring(f"bảng lịch {kind} hết vào {t.date()}")
    return sorted(events, key=lambda e: (e.event_time, e.logical_key))


# ---------------------------------------------------------------- 2. Số actual (API v2)

@dataclass(frozen=True)
class SeriesSpec:
    code: str
    release: str     # CPI | EMPSIT | PPI
    label: str
    unit: str


SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec("CUSR0000SA0", "CPI", "CPI-U toàn bộ, đã điều chỉnh mùa vụ", "INDEX_1982_84"),
    SeriesSpec("CUSR0000SA0L1E", "CPI", "CPI-U lõi (trừ thực phẩm, năng lượng), đã điều chỉnh "
               "mùa vụ", "INDEX_1982_84"),
    SeriesSpec("CUUR0000SA0", "CPI", "CPI-U toàn bộ, chưa điều chỉnh mùa vụ", "INDEX_1982_84"),
    SeriesSpec("CES0000000001", "EMPSIT", "Việc làm phi nông nghiệp (NFP), đã điều chỉnh mùa vụ",
               "THOUSANDS_OF_PERSONS"),
    SeriesSpec("LNS14000000", "EMPSIT", "Tỷ lệ thất nghiệp, đã điều chỉnh mùa vụ", "PERCENT"),
    SeriesSpec("CES0500000003", "EMPSIT", "Lương giờ trung bình khu vực tư nhân, đã điều chỉnh "
               "mùa vụ", "USD_PER_HOUR"),
    SeriesSpec("WPSFD4", "PPI", "PPI nhu cầu cuối cùng, đã điều chỉnh mùa vụ", "INDEX_2009_11"),
)
SPEC_BY = {s.code: s for s in SERIES}
# Khoảng giá trị hợp lý (bắt đổi đơn vị / số hỏng → cả lần tải INVALID, không ghi).
RANGES = {"INDEX_1982_84": (Decimal(100), Decimal(1000)),
          "INDEX_2009_11": (Decimal(50), Decimal(500)),
          "THOUSANDS_OF_PERSONS": (Decimal(100000), Decimal(250000)),
          "PERCENT": (Decimal(0), Decimal(30)),
          "USD_PER_HOUR": (Decimal(10), Decimal(100))}
_NUM = re.compile(r"^-?\d+(\.\d+)?$")
_NA = frozenset({"-", "(NA)", "NA", ""})


@dataclass(frozen=True)
class Observation:
    series: str
    period: str              # YYYY-MM
    period_end: datetime     # 0:00 ET ngày đầu tháng sau (UTC)
    value: str | None        # chuỗi thập phân nguyên văn; None = BLS ghi không có số
    footnotes: tuple[str, ...]
    raw: dict


def api_error_code(body: dict) -> str | None:
    """Mã ngắn cho phản hồi từ chối của API (không bao giờ chép thông điệp — có thể lẫn khóa)."""
    status = body.get("status")
    if status == "REQUEST_SUCCEEDED":
        return None
    text = " ".join(str(m) for m in body.get("message") or []).lower()
    if "key" in text and ("invalid" in text or "not valid" in text or "expired" in text
                          or "inactive" in text):
        return "AUTH_FAILED"
    if "threshold" in text or "limit" in text:
        return "RATE_LIMITED"
    return "API_NOT_PROCESSED"


def _period_end(y: int, m: int) -> datetime:
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return datetime.combine(date(ny, nm, 1), time(0, 0), tzinfo=ET).astimezone(UTC)


def parse_response(text: str) -> list[Observation]:
    """Kiểm toàn bộ phản hồi; hỏng bất kỳ chỗ nào → ``BlsParseError`` (không ghi gì)."""
    try:
        body = json.loads(text)
    except ValueError as e:
        raise BlsParseError("phản hồi không phải JSON") from e
    if not isinstance(body, dict):
        raise BlsParseError("phản hồi không phải object")
    if code := api_error_code(body):
        raise FetchError(code)
    series = (body.get("Results") or {}).get("series")
    if not isinstance(series, list):
        raise BlsParseError("thiếu Results.series")
    seen: set[str] = set()
    out: list[Observation] = []
    for s in series:
        code = s.get("seriesID")
        spec = SPEC_BY.get(code)
        if spec is None:
            raise BlsParseError(f"series lạ {code!r}")
        if code in seen:
            raise BlsParseError(f"series trùng {code}")
        seen.add(code)
        lo, hi = RANGES[spec.unit]
        periods: set[str] = set()
        for d in s.get("data") or []:
            per = d.get("period", "")
            if per == "M13":
                continue    # trung bình năm — không dùng
            m = re.fullmatch(r"M(0[1-9]|1[0-2])", per)
            y = str(d.get("year", ""))
            if not m or not re.fullmatch(r"\d{4}", y):
                raise BlsParseError(f"{code}: kỳ lạ {y}/{per}")
            period = f"{y}-{m.group(1)}"
            if period in periods:
                raise BlsParseError(f"{code}: kỳ trùng {period}")
            periods.add(period)
            raw_v = str(d.get("value", "")).strip()
            if raw_v in _NA:
                value = None
            elif _NUM.match(raw_v):
                try:
                    dv = Decimal(raw_v)
                except InvalidOperation as e:
                    raise BlsParseError(f"{code} {period}: số lạ") from e
                if not lo <= dv <= hi:
                    raise BlsParseError(f"{code} {period}: {raw_v} ngoài khoảng (đổi đơn vị?)")
                value = raw_v
            else:
                raise BlsParseError(f"{code} {period}: giá trị lạ")
            codes = tuple(sorted({str(f.get("code")) for f in d.get("footnotes") or []
                                  if isinstance(f, dict) and f.get("code")}))
            out.append(Observation(code, period, _period_end(int(y), int(m.group(1))), value,
                                   codes, {k: d.get(k) for k in ("year", "period", "value")}
                                   | {"footnote_codes": list(codes)}))
    missing = set(SPEC_BY) - seen
    if missing:
        raise BlsParseError(f"thiếu series {sorted(missing)}")
    return out


def http_poster(client, timeout: float = 30.0):
    """``post(body: dict) -> str``: chỉ ``api.bls.gov``, không đi theo chuyển hướng, giới hạn cỡ,
    lỗi → ``FetchError`` mã ngắn. Khóa đi trong thân JSON — không bao giờ trong URL / log."""
    import httpx

    from gold_trading.ingestion.api_keys import error_code_for_exception, error_code_for_http

    def post(body: dict) -> str:
        try:
            r = client.post(API_URL, json=body, timeout=timeout, follow_redirects=False)
        except httpx.HTTPError as e:
            raise FetchError(error_code_for_exception(e)) from None
        if r.url.scheme != "https" or r.url.host not in ALLOWED_HOSTS:
            raise FetchError("UNEXPECTED_REDIRECT")
        if r.status_code != 200:
            raise FetchError(error_code_for_http(r.status_code))
        if len(r.content) > MAX_BYTES:
            raise FetchError("RESPONSE_TOO_LARGE")
        return r.text

    return post


def fetch_values(post, key, now: datetime) -> list[Observation]:
    y = now.astimezone(ET).year
    return parse_response(post({"seriesid": [s.code for s in SERIES],
                                "startyear": str(y - 1), "endyear": str(y),
                                "registrationkey": key.reveal()}))


# ---------------------------------------------------------------- 3. Ghi + chạy

SCHEDULE_FETCH_TTL = timedelta(hours=26)
VALUES_FETCH_TTL = timedelta(days=8)
# Số mới nhất bình thường cũ nhất ~41 ngày tính từ cuối kỳ (vd. CPI tháng 10: cuối kỳ 1/11, số
# tháng 11 công bố 10/12 → cuối kỳ 1/12; giữa hai lần ~40 ngày). Quá 45 ngày → BLS trễ (chính phủ
# đóng cửa) → STALE.
VALUES_DATA_TTL = timedelta(days=45)
RELEASE_MATCH_WINDOW = timedelta(days=3)
POLL_WINDOW = timedelta(minutes=90)


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
    """Ghi lịch từ bảng chép tay theo revision. Không gọi mạng."""
    from gold_trading.ingestion.calendar_sync import EventIn, sync_calendar
    from gold_trading.ingestion.source_status import CheckOutcome, SourceCheck

    _enabled(registry, SCHEDULE_SOURCE)
    try:
        events = build_schedule(now)
    except ScheduleExpiring:
        check = SourceCheck(SCHEDULE_SOURCE, now, CheckOutcome.INVALID, "SCHEDULE_TABLE_EXPIRING")
    except BlsParseError:
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


def release_for(store, release: str, now: datetime):
    """Lần công bố (lịch BLS đã biết tại ``now``) gần nhất đã tới giờ, trong 3 ngày qua."""
    name = EVENT_NAME[release]
    cands = [r for r in store.as_of(now, source=SCHEDULE_SOURCE, kind="calendar",
                                    event_from=now - RELEASE_MATCH_WINDOW)
             if r.payload.get("event") == name and r.payload.get("status") == "SCHEDULED"
             and r.event_time <= now]
    return max(cands, key=lambda r: r.event_time, default=None)


def _content(p: dict) -> tuple:
    return (p.get("value"), tuple(p.get("footnote_codes") or ()))


def sync_values(store, observations: list[Observation], now: datetime):
    """Ghi số: mới → revision 0; đổi số / đổi chú thích (vd. bỏ "P" sơ bộ) → revision mới."""
    from gold_trading.common.enums import SourceStatus
    from gold_trading.contracts.records import NormalizedRecord
    from gold_trading.ingestion.point_in_time import AppendCounts

    known = {r.logical_key: r for r in store.as_of(now, source=VALUES_SOURCE, kind="macro")}
    initial = not known
    rel_cache: dict[str, object] = {}
    counts = AppendCounts()
    for o in observations:
        key = f"{o.series}:{o.period}"
        prev = known.get(key)
        if prev is not None and _content(prev.payload) == (o.value, o.footnotes):
            continue
        spec = SPEC_BY[o.series]
        if spec.release not in rel_cache:
            rel_cache[spec.release] = release_for(store, spec.release, now)
        rel = rel_cache[spec.release]
        flags: list[str] = []
        if rel is None:
            flags.append("INITIAL_LOAD" if initial else "UNSCHEDULED_CHANGE")
        if o.value is None:
            flags.append("VALUE_NOT_AVAILABLE")
        if "P" in o.footnotes:
            flags.append("PRELIMINARY")
        rev = 0 if prev is None else max(
            r.revision for r in store.history(VALUES_SOURCE, key, now)) + 1
        payload = {
            "series": o.series, "release": spec.release, "label": spec.label,
            "unit": spec.unit, "period": o.period, "value": o.value,
            "value_status": "AVAILABLE" if o.value is not None else "NOT_AVAILABLE",
            "footnote_codes": list(o.footnotes),
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
            raw_ref=f"bls:api:v2:{o.series}@{now.isoformat()}",
            quality_flags=frozenset(flags), payload=payload)
        counts.add(store.append(rec, o.raw))
    return counts


def run_values_once(*, store, log, post, key_lookup, now: datetime, registry=None):
    """Một lần lấy số (cần khóa). Thiếu / sai khóa → ghi lỗi, **không** gọi BLS."""
    from gold_trading.ingestion.source_status import CheckOutcome, SourceCheck

    _enabled(registry, VALUES_SOURCE)
    if not key_lookup.ok:
        check = SourceCheck(VALUES_SOURCE, now, CheckOutcome.ERROR,
                            key_lookup.error_code or "KEY_MISSING")
    else:
        try:
            obs = fetch_values(post, key_lookup.key, now)
            if any(o.period_end > now for o in obs):
                raise BlsParseError("số của tháng chưa kết thúc")
        except FetchError as e:
            check = SourceCheck(VALUES_SOURCE, now, CheckOutcome.ERROR, e.code)
        except BlsParseError:
            check = SourceCheck(VALUES_SOURCE, now, CheckOutcome.INVALID, "PARSE_ERROR")
        else:
            check = SourceCheck.from_counts(VALUES_SOURCE, now, sync_values(store, obs, now))
    log.record(check)
    return check


def values_due(now: datetime, store, last_ok_at: datetime | None,
               poll_window: timedelta = POLL_WINDOW) -> str | None:
    """``RELEASE_WINDOW``: trong 90 phút sau giờ công bố CPI / NFP / PPI trên lịch mà chưa có số
    gắn lần công bố đó. ``RECONCILE``: chưa OK lần nào / lần OK cuối cũ hơn 7 ngày. None: thôi.
    Dựa trên dữ liệu đã lưu → khởi động lại không gọi dồn."""
    captured = None
    for r in store.as_of(now, source=SCHEDULE_SOURCE, kind="calendar",
                         event_from=now - poll_window):
        if r.payload.get("status") == "SCHEDULED" and r.event_time <= now:
            if captured is None:
                captured = {v.payload.get("release_ref") for v in store.as_of(
                    now, source=VALUES_SOURCE, kind="macro",
                    event_from=now - timedelta(days=400))}
            if r.logical_key not in captured:
                return "RELEASE_WINDOW"
    if last_ok_at is None or now - last_ok_at > timedelta(days=7):
        return "RECONCILE"
    return None
