"""GĐ5 bước 3 (DB-07, RPF-01; DEC-09, KN-12, Q6): hồ sơ rủi ro có phiên bản — chỉ thêm.

Mỗi tài khoản một chuỗi phiên bản ``(account_id, version)``; chỉ chủ tài khoản tạo (kiểm ở
``storage/risk_profiles.create_profile``). Rủi ro / lệnh trong [0,25 %; 0,5 %] kiểm cả bằng CHECK
(DEC-09). Trigger chặn UPDATE + DELETE. Thiết kế: docs/thiet-ke/35-risk-engine.md mục 9.

Revision ID: 0025
Revises: 0024
"""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

_N = sa.Numeric(10, 6)


def upgrade() -> None:
    op.create_table(
        "risk_profiles",
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("reason", sa.String(256), nullable=False),
        sa.Column("risk_per_trade", _N, nullable=False),
        sa.Column("min_reward_risk", _N, nullable=False),
        sa.Column("max_open_risk", _N, nullable=False),
        sa.Column("max_daily_loss", _N, nullable=False),
        sa.Column("max_weekly_loss", _N, nullable=False),
        sa.Column("max_monthly_loss", _N, nullable=False),
        sa.Column("max_consecutive_losses", sa.Integer(), nullable=False),
        sa.Column("day_reset_tz", sa.String(64), nullable=False),
        sa.Column("day_reset_time", sa.String(5), nullable=False),
        sa.Column("max_trades_per_day", sa.Integer(), nullable=False),
        sa.Column("max_drawdown_halt", _N, nullable=False),
        sa.Column("news_hold_policy", sa.String(32), nullable=False),
        sa.Column("weekend_policy", sa.String(32), nullable=False),
        sa.Column("weekend_close_before_min", sa.Integer(), nullable=False),
        sa.Column("max_effective_leverage", _N, nullable=False),
        sa.Column("cash_flow_policy", sa.String(32), nullable=False),
        sa.Column("pyramiding_policy", sa.String(32), nullable=False),
        sa.Column("notes", sa.String(1000), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("account_id", "version"),
        sa.CheckConstraint("risk_per_trade >= 0.0025 AND risk_per_trade <= 0.005",
                           name="ck_risk_profiles_dec09"),
        sa.CheckConstraint("version >= 1", name="ck_risk_profiles_version"),
    )
    op.execute("CREATE TRIGGER risk_profiles_append_only BEFORE UPDATE OR DELETE "
               "ON risk_profiles FOR EACH ROW EXECUTE FUNCTION forbid_mutation();")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS risk_profiles_append_only ON risk_profiles;")
    op.drop_table("risk_profiles")
