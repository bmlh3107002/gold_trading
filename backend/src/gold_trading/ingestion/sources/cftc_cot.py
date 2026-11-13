"""CFTC — báo cáo COT vàng (GĐ1 bước 9e: ING-12, 1F-C01..C03).

Thiết kế + lý do: ``docs/thiet-ke/20-cot-vang.md``.

Nguồn: báo cáo văn bản "CMX (Futures Only)" legacy short format của CFTC
(``www.cftc.gov/dea/futures/deacmxsf.htm``), khối **GOLD – COMMODITY EXCHANGE INC.,
Code-088691** (hợp đồng 100 troy ounce). Public domain, ghi nguồn CFTC (``cftc`` ``VERIFIED``).
API ``publicreporting.cftc.gov`` bị chặn từ máy người dùng (403) → không dùng.

Point-in-time (1F-C01): vị thế chốt **thứ Ba** (``event_time`` = hết thứ Ba giờ New York), công
bố **15:30 giờ New York** ngày trong lịch chính thức của CFTC (thường thứ Sáu; tuần lễ dời 1–2
ngày) → ``available_at`` = giờ công bố đó. Tuần không có trong lịch (CFTC mới đăng tới hết 2026)
→ **không đoán**: ``available_at`` trống, hệ thống biết số từ lúc tải + cờ
``RELEASE_SCHEDULE_UNKNOWN``.

Kiểm tra (sai → ``INVALID`` cả lần tải, không ghi gì):
- đúng một khối Code-088691, đúng đơn vị "(CONTRACTS OF 100 TROY OUNCES)" (1F-C03: đổi mã /
  đổi hợp đồng → dừng);
- 9 số vị thế + 9 số thay đổi + 9 tỷ lệ %; **đẳng thức số học của CFTC**: long không thương mại
  + spread + long thương mại = tổng long (tương tự short); tổng + nhỏ lẻ = khối lượng mở (OI);
  cùng đẳng thức cho dòng thay đổi; % ≈ số / OI (lệch ≤ 0,1);
- ngày "CHANGES FROM" = ngày chốt − 7 ngày (khác → cờ ``CHANGE_BASE_NOT_PRIOR_WEEK``).
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PROVIDER = "cftc"
SOURCE = "cftc_cot_gold"
URL = "https://www.cftc.gov/dea/futures/deacmxsf.htm"
ALLOWED_HOST = "www.cftc.gov"
PAYLOAD_VERSION = "cftc-cot-legacy-1"
CONTRACT_CODE = "088691"
MARKET = "GOLD - COMMODITY EXCHANGE INC."
UNIT_LINE = "(CONTRACTS OF 100 TROY OUNCES)"
MAX_BYTES = 2 * 1024 * 1024
RELEASE_TIME = time(15, 30)
SCHEDULE_VERSION = "cftc-cot-schedule-2026.11.13"

# Lịch công bố chính thức 2026 (CFTC "Release Schedule", đọc nguyên văn từ máy người dùng
# 2026-11-13). Ngày có * trên trang = dời vì ngày lễ liên bang.
_RAW_2026 = {
    1: "05* 09 16 23 30", 2: "06 13 20 27", 3: "06 13 20 27", 4: "03 10 17 24",
    5: "01 08 15 22 29", 6: "05 12 22* 26", 7: "06* 10 17 24 31", 8: "07 14 21 28",
    9: "04 11 18 25", 10: "02 09 16 23 30", 11: "06 16* 20 30*", 12: "04 11 18 28*",
}
RELEASES: tuple[date, ...] = tuple(sorted(
    date(2026, m, int(d.rstrip("*"))) for m, ds in _RAW_2026.items() for d in ds.split()))
DELAYED: frozenset[date] = frozenset(
    date(2026, m, int(d.rstrip("*"))) for m, ds in _RAW_2026.items() for d in ds.split()
    if d.endswith("*"))

COLUMNS = ("noncomm_long", "noncomm_short", "noncomm_spreads", "comm_long", "comm_short",
           "total_long", "total_short", "nonrept_long", "nonrept_short")
TRADER_COLUMNS = ("noncomm_long", "noncomm_short", "noncomm_spreads", "comm_long",
                  "comm_short", "total_long", "total_short")


class CotParseError(ValueError):
    pass


class FetchError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CotReport:
    as_of: date                    # ngày chốt vị thế (thứ Ba)
    change_from: date
    open_interest: int
    oi_change: int
    positions: dict[str, int]
    changes: dict[str, int]
    percents: dict[str, str]
    total_traders: int
    traders: dict[str, int]
    flags: tuple[str, ...]


def release_for(as_of: date) -> date | None:
    """Ngày công bố theo lịch: ngày đầu tiên trong lịch sau ngày chốt, trong vòng 8 ngày."""
    for d in RELEASES:
        if as_of < d <= as_of + timedelta(days=8):
            return d
    return None


def release_at(as_of: date) -> datetime | None:
    d = release_for(as_of)
    return None if d is None else datetime.combine(d, RELEASE_TIME, tzinfo=ET).astimezone(UTC)


# ---------------------------------------------------------------- 1. Đọc

_NUM = r"(-?\d{1,3}(?:,\d{3})*)"
_HEAD = re.compile(r"(?m)^GOLD - COMMODITY EXCHANGE INC\.\s+Code-(\d{6})\s*$")
_ANY_HEAD = re.compile(r"(?m)^\S.* - .*\s+Code-[0-9A-Z]{6}\s*$")


def _ints(line: str, n: int) -> list[int]:
    parts = line.split()
    if len(parts) != n or not all(re.fullmatch(_NUM, p) for p in parts):
        raise CotParseError(f"dòng số lạ: {line.strip()[:60]!r}")
    return [int(p.replace(",", "")) for p in parts]


def _date(m: str, d: str, y: str) -> date:
    try:
        return date(2000 + int(y), int(m), int(d))
    except ValueError as e:
        raise CotParseError("ngày sai") from e


def parse(page: str) -> CotReport:
    text = _html.unescape(re.sub(r"<[^>]+>", "", page)).replace("\r\n", "\n")
    heads = list(_HEAD.finditer(text))
    if len(heads) != 1:
        raise CotParseError(f"cần đúng một khối GOLD, thấy {len(heads)}")
    if heads[0].group(1) != CONTRACT_CODE:
        raise CotParseError("mã hợp đồng vàng đổi")  # 1F-C03
    start = heads[0].end()
    nxt = _ANY_HEAD.search(text, start)
    block = text[start:nxt.start() if nxt else len(text)]
    lines = [ln for ln in block.split("\n")]

    def after(label: str) -> tuple[int, str]:
        for i, ln in enumerate(lines):
            if ln.strip().startswith(label):
                return i, ln
        raise CotParseError(f"thiếu dòng {label!r}")

    _, ln = after("FUTURES ONLY POSITIONS AS OF")
    m = re.match(r"\s*FUTURES ONLY POSITIONS AS OF (\d{2})/(\d{2})/(\d{2})\b", ln)
    if not m:
        raise CotParseError("dòng ngày chốt lạ")
    as_of = _date(*m.groups())
    _, ln = after("(CONTRACTS OF")
    m = re.match(r"\s*(\(CONTRACTS OF [^)]*\))\s+OPEN INTEREST:\s+" + _NUM + r"\s*$", ln)
    if not m:
        raise CotParseError("dòng đơn vị / OI lạ")
    if m.group(1) != UNIT_LINE:
        raise CotParseError("đổi đơn vị hợp đồng")  # 1F-C03
    oi = int(m.group(2).replace(",", ""))
    i, _ = after("COMMITMENTS")
    pos = dict(zip(COLUMNS, _ints(lines[i + 1], 9), strict=True))
    i, ln = after("CHANGES FROM")
    m = re.match(r"\s*CHANGES FROM (\d{2})/(\d{2})/(\d{2}) \(CHANGE IN OPEN INTEREST:\s+"
                 + _NUM + r"\)\s*$", ln)
    if not m:
        raise CotParseError("dòng thay đổi lạ")
    change_from = _date(*m.groups()[:3])
    oi_change = int(m.group(4).replace(",", ""))
    chg = dict(zip(COLUMNS, _ints(lines[i + 1], 9), strict=True))
    i, _ = after("PERCENT OF OPEN INTEREST")
    pct_raw = lines[i + 1].split()
    if len(pct_raw) != 9 or not all(re.fullmatch(r"\d{1,3}\.\d", p) for p in pct_raw):
        raise CotParseError("dòng % lạ")
    pct = dict(zip(COLUMNS, pct_raw, strict=True))
    i, ln = after("NUMBER OF TRADERS")
    m = re.search(r"TOTAL TRADERS:\s+" + _NUM + r"\)", ln)
    if not m:
        raise CotParseError("dòng số trader lạ")
    total_traders = int(m.group(1).replace(",", ""))
    traders = dict(zip(TRADER_COLUMNS, _ints(lines[i + 1], 7), strict=True))
    _check(pos, oi, "vị thế", non_negative=True)
    _check(chg, oi_change, "thay đổi", non_negative=False)
    for k, p in pct.items():
        exp = Decimal(pos[k]) * 100 / Decimal(oi) if oi else Decimal(0)
        if abs(Decimal(p) - exp) > Decimal("0.1"):
            raise CotParseError(f"% {k} lệch số")
    flags = []
    if as_of.weekday() != 1:
        flags.append("AS_OF_NOT_TUESDAY")
    if change_from != as_of - timedelta(days=7):
        flags.append("CHANGE_BASE_NOT_PRIOR_WEEK")
    return CotReport(as_of, change_from, oi, oi_change, pos, chg, pct, total_traders, traders,
                     tuple(flags))


def _check(v: dict[str, int], oi: int, what: str, *, non_negative: bool) -> None:
    if non_negative and (oi <= 0 or min(v.values()) < 0):
        raise CotParseError(f"{what}: số âm / OI không dương")
    if v["noncomm_long"] + v["noncomm_spreads"] + v["comm_long"] != v["total_long"]:
        raise CotParseError(f"{what}: tổng long không khớp")
    if v["noncomm_short"] + v["noncomm_spreads"] + v["comm_short"] != v["total_short"]:
        raise CotParseError(f"{what}: tổng short không khớp")
    if v["total_long"] + v["nonrept_long"] != oi or v["total_short"] + v["nonrept_short"] != oi:
        raise CotParseError(f"{what}: không khớp khối lượng mở")


# ---------------------------------------------------------------- 2. Tải

def http_getter(client, timeout: float = 30.0):
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


# ---------------------------------------------------------------- 3. Ghi + chạy

FETCH_TTL = timedelta(hours=30)
# Chốt thứ Ba → công bố thứ Sáu (3 ngày) → báo cáo kế tiếp sau 7 ngày nữa; lễ dời +3 ngày (vd.
# công bố thứ Hai) → số mới nhất cũ nhất ~13 ngày. Quá 14 ngày → CFTC trễ (chính phủ đóng cửa,
# 1F-C02) → STALE, không dùng số cũ như số mới.
DATA_TTL = timedelta(days=14)
REFRESH = timedelta(hours=6)


def spec():
    from gold_trading.ingestion.source_status import SourceSpec
    return SourceSpec(SOURCE, "positioning", fetch_ttl=FETCH_TTL, data_ttl=DATA_TTL,
                      provider=PROVIDER)


def _event_time(d: date) -> datetime:
    return datetime.combine(d + timedelta(days=1), time(0, 0), tzinfo=ET).astimezone(UTC)


def sync(store, rep: CotReport, now: datetime):
    from gold_trading.common.enums import SourceStatus
    from gold_trading.contracts.records import NormalizedRecord
    from gold_trading.ingestion.point_in_time import AppendCounts

    key = f"GOLD_{CONTRACT_CODE}:{rep.as_of.isoformat()}"
    rel = release_at(rep.as_of)
    flags = list(rep.flags)
    if rel is None:
        flags.append("RELEASE_SCHEDULE_UNKNOWN")
    payload = {
        "market": MARKET, "contract_code": CONTRACT_CODE, "report": "LEGACY_FUTURES_ONLY",
        "unit": "CONTRACTS_100_TROY_OZ", "as_of": rep.as_of.isoformat(),
        "change_from": rep.change_from.isoformat(), "open_interest": rep.open_interest,
        "open_interest_change": rep.oi_change, "positions": rep.positions,
        "changes": rep.changes, "percent_of_oi": rep.percents,
        "total_traders": rep.total_traders, "traders": rep.traders,
        "noncomm_net": rep.positions["noncomm_long"] - rep.positions["noncomm_short"],
        "release_at": rel.isoformat() if rel else None,
        "schedule_version": SCHEDULE_VERSION, "flags": sorted(flags)}
    counts = AppendCounts()
    hist = store.history(SOURCE, key, now)
    if hist:
        last = max(hist, key=lambda r: r.revision)
        same = {k: v for k, v in last.payload.items() if k != "flags"} == \
            {k: v for k, v in payload.items() if k != "flags"}
        if same:
            return counts
    newest = store.latest_event_time(SOURCE, now)
    if not hist and newest is not None and _event_time(rep.as_of) < newest:
        return counts  # trang trả báo cáo cũ hơn số đã có → không ghi (không lùi)
    rev = max((r.revision for r in hist), default=-1) + 1
    rec = NormalizedRecord(
        record_id=f"{SOURCE}:{key}:r{rev}", source=SOURCE, kind="positioning", logical_key=key,
        revision=rev, event_time=_event_time(rep.as_of), ingested_at=now, available_at=rel,
        source_status=SourceStatus.HEALTHY, payload_version=PAYLOAD_VERSION,
        raw_ref=f"{URL}@{rep.as_of.isoformat()}", quality_flags=frozenset(flags),
        payload=payload)
    counts.add(store.append(rec, {"as_of": rep.as_of.isoformat(), "positions": rep.positions}))
    return counts


def run_once(*, store, log, get, now: datetime, registry=None):
    from gold_trading.ingestion.source_status import CheckOutcome, SourceCheck, SourceRegistry

    registry = registry if registry is not None else SourceRegistry([spec()])
    sp = registry.get(SOURCE)
    if sp is None or not sp.enabled:
        raise ValueError("nguồn cftc_cot_gold chưa được bật")
    try:
        rep = parse(get())
        if _event_time(rep.as_of) > now:
            raise CotParseError("ngày chốt ở tương lai")
    except FetchError as e:
        check = SourceCheck(SOURCE, now, CheckOutcome.ERROR, e.code)
    except CotParseError:
        check = SourceCheck(SOURCE, now, CheckOutcome.INVALID, "PARSE_ERROR")
    else:
        check = SourceCheck.from_counts(SOURCE, now, sync(store, rep, now))
    log.record(check)
    return check


def due(now: datetime, summary) -> str | None:
    """Tải lại khi lần OK cuối > 6 giờ (báo cáo tuần; giờ công bố lấy từ lịch nên tải muộn vài giờ
    không làm sai point-in-time); lỗi → thử lại sau 30 phút."""
    from gold_trading.ingestion.source_status import CheckOutcome

    last = summary.last_check
    if summary.last_ok_at is not None and now - summary.last_ok_at < REFRESH:
        return None
    if last is None or last.outcome is CheckOutcome.OK:
        return "REFRESH"
    return "RETRY" if now - last.checked_at >= timedelta(minutes=30) else None
