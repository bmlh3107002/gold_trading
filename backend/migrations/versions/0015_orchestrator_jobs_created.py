"""GĐ2 bước 2: chỉ mục ``orchestrator_jobs(created_at)`` — bộ điều phối đọc job tạo gần đây
(khôi phục job dở dang sau khi khởi động lại, ORC-08 / 2-C05).

Revision ID: 0015
Revises: 0014
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_orchestrator_jobs_created", "orchestrator_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_orchestrator_jobs_created", table_name="orchestrator_jobs")
