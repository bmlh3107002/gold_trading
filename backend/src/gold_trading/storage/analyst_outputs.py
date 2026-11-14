"""Lưu kết quả analyst append-only.

Cùng (nguồn giá, output_id) (cùng phiên bản + as_of + hash đầu vào) thì không ghi lại. MT-05:
hai nguồn có nến giống hệt nhau vẫn mỗi nguồn một kết quả (migration 0010).
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
class ExpiredOutput:
    """Kết quả hết hạn tại ``expires_at`` mà tới lúc đó chưa có kết quả mới hơn cùng chuỗi."""

    analyst_id: str
    symbol: str
    timeframe: str
    source: str
    feed: str
    output_id: str
    expires_at: datetime


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
        feed: str = "",
    ) -> bool: ...
    def latest(
        self, analyst_id: str, *, symbol: str, tf: Timeframe, source: DataSource, feed: str = ""
    ) -> StoredOutput | None: ...


class InMemoryAnalystOutputStore:
    def __init__(self) -> None:
        self._rows: list[tuple[str, Timeframe, DataSource, str, StoredOutput]] = []
        self._ids: set[tuple[str, str]] = set()  # (feed, output_id)
        self._lock = threading.Lock()

    def append(self, out, *, symbol, tf, source, computed_at, feed=""):
        with self._lock:
            if (feed, out.output_id) in self._ids:
                return False
            self._ids.add((feed, out.output_id))
            self._rows.append((symbol, tf, source, feed, StoredOutput(out, computed_at, source)))
            return True

    def expired_unreplaced(self, lo: datetime, hi: datetime) -> list[ExpiredOutput]:
        """``lo < expires_at <= hi`` và không có kết quả cùng chuỗi tính sau nó, trước khi nó hết
        hạn (GĐ2 ORC-07). Chỉ dựa vào dữ liệu đã lưu → tính lại được."""
        with self._lock:
            rows = list(self._rows)
        out = []
        for (s, t, src, f, r) in rows:
            o = r.output
            if not (lo < o.expires_at <= hi):
                continue
            newer = any((s2, t2, src2, f2) == (s, t, src, f)
                        and r2.output.analyst_id == o.analyst_id
                        and r.computed_at < r2.computed_at <= o.expires_at
                        for (s2, t2, src2, f2, r2) in rows)
            if not newer:
                out.append(ExpiredOutput(o.analyst_id, s, t.value, src.value, f, o.output_id,
                                         o.expires_at))
        return out

    def computed_between(self, lo: datetime, hi: datetime) -> list[tuple]:
        """(analyst_id, feed, symbol, tf, source, output_id, computed_at) có ``lo < computed_at
        <= hi`` (GĐ2 replay)."""
        with self._lock:
            rows = list(self._rows)
        return sorted(((r.output.analyst_id, f, s, t.value, src.value, r.output.output_id,
                        r.computed_at) for (s, t, src, f, r) in rows
                       if lo < r.computed_at <= hi), key=lambda x: (x[6], x[5]))

    def latest(self, analyst_id, *, symbol, tf, source, feed=""):
        rows = [
            r
            for (s, t, src, f, r) in self._rows
            if (s, t, src, f) == (symbol, tf, source, feed) and r.output.analyst_id == analyst_id
        ]
        return max(rows, key=lambda r: (r.output.as_of, r.computed_at)) if rows else None


def _utc(v: datetime) -> datetime:
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v


class SqlAnalystOutputStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append(self, out, *, symbol, tf, source, computed_at, feed=""):
        row = dict(
            feed_id=feed,
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
                # RETURNING thay cho rowcount: psycopg 3 trả rowcount = -1 cho câu này, nên trước
                # đây append luôn báo False trên Postgres dù đã lưu (tìm được khi soát MT-05).
                res = conn.execute(
                    pg_insert(analyst_outputs)
                    .values(**row)
                    .on_conflict_do_nothing(index_elements=["feed_id", "output_id"])
                    .returning(analyst_outputs.c.seq)
                )
                return res.first() is not None
            exists = conn.execute(
                select(analyst_outputs.c.seq).where(
                    analyst_outputs.c.output_id == out.output_id, analyst_outputs.c.feed_id == feed
                )
            ).first()
            if exists:
                return False
            try:
                conn.execute(analyst_outputs.insert().values(**row))
            except IntegrityError:
                return False
            return True

    def expired_unreplaced(self, lo: datetime, hi: datetime) -> list[ExpiredOutput]:
        c = analyst_outputs.c
        cand = (select(c.analyst_id, c.symbol, c.timeframe, c.source, c.feed_id, c.output_id,
                       c.expires_at, c.computed_at)
                .where(c.expires_at > lo, c.expires_at <= hi))
        out = []
        with self.engine.connect() as conn:
            for m in conn.execute(cand).all():
                newer = conn.execute(select(c.seq).where(
                    c.analyst_id == m.analyst_id, c.symbol == m.symbol,
                    c.timeframe == m.timeframe, c.source == m.source, c.feed_id == m.feed_id,
                    c.computed_at > m.computed_at, c.computed_at <= m.expires_at).limit(1)).first()
                if newer is None:
                    out.append(ExpiredOutput(m.analyst_id, m.symbol, m.timeframe, m.source,
                                             m.feed_id, m.output_id, _utc(m.expires_at)))
        return out

    def computed_between(self, lo: datetime, hi: datetime) -> list[tuple]:
        c = analyst_outputs.c
        q = (select(c.analyst_id, c.feed_id, c.symbol, c.timeframe, c.source, c.output_id,
                    c.computed_at).where(c.computed_at > lo, c.computed_at <= hi)
             .order_by(c.computed_at, c.output_id))
        with self.engine.connect() as conn:
            return [(m.analyst_id, m.feed_id, m.symbol, m.timeframe, m.source, m.output_id,
                     _utc(m.computed_at)) for m in conn.execute(q).all()]

    def latest(self, analyst_id, *, symbol, tf, source, feed=""):
        q = (
            select(analyst_outputs.c.payload, analyst_outputs.c.computed_at)
            .where(
                analyst_outputs.c.analyst_id == analyst_id,
                analyst_outputs.c.symbol == symbol,
                analyst_outputs.c.timeframe == tf.value,
                analyst_outputs.c.source == source.value,
                analyst_outputs.c.feed_id == feed,
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
