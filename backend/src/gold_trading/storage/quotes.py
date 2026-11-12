"""Kho giá sống theo giây (ING-08): bộ nhớ (test/dev) và SQL. Mỗi (nguồn, giây) ghi một lần."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from sqlalchemy import Engine, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from gold_trading.market.quotes import QuoteSecond
from gold_trading.storage.schema import quote_seconds


class InMemoryQuoteStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, datetime], QuoteSecond] = {}
        self._lock = threading.Lock()

    def window(self, feed, lo, hi):
        with self._lock:
            return sorted((r for (f, t), r in self._rows.items() if f == feed and lo <= t < hi),
                          key=lambda r: r.t)

    def append(self, rows):
        n = 0
        with self._lock:
            for r in rows:
                if (r.feed_id, r.t) not in self._rows:
                    self._rows[(r.feed_id, r.t)] = r
                    n += 1
        return n

    def latest(self, feed, as_of):
        with self._lock:
            ok = [r for (f, _), r in self._rows.items() if f == feed and r.available_at <= as_of]
        return max(ok, key=lambda r: r.t) if ok else None

    def purge_before(self, cutoff):
        with self._lock:
            old = [k for k, r in self._rows.items() if r.t < cutoff]
            for k in old:
                del self._rows[k]
        return len(old)


def _utc(v: datetime) -> datetime:
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


def _row(m) -> QuoteSecond:
    return QuoteSecond(
        feed_id=m.feed_id, t=_utc(m.t), bid=m.bid, ask=m.ask, bid_low=m.bid_low,
        ask_high=m.ask_high, spread_points=m.spread_points,
        spread_max_points=m.spread_max_points, ticks=m.ticks, flags=tuple(m.flags or ()),
        ingested_at=_utc(m.ingested_at), available_at=_utc(m.available_at),
    )


class SqlQuoteStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def window(self, feed, lo, hi):
        q = (select(quote_seconds)
             .where(quote_seconds.c.feed_id == feed, quote_seconds.c.t >= lo,
                    quote_seconds.c.t < hi)
             .order_by(quote_seconds.c.t))
        with self.engine.connect() as conn:
            return [_row(m) for m in conn.execute(q).mappings()]

    def append(self, rows):
        if not rows:
            return 0
        values = [dict(feed_id=r.feed_id, t=r.t, bid=r.bid, ask=r.ask, bid_low=r.bid_low,
                       ask_high=r.ask_high, spread_points=r.spread_points,
                       spread_max_points=r.spread_max_points, ticks=r.ticks,
                       flags=list(r.flags), ingested_at=r.ingested_at,
                       available_at=r.available_at) for r in rows]
        with self.engine.begin() as conn:
            if self.engine.dialect.name == "postgresql":
                # Hai Gateway cùng broker gửi cùng giây cùng lúc: giữ bản đầu, không lỗi cả lô.
                res = conn.execute(
                    pg_insert(quote_seconds).values(values)
                    .on_conflict_do_nothing(index_elements=["feed_id", "t"])
                    .returning(quote_seconds.c.t)
                )
                return len(res.fetchall())
            n = 0
            for v in values:
                exists = conn.execute(select(quote_seconds.c.t).where(
                    quote_seconds.c.feed_id == v["feed_id"], quote_seconds.c.t == v["t"])).first()
                if exists is None:
                    conn.execute(quote_seconds.insert().values(**v))
                    n += 1
            return n

    def latest(self, feed, as_of):
        q = (select(quote_seconds)
             .where(quote_seconds.c.feed_id == feed, quote_seconds.c.available_at <= as_of)
             .order_by(quote_seconds.c.t.desc()).limit(1))
        with self.engine.connect() as conn:
            m = conn.execute(q).mappings().first()
        return _row(m) if m else None

    def purge_before(self, cutoff):
        """Ngoại lệ append-only duy nhất: xóa dữ liệu quá hạn giữ (ING-08)."""
        with self.engine.begin() as conn:
            return conn.execute(delete(quote_seconds).where(quote_seconds.c.t < cutoff)).rowcount
