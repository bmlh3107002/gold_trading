"""Bảng kết quả analyst (append-only, có manifest đầu vào trong payload)

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analyst_outputs",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("output_id", sa.String(256), nullable=False, unique=True),
        sa.Column("analyst_id", sa.String(32), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_status", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("expires_at > as_of", name="ck_analyst_outputs_expiry"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_analyst_outputs_conf"),
    )
    op.create_index(
        "ix_analyst_outputs_lookup",
        "analyst_outputs",
        ["analyst_id", "symbol", "timeframe", "source", "as_of"],
    )
    op.execute(
        "CREATE TRIGGER analyst_outputs_append_only BEFORE UPDATE OR DELETE ON analyst_outputs "
        "FOR EACH ROW EXECUTE FUNCTION forbid_mutation();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS analyst_outputs_append_only ON analyst_outputs;")
    op.drop_index("ix_analyst_outputs_lookup", table_name="analyst_outputs")
    op.drop_table("analyst_outputs")
