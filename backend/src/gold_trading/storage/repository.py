"""Repository cho trạng thái vận hành. Có bản bộ nhớ (test/dev) và bản SQL (Postgres)."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import Engine, create_engine, insert, select, text

from gold_trading.common.enums import SafetyState, TradingMode
from gold_trading.common.time import utcnow
from gold_trading.contracts.safety import SafetyTransition
from gold_trading.modes.manager import ModeChange
from gold_trading.storage.schema import audit_log, metadata, mode_changes, safety_transitions


@dataclass(frozen=True)
class AuditEntry:
    at: datetime
    actor: str
    action: str
    outcome: str
    payload: dict[str, Any]
    detail: str | None = None


class Repository(Protocol):
    kind: str

    def healthy(self) -> bool: ...
    def safety_history(self, limit: int = 200) -> list[SafetyTransition]: ...
    def append_safety(self, t: SafetyTransition) -> None: ...
    def last_mode(self) -> TradingMode | None: ...
    def append_mode(self, change: ModeChange) -> None: ...
    def append_audit(self, entry: AuditEntry) -> None: ...
    def audit(self, limit: int = 100) -> list[AuditEntry]: ...


class InMemoryRepository:
    kind = "memory"

    def __init__(self) -> None:
        self._safety: list[SafetyTransition] = []
        self._modes: list[ModeChange] = []
        self._audit: list[AuditEntry] = []
        self._lock = threading.Lock()

    def healthy(self) -> bool:
        return True

    def safety_history(self, limit: int = 200) -> list[SafetyTransition]:
        return self._safety[-limit:]

    def append_safety(self, t: SafetyTransition) -> None:
        with self._lock:
            self._safety.append(t)

    def last_mode(self) -> TradingMode | None:
        return self._modes[-1].to_mode if self._modes else None

    def append_mode(self, change: ModeChange) -> None:
        with self._lock:
            self._modes.append(change)

    def append_audit(self, entry: AuditEntry) -> None:
        with self._lock:
            self._audit.append(entry)

    def audit(self, limit: int = 100) -> list[AuditEntry]:
        return list(reversed(self._audit[-limit:]))


def _row(r) -> dict[str, Any]:
    """Bỏ cột seq; SQLite không lưu timezone nên gắn lại UTC (mọi thời gian lưu là UTC)."""
    out: dict[str, Any] = {}
    for k, v in r.items():
        if k == "seq":
            continue
        if isinstance(v, datetime) and v.tzinfo is None:
            v = v.replace(tzinfo=UTC)
        out[k] = v
    return out


class SqlRepository:
    kind = "postgres"

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        if engine.dialect.name != "postgresql":
            self.kind = engine.dialect.name

    @classmethod
    def from_url(cls, url: str) -> SqlRepository:
        return cls(create_engine(url, pool_pre_ping=True, future=True))

    def create_all(self) -> None:
        """Chỉ dùng cho test (SQLite). Môi trường thật dùng Alembic."""
        metadata.create_all(self.engine)

    def healthy(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def safety_history(self, limit: int = 200) -> list[SafetyTransition]:
        q = select(safety_transitions).order_by(safety_transitions.c.seq.desc()).limit(limit)
        with self.engine.connect() as conn:
            rows = conn.execute(q).mappings().all()
        return [SafetyTransition(**_row(r)) for r in reversed(rows)]

    def append_safety(self, t: SafetyTransition) -> None:
        with self.engine.begin() as conn:
            conn.execute(insert(safety_transitions).values(**t.model_dump()))

    def last_mode(self) -> TradingMode | None:
        q = select(mode_changes.c.to_mode).order_by(mode_changes.c.seq.desc()).limit(1)
        with self.engine.connect() as conn:
            value = conn.execute(q).scalar_one_or_none()
        return TradingMode(value) if value else None

    def append_mode(self, change: ModeChange) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                insert(mode_changes).values(
                    from_mode=change.from_mode,
                    to_mode=change.to_mode,
                    actor=change.actor,
                    approver=change.approver,
                    at=utcnow(),
                )
            )

    def append_audit(self, entry: AuditEntry) -> None:
        with self.engine.begin() as conn:
            conn.execute(insert(audit_log).values(**entry.__dict__))

    def audit(self, limit: int = 100) -> list[AuditEntry]:
        q = select(audit_log).order_by(audit_log.c.seq.desc()).limit(limit)
        with self.engine.connect() as conn:
            rows = conn.execute(q).mappings().all()
        return [AuditEntry(**_row(r)) for r in rows]


def restore_safety_state(history: list[SafetyTransition]) -> tuple[SafetyState, str | None]:
    """Trạng thái khởi động từ lịch sử.

    - HALTED được giữ nguyên: restart không được tự gỡ dừng khẩn cấp.
    - ACTIVE -> PAUSED: sau restart phải kiểm tra lại rồi mới mở lệnh.
    Trả về (trạng thái, reason_code cần ghi nếu phải hạ trạng thái).
    """
    if not history:
        return SafetyState.PAUSED, None
    last = history[-1].to_state
    if last is SafetyState.ACTIVE:
        return SafetyState.ACTIVE, "STARTUP_REQUIRES_REVIEW"
    return last, None


def restore_mode(last: TradingMode | None, default: TradingMode) -> tuple[TradingMode, bool]:
    """Mode khởi động. LIVE không bao giờ được khôi phục tự động -> PAPER."""
    if last is None:
        return default, False
    if last is TradingMode.LIVE:
        return TradingMode.PAPER, True
    return last, False
