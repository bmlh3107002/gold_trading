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
    UniqueConstraint,
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
    # MT-05 (migration 0009): symbol của broker (vd. XAUUSD.r) khóa ở lô nến đầu tiên được ghi.
    # Đổi symbol = nguồn giá khác → phải gỡ + liên kết lại (ING-15).
    Column("broker_symbol", String(64)),
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
    # MT-05 (migration 0009): nguồn giá. "" = không gắn broker (SAMPLE/CSV); nến MT5 có trước
    # 0009 (không biết broker nào) = LEGACY_FEED, không dùng cho tài khoản nào.
    Column("feed_id", String(64), nullable=False, server_default=""),
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
    PrimaryKeyConstraint("symbol", "timeframe", "source", "feed_id", "open_time", "revision"),
)

candle_quarantine = Table(
    "candle_quarantine",
    metadata,
    Column("seq", SeqId, Identity(), primary_key=True),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("source", String(16), nullable=False),
    Column("feed_id", String(64), nullable=False, server_default=""),
    Column("symbol", String(32), nullable=False),
    Column("timeframe", String(8), nullable=False),
    Column("reason", String(64), nullable=False),
    Column("raw", JsonType, nullable=False),
)


# MT-05 (migration 0009): danh mục nguồn giá. feed_id = "pf_" + 24 ký tự hex của
# sha256(lower(server) + "\0" + broker_symbol): cùng server + symbol → cùng feed (dùng chung giữa
# các tài khoản), khác → khác (không trộn). Chỉ thêm dòng.
LEGACY_FEED = "legacy-unknown-broker"

price_feeds = Table(
    "price_feeds",
    metadata,
    Column("feed_id", String(64), primary_key=True),
    Column("mt5_server", String(256), nullable=False),
    Column("broker_symbol", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


# --- Giá sống bid/ask/spread (ING-08, migration 0011) ---
# Gom theo GIÂY (Gateway gom tick của một giây đã trọn): mỗi (nguồn giá, giây) một dòng, ghi một
# lần (không sửa). Ngoại lệ append-only DUY NHẤT: xóa dòng cũ hơn hạn giữ (GT_QUOTE_RETENTION_DAYS)
# — trigger chỉ chặn UPDATE. Point-in-time: available_at = lúc backend nhận.
quote_seconds = Table(
    "quote_seconds",
    metadata,
    Column("feed_id", String(64), nullable=False),
    Column("t", DateTime(timezone=True), nullable=False),  # đầu giây, UTC
    Column("bid", Float, nullable=False),  # giá cuối giây
    Column("ask", Float, nullable=False),
    Column("bid_low", Float, nullable=False),
    Column("ask_high", Float, nullable=False),
    Column("spread_points", Integer, nullable=False),  # spread cuối giây
    Column("spread_max_points", Integer, nullable=False),
    Column("ticks", Integer, nullable=False),
    Column("flags", JsonType, nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("feed_id", "t"),
    CheckConstraint("bid > 0 AND ask >= bid AND bid_low > 0 AND bid_low <= bid "
                    "AND ask_high >= ask", name="ck_quote_seconds_price"),
    CheckConstraint("spread_points >= 0 AND spread_max_points >= 0 AND ticks >= 1",
                    name="ck_quote_seconds_counts"),
)
Index("ix_quote_seconds_available", quote_seconds.c.feed_id, quote_seconds.c.available_at)

# --- Dữ liệu nguồn ngoài: lịch kinh tế, tin, vĩ mô, vị thế (DB-08, ING-13, migration 0012) ---
# Chỉ thêm (trigger chặn UPDATE + DELETE). Mỗi dòng = một revision của một dữ kiện
# (source, logical_key). known_at = max(ingested_at, available_at): đọc tại as_of chỉ thấy dòng có
# known_at <= as_of. Quy tắc đầy đủ: docs/thiet-ke/10-nguon-ngoai.md.
EXTERNAL_KINDS_SQL = "kind IN ('calendar', 'news', 'macro', 'positioning')"

external_records = Table(
    "external_records",
    metadata,
    Column("seq", SeqId, Identity(), primary_key=True),
    Column("record_id", String(256), nullable=False, unique=True),
    Column("source", String(64), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("logical_key", String(256), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("event_time", DateTime(timezone=True), nullable=False),
    Column("available_at", DateTime(timezone=True)),  # NULL = nguồn không cho giờ công bố
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    Column("known_at", DateTime(timezone=True), nullable=False),
    Column("source_status", String(16), nullable=False),
    Column("payload_version", String(32), nullable=False),
    Column("raw_ref", String(1024), nullable=False),
    Column("fingerprint", String(64), nullable=False),
    Column("quality_flags", JsonType, nullable=False),
    Column("payload", JsonType, nullable=False),
    Column("raw", JsonType),
    UniqueConstraint("source", "logical_key", "revision", name="uq_external_records_identity"),
    CheckConstraint(EXTERNAL_KINDS_SQL, name="ck_external_records_kind"),
    CheckConstraint("revision >= 0", name="ck_external_records_revision"),
    CheckConstraint("known_at >= ingested_at AND "
                       "(available_at IS NULL OR known_at >= available_at)",
                    name="ck_external_records_known_at"),
    CheckConstraint("source_status IN ('HEALTHY', 'STALE', 'MISSING', 'INVALID')",
                    name="ck_external_records_status"),
)
Index("ix_external_records_lookup", external_records.c.source, external_records.c.kind,
      external_records.c.event_time)
Index("ix_external_records_known", external_records.c.source, external_records.c.known_at)

external_quarantine = Table(
    "external_quarantine",
    metadata,
    Column("seq", SeqId, Identity(), primary_key=True),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("source", String(64), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("reason", String(64), nullable=False),
    Column("raw", JsonType, nullable=False),
)
Index("ix_external_quarantine_source", external_quarantine.c.source,
      external_quarantine.c.received_at)

# --- Nhật ký các lần kiểm (gọi) nguồn ngoài (ING-30, migration 0013) ---
# Chỉ thêm. Mỗi lần bộ nạp gọi một nguồn ghi một dòng; trạng thái HEALTHY/STALE/MISSING/INVALID
# tính lại từ đây tại mọi as_of (point-in-time). error_code chỉ là mã ngắn (không ghi thông điệp
# lỗi gốc để không lộ khóa API trong URL). Quy tắc: docs/thiet-ke/10-nguon-ngoai.md mục 2.
external_source_checks = Table(
    "external_source_checks",
    metadata,
    Column("seq", SeqId, Identity(), primary_key=True),
    Column("source", String(64), nullable=False),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    Column("outcome", String(16), nullable=False),
    Column("error_code", String(64)),
    Column("inserted", Integer, nullable=False),
    Column("duplicate", Integer, nullable=False),
    Column("conflict", Integer, nullable=False),
    Column("invalid", Integer, nullable=False),
    CheckConstraint("outcome IN ('OK', 'ERROR', 'INVALID')",
                    name="ck_external_source_checks_outcome"),
    CheckConstraint("(outcome = 'OK') = (error_code IS NULL)",
                    name="ck_external_source_checks_error_code"),
    CheckConstraint("inserted >= 0 AND duplicate >= 0 AND conflict >= 0 AND invalid >= 0",
                    name="ck_external_source_checks_counts"),
)
Index("ix_external_source_checks_source", external_source_checks.c.source,
      external_source_checks.c.checked_at)

# --- Kết quả analyst (migration 0003) ---

analyst_outputs = Table(
    "analyst_outputs",
    metadata,
    Column("seq", SeqId, Identity(), primary_key=True),
    # migration 0010: duy nhất theo (feed_id, output_id) — hai broker có thể có nến giống hệt nhau
    Column("output_id", String(256), nullable=False),
    Column("analyst_id", String(32), nullable=False),
    Column("version", String(32), nullable=False),
    Column("symbol", String(32), nullable=False),
    Column("timeframe", String(8), nullable=False),
    Column("source", String(16), nullable=False),
    Column("feed_id", String(64), nullable=False, server_default=""),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("computed_at", DateTime(timezone=True), nullable=False),
    Column("source_status", String(16), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("payload", JsonType, nullable=False),
    UniqueConstraint("feed_id", "output_id", name="uq_analyst_outputs_feed_output"),
)
Index(
    "ix_analyst_outputs_lookup",
    analyst_outputs.c.analyst_id,
    analyst_outputs.c.symbol,
    analyst_outputs.c.timeframe,
    analyst_outputs.c.source,
    analyst_outputs.c.feed_id,
    analyst_outputs.c.as_of,
)


# --- Event Orchestrator (GĐ2 bước 1, migration 0014) — chỉ thêm ---
# Sự kiện suy ra từ dữ liệu đã lưu; event_id duy nhất (ghi lại → bỏ qua). Thiết kế:
# docs/thiet-ke/25-event-orchestrator.md
orchestrator_events = Table(
    "orchestrator_events",
    metadata,
    Column("seq", SeqId, Identity(), primary_key=True),
    Column("event_id", String(40), nullable=False, unique=True),
    Column("event_type", String(32), nullable=False),
    Column("subject", String(256), nullable=False),
    Column("event_version", String(64), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("known_at", DateTime(timezone=True), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("correlation_id", String(40), nullable=False),
    Column("payload", JsonType, nullable=False),
)
Index("ix_orchestrator_events_known", orchestrator_events.c.event_type,
      orchestrator_events.c.known_at)

orchestrator_jobs = Table(
    "orchestrator_jobs",
    metadata,
    Column("job_key", String(512), primary_key=True),
    Column("event_id", String(40), nullable=False),
    Column("job_type", String(48), nullable=False),
    Column("analyzer_version", String(32), nullable=False),
    Column("correlation_id", String(40), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

Index("ix_orchestrator_jobs_created", orchestrator_jobs.c.created_at)  # migration 0015

orchestrator_job_attempts = Table(
    "orchestrator_job_attempts",
    metadata,
    Column("seq", SeqId, Identity(), primary_key=True),
    Column("job_key", String(512), nullable=False),
    Column("state", String(16), nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("at", DateTime(timezone=True), nullable=False),
    Column("deadline_at", DateTime(timezone=True)),
    Column("error_code", String(64)),
    Column("output_ref", String(256)),
    CheckConstraint("state IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'DEAD', "
                    "'NO_HANDLER', 'SUPERSEDED')", name="ck_orchestrator_job_attempts_state"),
    CheckConstraint("attempt >= 0", name="ck_orchestrator_job_attempts_attempt"),
    CheckConstraint("state NOT IN ('FAILED', 'DEAD') OR error_code IS NOT NULL",
                    name="ck_orchestrator_job_attempts_error"),
)
Index("ix_orchestrator_job_attempts_key", orchestrator_job_attempts.c.job_key,
      orchestrator_job_attempts.c.at)


# --- Lệnh cấm mở lệnh mới có hạn của làn nhanh (GĐ2 bước 4a, migration 0016) — chỉ thêm ---
# Thiết kế: docs/thiet-ke/26-lam-nhanh.md (DEC-20)
risk_blocks = Table(
    "risk_blocks",
    metadata,
    Column("block_id", String(40), primary_key=True),
    Column("kind", String(16), nullable=False),
    Column("scope", String(64), nullable=False),
    Column("reason_code", String(64), nullable=False),
    Column("start_at", DateTime(timezone=True), nullable=False),
    Column("end_at", DateTime(timezone=True)),
    Column("cause_ref", String(256), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("policy_version", String(32), nullable=False),
    Column("latency_ms", Integer),
    CheckConstraint("kind IN ('RELEASE', 'NEWS', 'SPREAD', 'LATENCY')",
                    name="ck_risk_blocks_kind"),
    CheckConstraint("end_at IS NULL OR end_at > start_at", name="ck_risk_blocks_window"),
)
Index("ix_risk_blocks_created", risk_blocks.c.created_at)

risk_block_lifts = Table(
    "risk_block_lifts",
    metadata,
    Column("block_id", String(40), primary_key=True),
    Column("lifted_at", DateTime(timezone=True), nullable=False),
    Column("reason_code", String(64), nullable=False),
)


# --- GĐ3 bước 6 (NEWS-02..04, DEC-08): mỗi lần gọi Claude cho một tin — chỉ thêm (migration 0017).
# Vừa là sổ ngân sách (chi phí theo tháng tính từ bảng này) vừa là kết quả trích xuất có phiên bản
# prompt + mô hình. Thiết kế: docs/thiet-ke/32-news-analyst.md
news_llm_calls = Table(
    "news_llm_calls",
    metadata,
    Column("call_id", String(64), primary_key=True),
    Column("story_key", String(256), nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("model", String(64), nullable=False),
    Column("served_model", String(64)),
    Column("prompt_version", String(40), nullable=False),
    Column("status", String(24), nullable=False),
    Column("input_tokens", Integer, nullable=False),
    Column("output_tokens", Integer, nullable=False),
    Column("cost_usd", String(24), nullable=False),        # Decimal dạng chuỗi (tiền)
    Column("error_code", String(64)),
    Column("request_id", String(128)),
    Column("result", JsonType),
    CheckConstraint("status IN ('OK', 'REFUSED', 'ERROR', 'INVALID_OUTPUT', 'TRUNCATED')",
                    name="ck_news_llm_calls_status"),
    CheckConstraint("attempt >= 1", name="ck_news_llm_calls_attempt"),
    UniqueConstraint("story_key", "prompt_version", "model", "attempt",
                     name="uq_news_llm_calls_attempt"),
)
Index("ix_news_llm_calls_created", news_llm_calls.c.created_at)
Index("ix_news_llm_calls_story", news_llm_calls.c.story_key)
