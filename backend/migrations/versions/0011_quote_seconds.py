"""ING-08: giá sống bid/ask/spread gom theo giây (bảng quote_seconds).

Ghi một lần (trigger chặn UPDATE). DELETE được phép CHỈ để xóa dữ liệu quá hạn giữ
(GT_QUOTE_RETENTION_DAYS) — ngoại lệ duy nhất của quy tắc append-only, ghi ở docs/thiet-ke/09a.
Hypertable (TimescaleDB) theo ``t``, mỗi chunk 1 ngày.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quote_seconds",
        sa.Column("feed_id", sa.String(64), nullable=False),
        sa.Column("t", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bid", sa.Float(), nullable=False),
        sa.Column("ask", sa.Float(), nullable=False),
        sa.Column("bid_low", sa.Float(), nullable=False),
        sa.Column("ask_high", sa.Float(), nullable=False),
        sa.Column("spread_points", sa.Integer(), nullable=False),
        sa.Column("spread_max_points", sa.Integer(), nullable=False),
        sa.Column("ticks", sa.Integer(), nullable=False),
        sa.Column("flags", postgresql.JSONB(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("feed_id", "t"),
        sa.CheckConstraint("bid > 0 AND ask >= bid AND bid_low > 0 AND bid_low <= bid "
                           "AND ask_high >= ask", name="ck_quote_seconds_price"),
        sa.CheckConstraint("spread_points >= 0 AND spread_max_points >= 0 AND ticks >= 1",
                           name="ck_quote_seconds_counts"),
    )
    op.create_index("ix_quote_seconds_available", "quote_seconds", ["feed_id", "available_at"])
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
            PERFORM create_hypertable('quote_seconds', 't',
                                      chunk_time_interval => INTERVAL '1 day');
          END IF;
        END
        $$;
        """
    )
    op.execute(
        "CREATE TRIGGER quote_seconds_no_update BEFORE UPDATE ON quote_seconds "
        "FOR EACH ROW EXECUTE FUNCTION forbid_mutation();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS quote_seconds_no_update ON quote_seconds;")
    op.drop_index("ix_quote_seconds_available", table_name="quote_seconds")
    op.drop_table("quote_seconds")
