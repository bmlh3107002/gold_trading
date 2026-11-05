"""Định nghĩa bảng. Mọi bảng là append-only: không UPDATE/DELETE, trạng thái hiện tại = event cuối.

Migration nằm ở backend/migrations (Alembic) và phải khớp với file này.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    Identity,
    Index,
    Integer,
    MetaData,
    String,
    Table,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

JsonType = JSON().with_variant(JSONB(), "postgresql")
# SQLite chỉ tự tăng với INTEGER PRIMARY KEY; Postgres dùng BIGINT IDENTITY.
SeqId = BigInteger().with_variant(Integer(), "sqlite")

safety_transitions = Table(
    "safety_transitions",
    metadata,
    Column("seq", SeqId, Identity(), primary_key=True),
    Column("transition_id", String(64), nullable=False, unique=True),
    Column("from_state", String(16), nullable=False),
    Column("to_state", String(16), nullable=False),
    Column("reason_code", String(128), nullable=False),
    Column("trigger_source", String(64), nullable=False),
    Column("actor", String(128), nullable=False),
    Column("at", DateTime(timezone=True), nullable=False),
    Column("policy_version", String(64), nullable=False),
)

mode_changes = Table(
    "mode_changes",
    metadata,
    Column("seq", SeqId, Identity(), primary_key=True),
    Column("from_mode", String(16), nullable=False),
    Column("to_mode", String(16), nullable=False),
    Column("actor", String(128), nullable=False),
    Column("approver", String(128)),
    Column("at", DateTime(timezone=True), nullable=False),
)

audit_log = Table(
    "audit_log",
    metadata,
    Column("seq", SeqId, Identity(), primary_key=True),
    Column("at", DateTime(timezone=True), nullable=False),
    Column("actor", String(128), nullable=False),
    Column("action", String(64), nullable=False),
    Column("outcome", String(16), nullable=False),  # ACCEPTED | REJECTED | NOOP
    Column("payload", JsonType, nullable=False),
    Column("detail", String(512)),
)
Index("ix_audit_log_at", audit_log.c.at)
