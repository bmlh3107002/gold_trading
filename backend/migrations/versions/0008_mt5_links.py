"""MT-13: bảng ``mt5_links`` — liên kết tài khoản giao dịch ↔ MT5 ``(login, server)``.

Luồng: Gateway báo danh tính (MT-12) → liên kết ``PENDING_CONFIRM`` → USER (chủ tài khoản) xác
nhận "login X / server Y" → ``ACTIVE``. Dòng chỉ thêm và đổi trạng thái (trigger chặn DELETE).
Index duy nhất có điều kiện: một ``(login, server)`` chỉ được giữ (ACTIVE/MISMATCH/DISCONNECTED)
ở một tài khoản (MT-C11, server không phân biệt hoa/thường); mỗi tài khoản giữ tối đa một
liên kết và có tối đa một liên kết chờ.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

HELD = "status IN ('ACTIVE', 'MISMATCH', 'DISCONNECTED')"
PENDING = "status = 'PENDING_CONFIRM'"


def upgrade() -> None:
    op.create_table(
        "mt5_links",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("link_id", sa.String(64), nullable=False, unique=True),
        sa.Column("account_id", sa.String(64), sa.ForeignKey("trading_accounts.account_id"),
                  nullable=False),
        sa.Column("mt5_login", sa.BigInteger(), nullable=False),
        sa.Column("mt5_server", sa.String(256), nullable=False),
        sa.Column("mt5_company", sa.String(256)),
        sa.Column("trade_mode", sa.String(16), nullable=False),
        sa.Column("gateway_id", sa.String(64), nullable=False),
        sa.Column("token_id", sa.String(64)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("verified_by", sa.String(128)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("ended_by", sa.String(128)),
        sa.Column("end_reason", sa.String(128)),
        sa.CheckConstraint(
            "status IN ('PENDING_CONFIRM', 'ACTIVE', 'MISMATCH', 'DISCONNECTED', 'REVOKED', "
            "'CANCELLED')", name="ck_mt5_links_status",
        ),
        sa.CheckConstraint("trade_mode IN ('DEMO', 'CONTEST', 'REAL')",
                           name="ck_mt5_links_trade_mode"),
        sa.CheckConstraint("mt5_login > 0", name="ck_mt5_links_login"),
    )
    op.create_index("ix_mt5_links_account", "mt5_links", ["account_id", "seq"])
    # Server so không phân biệt hoa/thường (cùng MT5 dù terminal báo khác kiểu chữ).
    op.create_index("uq_mt5_links_identity_held", "mt5_links",
                    ["mt5_login", sa.text("lower(mt5_server)")],
                    unique=True, postgresql_where=sa.text(HELD))
    op.create_index("uq_mt5_links_account_held", "mt5_links", ["account_id"], unique=True,
                    postgresql_where=sa.text(HELD))
    op.create_index("uq_mt5_links_account_pending", "mt5_links", ["account_id"], unique=True,
                    postgresql_where=sa.text(PENDING))
    op.execute(
        "CREATE TRIGGER mt5_links_no_delete BEFORE DELETE ON mt5_links "
        "FOR EACH ROW EXECUTE FUNCTION forbid_mutation();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS mt5_links_no_delete ON mt5_links;")
    op.drop_table("mt5_links")
