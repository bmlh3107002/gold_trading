"""GĐ4 bước 2 (SNP-01, SNP-02): snapshot theo nguồn giá — chỉ thêm.

Mỗi dòng = một snapshot (id xác định theo phạm vi + manifest → replay không nhân đôi). Chỉ lưu
manifest analyst -> output_id (analyst_outputs đã chỉ thêm) để tái dựng. Bảng thường, không phải
hypertable. Trigger chặn UPDATE + DELETE.
Thiết kế: docs/thiet-ke/33-snapshot-fusion-marketview.md mục 3

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_snapshots",
        sa.Column("snapshot_id", sa.String(256), primary_key=True),
        sa.Column("builder_version", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("feed_id", sa.String(64), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quality_flags", JSONB(), nullable=False),
        sa.Column("input_manifest", JSONB(), nullable=False),
        sa.Column("excluded_inputs", JSONB(), nullable=False),
        sa.CheckConstraint("expires_at >= available_at", name="ck_market_snapshots_expiry"),
        sa.CheckConstraint("event_time <= available_at", name="ck_market_snapshots_event_time"),
    )
    op.create_index("ix_market_snapshots_scope", "market_snapshots",
                    ["source", "feed_id", "symbol", "timeframe", "available_at"])
    op.execute("CREATE TRIGGER market_snapshots_append_only BEFORE UPDATE OR DELETE "
               "ON market_snapshots FOR EACH ROW EXECUTE FUNCTION forbid_mutation();")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS market_snapshots_append_only ON market_snapshots;")
    op.drop_index("ix_market_snapshots_scope", table_name="market_snapshots")
    op.drop_table("market_snapshots")
