"""Lưu kết quả analyst append-only.

Cùng output_id (cùng phiên bản + as_of + hash đầu vào) thì không ghi lại.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from gold_trading.contracts.analyst import AnalystOutput
from gold_trading.contracts.candle import DataSource
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.schema import analyst_outputs


@dataclass(frozen=True)
class StoredOutput:
    output: AnalystOutput
    computed_at: datetime
    source: DataSource


class AnalystOutputStore(Protocol):
    def append(
        self,
        out: AnalystOutput,
        *,
        symbol: str,
        tf: Timeframe,
        source: DataSource,
        computed_at: datetime,
    ) -> bool: ...
    def latest(
        self, analyst_id: str, *, symbol: str, tf: Timeframe, source: DataSource
    ) -> StoredOutput | None: ...


class InMemoryAnalystOutputStore:
    def __init__(self) -> None:
        self._rows: list[tuple[str, Timeframe, DataSource, StoredOutput]] = []
        self._ids: set[str] = set()
        self._lock = threading.Lock()

    def append(self, out, *, symbol, tf, source, computed_at):
        with self._lock:
            if out.output_id in self._ids:
                return False
            self._ids.add(out.output_id)
            self._rows.append((symbol, tf, source, StoredOutput(out, computed_at, source)))
            return True

    def latest(self, analyst_id, *, symbol, tf, source):
        rows = [
            r
            for (s, t, src, r) in self._rows
            if (s, t, src) == (symbol, tf, source) and r.output.analyst_id == analyst_id
        ]
        return max(rows, key=lambda r: (r.output.as_of, r.computed_at)) if rows else None


def _utc(v: datetime) -> datetime:
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v


class SqlAnalystOutputStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append(self, out, *, symbol, tf, source, computed_at):
        row = dict(
            output_id=out.output_id,
            analyst_id=out.analyst_id,
            version=out.version,
            symbol=symbol,
            timeframe=tf.value,
            source=source.value,
            as_of=out.as_of,
            expires_at=out.expires_at,
            computed_at=computed_at,
            source_status=out.source_status.value,
            confidence=out.confidence,
            payload=out.model_dump(mode="json"),
        )
        with self.engine.begin() as conn:
            if self.engine.dialect.name == "postgresql":
                res = conn.execute(
                    pg_insert(analyst_outputs)
                    .values(**row)
                    .on_conflict_do_nothing(index_elements=["output_id"])
                )
                return res.rowcount == 1
            exists = conn.execute(
                select(analyst_outputs.c.seq).where(analyst_outputs.c.output_id == out.output_id)
            ).first()
            if exists:
                return False
            try:
                conn.execute(analyst_outputs.insert().values(**row))
            except IntegrityError:
                return False
            return True

    def latest(self, analyst_id, *, symbol, tf, source):
        q = (
            select(analyst_outputs.c.payload, analyst_outputs.c.computed_at)
            .where(
                analyst_outputs.c.analyst_id == analyst_id,
                analyst_outputs.c.symbol == symbol,
                analyst_outputs.c.timeframe == tf.value,
                analyst_outputs.c.source == source.value,
            )
            .order_by(analyst_outputs.c.as_of.desc(), analyst_outputs.c.seq.desc())
            .limit(1)
        )
        with self.engine.connect() as conn:
            row = conn.execute(q).first()
        if row is None:
            return None
        return StoredOutput(
            AnalystOutput.model_validate(row.payload), _utc(row.computed_at), source
        )
