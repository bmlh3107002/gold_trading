"""Kho snapshot (GĐ4 bước 2 — SNP-02) + kết quả Quality Gate (bước 3 — DQG-03): chỉ thêm,
idempotent theo id.

Lưu ``SnapshotRecord`` (manifest + thời điểm + cờ), không lưu output analyst. Dựng lại snapshot đầy
đủ bằng ``intelligence.snapshot_builder.rebuild``. Thiết kế 33 mục 3.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from gold_trading.common.enums import QualityVerdict
from gold_trading.contracts.snapshot import QualityReport
from gold_trading.intelligence.snapshot_builder import SnapshotRecord
from gold_trading.storage.schema import market_snapshots, quality_reports


class SnapshotStore(Protocol):
    def append(self, record: SnapshotRecord) -> bool: ...
    def get(self, snapshot_id: str) -> SnapshotRecord | None: ...


class InMemorySnapshotStore:
    def __init__(self) -> None:
        self._rows: dict[str, SnapshotRecord] = {}
        self._lock = threading.Lock()

    def append(self, record: SnapshotRecord) -> bool:
        with self._lock:
            if record.snapshot_id in self._rows:
                return False
            self._rows[record.snapshot_id] = record
            return True

    def get(self, snapshot_id: str) -> SnapshotRecord | None:
        with self._lock:
            return self._rows.get(snapshot_id)


def _utc(v: datetime) -> datetime:
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


class SqlSnapshotStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append(self, record: SnapshotRecord) -> bool:
        row = dict(
            snapshot_id=record.snapshot_id,
            builder_version=record.builder_version,
            symbol=record.symbol,
            timeframe=record.timeframe,
            source=record.source,
            feed_id=record.feed_id,
            event_time=record.event_time,
            available_at=record.available_at,
            expires_at=record.expires_at,
            quality_flags=sorted(record.quality_flags),
            input_manifest=dict(record.input_manifest),
            excluded_inputs=dict(record.excluded_inputs),
        )
        with self.engine.begin() as conn:
            if self.engine.dialect.name == "postgresql":
                res = conn.execute(
                    pg_insert(market_snapshots).values(**row)
                    .on_conflict_do_nothing(index_elements=["snapshot_id"])
                    .returning(market_snapshots.c.snapshot_id))
                return res.first() is not None
            if conn.execute(select(market_snapshots.c.snapshot_id).where(
                    market_snapshots.c.snapshot_id == record.snapshot_id)).first():
                return False
            try:
                conn.execute(market_snapshots.insert().values(**row))
            except IntegrityError:
                if self.get(record.snapshot_id) is None:
                    raise           # vi phạm ràng buộc (CHECK / FK), không phải trùng id
                return False
            return True

    def get(self, snapshot_id: str) -> SnapshotRecord | None:
        c = market_snapshots.c
        with self.engine.connect() as conn:
            m = conn.execute(select(market_snapshots).where(c.snapshot_id == snapshot_id)).first()
        if m is None:
            return None
        return SnapshotRecord(
            snapshot_id=m.snapshot_id, builder_version=m.builder_version, symbol=m.symbol,
            timeframe=m.timeframe, source=m.source, feed_id=m.feed_id,
            event_time=_utc(m.event_time), available_at=_utc(m.available_at),
            expires_at=_utc(m.expires_at), quality_flags=frozenset(m.quality_flags),
            input_manifest=dict(m.input_manifest), excluded_inputs=dict(m.excluded_inputs))


class QualityReportStore(Protocol):
    def append(self, report: QualityReport) -> bool: ...
    def get(self, report_id: str) -> QualityReport | None: ...
    def for_snapshot(self, snapshot_id: str) -> list[QualityReport]: ...
    def latest_for_scope(self, scope_key: str, known_by: datetime) -> QualityReport | None: ...


class InMemoryQualityReportStore:
    def __init__(self) -> None:
        self._rows: dict[str, QualityReport] = {}
        self._lock = threading.Lock()

    def append(self, report: QualityReport) -> bool:
        with self._lock:
            if report.report_id in self._rows:
                return False
            self._rows[report.report_id] = report
            return True

    def get(self, report_id: str) -> QualityReport | None:
        with self._lock:
            return self._rows.get(report_id)

    def for_snapshot(self, snapshot_id: str) -> list[QualityReport]:
        with self._lock:
            rows = [r for r in self._rows.values() if r.snapshot_id == snapshot_id]
        return sorted(rows, key=lambda r: (r.evaluated_at, r.report_id))

    def latest_for_scope(self, scope_key: str, known_by: datetime) -> QualityReport | None:
        """Báo cáo mới nhất (``evaluated_at ≤ known_by``) của nguồn giá ``scope_key`` (GĐ4 b6)."""
        prefix = f"snap:{scope_key}:"
        with self._lock:
            rows = [r for r in self._rows.values()
                    if r.snapshot_id.startswith(prefix) and r.evaluated_at <= known_by]
        return max(rows, key=lambda r: (r.evaluated_at, r.report_id)) if rows else None


class SqlQualityReportStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append(self, report: QualityReport) -> bool:
        row = dict(report_id=report.report_id, snapshot_id=report.snapshot_id,
                   evaluated_at=report.evaluated_at, verdict=report.verdict.value,
                   reasons=list(report.reasons),
                   confidence_multiplier=report.confidence_multiplier,
                   flags=sorted(report.flags), policy_version=report.policy_version)
        with self.engine.begin() as conn:
            if self.engine.dialect.name == "postgresql":
                res = conn.execute(
                    pg_insert(quality_reports).values(**row)
                    .on_conflict_do_nothing(index_elements=["report_id"])
                    .returning(quality_reports.c.report_id))
                return res.first() is not None
            if conn.execute(select(quality_reports.c.report_id).where(
                    quality_reports.c.report_id == report.report_id)).first():
                return False
            try:
                conn.execute(quality_reports.insert().values(**row))
            except IntegrityError:
                if self.get(report.report_id) is None:
                    raise           # vi phạm ràng buộc (CHECK / FK), không phải trùng id
                return False
            return True

    @staticmethod
    def _of(m) -> QualityReport:
        return QualityReport(report_id=m.report_id, snapshot_id=m.snapshot_id,
                             evaluated_at=_utc(m.evaluated_at), verdict=QualityVerdict(m.verdict),
                             reasons=tuple(m.reasons),
                             confidence_multiplier=m.confidence_multiplier,
                             flags=frozenset(m.flags), policy_version=m.policy_version)

    def get(self, report_id: str) -> QualityReport | None:
        c = quality_reports.c
        with self.engine.connect() as conn:
            m = conn.execute(select(quality_reports).where(c.report_id == report_id)).first()
        return self._of(m) if m is not None else None

    def for_snapshot(self, snapshot_id: str) -> list[QualityReport]:
        c = quality_reports.c
        q = (select(quality_reports).where(c.snapshot_id == snapshot_id)
             .order_by(c.evaluated_at, c.report_id))
        with self.engine.connect() as conn:
            return [self._of(m) for m in conn.execute(q).all()]

    def latest_for_scope(self, scope_key: str, known_by: datetime) -> QualityReport | None:
        """Báo cáo mới nhất (``evaluated_at ≤ known_by``) của nguồn giá ``scope_key`` (GĐ4 b6) —
        lọc theo cột phạm vi của snapshot (không dựa vào chuỗi id)."""
        src, feed, sym, tf = scope_key.split(":", 3)
        c, sn = quality_reports.c, market_snapshots.c
        q = (select(quality_reports)
             .join(market_snapshots, sn.snapshot_id == c.snapshot_id)
             .where(sn.source == src, sn.feed_id == feed, sn.symbol == sym, sn.timeframe == tf,
                    c.evaluated_at <= known_by)
             .order_by(c.evaluated_at.desc(), c.report_id.desc()).limit(1))
        with self.engine.connect() as conn:
            m = conn.execute(q).first()
        return self._of(m) if m is not None else None
