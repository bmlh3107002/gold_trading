"""ING-30: nhật ký các lần kiểm nguồn ngoài — để tính trạng thái HEALTHY/STALE/MISSING/INVALID.

Bảng chỉ-thêm (trigger chặn UPDATE + DELETE). Bảng thường (không hypertable): vài nghìn dòng
mỗi ngày. Quy tắc: docs/thiet-ke/10-nguon-ngoai.md mục 2.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_source_checks",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("inserted", sa.Integer(), nullable=False),
        sa.Column("duplicate", sa.Integer(), nullable=False),
        sa.Column("conflict", sa.Integer(), nullable=False),
        sa.Column("invalid", sa.Integer(), nullable=False),
        sa.CheckConstraint("outcome IN ('OK', 'ERROR', 'INVALID')",
                           name="ck_external_source_checks_outcome"),
        sa.CheckConstraint("(outcome = 'OK') = (error_code IS NULL)",
                           name="ck_external_source_checks_error_code"),
        sa.CheckConstraint("inserted >= 0 AND duplicate >= 0 AND conflict >= 0 AND invalid >= 0",
                           name="ck_external_source_checks_counts"),
    )
    op.create_index("ix_external_source_checks_source", "external_source_checks",
                    ["source", "checked_at"])
    op.execute(
        "CREATE TRIGGER external_source_checks_append_only BEFORE UPDATE OR DELETE "
        "ON external_source_checks FOR EACH ROW EXECUTE FUNCTION forbid_mutation();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS external_source_checks_append_only "
               "ON external_source_checks;")
    op.drop_index("ix_external_source_checks_source", table_name="external_source_checks")
    op.drop_table("external_source_checks")
