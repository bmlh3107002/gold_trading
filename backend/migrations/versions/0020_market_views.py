"""GĐ4 bước 5a (MKV-02): MarketView + vô hiệu MarketView — chỉ thêm.

``market_views``: mỗi dòng một MarketView (id xác định → replay không nhân đôi), khóa ngoại tới
snapshot + báo cáo Quality Gate để truy vết. ``market_view_invalidations``: vô hiệu (một lần / view)
kèm lý do + tham chiếu (vd. output bắt buộc hết hạn). Bảng thường. Trigger chặn UPDATE + DELETE.
Thiết kế: docs/thiet-ke/33-snapshot-fusion-marketview.md mục 7

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_views",
        sa.Column("market_view_id", sa.String(256), primary_key=True),
        sa.Column("snapshot_id", sa.String(256), sa.ForeignKey("market_snapshots.snapshot_id"),
                  nullable=False),
        sa.Column("report_id", sa.String(80), sa.ForeignKey("quality_reports.report_id"),
                  nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("feed_id", sa.String(64), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bias", sa.String(8), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("model_version", sa.String(40), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.CheckConstraint("expires_at > as_of", name="ck_market_views_expiry"),
        sa.CheckConstraint("bias IN ('LONG', 'SHORT', 'NEUTRAL')", name="ck_market_views_bias"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1",
                           name="ck_market_views_confidence"),
    )
    op.create_index("ix_market_views_scope", "market_views",
                    ["source", "feed_id", "symbol", "timeframe", "as_of"])
    op.create_table(
        "market_view_invalidations",
        sa.Column("market_view_id", sa.String(256), sa.ForeignKey("market_views.market_view_id"),
                  primary_key=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("ref", sa.String(256), nullable=False, server_default=""),
    )
    for t in ("market_views", "market_view_invalidations"):
        op.execute(f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE "
                   f"ON {t} FOR EACH ROW EXECUTE FUNCTION forbid_mutation();")


def downgrade() -> None:
    for t in ("market_view_invalidations", "market_views"):
        op.execute(f"DROP TRIGGER IF EXISTS {t}_append_only ON {t};")
    op.drop_table("market_view_invalidations")
    op.drop_index("ix_market_views_scope", table_name="market_views")
    op.drop_table("market_views")
