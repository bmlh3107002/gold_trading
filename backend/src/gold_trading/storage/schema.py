"""Định nghĩa bảng. Mọi bảng là append-only: không UPDATE/DELETE, trạng thái hiện tại = event cuối.

Migration nằm ở backend/migrations (Alembic) và phải khớp với file này.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

DEFAULT_ACCOUNT_ID = "default"
ACCOUNT_ROLES = ("OWNER", "OPERATOR", "VIEWER")

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
    # migration 0004: Safety theo từng tài khoản giao dịch
    Column("account_id", String(64), ForeignKey("trading_accounts.account_id"), nullable=False),
)
Index("ix_safety_transitions_account", safety_transitions.c.account_id, safety_transitions.c.seq)

mode_changes = Table(
    "mode_changes",
    metadata,
    Column("seq", SeqId, Identity(), primary_key=True),
    Column("from_mode", String(16), nullable=False),
    Column("to_mode", String(16), nullable=False),
    Column("actor", String(128), nullable=False),
    Column("approver", String(128)),
    Column("at", DateTime(timezone=True), nullable=False),
    Column("account_id", String(64), ForeignKey("trading_accounts.account_id"), nullable=False),
)
Index("ix_mode_changes_account", mode_changes.c.account_id, mode_changes.c.seq)

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
    # NULL = sự kiện hệ thống (đăng nhập, kill switch toàn hệ thống...)
    Column("account_id", String(64)),
    Column("actor_sub", String(255)),
)
Index("ix_audit_log_at", audit_log.c.at)
Index("ix_audit_log_account", audit_log.c.account_id, audit_log.c.seq)


# --- Người dùng, tài khoản giao dịch, phân quyền (migration 0004) ---

users = Table(
    "users",
    metadata,
    Column("sub", String(255), primary_key=True),  # `sub` của Keycloak
    Column("username", String(128), nullable=False),
    Column("email", String(256)),
    Column("display_name", String(256)),
    # NULL = do ADMIN tạo trên Dashboard (MT-20), chưa đăng nhập lần nào (migration 0005)
    Column("first_login_at", DateTime(timezone=True)),
    Column("last_login_at", DateTime(timezone=True)),
    # DEC-16 (migration 0006): chỉ hai vai trò và hai trạng thái
    Column("role", String(8), nullable=False, server_default="USER"),
    Column("status", String(8), nullable=False, server_default="ACTIVE"),
    Column("updated_at", DateTime(timezone=True)),
    CheckConstraint("role IN ('ADMIN', 'USER')", name="ck_users_role"),
    # DEC-17 (migration 0007): DELETED = ADMIN đã xóa (ẩn, không đăng nhập, token thu hồi; giữ
    # dòng để còn lịch sử)
    CheckConstraint("status IN ('ACTIVE', 'LOCKED', 'DELETED')", name="ck_users_status"),
)
Index("ix_users_username", users.c.username)
Index("ix_users_email", users.c.email)

trading_accounts = Table(
    "trading_accounts",
    metadata,
    Column("account_id", String(64), primary_key=True),
    Column("name", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("created_by", String(128), nullable=False),
    # Được ghi nến vào kho dùng chung (tới MT-05 chỉ tài khoản mặc định)
    Column("price_feed", Boolean, nullable=False),
)

account_members = Table(
    "account_members",
    metadata,
    Column("account_id", String(64), ForeignKey("trading_accounts.account_id"), nullable=False),
    Column("sub", String(255), ForeignKey("users.sub"), nullable=False),
    Column("role", String(16), nullable=False),
    Column("granted_at", DateTime(timezone=True), nullable=False),
    Column("granted_by", String(128), nullable=False),
    PrimaryKeyConstraint("account_id", "sub"),
    CheckConstraint("role IN ('OWNER', 'OPERATOR', 'VIEWER')", name="ck_account_members_role"),
)

gateway_tokens = Table(
    "gateway_tokens",
    metadata,
    Column("seq", SeqId, Identity(), primary_key=True),
    Column("token_id", String(64), nullable=False, unique=True),
    Column("account_id", String(64), ForeignKey("trading_accounts.account_id"), nullable=False),
    Column("token_sha256", String(64), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("created_by", String(128), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
)
Index("ix_gateway_tokens_account", gateway_tokens.c.account_id)

# DEC-17 (migration 0007): USER xin cấp token Gateway, ADMIN cấp hoặc từ chối. Chỉ thêm dòng:
# trạng thái hiện tại của một tài khoản = sự kiện cuối cùng.
TOKEN_REQUEST_EVENTS = ("REQUESTED", "APPROVED", "REJECTED", "CANCELLED")

gateway_token_requests = Table(
    "gateway_token_requests",
    metadata,
    Column("seq", SeqId, Identity(), primary_key=True),
    Column("account_id", String(64), ForeignKey("trading_accounts.account_id"), nullable=False),
    Column("sub", String(255), ForeignKey("users.sub"), nullable=False),
    Column("event", String(16), nullable=False),
    Column("at", DateTime(timezone=True), nullable=False),
    Column("actor", String(128), nullable=False),
    CheckConstraint("event IN ('REQUESTED', 'APPROVED', 'REJECTED', 'CANCELLED')",
                    name="ck_gateway_token_requests_event"),
)
Index("ix_gateway_token_requests_account", gateway_token_requests.c.account_id,
      gateway_token_requests.c.seq)


# MT-13 (migration 0008): liên kết tài khoản giao dịch ↔ MT5 ``(login, server)`` do terminal báo.
# Chỉ thêm dòng và đổi trạng thái (không xóa; Postgres có trigger chặn DELETE); mỗi lần đổi trạng
# thái đều ghi audit. Liên kết MT5 mới luôn là DÒNG MỚI (lịch sử cũ không trộn, MT-C14).
#
# "Đang giữ" (HELD) = ACTIVE / MISMATCH / DISCONNECTED: liên kết vẫn thuộc tài khoản dù đang bị
# chặn (MT-14). Index duy nhất có điều kiện bảo đảm ngay ở DB:
#   - một ``(login, server)`` chỉ được GIỮ ở một tài khoản giao dịch (MT-C11);
#   - mỗi tài khoản giữ tối đa một liên kết, và có tối đa một liên kết chờ xác nhận.
MT5_LINK_STATUSES = (
    "PENDING_CONFIRM", "ACTIVE", "MISMATCH", "DISCONNECTED", "REVOKED", "CANCELLED",
)
MT5_LINK_HELD = ("ACTIVE", "MISMATCH", "DISCONNECTED")
_HELD_SQL = "status IN ('ACTIVE', 'MISMATCH', 'DISCONNECTED')"
_PENDING_SQL = "status = 'PENDING_CONFIRM'"

mt5_links = Table(
    "mt5_links",
    metadata,
    Column("seq", SeqId, Identity(), primary_key=True),
    Column("link_id", String(64), nullable=False, unique=True),
    Column("account_id", String(64), ForeignKey("trading_accounts.account_id"), nullable=False),
    Column("mt5_login", BigInteger, nullable=False),
    Column("mt5_server", String(256), nullable=False),
    Column("mt5_company", String(256)),
    Column("trade_mode", String(16), nullable=False),  # DEMO | CONTEST | REAL
    Column("gateway_id", String(64), nullable=False),
    # Token Gateway đã gửi danh tính. NULL = token cũ GT_INGEST_TOKEN (chỉ tài khoản mặc định)
    Column("token_id", String(64)),
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("verified_at", DateTime(timezone=True)),
    Column("verified_by", String(128)),
    Column("ended_at", DateTime(timezone=True)),
    Column("ended_by", String(128)),
    Column("end_reason", String(128)),
    CheckConstraint(
        "status IN ('PENDING_CONFIRM', 'ACTIVE', 'MISMATCH', 'DISCONNECTED', 'REVOKED', "
        "'CANCELLED')", name="ck_mt5_links_status",
    ),
    CheckConstraint("trade_mode IN ('DEMO', 'CONTEST', 'REAL')", name="ck_mt5_links_trade_mode"),
    CheckConstraint("mt5_login > 0", name="ck_mt5_links_login"),
)
Index("ix_mt5_links_account", mt5_links.c.account_id, mt5_links.c.seq)
# Server so không phân biệt hoa/thường: "Broker-Demo" và "broker-demo" là cùng một MT5.
Index("uq_mt5_links_identity_held", mt5_links.c.mt5_login, func.lower(mt5_links.c.mt5_server),
      unique=True, postgresql_where=text(_HELD_SQL), sqlite_where=text(_HELD_SQL))
Index("uq_mt5_links_account_held", mt5_links.c.account_id, unique=True,
      postgresql_where=text(_HELD_SQL), sqlite_where=text(_HELD_SQL))
Index("uq_mt5_links_account_pending", mt5_links.c.account_id, unique=True,
      postgresql_where=text(_PENDING_SQL), sqlite_where=text(_PENDING_SQL))

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
