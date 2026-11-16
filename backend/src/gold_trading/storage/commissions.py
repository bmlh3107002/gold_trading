"""Phí hoa hồng khứ hồi / lot của từng tài khoản (GĐ5 RSK-11, Q3) — chỉ thêm, có phiên bản.

MT5 không báo phí trong thông số mã → người dùng nhập theo trang của sàn (đơn vị: tiền tài khoản,
khứ hồi = mở + đóng, cho 1 lot). **Chưa nhập → ``None``** (Risk từ chối ``COMMISSION_UNKNOWN``);
0 chỉ khi người dùng chủ động nhập 0. Thiết kế: docs/thiet-ke/35-risk-engine.md mục 7.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import insert, select
from sqlalchemy.engine import Engine

from gold_trading.storage.schema import account_commissions

MAX_PER_LOT = Decimal("1000")      # chặn gõ nhầm (vd. 7000 thay vì 7); phí thật / lot nhỏ hơn nhiều


@dataclass(frozen=True)
class Commission:
    account_id: str
    per_lot: Decimal
    currency: str
    created_at: datetime
    created_by: str
    reason: str


def _utc(v: datetime) -> datetime:
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError("thời điểm phải có múi giờ (UTC)")
    return v.astimezone(UTC)


def _db(v: datetime) -> datetime:
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


def check(c: Commission) -> Commission:
    if not isinstance(c.per_lot, Decimal) or not c.per_lot.is_finite():
        raise ValueError("phí / lot phải là số thập phân hữu hạn (Decimal)")
    if c.per_lot < 0 or c.per_lot > MAX_PER_LOT:
        raise ValueError(f"phí / lot phải trong [0; {MAX_PER_LOT}]")
    if c.per_lot.as_tuple().exponent < -6:  # type: ignore[operator]
        raise ValueError("phí / lot tối đa 6 chữ số thập phân")
    if c.currency != "USD":
        raise ValueError("GĐ5 chỉ hỗ trợ tài khoản USD (Q2)")
    if not c.created_by or not c.reason or len(c.reason) > 256:
        raise ValueError("cần người nhập và lý do (≤ 256 ký tự)")
    return Commission(c.account_id, c.per_lot, c.currency, _utc(c.created_at), c.created_by,
                      c.reason)


class CommissionStore(Protocol):
    def record(self, c: Commission) -> None: ...
    def at(self, account_id: str, at: datetime) -> Commission | None: ...
    def history(self, account_id: str) -> list[Commission]: ...


class InMemoryCommissionStore:
    def __init__(self) -> None:
        self._rows: list[Commission] = []
        self._lock = threading.Lock()

    def record(self, c):
        c = check(c)
        with self._lock:
            self._rows.append(c)

    def at(self, account_id, at):
        at = _utc(at)
        with self._lock:
            rows = [r for r in self._rows if r.account_id == account_id and r.created_at <= at]
        return max(rows, key=lambda r: r.created_at) if rows else None

    def history(self, account_id):
        with self._lock:
            return [r for r in self._rows if r.account_id == account_id]


class SqlCommissionStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _row(m) -> Commission:
        return Commission(m.account_id, Decimal(str(m.commission_per_lot)), m.currency,
                          _db(m.created_at), m.created_by, m.reason)

    def record(self, c):
        c = check(c)
        with self.engine.begin() as conn:
            conn.execute(insert(account_commissions).values(
                account_id=c.account_id, commission_per_lot=c.per_lot, currency=c.currency,
                created_at=c.created_at, created_by=c.created_by, reason=c.reason))

    def at(self, account_id, at):
        t = account_commissions.c
        with self.engine.connect() as conn:
            m = conn.execute(select(account_commissions).where(
                t.account_id == account_id, t.created_at <= _utc(at))
                .order_by(t.created_at.desc(), t.seq.desc()).limit(1)).first()
        return self._row(m) if m is not None else None

    def history(self, account_id):
        t = account_commissions.c
        with self.engine.connect() as conn:
            rows = conn.execute(select(account_commissions).where(t.account_id == account_id)
                                .order_by(t.created_at, t.seq)).all()
        return [self._row(m) for m in rows]
