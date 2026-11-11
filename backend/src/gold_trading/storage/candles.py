"""Kho nến append-only. Bản bộ nhớ cho test, bản SQL cho Postgres/TimescaleDB."""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import Engine, and_, func, insert, select

from gold_trading.contracts.candle import Candle, CandleFlag, DataSource
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.schema import candle_quarantine, candles

Key = tuple[str, Timeframe, DataSource, str]  # (symbol, khung, nguồn, feed_id)


@dataclass(frozen=True)
class QuarantineEntry:
    source: DataSource
    symbol: str
    timeframe: Timeframe
    received_at: datetime
    reason: str
    raw: dict[str, Any] = field(default_factory=dict)
    feed_id: str = ""


@dataclass(frozen=True)
class SeriesStats:
    count: int
    first_open_time: datetime | None
    last_open_time: datetime | None
    last_ingested_at: datetime | None
    quarantined: int


class CandleStore(Protocol):
    def append(self, items: list[Candle], quarantine: list[QuarantineEntry]) -> None: ...
    # ``feed``: MT-05, nguồn giá (""= không gắn broker). Mọi đọc/ghi đều theo đúng một feed.
    def latest_by_open_time(
        self, symbol: str, tf: Timeframe, source: DataSource, lo: datetime, hi: datetime,
        *, feed: str = "",
    ) -> dict[datetime, Candle]: ...
    def last_before(
        self, symbol: str, tf: Timeframe, source: DataSource, t: datetime, *, feed: str = ""
    ) -> Candle | None: ...
    def query(
        self,
        symbol: str,
        tf: Timeframe,
        source: DataSource,
        *,
        as_of: datetime,
        end: datetime | None = None,
        limit: int = 500,
        feed: str = "",
    ) -> list[Candle]: ...
    def stats(
        self, symbol: str, tf: Timeframe, source: DataSource, *, feed: str = ""
    ) -> SeriesStats: ...
    def quarantine(self, limit: int = 50) -> list[QuarantineEntry]: ...


def _visible(revs: list[Candle], as_of: datetime | None) -> Candle | None:
    """Revision mới nhất đã biết tại as_of (None = mới nhất tuyệt đối)."""
    pick = [c for c in revs if as_of is None or c.available_at <= as_of]
    return max(pick, key=lambda c: c.revision) if pick else None


class InMemoryCandleStore:
    def __init__(self) -> None:
        self._rows: dict[Key, dict[datetime, list[Candle]]] = defaultdict(lambda: defaultdict(list))
        self._quarantine: list[QuarantineEntry] = []
        self._lock = threading.Lock()

    def append(self, items: list[Candle], quarantine: list[QuarantineEntry]) -> None:
        with self._lock:
            for c in items:
                self._rows[(c.symbol, c.timeframe, c.source, c.feed_id)][c.open_time].append(c)
            self._quarantine.extend(quarantine)

    def latest_by_open_time(self, symbol, tf, source, lo, hi, *, feed=""):
        series = self._rows.get((symbol, tf, source, feed), {})
        out = {}
        for t, revs in series.items():
            if lo <= t <= hi and (c := _visible(revs, None)):
                out[t] = c
        return out

    def last_before(self, symbol, tf, source, t, *, feed=""):
        series = self._rows.get((symbol, tf, source, feed), {})
        earlier = [k for k in series if k < t]
        return _visible(series[max(earlier)], None) if earlier else None

    def query(self, symbol, tf, source, *, as_of, end=None, limit=500, feed=""):
        series = self._rows.get((symbol, tf, source, feed), {})
        out = []
        for t in sorted(series):
            if end is not None and t > end:
                continue
            if c := _visible(series[t], as_of):
                out.append(c)
        return out[-limit:]

    def stats(self, symbol, tf, source, *, feed=""):
        series = self._rows.get((symbol, tf, source, feed), {})
        keys = sorted(series)
        q = sum(
            1 for e in self._quarantine
            if (e.symbol, e.timeframe, e.source, e.feed_id) == (symbol, tf, source, feed)
        )
        last_ing = max((c.ingested_at for revs in series.values() for c in revs), default=None)
        return SeriesStats(
            len(keys), keys[0] if keys else None, keys[-1] if keys else None, last_ing, q
        )

    def quarantine(self, limit=50):
        return list(reversed(self._quarantine[-limit:]))


def _utc(v: datetime | None) -> datetime | None:
    if v is not None and v.tzinfo is None:
        return v.replace(tzinfo=UTC)
    return v


def _to_candle(r: Any) -> Candle:
    return Candle(
        symbol=r.symbol,
        timeframe=Timeframe(r.timeframe),
        source=DataSource(r.source),
        feed_id=r.feed_id,
        open_time=_utc(r.open_time),
        close_time=_utc(r.close_time),
        open=r.open,
        high=r.high,
        low=r.low,
        close=r.close,
        tick_volume=r.tick_volume,
        spread_points=r.spread_points,
        revision=r.revision,
        ingested_at=_utc(r.ingested_at),
        available_at=_utc(r.available_at),
        flags=frozenset(CandleFlag(f) for f in (r.flags or [])),
    )


class SqlCandleStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append(self, items: list[Candle], quarantine: list[QuarantineEntry]) -> None:
        # Một transaction: nến và bản ghi cách ly của cùng batch cùng thành công hoặc cùng hủy.
        with self.engine.begin() as conn:
            if items:
                conn.execute(
                    insert(candles),
                    [
                        {
                            "symbol": c.symbol,
                            "timeframe": c.timeframe.value,
                            "source": c.source.value,
                            "feed_id": c.feed_id,
                            "open_time": c.open_time,
                            "revision": c.revision,
                            "close_time": c.close_time,
                            "open": c.open,
                            "high": c.high,
                            "low": c.low,
                            "close": c.close,
                            "tick_volume": c.tick_volume,
                            "spread_points": c.spread_points,
                            "ingested_at": c.ingested_at,
                            "available_at": c.available_at,
                            "flags": sorted(f.value for f in c.flags),
                        }
                        for c in items
                    ],
                )
            if quarantine:
                conn.execute(
                    insert(candle_quarantine),
                    [
                        {
                            "received_at": q.received_at,
                            "source": q.source.value,
                            "feed_id": q.feed_id,
                            "symbol": q.symbol,
                            "timeframe": q.timeframe.value,
                            "reason": q.reason,
                            "raw": q.raw,
                        }
                        for q in quarantine
                    ],
                )

    def _key(self, symbol: str, tf: Timeframe, source: DataSource, feed: str):
        return and_(
            candles.c.symbol == symbol,
            candles.c.timeframe == tf.value,
            candles.c.source == source.value,
            candles.c.feed_id == feed,
        )

    def _latest(self, symbol, tf, source, feed, *conds):
        sub = (
            select(candles.c.open_time, func.max(candles.c.revision).label("rev"))
            .where(self._key(symbol, tf, source, feed), *conds)
            .group_by(candles.c.open_time)
            .subquery()
        )
        return select(candles).join(
            sub,
            and_(
                self._key(symbol, tf, source, feed),
                candles.c.open_time == sub.c.open_time,
                candles.c.revision == sub.c.rev,
            ),
        )

    def latest_by_open_time(self, symbol, tf, source, lo, hi, *, feed=""):
        q = self._latest(
            symbol, tf, source, feed, candles.c.open_time >= lo, candles.c.open_time <= hi
        )
        with self.engine.connect() as conn:
            rows = conn.execute(q).all()
        return {c.open_time: c for c in map(_to_candle, rows)}

    def last_before(self, symbol, tf, source, t, *, feed=""):
        t_last = (
            select(func.max(candles.c.open_time))
            .where(self._key(symbol, tf, source, feed), candles.c.open_time < t)
            .scalar_subquery()
        )
        q = self._latest(symbol, tf, source, feed, candles.c.open_time == t_last)
        with self.engine.connect() as conn:
            row = conn.execute(q).first()
        return _to_candle(row) if row else None

    def query(self, symbol, tf, source, *, as_of, end=None, limit=500, feed=""):
        conds = [candles.c.available_at <= as_of]
        if end is not None:
            conds.append(candles.c.open_time <= end)
        q = (
            self._latest(symbol, tf, source, feed, *conds)
            .order_by(candles.c.open_time.desc())
            .limit(limit)
        )
        with self.engine.connect() as conn:
            rows = conn.execute(q).all()
        return [_to_candle(r) for r in reversed(rows)]

    def stats(self, symbol, tf, source, *, feed=""):
        key = self._key(symbol, tf, source, feed)
        with self.engine.connect() as conn:
            count, first, last, last_ing = conn.execute(
                select(
                    func.count(func.distinct(candles.c.open_time)),
                    func.min(candles.c.open_time),
                    func.max(candles.c.open_time),
                    func.max(candles.c.ingested_at),
                ).where(key)
            ).one()
            q = conn.execute(
                select(func.count()).where(
                    candle_quarantine.c.symbol == symbol,
                    candle_quarantine.c.timeframe == tf.value,
                    candle_quarantine.c.source == source.value,
                    candle_quarantine.c.feed_id == feed,
                )
            ).scalar_one()
        return SeriesStats(count, _utc(first), _utc(last), _utc(last_ing), q)

    def quarantine(self, limit=50):
        q = select(candle_quarantine).order_by(candle_quarantine.c.seq.desc()).limit(limit)
        with self.engine.connect() as conn:
            rows = conn.execute(q).all()
        return [
            QuarantineEntry(
                source=DataSource(r.source),
                symbol=r.symbol,
                timeframe=Timeframe(r.timeframe),
                received_at=_utc(r.received_at),
                reason=r.reason,
                raw=r.raw,
                feed_id=r.feed_id,
            )
            for r in rows
        ]
