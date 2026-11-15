"""Kho giá sống theo giây (ING-08): bộ nhớ (test/dev) và SQL. Mỗi (nguồn, giây) ghi một lần.

ING-35: kho thống kê spread theo phút (``quote_minutes``, chỉ-thêm, giữ vĩnh viễn, có revision)."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from gold_trading.market.quote_minutes import QuoteMinute
from gold_trading.market.quotes import QuoteSecond
from gold_trading.storage.schema import quote_minutes, quote_seconds


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

    def feeds_between(self, lo, hi):
        with self._lock:
            return sorted({f for (f, t) in self._rows if lo <= t < hi})

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

    def feeds_between(self, lo, hi):
        q = (select(quote_seconds.c.feed_id).distinct()
             .where(quote_seconds.c.t >= lo, quote_seconds.c.t < hi))
        with self.engine.connect() as conn:
            return sorted(r[0] for r in conn.execute(q))

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


def _pick(rows: list[QuoteMinute], as_of: datetime | None) -> dict[datetime, QuoteMinute]:
    """Revision mới nhất của mỗi phút (đã biết tại ``as_of`` nếu có)."""
    out: dict[datetime, QuoteMinute] = {}
    for r in rows:
        if as_of is not None and r.available_at > as_of:
            continue
        cur = out.get(r.t)
        if cur is None or r.revision > cur.revision:
            out[r.t] = r
    return out


class InMemoryQuoteMinuteStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, datetime, int], QuoteMinute] = {}
        self._lock = threading.Lock()

    def _between(self, feed, lo, hi):
        with self._lock:
            return [r for (f, t, _), r in self._rows.items() if f == feed and lo <= t < hi]

    def latest_revisions(self, feed, lo, hi):
        return _pick(self._between(feed, lo, hi), None)

    def append(self, rows):
        n = 0
        with self._lock:
            for r in rows:
                k = (r.feed_id, r.t, r.revision)
                if k not in self._rows:
                    self._rows[k] = r
                    n += 1
        return n

    def query(self, feed, lo, hi, *, as_of):
        return [v for _, v in sorted(_pick(self._between(feed, lo, hi), as_of).items())]


_MIN_COLS = ("seconds", "ticks", "bid_open", "bid_close", "ask_close", "bid_low", "ask_high",
             "spread_min", "spread_median", "spread_p95", "spread_max", "seconds_wide",
             "seconds_closed", "version", "revision")


def _minute(m) -> QuoteMinute:
    return QuoteMinute(feed_id=m.feed_id, t=_utc(m.t), **{c: m[c] for c in _MIN_COLS},
                       computed_at=_utc(m.computed_at), available_at=_utc(m.available_at))


class SqlQuoteMinuteStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _between(self, feed, lo, hi, as_of=None):
        c = quote_minutes.c
        q = select(quote_minutes).where(c.feed_id == feed, c.t >= lo, c.t < hi)
        if as_of is not None:
            q = q.where(c.available_at <= as_of)
        with self.engine.connect() as conn:
            return [_minute(m) for m in conn.execute(q).mappings()]

    def latest_revisions(self, feed, lo, hi):
        return _pick(self._between(feed, lo, hi), None)

    def append(self, rows):
        if not rows:
            return 0
        values = [dict(feed_id=r.feed_id, t=r.t, **{c: getattr(r, c) for c in _MIN_COLS},
                       computed_at=r.computed_at, available_at=r.available_at) for r in rows]
        with self.engine.begin() as conn:
            if self.engine.dialect.name == "postgresql":
                res = conn.execute(
                    pg_insert(quote_minutes).values(values)
                    .on_conflict_do_nothing(index_elements=["feed_id", "t", "revision"])
                    .returning(quote_minutes.c.t))
                return len(res.fetchall())
            n = 0
            for v in values:
                c = quote_minutes.c
                if conn.execute(select(c.t).where(c.feed_id == v["feed_id"], c.t == v["t"],
                                                  c.revision == v["revision"])).first() is None:
                    conn.execute(quote_minutes.insert().values(**v))
                    n += 1
            return n

    def query(self, feed, lo, hi, *, as_of):
        return [v for _, v in sorted(_pick(self._between(feed, lo, hi, as_of), as_of).items())]

    def summary(self) -> list[tuple]:
        """(nguồn, số phút, phút đầu, phút cuối) — cho lệnh kiểm chỉ đọc."""
        c = quote_minutes.c
        q = (select(c.feed_id, func.count(func.distinct(c.t)), func.min(c.t), func.max(c.t))
             .group_by(c.feed_id).order_by(c.feed_id))
        with self.engine.connect() as conn:
            return [(f, n, _utc(a), _utc(b)) for f, n, a, b in conn.execute(q)]
