"""Ghi danh sách sự kiện lịch của một nguồn vào store point-in-time theo revision (ING-09, ING-19).

Mỗi lần tải xong một nguồn lịch, bộ nạp gọi ``sync_calendar`` với **toàn bộ** sự kiện nguồn đang
công bố (từ một mốc trở đi):

- Sự kiện mới → revision 0. Nội dung không đổi → bỏ qua (nạp lại → cùng kết quả).
- Nội dung đổi (giờ được xác nhận, dời ngày trong cùng khóa, cờ đổi...) → revision mới; quá khứ
  không bị viết lại (1C-C03: đổi giờ công bố).
- Sự kiện **tương lai** đã biết mà lần này không còn trên trang → revision mới với
  ``status = "REMOVED"`` (1C-C02: hoãn/hủy) — không xóa. Quá ``max_removals`` trong một lần →
  nghi trang hỏng: **không ghi gì**, trả ``TOO_MANY_REMOVALS`` (hướng an toàn).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from gold_trading.common.enums import SourceStatus
from gold_trading.contracts.records import NormalizedRecord
from gold_trading.ingestion.point_in_time import AppendCounts, canonical_json


class _Store(Protocol):
    def append(self, record: NormalizedRecord, raw: Any = None, *,
               received_at: datetime | None = None): ...
    def as_of(self, as_of: datetime, **kw) -> list[NormalizedRecord]: ...
    def history(self, source: str, logical_key: str, as_of: datetime
                ) -> list[NormalizedRecord]: ...


@dataclass(frozen=True)
class EventIn:
    logical_key: str
    event_time: datetime
    payload: dict


@dataclass
class SyncResult:
    counts: AppendCounts
    unchanged: int = 0
    revised: int = 0
    removed: int = 0
    error_code: str | None = None


def _same(r: NormalizedRecord, e: EventIn) -> bool:
    return r.event_time == e.event_time and canonical_json(r.payload) == canonical_json(e.payload)


def sync_calendar(store: _Store, *, source: str, payload_version: str, raw_ref: str,
                  events: Iterable[EventIn], now: datetime, max_removals: int = 2,
                  raw: Any = None) -> SyncResult:
    events = list(events)
    keys = [e.logical_key for e in events]
    if len(keys) != len(set(keys)):
        raise ValueError("trùng logical_key trong một lần đồng bộ")
    known = {r.logical_key: r for r in store.as_of(now, source=source, kind="calendar")}
    present = set(keys)
    gone = [r for k, r in known.items() if k not in present and r.event_time > now
            and r.payload.get("status") != "REMOVED"]
    result = SyncResult(AppendCounts())
    if len(gone) > max_removals:
        result.error_code = "TOO_MANY_REMOVALS"
        return result

    def write(key: str, event_time: datetime, payload: dict, prev: NormalizedRecord | None):
        rev = 0 if prev is None else max(r.revision for r in store.history(source, key, now)) + 1
        rec = NormalizedRecord(
            record_id=f"{source}:{key}:r{rev}", source=source, kind="calendar",
            logical_key=key, revision=rev, event_time=event_time, ingested_at=now,
            source_status=SourceStatus.HEALTHY, payload_version=payload_version,
            raw_ref=raw_ref, payload=payload)
        result.counts.add(store.append(rec, raw))

    for e in events:
        prev = known.get(e.logical_key)
        if prev is not None and _same(prev, e):
            result.unchanged += 1
            continue
        write(e.logical_key, e.event_time, e.payload, prev)
        if prev is not None:
            result.revised += 1
    for r in gone:
        write(r.logical_key, r.event_time, {**r.payload, "status": "REMOVED"}, r)
        result.removed += 1
    return result
