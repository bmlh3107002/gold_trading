"""Store point-in-time bằng SQL cho nguồn không phải nến (ING-13, DB-08, migration 0012).

Cùng interface + quy tắc với ``gold_trading.ingestion.point_in_time.PointInTimeStore``
(bản tham chiếu trong bộ nhớ). Bảng chỉ thêm: không bao giờ UPDATE/DELETE.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError

from gold_trading.common.enums import SourceStatus
from gold_trading.contracts.records import NormalizedRecord
from gold_trading.ingestion.point_in_time import (
    CONFLICT_REASONS,
    MAX_SOURCE_LEN,
    AppendCounts,
    AppendOutcome,
    AppendResult,
    QuarantineEntry,
    clean_label,
    fingerprint,
    quarantine_raw,
    validate,
)
from gold_trading.storage.schema import external_quarantine, external_records

_R = external_records.c


def _utc(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


def _record(m) -> NormalizedRecord:
    return NormalizedRecord(
        record_id=m.record_id, source=m.source, kind=m.kind, logical_key=m.logical_key,
        revision=m.revision, event_time=_utc(m.event_time), available_at=_utc(m.available_at),
        ingested_at=_utc(m.ingested_at), source_status=SourceStatus(m.source_status),
        payload_version=m.payload_version, raw_ref=m.raw_ref,
        quality_flags=frozenset(m.quality_flags or ()), payload=dict(m.payload or {}),
    )


class SqlExternalRecordStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # --- ghi ---

    def _conflict_reason(self, conn, r: NormalizedRecord, fp: str) -> str | None | AppendOutcome:
        """DUPLICATE, lý do xung đột, hoặc None (được thêm)."""
        old = conn.execute(select(_R.record_id, _R.fingerprint).where(
            _R.source == r.source, _R.logical_key == r.logical_key,
            _R.revision == r.revision)).first()
        if old is not None:
            if old.fingerprint == fp and old.record_id == r.record_id:
                return AppendOutcome.DUPLICATE
            return "REVISION_CONFLICT"
        if conn.execute(select(_R.seq).where(_R.record_id == r.record_id)).first() is not None:
            return "RECORD_ID_CONFLICT"
        kind = conn.execute(select(_R.kind).where(
            _R.source == r.source, _R.logical_key == r.logical_key).limit(1)).scalar()
        if kind is not None and kind != r.kind:
            return "KIND_CHANGED"
        return None

    def _quarantine(self, r: NormalizedRecord, raw: Any, reason: str,
                    received_at: datetime | None) -> None:
        with self.engine.begin() as conn:
            conn.execute(external_quarantine.insert().values(
                received_at=received_at or r.ingested_at,
                source=clean_label(r.source, MAX_SOURCE_LEN),
                kind=clean_label(r.kind, 16), reason=reason,
                raw=quarantine_raw(r, raw)))

    def append(self, record: NormalizedRecord, raw: Any = None, *,
               received_at: datetime | None = None) -> AppendResult:
        reason = validate(record, raw)
        if reason is None:
            fp = fingerprint(record)
            for _attempt in range(2):
                try:
                    with self.engine.begin() as conn:
                        found = self._conflict_reason(conn, record, fp)
                        if found is AppendOutcome.DUPLICATE:
                            return AppendResult(AppendOutcome.DUPLICATE)
                        if found is None:
                            conn.execute(external_records.insert().values(
                                record_id=record.record_id, source=record.source,
                                kind=record.kind, logical_key=record.logical_key,
                                revision=record.revision, event_time=record.event_time,
                                available_at=record.available_at,
                                ingested_at=record.ingested_at, known_at=record.known_at,
                                source_status=record.source_status.value,
                                payload_version=record.payload_version,
                                raw_ref=record.raw_ref, fingerprint=fp,
                                quality_flags=sorted(record.quality_flags),
                                payload=record.payload, raw=raw))
                            return AppendResult(AppendOutcome.INSERTED)
                        reason = found
                        break
                except IntegrityError:
                    # Hai tiến trình ghi cùng dữ kiện cùng lúc: kiểm lại một lần.
                    continue
            else:
                reason = "WRITE_RACE"
        self._quarantine(record, raw, reason, received_at)
        outcome = AppendOutcome.CONFLICT if reason in CONFLICT_REASONS else AppendOutcome.INVALID
        return AppendResult(outcome, reason)

    def extend(self, records: Iterable[NormalizedRecord]) -> AppendCounts:
        counts = AppendCounts()
        for r in records:
            counts.add(self.append(r))
        return counts

    # --- đọc ---

    def as_of(self, as_of: datetime, *, source: str | None = None, kind: str | None = None,
              logical_key: str | None = None, event_from: datetime | None = None,
              event_to: datetime | None = None) -> list[NormalizedRecord]:
        """Bản mới nhất (đã biết tại ``as_of``) của mỗi dữ kiện khớp bộ lọc."""
        conds = [_R.known_at <= as_of]
        if source is not None:
            conds.append(_R.source == source)
        if kind is not None:
            conds.append(_R.kind == kind)
        if logical_key is not None:
            conds.append(_R.logical_key == logical_key)
        rn = func.row_number().over(partition_by=(_R.source, _R.logical_key),
                                    order_by=_R.revision.desc()).label("rn")
        inner = select(external_records, rn).where(*conds).subquery()
        # Lọc theo event_time SAU khi chọn revision mới nhất (sự kiện bị dời ra ngoài khoảng
        # thì bản cũ không được coi là còn hiệu lực).
        outer = [inner.c.rn == 1]
        if event_from is not None:
            outer.append(inner.c.event_time >= event_from)
        if event_to is not None:
            outer.append(inner.c.event_time < event_to)
        q = (select(inner).where(*outer)
             .order_by(inner.c.event_time, inner.c.source, inner.c.logical_key))
        with self.engine.connect() as conn:
            return [_record(m) for m in conn.execute(q).mappings()]

    def latest_event_time(self, source: str, as_of: datetime) -> datetime | None:
        """``event_time`` lớn nhất (không quá ``as_of``) trong các bản ghi đã biết tại ``as_of``."""
        as_of = _utc(as_of)  # SQLite so sánh chuỗi: phải cùng múi UTC
        q = select(func.max(_R.event_time)).where(
            _R.source == source, _R.known_at <= as_of, _R.event_time <= as_of)
        with self.engine.connect() as conn:
            return _utc(conn.execute(q).scalar())

    def history(self, source: str, logical_key: str, as_of: datetime) -> list[NormalizedRecord]:
        q = (select(external_records)
             .where(_R.source == source, _R.logical_key == logical_key, _R.known_at <= as_of)
             .order_by(_R.revision))
        with self.engine.connect() as conn:
            return [_record(m) for m in conn.execute(q).mappings()]

    def quarantined(self, source: str | None = None, limit: int = 100) -> list[QuarantineEntry]:
        c = external_quarantine.c
        q = select(external_quarantine).order_by(c.seq.desc()).limit(limit)
        if source is not None:
            q = q.where(c.source == source)
        with self.engine.connect() as conn:
            return [QuarantineEntry(_utc(m.received_at), m.source, m.kind, m.reason, m.raw)
                    for m in conn.execute(q).mappings()]
