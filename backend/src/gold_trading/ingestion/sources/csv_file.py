"""Đọc nến từ CSV.

Hỗ trợ:
1. File xuất từ MetaTrader 5, tiêu đề dạng
   ``<DATE> <TIME> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> <VOL> <SPREAD>``, ngày ``2024.01.02``.
   Thời gian trong file là **giờ server của broker**, KHÔNG phải UTC,
   nên bắt buộc truyền ``server_tz`` (tên IANA, ví dụ ``Europe/Athens`` cho broker GMT+2/GMT+3).
2. CSV chung có cột ``time,open,high,low,close[,tick_volume][,spread]``. Thời gian ISO 8601;
   nếu không kèm múi giờ thì cũng phải truyền ``server_tz``.

Dòng không đọc được không bị bỏ qua âm thầm: trả về ``CsvReject`` để đưa vào quarantine.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from gold_trading.ingestion.candles import RawBar


@dataclass(frozen=True)
class CsvReject:
    line: int
    reason: str
    raw: dict[str, str]


class CsvFormatError(ValueError):
    pass


_ALIASES = {
    "date": "date",
    "time": "time",
    "datetime": "time",
    "timestamp": "time",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "tickvol": "tick_volume",
    "tick_volume": "tick_volume",
    "volume": "volume",
    "vol": "volume",
    "spread": "spread",
}


def _norm(name: str) -> str:
    return _ALIASES.get(name.strip().strip("<>").lower(), name.strip().lower())


def _local_to_utc(naive: datetime, tz: ZoneInfo) -> datetime | None:
    """None nếu giờ địa phương không tồn tại hoặc mơ hồ (chuyển DST) — không đoán."""
    a = naive.replace(tzinfo=tz, fold=0)
    b = naive.replace(tzinfo=tz, fold=1)
    if a.utcoffset() != b.utcoffset():
        return None
    utc = a.astimezone(UTC)
    if utc.astimezone(tz).replace(tzinfo=None) != naive:
        return None
    return utc


def _parse_time(date_part: str, time_part: str) -> datetime:
    """MT5: date ``2024.01.02`` + time ``00:15:00``. CSV chung: time ISO 8601, có thể có tz."""
    if date_part:
        stamp = f"{date_part.replace('.', '-')}T{time_part or '00:00:00'}"
    else:
        stamp = time_part
        if len(stamp) >= 10 and stamp[4] == "." and stamp[7] == ".":
            stamp = stamp[:10].replace(".", "-") + stamp[10:]
        stamp = stamp.replace(" ", "T", 1)
    return datetime.fromisoformat(stamp)


def parse(text: str, *, server_tz: str | None) -> tuple[list[RawBar], list[CsvReject]]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="\t,;")
    except csv.Error as e:
        raise CsvFormatError("Không nhận ra dấu phân cách (tab, phẩy hoặc chấm phẩy)") from e
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        header = [_norm(h) for h in next(reader)]
    except StopIteration as e:
        raise CsvFormatError("File rỗng") from e

    missing = {"open", "high", "low", "close"} - set(header)
    if "time" not in header and "date" not in header:
        missing.add("time")
    if missing:
        raise CsvFormatError(f"Thiếu cột bắt buộc: {', '.join(sorted(missing))}")
    tz = ZoneInfo(server_tz) if server_tz else None

    bars: list[RawBar] = []
    rejects: list[CsvReject] = []
    for line_no, row in enumerate(reader, start=2):
        if not row or all(not c.strip() for c in row):
            continue
        rec = dict(zip(header, (c.strip() for c in row), strict=False))
        try:
            dt = _parse_time(rec.get("date", ""), rec.get("time", ""))
        except ValueError:
            rejects.append(CsvReject(line_no, "BAD_TIME", rec))
            continue
        if dt.tzinfo is None:
            if tz is None:
                raise CsvFormatError(
                    "Thời gian trong file không có múi giờ. Hãy khai báo múi giờ server của broker "
                    "(ví dụ Europe/Athens) — MT5 xuất theo giờ server, không phải UTC."
                )
            utc = _local_to_utc(dt, tz)
            if utc is None:
                rejects.append(CsvReject(line_no, "AMBIGUOUS_LOCAL_TIME", rec))
                continue
        else:
            utc = dt.astimezone(UTC)
        try:
            spread = rec.get("spread")
            bars.append(
                RawBar(
                    open_time=utc,
                    open=float(rec["open"]),
                    high=float(rec["high"]),
                    low=float(rec["low"]),
                    close=float(rec["close"]),
                    tick_volume=int(float(rec.get("tick_volume") or rec.get("volume") or 0)),
                    spread_points=int(float(spread)) if spread else None,
                    raw={"line": line_no},
                )
            )
        except (KeyError, ValueError):
            rejects.append(CsvReject(line_no, "BAD_NUMBER", rec))
    return bars, rejects
