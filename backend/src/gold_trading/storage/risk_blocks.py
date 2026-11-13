"""Lệnh cấm có hạn của làn nhanh bằng SQL (GĐ2 bước 4a, migration 0016).

Cùng giao diện + quy tắc với ``gold_trading.risk.blocks.BlockStore``. Ghi trùng → False (kể cả
hai tiến trình cùng lúc: khóa chính quyết định).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, and_, or_, select
from sqlalchemy.exc import IntegrityError

from gold_trading.risk.blocks import ALL, Block, BlockKind, Lift
from gold_trading.storage.schema import risk_block_lifts, risk_blocks

_B = risk_blocks.c
_L = risk_block_lifts.c


def _utc(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


def _req(v: datetime) -> datetime:
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError("thời điểm phải có múi giờ (UTC)")
    return v.astimezone(UTC)


def _block(m) -> Block:
    return Block(BlockKind(m.kind), m.scope, m.reason_code, _utc(m.start_at), _utc(m.end_at),
                 m.cause_ref, _utc(m.created_at), m.policy_version, m.latency_ms)


class SqlBlockStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def add(self, b: Block) -> bool:
        try:
            with self.engine.begin() as conn:
                if conn.execute(select(_B.block_id).where(_B.block_id == b.block_id)).first():
                    return False
                conn.execute(risk_blocks.insert().values(
                    block_id=b.block_id, kind=b.kind.value, scope=b.scope,
                    reason_code=b.reason_code, start_at=b.start_at, end_at=b.end_at,
                    cause_ref=b.cause_ref, created_at=b.created_at,
                    policy_version=b.policy_version, latency_ms=b.latency_ms))
        except IntegrityError:
            return False
        return True

    def lift(self, x: Lift) -> bool:
        try:
            with self.engine.begin() as conn:
                if not conn.execute(select(_B.block_id).where(_B.block_id == x.block_id)).first():
                    raise ValueError("lệnh cấm chưa có")
                if conn.execute(select(_L.block_id).where(_L.block_id == x.block_id)).first():
                    return False
                conn.execute(risk_block_lifts.insert().values(
                    block_id=x.block_id, lifted_at=x.lifted_at, reason_code=x.reason_code))
        except IntegrityError:
            return False
        return True

    def get(self, block_id: str):
        with self.engine.connect() as conn:
            m = conn.execute(select(risk_blocks).where(_B.block_id == block_id)
                             ).mappings().first()
            if m is None:
                return None
            lm = conn.execute(select(risk_block_lifts).where(_L.block_id == block_id)
                              ).mappings().first()
        lift = Lift(lm.block_id, _utc(lm.lifted_at), lm.reason_code) if lm else None
        return _block(m), lift

    def _visible(self, at: datetime):
        lifted = select(_L.block_id).where(_L.lifted_at <= at)
        return [_B.created_at <= at, _B.block_id.not_in(lifted)]

    def active(self, at: datetime, feed: str | None = None) -> list[Block]:
        at = _req(at)
        scopes = [ALL] + ([feed] if feed is not None else [])
        q = (select(risk_blocks).where(
            *self._visible(at), _B.start_at <= at, _B.scope.in_(scopes),
            or_(_B.end_at.is_(None), _B.end_at > at))
             .order_by(_B.start_at, _B.block_id))
        with self.engine.connect() as conn:
            return [_block(m) for m in conn.execute(q).mappings()]

    def open_spread(self, at: datetime) -> list[Block]:
        at = _req(at)
        q = select(risk_blocks).where(and_(*self._visible(at),
                                           _B.kind == BlockKind.SPREAD.value))
        with self.engine.connect() as conn:
            return [_block(m) for m in conn.execute(q).mappings()]
