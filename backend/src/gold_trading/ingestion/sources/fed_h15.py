"""Fed H.15 — lãi suất hằng ngày (GĐ1 bước 9b: ING-11, ING-25, ING-26; dữ liệu cho ING-27).

Thiết kế + lý do: ``docs/thiet-ke/18-h15-lai-suat.md``. Thay FRED (điều khoản FRED cấm lưu vào
database + cấm dùng cho AI → ``BLOCKED``, người dùng chọn H.15 ngày 2026-11-13).

Nguồn: trang phát hành **H.15 Selected Interest Rates (Daily)** của Hội đồng Thống đốc Fed
(``www.federalreserve.gov/releases/h15/``), không cần khóa, điều khoản ``fed`` ``VERIFIED``. Lợi
suất trái phiếu (danh nghĩa + TIPS) do **Bộ Tài chính Mỹ** tính, Fed đăng lại (chú thích 9, 10
của trang) → ghi nguồn cả hai. Không dùng "Data Download Program" (Fed gỡ 2027).

Series lấy (đơn vị: % năm, đúng 2 chữ số thập phân như trang):

==================  ===============================================================
``EFFR``            Federal funds (effective) — lãi suất Fed hiệu dụng
``UST_CMT_2Y``      Treasury constant maturities › Nominal › 2-year
``UST_CMT_10Y``     Treasury constant maturities › Nominal › 10-year
``UST_TIPS_10Y``    Treasury constant maturities › Inflation indexed › 10-year (lợi suất thực)
==================  ===============================================================

Quy tắc an toàn:

- Thời điểm "đã biết": trang chỉ ghi **ngày** phát hành, không ghi giờ → ``available_at`` để
  trống, hệ thống biết số từ lúc tải về (``known_at = ingested_at``) — không đoán giờ (1E-C01).
  ``event_time`` = hết ngày quan sát (0:00 New York hôm sau).
- Ô trống ở cột có dấu ``*`` (thị trường đóng) → bản ghi ``value = None``,
  ``MARKET_CLOSED``; ``n.a.`` → ``None``, ``NOT_AVAILABLE``; không nội suy (1E-C02). Ô trống ở
  cột thường → chưa công bố, không ghi.
- Thiếu dòng / nhóm bắt buộc (đổi tên, ngừng), cột ngày sai thứ tự, ngày sau ngày phát hành,
  số sai định dạng hoặc ngoài khoảng [-5, 25] % → ``INVALID`` cả lần tải, **không ghi gì**
  (1E-C03, 1E-C04).
- Giá trị đổi → revision mới (không viết lại quá khứ); bản phát hành cũ hơn số đã có không viết
  lại gì.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PROVIDER = "fed"
SOURCE = "fed_h15"
URL = "https://www.federalreserve.gov/releases/h15/"
ALLOWED_HOST = "www.federalreserve.gov"
PAYLOAD_VERSION = "fed-h15-1"
MAX_BYTES = 5 * 1024 * 1024
VALUE_MIN, VALUE_MAX = Decimal("-5"), Decimal("25")

MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
LONG_MONTHS = {m: i for i, m in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August", "September",
     "October", "November", "December"), 1)}

TREASURY = "U.S. Treasury qua Federal Reserve H.15"
BOARD = "Federal Reserve Board H.15"


@dataclass(frozen=True)
class SeriesSpec:
    code: str
    path: tuple[str, ...]     # đường dẫn nhóm (đã chuẩn hóa) tới dòng trong bảng
    label: str
    source_note: str


SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec("EFFR", ("federal funds (effective)",),
               "Lãi suất Fed hiệu dụng (EFFR), % năm", BOARD),
    SeriesSpec("UST_CMT_2Y", ("u.s. government securities", "treasury constant maturities",
                              "nominal", "2-year"),
               "Lợi suất trái phiếu Mỹ 2 năm (kỳ hạn cố định), % năm", TREASURY),
    SeriesSpec("UST_CMT_10Y", ("u.s. government securities", "treasury constant maturities",
                               "nominal", "10-year"),
               "Lợi suất trái phiếu Mỹ 10 năm (kỳ hạn cố định), % năm", TREASURY),
    SeriesSpec("UST_TIPS_10Y", ("u.s. government securities", "treasury constant maturities",
                                "inflation indexed", "10-year"),
               "Lợi suất thực 10 năm (TIPS kỳ hạn cố định), % năm", TREASURY),
)


class H15ParseError(ValueError):
    pass


class FetchError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------- 1. Đọc trang

@dataclass(frozen=True)
class Observation:
    series: str
    day: date
    value: str | None          # chuỗi đúng như trang ("4.73"), None nếu không có số
    status: str                # AVAILABLE / NOT_AVAILABLE / MARKET_CLOSED


@dataclass(frozen=True)
class Release:
    release_date: date
    observations: tuple[Observation, ...]


_RELEASE = re.compile(r'<div class="dates">\s*Release date:\s*([A-Z][a-z]+) (\d{1,2}), (\d{4})'
                      r'\s*</div>')
_TABLE = re.compile(r'(?s)<table id="h15table"[^>]*>(.*?)</table>')
_COLHEAD = re.compile(r'(?s)<th id="col(\d+)" class="colhead">(.*?)</th>')
_COLDATE = re.compile(r"^(\d{4})([A-Z][a-z]{2})(\d{1,2})(\*?)$")
_ROW = re.compile(r"(?s)<tr>(.*?)</tr>")
_STUB = re.compile(r'(?s)<th nowrap="nowrap" id="([A-Za-z0-9_]+)" headers="([A-Za-z0-9_ ]+)"'
                   r' class="stub(?: in\d)?">(.*?)</th>')
_CELL = re.compile(r'(?s)<td class="data"[^>]*>(.*?)</td>')
_NUM = re.compile(r"^-?\d{1,2}\.\d{2}$")


def _clean(fragment: str) -> str:
    s = re.sub(r'(?s)<a class="foot"[^>]*>.*?</a>', "", fragment)
    s = _html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _cell(fragment: str, closed: bool) -> tuple[str | None, str] | None:
    """(giá trị, trạng thái) hoặc None nếu ô trống ở ngày thường (chưa công bố)."""
    s = _clean(fragment)
    if s == "":
        return (None, "MARKET_CLOSED") if closed else None
    if s.lower() in {"n.a.", "na", "n.a"}:
        return None, "NOT_AVAILABLE"
    if not _NUM.match(s):
        raise H15ParseError(f"giá trị lạ: {s[:20]!r}")
    v = Decimal(s)
    if not VALUE_MIN <= v <= VALUE_MAX:
        raise H15ParseError(f"giá trị ngoài khoảng: {s}")  # nghi đổi đơn vị (1E-C04)
    return s, "AVAILABLE"


def parse_release(page: str) -> Release:
    m = _RELEASE.search(page)
    if not m or m.group(1) not in LONG_MONTHS:
        raise H15ParseError("không thấy ngày phát hành")
    try:
        rdate = date(int(m.group(3)), LONG_MONTHS[m.group(1)], int(m.group(2)))
    except ValueError as e:
        raise H15ParseError("ngày phát hành sai") from e
    t = _TABLE.search(page)
    if not t:
        raise H15ParseError("không thấy bảng h15table")
    body = t.group(1)
    cols: list[tuple[date, bool]] = []
    for n, (idx, raw) in enumerate(_COLHEAD.findall(body), 1):
        if int(idx) != n:
            raise H15ParseError("cột ngày sai thứ tự")
        cm = _COLDATE.match(_clean(raw).replace(" ", ""))
        if not cm or cm.group(2) not in MONTHS:
            raise H15ParseError(f"tiêu đề cột lạ: {_clean(raw)[:20]!r}")
        try:
            d = date(int(cm.group(1)), MONTHS[cm.group(2)], int(cm.group(3)))
        except ValueError as e:
            raise H15ParseError("ngày cột sai") from e
        cols.append((d, cm.group(4) == "*"))
    if not 1 <= len(cols) <= 10:
        raise H15ParseError(f"số cột ngày lạ: {len(cols)}")
    days = [d for d, _ in cols]
    if days != sorted(set(days)):
        raise H15ParseError("cột ngày trùng hoặc không tăng dần")
    if days[-1] >= rdate or days[0] < rdate - timedelta(days=21):
        raise H15ParseError("ngày dữ liệu không khớp ngày phát hành")
    want = {s.path: s for s in SERIES}
    found: dict[str, list] = {}
    labels: dict[str, str] = {}
    for row in _ROW.findall(body):
        st = _STUB.search(row)
        if not st:
            if "<th" in row and 'class="colhead"' not in row:
                raise H15ParseError("dòng tiêu đề lạ")
            continue
        rid, parents, label = st.group(1), st.group(2).split(), _clean(st.group(3)).lower()
        if rid in labels or not parents or parents[0] != "instruments":
            raise H15ParseError("định danh dòng lạ")
        if any(p not in labels for p in parents[1:]):
            raise H15ParseError("dòng cha chưa xuất hiện")
        labels[rid] = label
        spec = want.get(tuple(labels[p] for p in parents[1:]) + (label,))
        if spec is None:
            continue
        if spec.code in found:
            raise H15ParseError(f"dòng {spec.code} xuất hiện hai lần")
        cells = _CELL.findall(row)
        if len(cells) != len(cols):
            raise H15ParseError(f"dòng {spec.code}: số ô khác số cột")
        found[spec.code] = [(_cell(c, closed), d) for c, (d, closed) in zip(cells, cols,
                                                                          strict=True)]
    missing = [s.code for s in SERIES if s.code not in found]
    if missing:
        raise H15ParseError(f"thiếu dòng: {', '.join(missing)}")  # đổi tên / ngừng (1E-C03)
    obs = [Observation(code, d, c[0], c[1])
           for code, cells in found.items() for c, d in cells if c is not None]
    if not any(o.status == "AVAILABLE" for o in obs):
        raise H15ParseError("không có số nào")
    return Release(rdate, tuple(sorted(obs, key=lambda o: (o.series, o.day))))


# ---------------------------------------------------------------- 2. Tải

def http_getter(client, timeout: float = 30.0):
    """``get()`` → nội dung trang H.15. Chỉ ``www.federalreserve.gov``; lỗi → mã ngắn."""
    import httpx

    from gold_trading.ingestion.api_keys import error_code_for_exception, error_code_for_http

    def get() -> str:
        try:
            r = client.get(URL, timeout=timeout, follow_redirects=True)
        except httpx.HTTPError as e:
            raise FetchError(error_code_for_exception(e)) from None
        if r.url.host != ALLOWED_HOST:
            raise FetchError("UNEXPECTED_REDIRECT")
        if r.status_code != 200:
            raise FetchError(error_code_for_http(r.status_code))
        if len(r.content) > MAX_BYTES:
            raise FetchError("RESPONSE_TOO_LARGE")
        return r.text

    return get


# ---------------------------------------------------------------- 3. Ghi

FETCH_TTL = timedelta(hours=30)   # tải vài giờ một lần; quá 30 giờ không tải được → STALE
# Số mới nhất bình thường là ngày làm việc trước; nghỉ dài (lễ + cuối tuần) ~4 ngày + trễ 1 ngày
# phát hành → 7 ngày. Quá → Fed ngừng / đổi trang → STALE (1F-C02 cùng kiểu).
DATA_TTL = timedelta(days=7)


def spec():
    from gold_trading.ingestion.source_status import SourceSpec
    return SourceSpec(SOURCE, "macro", fetch_ttl=FETCH_TTL, data_ttl=DATA_TTL,
                      provider=PROVIDER)


def _event_time(d: date) -> datetime:
    return datetime.combine(d + timedelta(days=1), time(0, 0), tzinfo=ET).astimezone(UTC)


def sync(store, rel: Release, now: datetime):
    """Ghi số: mới → revision 0; giá trị / trạng thái đổi → revision mới; bỏ qua ngày chưa hết
    (``event_time > now``); bản phát hành cũ hơn bản đã ghi số đó → không viết lại."""
    from gold_trading.common.enums import SourceStatus
    from gold_trading.contracts.records import NormalizedRecord
    from gold_trading.ingestion.point_in_time import AppendCounts

    by = {s.code: s for s in SERIES}
    known = {r.logical_key: r for r in store.as_of(now, source=SOURCE, kind="macro")}
    counts = AppendCounts()
    for o in rel.observations:
        et = _event_time(o.day)
        if et > now:
            continue
        key = f"{o.series}:{o.day.isoformat()}"
        prev = known.get(key)
        if prev is not None:
            p = prev.payload
            if p.get("value") == o.value and p.get("value_status") == o.status:
                continue
            if p.get("release_date", "") > rel.release_date.isoformat():
                continue  # bản phát hành cũ hơn → không viết lại
        s = by[o.series]
        rev = 0 if prev is None else max(
            r.revision for r in store.history(SOURCE, key, now)) + 1
        flags = [] if o.status == "AVAILABLE" else [o.status]
        rec = NormalizedRecord(
            record_id=f"{SOURCE}:{key}:r{rev}", source=SOURCE, kind="macro", logical_key=key,
            revision=rev, event_time=et, ingested_at=now, available_at=None,
            source_status=SourceStatus.HEALTHY, payload_version=PAYLOAD_VERSION,
            raw_ref=f"{URL}@{rel.release_date.isoformat()}", quality_flags=frozenset(flags),
            payload={"series": o.series, "date": o.day.isoformat(), "value": o.value,
                     "value_status": o.status, "unit": "PERCENT_PER_YEAR", "label": s.label,
                     "source_note": s.source_note, "release_date": rel.release_date.isoformat(),
                     "flags": flags})
        counts.add(store.append(rec, {"series": o.series, "date": o.day.isoformat(),
                                      "cell": o.value, "status": o.status}))
    return counts


def run_once(*, store, log, get, now: datetime, registry=None):
    """Một lần tải trang H.15 → ghi số + nhật ký lần kiểm (ING-30)."""
    from gold_trading.ingestion.source_status import CheckOutcome, SourceCheck, SourceRegistry

    registry = registry if registry is not None else SourceRegistry([spec()])
    sp = registry.get(SOURCE)
    if sp is None or not sp.enabled:
        raise ValueError("nguồn fed_h15 chưa được bật")
    try:
        rel = parse_release(get())
        if rel.release_date > now.astimezone(ET).date():
            raise H15ParseError("ngày phát hành ở tương lai")
    except FetchError as e:
        check = SourceCheck(SOURCE, now, CheckOutcome.ERROR, e.code)
    except H15ParseError:
        check = SourceCheck(SOURCE, now, CheckOutcome.INVALID, "PARSE_ERROR")
    else:
        check = SourceCheck.from_counts(SOURCE, now, sync(store, rel, now))
    log.record(check)
    return check


REFRESH = timedelta(hours=4)


def due(now: datetime, summary) -> str | None:
    """Tải lại khi lần OK cuối cũ hơn 4 giờ (trang đổi mỗi ngày làm việc); lỗi → thử lại sau 30
    phút. H.15 không có "giờ công bố" cần bắt nhanh: số là bối cảnh vĩ mô, trễ vài giờ chấp nhận."""
    from gold_trading.ingestion.source_status import CheckOutcome

    last = summary.last_check
    if summary.last_ok_at is not None and now - summary.last_ok_at < REFRESH:
        return None
    if last is None or last.outcome is CheckOutcome.OK:
        return "REFRESH"
    return "RETRY" if now - last.checked_at >= timedelta(minutes=30) else None
