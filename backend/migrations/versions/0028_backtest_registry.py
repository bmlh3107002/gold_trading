"""GĐ6 bước 7 (BT-04, 6-C04): đăng ký lần chạy backtest, lần thử thêm, lần chạy đoạn để dành.

Chỉ thêm — trigger chặn UPDATE + DELETE. Đoạn để dành: khóa chính = đăng ký → chạy đúng một lần.
Chỉ dùng trong DB backtest riêng (``GT_BACKTEST_DATABASE_URL``); ở DB hệ thống thật luôn rỗng.
Thiết kế: docs/thiet-ke/39-backtest.md mục 10.

Revision ID: 0028
Revises: 0027
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

_TS = sa.DateTime(timezone=True)
_TABLES = ("backtest_registrations", "backtest_trials", "backtest_holdout_runs")


def upgrade() -> None:
    op.create_table(
        "backtest_registrations",
        sa.Column("registration_id", sa.String(64), primary_key=True),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("protocol_id", sa.String(32), nullable=False),
        sa.Column("strategy_ref", sa.String(64), nullable=False),
        sa.Column("data_start", _TS, nullable=False),
        sa.Column("dev_end", _TS, nullable=False),
        sa.Column("data_end", _TS, nullable=False),
        sa.Column("grid", JSONB(), nullable=False),
        sa.Column("data_fingerprint", sa.String(64), nullable=False),
        sa.Column("code_version", sa.String(128), nullable=False),
        sa.Column("notes", sa.String(2000), nullable=False),
        sa.CheckConstraint("data_start < dev_end AND dev_end < data_end",
                           name="ck_backtest_registrations_order"),
    )
    op.create_table(
        "backtest_trials",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("registration_id", sa.String(64), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False),
    )
    op.create_index("ix_backtest_trials_registration", "backtest_trials", ["registration_id"])
    op.create_table(
        "backtest_holdout_runs",
        sa.Column("registration_id", sa.String(64), primary_key=True),
        sa.Column("started_at", _TS, nullable=False),
        sa.Column("started_by", sa.String(128), nullable=False),
        sa.Column("combo", sa.String(64), nullable=False),
    )
    for t in _TABLES:
        op.execute(f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE "
                   f"ON {t} FOR EACH ROW EXECUTE FUNCTION forbid_mutation();")


def downgrade() -> None:
    for t in reversed(_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {t}_append_only ON {t};")
        op.drop_table(t)
