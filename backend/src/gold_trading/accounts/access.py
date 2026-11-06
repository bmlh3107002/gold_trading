"""Ma trận quyền (OPS-17). Nguồn sự thật: docs/thiet-ke/00-xac-thuc-phan-quyen.md mục 5.

Sửa bảng ở đây thì sửa cả tài liệu, và ngược lại (test so khớp hai nơi).
Vai trò theo tài khoản đọc từ DB **mỗi request** → thu hồi có hiệu lực ngay.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from gold_trading.storage.repository import ROLE_RANK


class Perm(StrEnum):
    VIEW = "VIEW"
    PAUSE_HALT = "PAUSE_HALT"
    RESUME = "RESUME"  # PAUSED → ACTIVE
    EXIT_HALTED = "EXIT_HALTED"  # HALTED → ACTIVE (cần tick xác nhận)
    SET_MODE = "SET_MODE"  # BACKTEST/PAPER/SHADOW
    REQUEST_LIVE = "REQUEST_LIVE"
    APPROVE_LIVE = "APPROVE_LIVE"
    ROTATE_TOKEN = "ROTATE_TOKEN"
    MANAGE_MEMBERS = "MANAGE_MEMBERS"


# Vai trò tối thiểu trong tài khoản cho từng quyền.
MIN_ROLE: dict[Perm, str] = {
    Perm.VIEW: "VIEWER",
    Perm.PAUSE_HALT: "OPERATOR",
    Perm.RESUME: "OPERATOR",
    Perm.EXIT_HALTED: "OWNER",
    Perm.SET_MODE: "OWNER",
    Perm.REQUEST_LIVE: "OWNER",
    Perm.APPROVE_LIVE: "OWNER",
    Perm.ROTATE_TOKEN: "OWNER",
    Perm.MANAGE_MEMBERS: "OWNER",
}

# ADMIN (realm role) được làm gì trên tài khoản mà mình KHÔNG là thành viên:
# chỉ giám sát, dừng (hướng an toàn), duyệt LIVE, quản lý thành viên.
# Không được mở giao dịch hay đổi Mode thay chủ tài khoản.
# Không xoay token Gateway (DEC-15): token là chìa khóa nối tài khoản với MT5, chỉ OWNER
# cầm; ADMIN muốn cấp token thì tự thêm mình làm OWNER (có ghi audit).
ADMIN_PERMS: frozenset[Perm] = frozenset(
    {Perm.VIEW, Perm.PAUSE_HALT, Perm.APPROVE_LIVE, Perm.MANAGE_MEMBERS}
)

Decision = Literal["ok", "forbidden", "not_found"]


def decide(perm: Perm, role: str | None, is_admin: bool) -> Decision:
    """Kết quả kiểm quyền. Không là thành viên và không phải ADMIN → not_found (không lộ
    tài khoản có tồn tại hay không)."""
    if role is not None and ROLE_RANK[role] >= ROLE_RANK[MIN_ROLE[perm]]:
        return "ok"
    if is_admin and perm in ADMIN_PERMS:
        return "ok"
    if role is None and not is_admin:
        return "not_found"
    return "forbidden"


def permissions(role: str | None, is_admin: bool) -> list[Perm]:
    """Danh sách quyền để giao diện ẩn/khóa nút (backend vẫn kiểm lại mỗi request)."""
    return [p for p in Perm if decide(p, role, is_admin) == "ok"]
