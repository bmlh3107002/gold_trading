"""Định nghĩa bảng. Mọi bảng là append-only: không UPDATE/DELETE, trạng thái hiện tại = event cuối.

Migration nằm ở backend/migrations (Alembic) và phải khớp với file này.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    Float,
    Identity,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
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


# --- Dữ liệu thị trường (migration 0002) ---

candles = Table(
    "candles",
    metadata,
    Column("symbol", String(32), nullable=False),
    Column("timeframe", String(8), nullable=False),
    Column("source", String(16), nullable=False),
    Column("open_time", DateTime(timezone=True), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("close_time", DateTime(timezone=True), nullable=False),
    Column("open", Float, nullable=False),
    Column("high", Float, nullable=False),
    Column("low", Float, nullable=False),
    Column("close", Float, nullable=False),
    Column("tick_volume", BigInteger, nullable=False),
    Column("spread_points", Integer),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("flags", JsonType, nullable=False),
    PrimaryKeyConstraint("symbol", "timeframe", "source", "open_time", "revision"),
)

candle_quarantine = Table(
    "candle_quarantine",
    metadata,
    Column("seq", SeqId, Identity(), primary_key=True),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("source", String(16), nullable=False),
    Column("symbol", String(32), nullable=False),
    Column("timeframe", String(8), nullable=False),
    Column("reason", String(64), nullable=False),
    Column("raw", JsonType, nullable=False),
)


# --- Kết quả analyst (migration 0003) ---

analyst_outputs = Table(
    "analyst_outputs",
    metadata,
    Column("seq", SeqId, Identity(), primary_key=True),
    Column("output_id", String(256), nullable=False, unique=True),
    Column("analyst_id", String(32), nullable=False),
    Column("version", String(32), nullable=False),
    Column("symbol", String(32), nullable=False),
    Column("timeframe", String(8), nullable=False),
    Column("source", String(16), nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("computed_at", DateTime(timezone=True), nullable=False),
    Column("source_status", String(16), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("payload", JsonType, nullable=False),
)
Index(
    "ix_analyst_outputs_lookup",
    analyst_outputs.c.analyst_id,
    analyst_outputs.c.symbol,
    analyst_outputs.c.timeframe,
    analyst_outputs.c.source,
    analyst_outputs.c.as_of,
)
