"""Đơn giản hóa phân quyền (DEC-16): người dùng chỉ có vai trò ADMIN | USER và trạng thái
ACTIVE | LOCKED.

- ``users.role``: ADMIN (quản lý tài khoản, không giao dịch) hoặc USER (giao dịch). Nguồn sự
  thật vẫn là realm role ``ADMIN`` trên Keycloak; cột này cập nhật mỗi lần đăng nhập để trang
  quản trị lọc được danh sách USER.
- ``users.status``: LOCKED → backend chặn đăng nhập/phiên, Gateway của người đó bị từ chối,
  không có lệnh mới.
- Chỉ THÊM cột có giá trị mặc định; không xóa hay sửa dòng nào. Bảng ``account_members`` giữ
  nguyên (cột ``role`` không còn ý nghĩa; backend chỉ coi dòng ``OWNER`` là quyền sở hữu).

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("role", sa.String(8), nullable=False,
                                     server_default="USER"))
    op.add_column("users", sa.Column("status", sa.String(8), nullable=False,
                                     server_default="ACTIVE"))
    op.add_column("users", sa.Column("updated_at", sa.DateTime(timezone=True)))
    op.create_check_constraint("ck_users_role", "users", "role IN ('ADMIN', 'USER')")
    op.create_check_constraint("ck_users_status", "users", "status IN ('ACTIVE', 'LOCKED')")


def downgrade() -> None:
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.drop_constraint("ck_users_role", "users", type_="check")
    for col in ("updated_at", "status", "role"):
        op.drop_column("users", col)
