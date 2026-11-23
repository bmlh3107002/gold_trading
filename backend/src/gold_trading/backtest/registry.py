"""Đăng ký lần chạy backtest theo protocol-1 (GĐ6 bước 7 — thiết kế 39 mục 10; 6-C04).

Ghi **trước** khi chạy: khoảng dữ liệu, ranh giới phát triển / để dành, lưới, dấu vân tay dữ liệu,
phiên bản mã. Chỉ thêm. Lần thử ngoài lưới → ``add_trial`` (cộng vào số lần thử cho Deflated
Sharpe). Đoạn để dành: ``claim_holdout`` ghi dòng **trước** khi chạy, khóa chính = đăng ký → lần
hai bị từ chối (kể cả khi lần đầu lỗi giữa chừng).
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from gold_trading.backtest.protocol import PROTOCOL_ID, Split, grid
from gold_trading.common.ids import new_id
from gold_trading.storage.schema import (
    backtest_holdout_runs,
    backtest_registrations,
    backtest_trials,
)
from gold_trading.strategy.trend_m15 import STRATEGY_REF


class RegistryError(RuntimeError):
    pass


class HoldoutAlreadyRun(RegistryError):
    """Đoạn để dành của đăng ký này đã chạy (hoặc đã được giành chạy) — không chạy lại."""


@dataclass(frozen=True)
class Registration:
    registration_id: str
    created_at: datetime
    created_by: str
    protocol_id: str
    strategy_ref: str
    data_start: datetime
    dev_end: datetime
    data_end: datetime
    grid: tuple[str, ...]
    data_fingerprint: str
    code_version: str
    notes: str


@dataclass(frozen=True)
class HoldoutClaim:
    registration_id: str
    started_at: datetime
    started_by: str
    combo: str


def data_fingerprint(parts: Iterable[str]) -> str:
    """SHA-256 của các dòng mô tả dữ liệu (nến + MarketView tầng 1). Đổi một số → đổi dấu."""
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode())
        h.update(b"\n")
    return h.hexdigest()


def _utc(t: datetime) -> datetime:
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


def new_registration(split: Split, *, fingerprint: str, code_version: str, created_by: str,
                     at: datetime, notes: str = "") -> Registration:
    if not created_by or not code_version or len(fingerprint) != 64:
        raise RegistryError("thiếu người đăng ký / phiên bản mã / dấu vân tay dữ liệu")
    return Registration(new_id("btr"), at, created_by, PROTOCOL_ID, STRATEGY_REF,
                        split.data_start, split.dev_end, split.data_end,
                        tuple(c.key for c in grid()), fingerprint, code_version, notes)


class RegistryStore(Protocol):
    def register(self, r: Registration) -> None: ...
    def get(self, registration_id: str) -> Registration | None: ...
    def add_trial(self, registration_id: str, description: str, *, by: str,
                  at: datetime) -> None: ...
    def trials(self, registration_id: str) -> list[str]: ...
    def claim_holdout(self, registration_id: str, combo: str, *, by: str,
                      at: datetime) -> HoldoutClaim: ...
    def holdout(self, registration_id: str) -> HoldoutClaim | None: ...


def n_trials(store: RegistryStore, r: Registration) -> int:
    """Số lần thử cho Deflated Sharpe = lưới đã đăng ký + mọi lần thử thêm đã ghi."""
    return len(r.grid) + len(store.trials(r.registration_id))


class InMemoryRegistryStore:
    def __init__(self) -> None:
        self._regs: dict[str, Registration] = {}
        self._trials: dict[str, list[str]] = {}
        self._holdout: dict[str, HoldoutClaim] = {}
        self._lock = threading.Lock()

    def register(self, r):
        with self._lock:
            if r.registration_id in self._regs:
                raise RegistryError("đăng ký đã tồn tại")
            self._regs[r.registration_id] = r

    def get(self, registration_id):
        return self._regs.get(registration_id)

    def add_trial(self, registration_id, description, *, by, at):
        if registration_id not in self._regs or not description or not by:
            raise RegistryError("đăng ký không có / thiếu mô tả / thiếu người ghi")
        with self._lock:
            self._trials.setdefault(registration_id, []).append(description)

    def trials(self, registration_id):
        return list(self._trials.get(registration_id, []))

    def claim_holdout(self, registration_id, combo, *, by, at):
        if registration_id not in self._regs:
            raise RegistryError("đăng ký không có")
        with self._lock:
            if registration_id in self._holdout:
                raise HoldoutAlreadyRun(registration_id)
            c = HoldoutClaim(registration_id, at, by, combo)
            self._holdout[registration_id] = c
            return c

    def holdout(self, registration_id):
        return self._holdout.get(registration_id)


class SqlRegistryStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def register(self, r):
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(backtest_registrations).values(
                    registration_id=r.registration_id, created_at=r.created_at,
                    created_by=r.created_by, protocol_id=r.protocol_id,
                    strategy_ref=r.strategy_ref, data_start=r.data_start, dev_end=r.dev_end,
                    data_end=r.data_end, grid=list(r.grid), data_fingerprint=r.data_fingerprint,
                    code_version=r.code_version, notes=r.notes))
        except IntegrityError as e:
            raise RegistryError("đăng ký đã tồn tại hoặc sai thứ tự thời gian") from e

    def get(self, registration_id):
        with self.engine.connect() as conn:
            m = conn.execute(select(backtest_registrations).where(
                backtest_registrations.c.registration_id == registration_id)).first()
        if m is None:
            return None
        return Registration(m.registration_id, _utc(m.created_at), m.created_by, m.protocol_id,
                            m.strategy_ref, _utc(m.data_start), _utc(m.dev_end),
                            _utc(m.data_end), tuple(m.grid), m.data_fingerprint,
                            m.code_version, m.notes)

    def add_trial(self, registration_id, description, *, by, at):
        if self.get(registration_id) is None or not description or not by:
            raise RegistryError("đăng ký không có / thiếu mô tả / thiếu người ghi")
        with self.engine.begin() as conn:
            conn.execute(insert(backtest_trials).values(
                registration_id=registration_id, created_at=at, created_by=by,
                description=description))

    def trials(self, registration_id):
        c = backtest_trials.c
        with self.engine.connect() as conn:
            rows = conn.execute(select(c.description).where(c.registration_id == registration_id)
                                .order_by(c.seq)).all()
        return [r[0] for r in rows]

    def claim_holdout(self, registration_id, combo, *, by, at):
        if self.get(registration_id) is None:
            raise RegistryError("đăng ký không có")
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(backtest_holdout_runs).values(
                    registration_id=registration_id, started_at=at, started_by=by, combo=combo))
        except IntegrityError as e:
            raise HoldoutAlreadyRun(registration_id) from e
        return HoldoutClaim(registration_id, at, by, combo)

    def holdout(self, registration_id):
        c = backtest_holdout_runs.c
        with self.engine.connect() as conn:
            m = conn.execute(select(backtest_holdout_runs).where(
                c.registration_id == registration_id)).first()
        return None if m is None else HoldoutClaim(m.registration_id, _utc(m.started_at),
                                                   m.started_by, m.combo)

    def count(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(
                backtest_registrations)).scalar_one())


def check_grid(r: Registration, keys: Sequence[str]) -> None:
    """Chỉ chạy đúng lưới đã đăng ký (6-C04); khác → lỗi (thử thêm phải ghi ``add_trial``)."""
    if tuple(keys) != r.grid:
        raise RegistryError("lưới chạy khác lưới đã đăng ký")
