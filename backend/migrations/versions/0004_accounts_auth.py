"""Đa tài khoản + phân quyền: users, trading_accounts, account_members, gateway_tokens;
account_id cho safety_transitions, mode_changes, audit_log (MT-01, MT-02, MT-04).

Dữ liệu cũ gán cho tài khoản 'default'. Cột mới thêm bằng ADD COLUMN ... DEFAULT: Postgres
điền giá trị cho hàng cũ MÀ KHÔNG chạy UPDATE, nên trigger append-only không bị đụng tới.
Sau đó bỏ DEFAULT để code bắt buộc truyền account_id.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("sub", sa.String(255), primary_key=True),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("email", sa.String(256)),
        sa.Column("display_name", sa.String(256)),
        sa.Column("first_login_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "trading_accounts",
        sa.Column("account_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("price_feed", sa.Boolean(), nullable=False),
    )
    op.execute(
        "INSERT INTO trading_accounts (account_id, name, created_at, created_by, price_feed) "
        "VALUES ('default', 'Tài khoản chính', now(), 'migration-0004', true)"
    )

    op.create_table(
        "account_members",
        sa.Column(
            "account_id", sa.String(64), sa.ForeignKey("trading_accounts.account_id"),
            nullable=False,
        ),
        sa.Column("sub", sa.String(255), sa.ForeignKey("users.sub"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granted_by", sa.String(128), nullable=False),
        sa.PrimaryKeyConstraint("account_id", "sub"),
        sa.CheckConstraint(
            "role IN ('OWNER', 'OPERATOR', 'VIEWER')", name="ck_account_members_role"
        ),
    )

    op.create_table(
        "gateway_tokens",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("token_id", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "account_id", sa.String(64), sa.ForeignKey("trading_accounts.account_id"),
            nullable=False,
        ),
        sa.Column("token_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_gateway_tokens_account", "gateway_tokens", ["account_id"])

    for table in ("safety_transitions", "mode_changes"):
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN account_id VARCHAR(64) NOT NULL DEFAULT 'default' "
            "REFERENCES trading_accounts(account_id)"
        )
        op.execute(f"ALTER TABLE {table} ALTER COLUMN account_id DROP DEFAULT")
    op.execute("ALTER TABLE audit_log ADD COLUMN account_id VARCHAR(64) DEFAULT 'default'")
    op.execute("ALTER TABLE audit_log ALTER COLUMN account_id DROP DEFAULT")
    op.execute("ALTER TABLE audit_log ADD COLUMN actor_sub VARCHAR(255)")
    op.create_index("ix_safety_transitions_account", "safety_transitions", ["account_id", "seq"])
    op.create_index("ix_mode_changes_account", "mode_changes", ["account_id", "seq"])
    op.create_index("ix_audit_log_account", "audit_log", ["account_id", "seq"])

    # Tài khoản giao dịch không bị xóa (lịch sử Safety/Mode/audit trỏ tới nó).
    op.execute(
        "CREATE TRIGGER trading_accounts_no_delete BEFORE DELETE ON trading_accounts "
        "FOR EACH ROW EXECUTE FUNCTION forbid_mutation();"
    )
    # Token Gateway: không xóa; chỉ được đặt revoked_at MỘT lần, mọi cột khác giữ nguyên.
    op.execute(
        """
        CREATE FUNCTION gateway_tokens_guard() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'gateway_tokens không được xóa';
          END IF;
          IF OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL
             OR NEW.token_id <> OLD.token_id OR NEW.account_id <> OLD.account_id
             OR NEW.token_sha256 <> OLD.token_sha256 OR NEW.created_at <> OLD.created_at
             OR NEW.created_by <> OLD.created_by THEN
            RAISE EXCEPTION 'gateway_tokens chỉ cho phép thu hồi một lần';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER gateway_tokens_guard BEFORE UPDATE OR DELETE ON gateway_tokens "
        "FOR EACH ROW EXECUTE FUNCTION gateway_tokens_guard();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS gateway_tokens_guard ON gateway_tokens;")
    op.execute("DROP FUNCTION IF EXISTS gateway_tokens_guard();")
    op.execute("DROP TRIGGER IF EXISTS trading_accounts_no_delete ON trading_accounts;")
    op.drop_index("ix_audit_log_account", "audit_log")
    op.drop_index("ix_mode_changes_account", "mode_changes")
    op.drop_index("ix_safety_transitions_account", "safety_transitions")
    # DROP COLUMN là DDL, không chạy trigger append-only.
    op.execute("ALTER TABLE audit_log DROP COLUMN actor_sub")
    op.execute("ALTER TABLE audit_log DROP COLUMN account_id")
    op.execute("ALTER TABLE mode_changes DROP COLUMN account_id")
    op.execute("ALTER TABLE safety_transitions DROP COLUMN account_id")
    op.drop_table("gateway_tokens")
    op.drop_table("account_members")
    op.drop_table("trading_accounts")
    op.drop_table("users")
