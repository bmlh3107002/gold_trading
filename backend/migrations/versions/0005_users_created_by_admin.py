"""MT-20: người dùng do ADMIN tạo trên Dashboard có hồ sơ trước lần đăng nhập đầu.

``users.first_login_at`` / ``last_login_at`` cho phép NULL (= chưa đăng nhập lần nào).
Bảng ``users`` không có trigger append-only nên ALTER không đụng tới dữ liệu khác.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col in ("first_login_at", "last_login_at"):
        op.alter_column("users", col, existing_type=sa.DateTime(timezone=True), nullable=True)


def downgrade() -> None:
    # Người dùng chưa đăng nhập lần nào không có thời điểm hợp lệ: không hạ cấp được an toàn.
    op.execute("UPDATE users SET first_login_at = now() WHERE first_login_at IS NULL")
    op.execute("UPDATE users SET last_login_at = first_login_at WHERE last_login_at IS NULL")
    for col in ("first_login_at", "last_login_at"):
        op.alter_column("users", col, existing_type=sa.DateTime(timezone=True), nullable=False)
