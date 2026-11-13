"""GĐ2 bước 1 (ORC-03, ORC-06, ORC-08): nhật ký sự kiện + job của Event Orchestrator.

Ba bảng chỉ-thêm (trigger chặn UPDATE + DELETE): sự kiện (event_id duy nhất), job (job_key là
khóa chính — tạo job đúng một lần), nhật ký lần thử (trạng thái job = dòng mới nhất). Bảng thường,
không hypertable (khóa duy nhất không chứa cột thời gian). Thiết kế:
docs/thiet-ke/25-event-orchestrator.md

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

TABLES = ("orchestrator_events", "orchestrator_jobs", "orchestrator_job_attempts")


def upgrade() -> None:
    op.create_table(
        "orchestrator_events",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("event_id", sa.String(40), nullable=False, unique=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(256), nullable=False),
        sa.Column("event_version", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(40), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_orchestrator_events_known", "orchestrator_events",
                    ["event_type", "known_at"])
    op.create_table(
        "orchestrator_jobs",
        sa.Column("job_key", sa.String(512), primary_key=True),
        sa.Column("event_id", sa.String(40), nullable=False),
        sa.Column("job_type", sa.String(48), nullable=False),
        sa.Column("analyzer_version", sa.String(32), nullable=False),
        sa.Column("correlation_id", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "orchestrator_job_attempts",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("job_key", sa.String(512), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("output_ref", sa.String(256)),
        sa.CheckConstraint("state IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'DEAD', "
                           "'NO_HANDLER', 'SUPERSEDED')",
                           name="ck_orchestrator_job_attempts_state"),
        sa.CheckConstraint("attempt >= 0", name="ck_orchestrator_job_attempts_attempt"),
        sa.CheckConstraint("state NOT IN ('FAILED', 'DEAD') OR error_code IS NOT NULL",
                           name="ck_orchestrator_job_attempts_error"),
    )
    op.create_index("ix_orchestrator_job_attempts_key", "orchestrator_job_attempts",
                    ["job_key", "at"])
    for t in TABLES:
        op.execute(f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE "
                   f"ON {t} FOR EACH ROW EXECUTE FUNCTION forbid_mutation();")


def downgrade() -> None:
    for t in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {t}_append_only ON {t};")
    op.drop_index("ix_orchestrator_job_attempts_key", table_name="orchestrator_job_attempts")
    op.drop_table("orchestrator_job_attempts")
    op.drop_table("orchestrator_jobs")
    op.drop_index("ix_orchestrator_events_known", table_name="orchestrator_events")
    op.drop_table("orchestrator_events")
