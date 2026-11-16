"""KN-20 (đánh giá độc lập, F-06): index ``expires_at`` cho ``analyst_outputs``.

``expired_unreplaced`` (bộ quét orchestrator, mỗi nhịp ~2 giây) lọc ``expires_at`` trong một khoảng
→ không có index thì quét toàn bảng, chậm dần theo thời gian (đo 200.000 dòng, Postgres 16:
28,9 ms → 0,6 ms). Chỉ thêm index, không đổi dữ liệu.

Revision ID: 0022
Revises: 0021
"""

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_analyst_outputs_expires_at", "analyst_outputs", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_analyst_outputs_expires_at", table_name="analyst_outputs")
