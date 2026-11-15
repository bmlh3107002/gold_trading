"""Kho MarketView + vô hiệu (GĐ4 bước 5a — MKV-02; 4-C05; 2-C06). Thiết kế 33 mục 7.

Bất biến phía dùng (``current``): chỉ trả MarketView **mới nhất đã biết** (``computed_at ≤ at``) của
đúng nguồn giá, nếu nó còn hạn tại ``at`` và chưa bị vô hiệu tới ``at``. MarketView mới nhất đã hết
hạn / bị vô hiệu → ``None`` — **không lùi về bản cũ hơn** (không có MarketView → không có tín hiệu).
Chỉ thêm: ghi lại cùng id bị bỏ qua; vô hiệu một lần / view.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from gold_trading.analysts.framework import Scope
from gold_trading.contracts.market_view import MarketView
from gold_trading.storage.schema import market_view_invalidations, market_views

REASON_MAX = 64


@dataclass(frozen=True)
class StoredView:
    view: MarketView
    report_id: str
    computed_at: datetime
    invalidated_at: datetime | None = None
    reason: str | None = None
    ref: str = ""


def _key(v: MarketView) -> tuple[str, str, str, str]:
    return (v.source, v.feed_id, v.symbol, v.timeframe)


def _scope_key(s: Scope) -> tuple[str, str, str, str]:
    if s.is_global:
        raise ValueError("MarketView theo nguồn giá cụ thể, không có phạm vi toàn cục")
    return (s.source, s.feed, s.symbol, s.timeframe)


def _check_reason(reason: str) -> None:
    if not reason or len(reason) > REASON_MAX:
        raise ValueError("lý do vô hiệu phải là mã ngắn (1–64 ký tự)")


def _visible(sv: StoredView, at: datetime) -> StoredView:
    """Ẩn phần vô hiệu xảy ra sau ``at`` (point-in-time)."""
    if sv.invalidated_at is not None and sv.invalidated_at > at:
        return StoredView(sv.view, sv.report_id, sv.computed_at)
    return sv


def usable(sv: StoredView | None, at: datetime) -> MarketView | None:
    if sv is None or sv.invalidated_at is not None or not sv.view.is_valid_at(at):
        return None
    return sv.view


class MarketViewStore(Protocol):
    def append(self, view: MarketView, *, report_id: str, computed_at: datetime) -> bool: ...
    def invalidate(self, market_view_id: str, *, at: datetime, reason: str, ref: str = ""
                   ) -> bool: ...
    def latest(self, scope: Scope, *, known_by: datetime) -> StoredView | None: ...
    def current(self, scope: Scope, at: datetime) -> MarketView | None: ...
    def computed_between(self, lo: datetime, hi: datetime) -> list[StoredView]: ...


class InMemoryMarketViewStore:
    def __init__(self) -> None:
        self._views: dict[str, StoredView] = {}
        self._inv: dict[str, tuple[datetime, str, str]] = {}
        self._lock = threading.Lock()

    def append(self, view, *, report_id, computed_at):
        with self._lock:
            if view.market_view_id in self._views:
                return False
            self._views[view.market_view_id] = StoredView(view, report_id, computed_at)
            return True

    def invalidate(self, market_view_id, *, at, reason, ref=""):
        _check_reason(reason)
        with self._lock:
            if market_view_id not in self._views:
                raise KeyError(f"không có MarketView {market_view_id!r}")
            if market_view_id in self._inv:
                return False
            self._inv[market_view_id] = (at, reason, ref)
            return True

    def latest(self, scope, *, known_by):
        key = _scope_key(scope)
        with self._lock:
            rows = [sv for sv in self._views.values()
                    if _key(sv.view) == key and sv.computed_at <= known_by]
            if not rows:
                return None
            sv = max(rows, key=lambda r: (r.view.as_of, r.computed_at, r.view.market_view_id))
            inv = self._inv.get(sv.view.market_view_id)
        if inv is not None:
            sv = StoredView(sv.view, sv.report_id, sv.computed_at, *inv)
        return _visible(sv, known_by)

    def current(self, scope, at):
        return usable(self.latest(scope, known_by=at), at)

    def computed_between(self, lo, hi):
        """MarketView có ``lo < computed_at <= hi`` + vô hiệu đã biết tới ``hi`` (kiểm Gate GĐ4)."""
        with self._lock:
            rows = [sv for sv in self._views.values() if lo < sv.computed_at <= hi]
            inv = dict(self._inv)
        out = []
        for sv in rows:
            i = inv.get(sv.view.market_view_id)
            out.append(_visible(StoredView(sv.view, sv.report_id, sv.computed_at, *i), hi)
                       if i else sv)
        return sorted(out, key=lambda r: (r.computed_at, r.view.market_view_id))


def _utc(v: datetime) -> datetime:
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


class SqlMarketViewStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _insert(self, table, row: dict, key: str, exists) -> bool:
        with self.engine.begin() as conn:
            if self.engine.dialect.name == "postgresql":
                res = conn.execute(pg_insert(table).values(**row)
                                   .on_conflict_do_nothing(index_elements=[key])
                                   .returning(table.c[key]))
                return res.first() is not None
            if exists(conn):
                return False
            try:
                conn.execute(table.insert().values(**row))
            except IntegrityError:
                with self.engine.connect() as again:
                    if not exists(again):
                        raise       # vi phạm ràng buộc (CHECK / FK), không phải trùng id
                return False
            return True

    def append(self, view, *, report_id, computed_at):
        c = market_views.c
        row = dict(market_view_id=view.market_view_id, snapshot_id=view.snapshot_id,
                   report_id=report_id, symbol=view.symbol, timeframe=view.timeframe,
                   source=view.source, feed_id=view.feed_id, as_of=view.as_of,
                   expires_at=view.expires_at, computed_at=computed_at, bias=view.bias.value,
                   confidence=view.confidence, model_version=view.model_version,
                   payload=view.model_dump(mode="json"))
        return self._insert(market_views, row, "market_view_id", lambda conn: conn.execute(
            select(c.market_view_id).where(c.market_view_id == view.market_view_id)).first())

    def invalidate(self, market_view_id, *, at, reason, ref=""):
        _check_reason(reason)
        with self.engine.connect() as conn:
            if conn.execute(select(market_views.c.market_view_id).where(
                    market_views.c.market_view_id == market_view_id)).first() is None:
                raise KeyError(f"không có MarketView {market_view_id!r}")
        i = market_view_invalidations.c
        return self._insert(
            market_view_invalidations,
            dict(market_view_id=market_view_id, invalidated_at=at, reason=reason, ref=ref[:256]),
            "market_view_id", lambda conn: conn.execute(
                select(i.market_view_id).where(i.market_view_id == market_view_id)).first())

    def latest(self, scope, *, known_by):
        src, feed, sym, tf = _scope_key(scope)
        c, i = market_views.c, market_view_invalidations.c
        q = (select(c.payload, c.report_id, c.computed_at, i.invalidated_at, i.reason, i.ref)
             .select_from(market_views.outerjoin(
                 market_view_invalidations, i.market_view_id == c.market_view_id))
             .where(c.source == src, c.feed_id == feed, c.symbol == sym, c.timeframe == tf,
                    c.computed_at <= known_by)
             .order_by(c.as_of.desc(), c.computed_at.desc(), c.market_view_id.desc()).limit(1))
        with self.engine.connect() as conn:
            m = conn.execute(q).first()
        if m is None:
            return None
        sv = StoredView(MarketView.model_validate(m.payload), m.report_id, _utc(m.computed_at),
                        _utc(m.invalidated_at) if m.invalidated_at is not None else None,
                        m.reason, m.ref or "")
        return _visible(sv, known_by)

    def current(self, scope, at):
        return usable(self.latest(scope, known_by=at), at)

    def computed_between(self, lo, hi):
        """MarketView có ``lo < computed_at <= hi`` + vô hiệu đã biết tới ``hi`` (kiểm Gate GĐ4)."""
        c, i = market_views.c, market_view_invalidations.c
        q = (select(c.payload, c.report_id, c.computed_at, i.invalidated_at, i.reason, i.ref)
             .select_from(market_views.outerjoin(
                 market_view_invalidations, i.market_view_id == c.market_view_id))
             .where(c.computed_at > lo, c.computed_at <= hi)
             .order_by(c.computed_at, c.market_view_id))
        with self.engine.connect() as conn:
            rows = conn.execute(q).all()
        return [_visible(StoredView(MarketView.model_validate(m.payload), m.report_id,
                                    _utc(m.computed_at),
                                    _utc(m.invalidated_at) if m.invalidated_at else None,
                                    m.reason, m.ref or ""), hi) for m in rows]
