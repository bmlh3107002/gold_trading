"""Kho point-in-time trong bộ nhớ.

Bất biến: quyết định tại ``decision_at`` chỉ thấy bản ghi có ``ingested_at <= decision_at``.
Bản sửa đổi (revision) không ghi đè lịch sử — chỉ thêm mới.
Bản triển khai thật sẽ dùng PostgreSQL/TimescaleDB với cùng interface.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

from gold_trading.contracts.records import NormalizedRecord


class DuplicateRecordError(ValueError):
    pass


class PointInTimeStore:
    def __init__(self) -> None:
        # key -> danh sách revision theo thứ tự thêm vào
        self._by_key: dict[tuple[str, str], list[NormalizedRecord]] = defaultdict(list)
        self._by_id: dict[str, NormalizedRecord] = {}

    def append(self, record: NormalizedRecord) -> bool:
        """Thêm bản ghi. Trùng hoàn toàn -> bỏ qua (idempotent); trùng id khác nội dung -> lỗi."""
        existing = self._by_id.get(record.record_id)
        if existing is not None:
            if existing == record:
                return False
            raise DuplicateRecordError(f"record_id {record.record_id} đã tồn tại với nội dung khác")
        self._by_id[record.record_id] = record
        self._by_key[(record.source, self._logical_key(record))].append(record)
        return True

    def as_of(
        self, decision_at: datetime, *, source: str | None = None, kind: str | None = None
    ) -> list[NormalizedRecord]:
        """Phiên bản mới nhất của mỗi bản ghi mà hệ thống đã biết tại ``decision_at``."""
        result: list[NormalizedRecord] = []
        for (src, _), revisions in self._by_key.items():
            if source is not None and src != source:
                continue
            known = [r for r in revisions if r.ingested_at <= decision_at]
            if not known:
                continue
            latest = max(known, key=lambda r: (r.revision, r.ingested_at))
            if kind is not None and latest.kind != kind:
                continue
            result.append(latest)
        return sorted(result, key=lambda r: (r.event_time, r.record_id))

    def extend(self, records: Iterable[NormalizedRecord]) -> int:
        return sum(self.append(r) for r in records)

    @staticmethod
    def _logical_key(record: NormalizedRecord) -> str:
        # Bản ghi cùng logical_key là các revision của cùng một dữ kiện.
        return str(record.payload.get("logical_key", record.record_id))
