"""GĐ5 RSK-11 / Q3: phí hoa hồng khứ hồi / lot do người dùng nhập — chỉ thêm, có phiên bản.

MT5 không báo phí trong thông số mã → người dùng nhập theo trang của sàn. Risk đọc bản mới nhất có
``created_at ≤ lúc quyết``; chưa có → từ chối (COMMISSION_UNKNOWN). Trigger chặn UPDATE + DELETE.
Thiết kế: docs/thiet-ke/35-risk-engine.md mục 7.

Revision ID: 0024
Revises: 0023
"""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_commissions",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("commission_per_lot", sa.Numeric(18, 6), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("reason", sa.String(256), nullable=False),
        sa.CheckConstraint("commission_per_lot >= 0", name="ck_account_commissions_value"),
    )
    op.create_index("ix_account_commissions_lookup", "account_commissions",
                    ["account_id", "created_at"])
    op.execute("CREATE TRIGGER account_commissions_append_only BEFORE UPDATE OR DELETE "
               "ON account_commissions FOR EACH ROW EXECUTE FUNCTION forbid_mutation();")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS account_commissions_append_only ON account_commissions;")
    op.drop_index("ix_account_commissions_lookup", table_name="account_commissions")
    op.drop_table("account_commissions")
