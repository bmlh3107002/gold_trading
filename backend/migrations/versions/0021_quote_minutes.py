"""ING-35 (KN-03): thống kê spread theo phút — chỉ thêm, giữ vĩnh viễn.

Giá theo giây (0011) chỉ giữ 30 ngày; bảng này giữ một dòng / phút / nguồn giá (spread nhỏ nhất,
trung vị, p95, lớn nhất, giá đầu / cuối, số giây / tick / giây có cờ). Giây tới muộn → revision mới.
Bảng thường (không hypertable). Trigger chặn UPDATE + DELETE.
Thiết kế: docs/thiet-ke/23-giu-du-lieu.md mục 6

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quote_minutes",
        sa.Column("feed_id", sa.String(64), nullable=False),
        sa.Column("t", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("seconds", sa.Integer(), nullable=False),
        sa.Column("ticks", sa.Integer(), nullable=False),
        sa.Column("bid_open", sa.Float(), nullable=False),
        sa.Column("bid_close", sa.Float(), nullable=False),
        sa.Column("ask_close", sa.Float(), nullable=False),
        sa.Column("bid_low", sa.Float(), nullable=False),
        sa.Column("ask_high", sa.Float(), nullable=False),
        sa.Column("spread_min", sa.Integer(), nullable=False),
        sa.Column("spread_median", sa.Float(), nullable=False),
        sa.Column("spread_p95", sa.Integer(), nullable=False),
        sa.Column("spread_max", sa.Integer(), nullable=False),
        sa.Column("seconds_wide", sa.Integer(), nullable=False),
        sa.Column("seconds_closed", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("feed_id", "t", "revision"),
        sa.CheckConstraint("seconds BETWEEN 1 AND 60 AND ticks >= seconds AND revision >= 0 "
                           "AND seconds_wide BETWEEN 0 AND seconds "
                           "AND seconds_closed BETWEEN 0 AND seconds",
                           name="ck_quote_minutes_counts"),
        sa.CheckConstraint("spread_min >= 0 AND spread_min <= spread_median "
                           "AND spread_median <= spread_max AND spread_p95 <= spread_max",
                           name="ck_quote_minutes_spread"),
        sa.CheckConstraint("bid_low > 0 AND bid_low <= bid_open AND bid_low <= bid_close "
                           "AND ask_high >= ask_close", name="ck_quote_minutes_price"),
    )
    op.create_index("ix_quote_minutes_available", "quote_minutes", ["feed_id", "available_at"])
    op.execute("CREATE TRIGGER quote_minutes_append_only BEFORE UPDATE OR DELETE "
               "ON quote_minutes FOR EACH ROW EXECUTE FUNCTION forbid_mutation();")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS quote_minutes_append_only ON quote_minutes;")
    op.drop_index("ix_quote_minutes_available", table_name="quote_minutes")
    op.drop_table("quote_minutes")
