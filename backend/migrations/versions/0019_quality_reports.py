"""GĐ4 bước 3 (DQG-03): kết quả Data Quality Gate — chỉ thêm.

Mỗi dòng = một lần đánh giá (id xác định theo snapshot + chính sách + kết quả → replay không nhân
đôi): verdict, lý do, hệ số, cờ, phiên bản chính sách. Bảng thường. Trigger chặn UPDATE + DELETE.
Thiết kế: docs/thiet-ke/33-snapshot-fusion-marketview.md mục 4

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quality_reports",
        sa.Column("report_id", sa.String(80), primary_key=True),
        sa.Column("snapshot_id", sa.String(256), sa.ForeignKey("market_snapshots.snapshot_id"),
                  nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("reasons", JSONB(), nullable=False),
        sa.Column("confidence_multiplier", sa.Float(), nullable=False),
        sa.Column("flags", JSONB(), nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.CheckConstraint("verdict IN ('ACCEPTED', 'DEGRADED', 'REJECTED')",
                           name="ck_quality_reports_verdict"),
        sa.CheckConstraint("confidence_multiplier >= 0 AND confidence_multiplier <= 1",
                           name="ck_quality_reports_multiplier"),
    )
    op.create_index("ix_quality_reports_snapshot", "quality_reports", ["snapshot_id"])
    op.execute("CREATE TRIGGER quality_reports_append_only BEFORE UPDATE OR DELETE "
               "ON quality_reports FOR EACH ROW EXECUTE FUNCTION forbid_mutation();")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS quality_reports_append_only ON quality_reports;")
    op.drop_index("ix_quality_reports_snapshot", table_name="quality_reports")
    op.drop_table("quality_reports")
