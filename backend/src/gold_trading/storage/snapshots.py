"""Kho snapshot (GĐ4 bước 2 — SNP-02): chỉ thêm, idempotent theo ``snapshot_id``.

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

from gold_trading.intelligence.snapshot_builder import SnapshotRecord
from gold_trading.storage.schema import market_snapshots


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
