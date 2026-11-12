"""DB-08 + ING-13: dữ liệu nguồn ngoài (lịch kinh tế, tin, vĩ mô, vị thế) — point-in-time.

Hai bảng chỉ-thêm (trigger chặn UPDATE + DELETE, như candles ở 0002):
- external_records: mỗi dòng một revision của một dữ kiện (source, logical_key).
- external_quarantine: bản ghi bị từ chối kèm lý do.
Bảng thường (KHÔNG hypertable): lượng dữ liệu nhỏ, khóa duy nhất không chứa cột thời gian.
Quy tắc: docs/thiet-ke/10-nguon-ngoai.md.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_TABLES = ("external_records", "external_quarantine")


def upgrade() -> None:
    op.create_table(
        "external_records",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("record_id", sa.String(256), nullable=False, unique=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("logical_key", sa.String(256), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True)),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_status", sa.String(16), nullable=False),
        sa.Column("payload_version", sa.String(32), nullable=False),
        sa.Column("raw_ref", sa.String(1024), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("raw", postgresql.JSONB()),
        sa.UniqueConstraint("source", "logical_key", "revision",
                            name="uq_external_records_identity"),
        sa.CheckConstraint("kind IN ('calendar', 'news', 'macro', 'positioning')",
                           name="ck_external_records_kind"),
        sa.CheckConstraint("revision >= 0", name="ck_external_records_revision"),
        sa.CheckConstraint("known_at >= ingested_at AND "
                              "(available_at IS NULL OR known_at >= available_at)",
                           name="ck_external_records_known_at"),
        sa.CheckConstraint("source_status IN ('HEALTHY', 'STALE', 'MISSING', 'INVALID')",
                           name="ck_external_records_status"),
    )
    op.create_index("ix_external_records_lookup", "external_records",
                    ["source", "kind", "event_time"])
    op.create_index("ix_external_records_known", "external_records", ["source", "known_at"])
    op.create_table(
        "external_quarantine",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("raw", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_external_quarantine_source", "external_quarantine",
                    ["source", "received_at"])
    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_mutation();"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};")
    op.drop_index("ix_external_quarantine_source", table_name="external_quarantine")
    op.drop_table("external_quarantine")
    op.drop_index("ix_external_records_known", table_name="external_records")
    op.drop_index("ix_external_records_lookup", table_name="external_records")
    op.drop_table("external_records")
