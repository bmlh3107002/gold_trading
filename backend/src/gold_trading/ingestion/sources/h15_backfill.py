"""Nạp bù lịch sử lãi suất H.15 (một lần, chạy tay) — cho Macro analyst (GĐ3 bước 4).

Thiết kế + lý do: ``docs/thiet-ke/18-h15-lai-suat.md`` mục 10. Trang phát hành H.15 chỉ hiện ~5 ngày
gần nhất → Macro cần ≥ 21 quan sát mới tính được độ bất thường. Hai nguồn chính thức, đã kiểm
**trùng số H.15** (5/5 ngày 05–10/11/2026):

- Lợi suất danh nghĩa 2 / 10 năm: gói CSV "Treasury Constant Maturities" của Data Download Program
  (Fed — nhà cung cấp ``fed`` đã VERIFIED), đúng mã chuỗi H.15 ``RIFLGFCY02_N.B`` /
  ``RIFLGFCY10_N.B``. DDP sắp gỡ (2027) → chỉ dùng cho **lần nạp bù này**, không phải nguồn định kỳ.
- Lợi suất thực 10 năm: "Daily Treasury Par Real Yield Curve Rates" của Bộ Tài chính (``treasury``
  VERIFIED) — chính là nguồn của dòng "inflation indexed 10-year" trên H.15.

An toàn:
- Chỉ **thêm ngày chưa có** (revision 0) dưới nguồn ``fed_h15``; ngày đã có → không đụng tới (kể cả
  khác số: ghi nhận ``CONFLICT``, không sửa). Không bao giờ viết lại số đã lưu.
- "Đã biết" = lúc nạp (``ingested_at = now``, ``available_at`` trống) → chạy lại quá khứ (replay /
  backtest) **không** thấy số nạp bù trước lúc nạp (không nhìn trước tương lai).
- File sai định dạng (thiếu cột / mã chuỗi / ngày hỏng / số ngoài [-5, 25]) → từ chối cả file.
- Payload ghi rõ ``backfill_source`` + ``raw_ref``.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from gold_trading.ingestion.sources import fed_h15 as H

DDP_URL = ("https://www.federalreserve.gov/datadownload/Output.aspx?rel=H15&series="
           "bf17364827e38702b42a58cf8eaa3f78&lastobs=&from=&to=&filetype=csv&label=include"
           "&layout=seriescolumn")
TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                "daily-treasury-rates.csv/{year}/all?type=daily_treasury_real_yield_curve"
                "&field_tdr_date_value={year}&page&_format=csv")
DDP_SERIES = {"RIFLGFCY02_N.B": "UST_CMT_2Y", "RIFLGFCY10_N.B": "UST_CMT_10Y"}
TREASURY_COLUMN = "10 YR"
BACKFILL_VERSION = "h15-backfill-2026.11.14"
MAX_BYTES = 5_000_000
_NUM = re.compile(r"^-?\d{1,2}\.\d{2}$")


class BackfillFormatError(ValueError):
    """File không đúng định dạng mong đợi → không ghi gì."""


@dataclass(frozen=True)
class Obs:
    series: str
    day: date
    value: str            # chuỗi gốc, vd. "4.86"
    origin: str           # DDP / TREASURY


@dataclass
class Counts:
    added: int = 0
    same: int = 0
    # (chuỗi, ngày, số đã có, số nguồn bù)
    conflict: list[tuple[str, str, str, str]] = field(default_factory=list)
    skipped_old: int = 0
    rejected: list[str] = field(default_factory=list)


def _value(raw: str, where: str) -> str | None:
    raw = raw.strip()
    if raw in ("ND", "NC", "NA", "", "N/A"):
        return None                  # không có số (ngày nghỉ) — không bao giờ thành 0
    if not _NUM.match(raw) or not -5 <= float(raw) <= 25:
        raise BackfillFormatError(f"số không hợp lệ {raw!r} ở {where}")
    return raw


def parse_ddp(text: str) -> list[Obs]:
    rows = list(csv.reader(io.StringIO(text)))
    ident = next((r for r in rows if r and r[0].startswith("Unique Identifier")), None)
    head_i = next((i for i, r in enumerate(rows) if r and r[0] == "Time Period"), None)
    if ident is None or head_i is None:
        raise BackfillFormatError("thiếu dòng 'Unique Identifier' / 'Time Period'")
    header = rows[head_i]
    cols = {}
    for code in DDP_SERIES:
        if code not in header or f"H15/H15/{code}" not in ident:
            raise BackfillFormatError(f"thiếu chuỗi {code}")
        cols[code] = header.index(code)
    unit = next((r for r in rows if r and r[0] == "Unit:"), None)
    if unit is None or any(unit[cols[c]] != "Percent:_Per_Year" for c in cols):
        raise BackfillFormatError("đơn vị không phải phần trăm / năm")
    out: list[Obs] = []
    for r in rows[head_i + 1:]:
        if not r:
            continue
        try:
            d = date.fromisoformat(r[0])
        except ValueError:
            raise BackfillFormatError(f"ngày hỏng {r[0]!r}") from None
        for code, i in cols.items():
            v = _value(r[i], f"{code} {d}")
            if v is not None:
                out.append(Obs(DDP_SERIES[code], d, v, "DDP"))
    return out


def parse_treasury_real(text: str) -> list[Obs]:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or rows[0][0] != "Date" or TREASURY_COLUMN not in rows[0]:
        raise BackfillFormatError("thiếu cột 'Date' / '10 YR'")
    i = rows[0].index(TREASURY_COLUMN)
    out: list[Obs] = []
    for r in rows[1:]:
        if not r:
            continue
        try:
            d = datetime.strptime(r[0], "%m/%d/%Y").date()
        except ValueError:
            raise BackfillFormatError(f"ngày hỏng {r[0]!r}") from None
        v = _value(r[i] if i < len(r) else "", f"10 YR {d}")
        if v is not None:
            out.append(Obs("UST_TIPS_10Y", d, v, "TREASURY"))
    return out


def backfill(store, obs: list[Obs], now: datetime, *, since: date) -> Counts:
    """Ghi các quan sát ``day >= since`` chưa có. Ngày đã có → so số, không sửa."""
    from gold_trading.common.enums import SourceStatus
    from gold_trading.contracts.records import NormalizedRecord

    known = {r.logical_key: r for r in store.as_of(now, source=H.SOURCE, kind="macro")}
    c = Counts()
    seen: set[str] = set()
    for o in sorted(obs, key=lambda o: (o.series, o.day)):
        key = f"{o.series}:{o.day.isoformat()}"
        if o.day < since:
            c.skipped_old += 1
            continue
        et = H._event_time(o.day)
        if et > now or key in seen:
            continue
        seen.add(key)
        prev = known.get(key)
        if prev is not None:
            old = prev.payload.get("value")
            if old == o.value:
                c.same += 1
            else:
                c.conflict.append((o.series, o.day.isoformat(), str(old), o.value))
            continue
        url = DDP_URL if o.origin == "DDP" else TREASURY_URL.format(year=o.day.year)
        res = store.append(NormalizedRecord(
            record_id=f"{H.SOURCE}:{key}:r0", source=H.SOURCE, kind="macro", logical_key=key,
            revision=0, event_time=et, ingested_at=now, available_at=None,
            source_status=SourceStatus.HEALTHY, payload_version=H.PAYLOAD_VERSION,
            raw_ref=url[:256], quality_flags=frozenset({"BACKFILL"}),
            payload={"series": o.series, "date": o.day.isoformat(), "value": o.value,
                     "value_status": "AVAILABLE", "unit": "PERCENT_PER_YEAR",
                     "backfill_source": o.origin, "backfill_version": BACKFILL_VERSION,
                     "flags": ["BACKFILL"]}), {"series": o.series, "cell": o.value})
        if res.outcome.value == "INSERTED":
            c.added += 1
        else:
            c.rejected.append(f"{key}:{res.outcome.value}")
    return c


def http_text(client, url: str, host: str, timeout: float = 60.0) -> str:
    r = client.get(url, timeout=timeout, follow_redirects=True)
    if r.url.host != host:
        raise BackfillFormatError(f"chuyển hướng lạ tới {r.url.host}")
    if r.status_code != 200:
        raise BackfillFormatError(f"HTTP {r.status_code} từ {host}")
    if len(r.content) > MAX_BYTES:
        raise BackfillFormatError("file quá lớn")
    return r.text


def default_since(now: datetime, days: int = 400) -> date:
    return (now - timedelta(days=days)).date()
