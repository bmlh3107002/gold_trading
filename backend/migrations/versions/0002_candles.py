"""Bảng nến (hypertable nếu có TimescaleDB) và bảng cách ly dữ liệu lỗi

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candles",
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("tick_volume", sa.BigInteger(), nullable=False),
        sa.Column("spread_points", sa.Integer()),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("flags", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "timeframe", "source", "open_time", "revision"),
        sa.CheckConstraint("high >= low AND low > 0", name="ck_candles_price"),
        sa.CheckConstraint("available_at >= close_time", name="ck_candles_closed"),
    )
    op.create_table(
        "candle_quarantine",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("raw", postgresql.JSONB(), nullable=False),
    )

    # TimescaleDB có sẵn trong image timescale/timescaledb; Postgres thường thì bỏ qua.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb') THEN
            CREATE EXTENSION IF NOT EXISTS timescaledb;
            PERFORM create_hypertable('candles', 'open_time',
                                      chunk_time_interval => INTERVAL '30 days');
          END IF;
        END
        $$;
        """
    )
    # Append-only giống các bảng vận hành (hàm forbid_mutation tạo ở 0001).
    for table in ("candles", "candle_quarantine"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_mutation();"
        )


def downgrade() -> None:
    for table in ("candle_quarantine", "candles"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};")
        op.drop_table(table)
