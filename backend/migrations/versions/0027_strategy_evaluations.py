"""GĐ5 bước 7 (STR-05): nhật ký mỗi lần chiến lược xét một MarketView — chỉ thêm.

Một dòng cho mỗi (tài khoản, chiến lược@phiên bản, MarketView): bỏ qua (kèm lý do) hoặc có ý định
(kèm quyết định Risk + kết quả khớp paper). Trigger chặn UPDATE + DELETE.
Thiết kế: docs/thiet-ke/36-chien-luoc-v1.md mục 9.

Revision ID: 0027
Revises: 0026
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_evaluations",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("strategy_ref", sa.String(64), nullable=False),
        sa.Column("market_view_id", sa.String(256), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reasons", JSONB(), nullable=False),
        sa.Column("details", JSONB(), nullable=False),
        sa.Column("intent_id", sa.String(128)),
        sa.Column("risk_decision_id", sa.String(64)),
        sa.Column("risk_outcome", sa.String(16)),
        sa.Column("fill_code", sa.String(64)),
        sa.Column("position_id", sa.String(64)),
        sa.UniqueConstraint("account_id", "strategy_ref", "market_view_id",
                            name="uq_strategy_evaluations_view"),
        sa.CheckConstraint("outcome IN ('SKIPPED', 'INTENT')",
                           name="ck_strategy_evaluations_outcome"),
    )
    op.create_index("ix_strategy_evaluations_account_time", "strategy_evaluations",
                    ["account_id", "evaluated_at"])
    op.execute("CREATE TRIGGER strategy_evaluations_append_only BEFORE UPDATE OR DELETE "
               "ON strategy_evaluations FOR EACH ROW EXECUTE FUNCTION forbid_mutation();")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS strategy_evaluations_append_only ON strategy_evaluations;")
    op.drop_index("ix_strategy_evaluations_account_time", table_name="strategy_evaluations")
    op.drop_table("strategy_evaluations")
