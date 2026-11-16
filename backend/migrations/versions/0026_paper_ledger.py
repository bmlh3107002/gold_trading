"""GĐ5 bước 6a (DB-06, LED-02, LED-05): sổ cái paper bền vững — chỉ thêm.

``risk_decisions``: mỗi quyết định Risk (cả từ chối) + intent gốc; duy nhất theo
(tài khoản, idempotency_key) → gọi lại cùng khóa nhận lại đúng quyết định cũ (khôi phục sau crash).
``paper_ledger_events``: giữ chỗ / nhả / khớp / đóng / nạp / rút… là sự kiện; ``account_seq`` duy
nhất trong tài khoản, ``once_key`` duy nhất (giữ chỗ kết thúc một lần, vị thế đóng một lần).
Trigger chặn UPDATE + DELETE. Thiết kế: docs/thiet-ke/35-risk-engine.md mục 12.

Revision ID: 0026
Revises: 0025
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "risk_decisions",
        sa.Column("risk_decision_id", sa.String(64), primary_key=True),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("intent_id", sa.String(128), nullable=False),
        sa.Column("intent_hash", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision", JSONB(), nullable=False),
        sa.Column("intent", JSONB(), nullable=False),
        sa.UniqueConstraint("account_id", "idempotency_key",
                            name="uq_risk_decisions_idempotency"),
    )
    op.create_index("ix_risk_decisions_account_time", "risk_decisions",
                    ["account_id", "decided_at"])
    op.create_table(
        "paper_ledger_events",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("event_id", sa.String(64), nullable=False, unique=True),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("account_seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("ref_id", sa.String(64), nullable=False),
        sa.Column("once_key", sa.String(160), unique=True),
        sa.Column("amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("reason", sa.String(256), nullable=False),
        sa.Column("links", sa.String(64)),
        sa.Column("data", JSONB(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "account_seq", name="uq_paper_ledger_account_seq"),
        sa.CheckConstraint("account_seq >= 1", name="ck_paper_ledger_account_seq"),
    )
    op.create_index("ix_paper_ledger_account_type", "paper_ledger_events",
                    ["account_id", "type", "at"])
    op.create_index("ix_paper_ledger_ref", "paper_ledger_events", ["ref_id"])
    for t in ("risk_decisions", "paper_ledger_events"):
        op.execute(f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE "
                   f"ON {t} FOR EACH ROW EXECUTE FUNCTION forbid_mutation();")


def downgrade() -> None:
    for t in ("paper_ledger_events", "risk_decisions"):
        op.execute(f"DROP TRIGGER IF EXISTS {t}_append_only ON {t};")
    op.drop_index("ix_paper_ledger_ref", table_name="paper_ledger_events")
    op.drop_index("ix_paper_ledger_account_type", table_name="paper_ledger_events")
    op.drop_table("paper_ledger_events")
    op.drop_index("ix_risk_decisions_account_time", table_name="risk_decisions")
    op.drop_table("risk_decisions")
