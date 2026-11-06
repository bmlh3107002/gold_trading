"""Phân quyền tối giản (DEC-16, thay ma trận quyền OPS-17).

Chỉ hai vai trò:

- **ADMIN** (realm role ``ADMIN`` trên Keycloak): chỉ quản lý tài khoản USER (tạo, khóa, mở khóa,
  đặt lại mật khẩu, cấp lại token Gateway) và duyệt/từ chối yêu cầu bật LIVE. **Không** vào được
  tài khoản giao dịch nào: không xem, không dừng, không đổi Mode, không lấy dữ liệu riêng.
- **USER**: làm mọi việc giao dịch hiện có trên tài khoản giao dịch **của mình**, khi đang
  ``ACTIVE``.

"Của mình" = có dòng ``account_members`` với ``role = 'OWNER'``. Dòng OPERATOR/VIEWER cũ (trước
DEC-16) bị bỏ qua — không cho quyền gì — để không vô tình mở rộng quyền khi bỏ vai trò trung gian.
Backend kiểm tra mỗi request (đọc DB); giao diện chỉ ẩn nút.
"""

from __future__ import annotations

from typing import Literal

from gold_trading.storage.repository import Repository

OWNER = "OWNER"
ACTIVE = "ACTIVE"
LOCKED = "LOCKED"

Decision = Literal["ok", "locked", "not_found"]


def decide(*, is_admin: bool, owns: bool, status: str | None) -> Decision:
    """ADMIN hoặc không sở hữu → not_found (không lộ tài khoản có tồn tại hay không).
    Sở hữu nhưng không ACTIVE (hoặc không có hồ sơ) → locked."""
    if is_admin or not owns:
        return "not_found"
    if status != ACTIVE:
        return "locked"
    return "ok"


def owns(repo: Repository, account_id: str, sub: str) -> bool:
    return repo.role(account_id, sub) == OWNER


def account_locked(repo: Repository, account_id: str) -> bool:
    """True khi tài khoản giao dịch có chủ đang bị khóa (Gateway từ chối, không lệnh mới).

    Tài khoản chưa có chủ (vd. tài khoản nguồn giá lúc mới cài) không bị coi là khóa."""
    for m in repo.members(account_id):
        if m.role != OWNER:
            continue
        u = repo.user(m.sub)
        if u is None or u.status != ACTIVE:
            return True
    return False
