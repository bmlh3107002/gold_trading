"""GĐ2 bước 4a (FAST-03, DEC-20): lệnh cấm mở lệnh mới có hạn của làn nhanh.

Hai bảng chỉ-thêm (trigger chặn UPDATE + DELETE): ``risk_blocks`` (block_id = sha256(loại |
phạm vi | nguyên nhân), ghi lại không trùng) và ``risk_block_lifts`` (gỡ lệnh cấm không có giờ hết
— spread; mỗi lệnh cấm gỡ một lần). Thiết kế: docs/thiet-ke/26-lam-nhanh.md

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

TABLES = ("risk_blocks", "risk_block_lifts")


def upgrade() -> None:
    op.create_table(
        "risk_blocks",
        sa.Column("block_id", sa.String(40), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True)),
        sa.Column("cause_ref", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.CheckConstraint("kind IN ('RELEASE', 'NEWS', 'SPREAD', 'LATENCY')",
                           name="ck_risk_blocks_kind"),
        sa.CheckConstraint("end_at IS NULL OR end_at > start_at", name="ck_risk_blocks_window"),
    )
    op.create_index("ix_risk_blocks_created", "risk_blocks", ["created_at"])
    op.create_table(
        "risk_block_lifts",
        sa.Column("block_id", sa.String(40), primary_key=True),
        sa.Column("lifted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
    )
    for t in TABLES:
        op.execute(f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE "
                   f"ON {t} FOR EACH ROW EXECUTE FUNCTION forbid_mutation();")


def downgrade() -> None:
    for t in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {t}_append_only ON {t};")
    op.drop_table("risk_block_lifts")
    op.drop_index("ix_risk_blocks_created", table_name="risk_blocks")
    op.drop_table("risk_blocks")
