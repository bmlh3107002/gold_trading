"""Nạp bù lịch sử COT vàng từ file năm của CFTC (một lần, chạy tay trên máy người dùng).

Thiết kế + lý do: ``docs/thiet-ke/20-cot-vang.md`` mục 7. Positioning analyst cần ≥ 52 tuần; GĐ1 chỉ
có báo cáo từ 11/2026 (bộ nạp định kỳ cố ý không ghi báo cáo cũ hơn).

Nguồn: file lịch sử "Futures Only" của báo cáo legacy (``deacot<năm>.zip`` → ``annual.txt``,
CSV có tiêu đề) — cùng báo cáo với trang ``deacmxsf.htm`` của GĐ1, nhà cung cấp ``cftc``.
Máy chủ đám mây bị cftc.gov trả 403 → **chưa đối chiếu được file thật khi viết code**, nên:

- Đọc cột **theo tên** (không theo vị trí); thiếu cột → dừng, in tên cột thấy được.
- Chỉ dòng mã ``088691`` + tên ``GOLD - COMMODITY EXCHANGE INC.`` (không lấy MICRO GOLD 088695).
- Mỗi tuần kiểm **đẳng thức của CFTC** như GĐ1 (tổng long/short, khớp OI, cả dòng thay đổi).
- **Cổng đối chiếu:** phải có ≥ 1 tuần trùng với báo cáo đã lưu (từ trang GĐ1) và **mọi** tuần trùng
  khớp 100 % (OI + 9 vị thế) — nếu không → không ghi gì (ánh xạ cột sai = dữ liệu sai).
- Chỉ thêm tuần chưa có; không sửa báo cáo đã lưu. "Đã biết" = lúc nạp (``available_at`` trống
  ngoài lịch 2026) → chạy lại quá khứ không thấy số nạp bù.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime

from gold_trading.ingestion.sources import cftc_cot as C

HISTORY_URL = "https://www.cftc.gov/files/dea/history/deacot{year}.zip"
BACKFILL_VERSION = "cot-backfill-2026.11.14"
MAX_ZIP_BYTES = 20 * 1024 * 1024

_POS = {
    "open interest (all)": "oi",
    "noncommercial positions-long (all)": "noncomm_long",
    "noncommercial positions-short (all)": "noncomm_short",
    "noncommercial positions-spreading (all)": "noncomm_spreads",
    "commercial positions-long (all)": "comm_long",
    "commercial positions-short (all)": "comm_short",
    "total reportable positions-long (all)": "total_long",
    "total reportable positions-short (all)": "total_short",
    "nonreportable positions-long (all)": "nonrept_long",
    "nonreportable positions-short (all)": "nonrept_short",
}
_CHG = {
    "change in open interest (all)": "oi",
    "change in noncommercial-long (all)": "noncomm_long",
    "change in noncommercial-short (all)": "noncomm_short",
    "change in noncommercial-spreading (all)": "noncomm_spreads",
    "change in commercial-long (all)": "comm_long",
    "change in commercial-short (all)": "comm_short",
    "change in total reportable-long (all)": "total_long",
    "change in total reportable-short (all)": "total_short",
    "change in nonreportable-long (all)": "nonrept_long",
    "change in nonreportable-short (all)": "nonrept_short",
}
_NAME = "market and exchange names"
_DATE = "as of date in form yyyy-mm-dd"
_CODE = "cftc contract market code"


class CotBackfillError(ValueError):
    pass


def norm(h: str) -> str:
    h = re.sub(r"\s+", " ", h.strip().lower())
    return re.sub(r"\s*-\s*", "-", h)


@dataclass(frozen=True)
class HistReport:
    as_of: date
    open_interest: int
    oi_change: int
    positions: dict[str, int]
    changes: dict[str, int]


@dataclass
class Counts:
    added: int = 0
    same: int = 0
    conflict: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)


def _int(v: str, where: str) -> int:
    v = v.strip().replace(",", "")
    if not re.fullmatch(r"-?\d+", v):
        raise CotBackfillError(f"số không hợp lệ {v!r} ở {where}")
    return int(v)


def parse_annual(text: str) -> list[HistReport]:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise CotBackfillError("file rỗng")
    head = {norm(h): i for i, h in enumerate(rows[0])}
    need = [_NAME, _DATE, _CODE, *_POS, *_CHG]
    missing = [n for n in need if n not in head]
    if missing:
        raise CotBackfillError("thiếu cột: " + "; ".join(missing) + " — cột thấy được: "
                               + " | ".join(h.strip() for h in rows[0][:40]))
    out: list[HistReport] = []
    for r in rows[1:]:
        if len(r) < len(rows[0]):
            continue
        if r[head[_CODE]].strip() != C.CONTRACT_CODE:
            continue
        if not norm(r[head[_NAME]]).startswith(norm(C.MARKET)):
            raise CotBackfillError(f"mã {C.CONTRACT_CODE} nhưng tên thị trường lạ: {r[0]!r}")
        try:
            d = date.fromisoformat(r[head[_DATE]].strip())
        except ValueError:
            raise CotBackfillError(f"ngày hỏng {r[head[_DATE]]!r}") from None
        pos = {k: _int(r[head[h]], f"{d} {h}") for h, k in _POS.items()}
        chg = {k: _int(r[head[h]], f"{d} {h}") for h, k in _CHG.items()}
        oi, oi_chg = pos.pop("oi"), chg.pop("oi")
        try:
            C._check(pos, oi, f"{d} vị thế", non_negative=True)
            C._check(chg, oi_chg, f"{d} thay đổi", non_negative=False)
        except C.CotParseError as e:
            raise CotBackfillError(str(e)) from None
        out.append(HistReport(d, oi, oi_chg, pos, chg))
    dates = [x.as_of for x in out]
    if len(set(dates)) != len(dates):
        raise CotBackfillError("một ngày chốt xuất hiện hai lần")
    return sorted(out, key=lambda x: x.as_of)


def read_zip(data: bytes) -> str:
    if len(data) > MAX_ZIP_BYTES:
        raise CotBackfillError("file zip quá lớn")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise CotBackfillError("không phải file zip") from None
    names = [n for n in z.namelist() if n.lower().endswith(".txt")]
    if len(names) != 1:
        raise CotBackfillError(f"zip phải có đúng 1 file .txt, thấy {z.namelist()}")
    if z.getinfo(names[0]).file_size > 10 * MAX_ZIP_BYTES:
        raise CotBackfillError("file trong zip quá lớn")
    return z.read(names[0]).decode("utf-8-sig", errors="strict")


def cross_check(store, reports: list[HistReport], now: datetime) -> tuple[int, list[str]]:
    """(số tuần trùng, danh sách lệch) giữa file lịch sử và báo cáo đã lưu từ trang GĐ1."""
    have = {r.payload.get("as_of"): r.payload for r in store.as_of(now, source=C.SOURCE)}
    n, bad = 0, []
    for x in reports:
        p = have.get(x.as_of.isoformat())
        if p is None or p.get("report_source") == "CFTC_HISTORY_ANNUAL":
            continue
        n += 1
        if p.get("open_interest") != x.open_interest or any(
                p.get("positions", {}).get(k) != v for k, v in x.positions.items()):
            bad.append(x.as_of.isoformat())
    return n, bad


def backfill(store, reports: list[HistReport], now: datetime) -> Counts:
    from gold_trading.common.enums import SourceStatus
    from gold_trading.contracts.records import NormalizedRecord

    have = {r.logical_key: r for r in store.as_of(now, source=C.SOURCE)}
    c = Counts()
    for x in reports:
        key = f"GOLD_{C.CONTRACT_CODE}:{x.as_of.isoformat()}"
        et = C._event_time(x.as_of)
        if et > now:
            continue
        prev = have.get(key)
        if prev is not None:
            same = (prev.payload.get("open_interest") == x.open_interest and all(
                prev.payload.get("positions", {}).get(k) == v for k, v in x.positions.items()))
            if same:
                c.same += 1
            else:
                c.conflict.append(x.as_of.isoformat())
            continue
        rel = C.release_at(x.as_of)
        flags = ["BACKFILL"] + ([] if rel else ["RELEASE_SCHEDULE_UNKNOWN"])
        payload = {"market": C.MARKET, "contract_code": C.CONTRACT_CODE,
                   "report": "LEGACY_FUTURES_ONLY", "unit": "CONTRACTS_100_TROY_OZ",
                   "as_of": x.as_of.isoformat(), "open_interest": x.open_interest,
                   "open_interest_change": x.oi_change, "positions": x.positions,
                   "changes": x.changes,
                   "noncomm_net": x.positions["noncomm_long"] - x.positions["noncomm_short"],
                   "release_at": rel.isoformat() if rel else None,
                   "report_source": "CFTC_HISTORY_ANNUAL", "backfill_version": BACKFILL_VERSION,
                   "flags": flags}
        res = store.append(NormalizedRecord(
            record_id=f"{C.SOURCE}:{key}:r0", source=C.SOURCE, kind="positioning",
            logical_key=key, revision=0, event_time=et, ingested_at=now,
            available_at=rel if rel and rel <= now else None,
            source_status=SourceStatus.HEALTHY, payload_version=C.PAYLOAD_VERSION,
            raw_ref=HISTORY_URL.format(year=x.as_of.year), quality_flags=frozenset(flags),
            payload=payload), {"as_of": x.as_of.isoformat()})
        if res.outcome.value == "INSERTED":
            c.added += 1
        else:
            c.rejected.append(f"{x.as_of}:{res.outcome.value}")
    return c
