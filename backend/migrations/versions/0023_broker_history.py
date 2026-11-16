"""KN-05 (đánh giá độc lập; GW-09): lịch sử thông số broker + số liệu tài khoản — chỉ thêm.

``broker_spec_history``: một dòng mỗi khi thông số (swap, stops / freeze level, cỡ hợp đồng, bước
khối lượng, đòn bẩy…) đổi. ``account_equity_hourly``: dòng đầu mỗi giờ UTC. Bảng thường.
Trigger chặn UPDATE + DELETE. Thiết kế: docs/thiet-ke/34-lich-su-thong-so-broker.md

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broker_spec_history",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("mt5_login", sa.BigInteger(), nullable=False),
        sa.Column("mt5_server", sa.String(256), nullable=False),
        sa.Column("broker_symbol", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("spec_hash", sa.String(64), nullable=False),
        sa.Column("gateway_version", sa.String(32), nullable=False),
        sa.Column("digits", sa.Integer(), nullable=False),
        sa.Column("point", sa.Float(), nullable=False),
        sa.Column("contract_size", sa.Float(), nullable=False),
        sa.Column("volume_min", sa.Float(), nullable=False),
        sa.Column("volume_max", sa.Float(), nullable=False),
        sa.Column("volume_step", sa.Float(), nullable=False),
        sa.Column("currency_profit", sa.String(16)),
        sa.Column("stops_level", sa.Integer()),
        sa.Column("freeze_level", sa.Integer()),
        sa.Column("swap_mode", sa.Integer()),
        sa.Column("swap_long", sa.Float()),
        sa.Column("swap_short", sa.Float()),
        sa.Column("swap_rollover3days", sa.Integer()),
        sa.Column("leverage", sa.Integer()),
        sa.Column("account_currency", sa.String(16)),
        sa.CheckConstraint("point > 0 AND contract_size > 0 AND volume_min > 0 AND volume_step > 0 "
                           "AND volume_max >= volume_min AND digits >= 0",
                           name="ck_broker_spec_history_values"),
        sa.CheckConstraint("leverage IS NULL OR leverage > 0",
                           name="ck_broker_spec_history_leverage"),
    )
    op.create_index("ix_broker_spec_history_lookup", "broker_spec_history",
                    ["account_id", "broker_symbol", "observed_at"])
    op.create_table(
        "account_equity_hourly",
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("mt5_login", sa.BigInteger(), nullable=False),
        sa.Column("mt5_server", sa.String(256), nullable=False),
        sa.Column("hour", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(16)),
        sa.Column("balance", sa.Float()),
        sa.Column("equity", sa.Float()),
        sa.Column("margin", sa.Float()),
        sa.Column("margin_free", sa.Float()),
        sa.Column("margin_level", sa.Float()),
        sa.Column("leverage", sa.Integer()),
        sa.PrimaryKeyConstraint("account_id", "mt5_login", "mt5_server", "hour"),
        sa.CheckConstraint("observed_at >= hour", name="ck_account_equity_hourly_time"),
        sa.CheckConstraint("(margin IS NULL OR margin >= 0) AND (leverage IS NULL OR leverage > 0)",
                           name="ck_account_equity_hourly_values"),
    )
    for t in ("broker_spec_history", "account_equity_hourly"):
        op.execute(f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE "
                   f"ON {t} FOR EACH ROW EXECUTE FUNCTION forbid_mutation();")


def downgrade() -> None:
    for t in ("account_equity_hourly", "broker_spec_history"):
        op.execute(f"DROP TRIGGER IF EXISTS {t}_append_only ON {t};")
    op.drop_table("account_equity_hourly")
    op.drop_index("ix_broker_spec_history_lookup", table_name="broker_spec_history")
    op.drop_table("broker_spec_history")
