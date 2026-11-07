"""MT-13: liên kết tài khoản giao dịch ↔ MT5 ``(login, server)``.

Luồng (``docs/thiet-ke/00-xac-thuc-phan-quyen.md`` mục 14.3):

1. Gateway gửi nhịp tim có ``identity`` (MT-12) → ``observe_identity`` tạo liên kết
   ``PENDING_CONFIRM`` cho đúng tài khoản của token (không bao giờ cho tài khoản khác).
2. USER (chủ tài khoản) xác nhận bằng cách gõ lại số login; backend chỉ nhận khi số đó khớp
   danh tính terminal báo **và** nhịp tim mới nhất (còn hạn) vẫn báo đúng danh tính đó.
3. ``ACTIVE``. Một ``(login, server)`` không được giữ ở hai tài khoản (MT-C11, có index DB).

Phạm vi MT-13: chỉ tạo + xác nhận + gỡ. Terminal đổi sang MT5 khác khi đã có liên kết → **không**
làm gì với liên kết (không tự đổi, không tạo liên kết chờ mới); MT-14 sẽ chuyển MISMATCH + chặn.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from gold_trading.common.ids import new_id
from gold_trading.storage.repository import AuditEntry, Mt5Link, Repository

if TYPE_CHECKING:
    from gold_trading.api.ingest import Heartbeat

log = logging.getLogger("gold_trading.mt5_link")

LINKABLE_TYPES = ("DEMO", "CONTEST", "REAL")


def canonical_server(server: str) -> bool:
    """Tên server dùng được làm danh tính: không rỗng, không khoảng trắng đầu/cuối, không ký tự
    điều khiển. (So trùng không phân biệt hoa/thường nằm ở kho + index DB.)"""
    return bool(server) and server == server.strip() and server.isprintable()


def observe_identity(repo: Repository, account_id: str, hb: Heartbeat, token_id: str | None,
                     now: datetime) -> Mt5Link | None:
    """Gọi sau mỗi nhịp tim đã xác thực. Trả liên kết chờ mới tạo (nếu có)."""
    ident = hb.identity
    if ident is None or ident.account_type not in LINKABLE_TYPES:
        return None  # chưa đăng nhập / không rõ loại tài khoản: không tạo gì (không đoán)
    if not canonical_server(ident.server):
        # Khoảng trắng thừa / ký tự điều khiển: có thể dùng để lách "một MT5 một tài khoản"
        # (MT-C11). Không liên kết; terminal MT5 thật không báo tên như vậy.
        log.warning("%s: tên server MT5 không hợp lệ (%r), không tạo liên kết", account_id,
                    ident.server[:64])
        return None
    link = Mt5Link(
        link_id=new_id("mtl"), account_id=account_id, mt5_login=ident.login,
        mt5_server=ident.server, mt5_company=ident.company, trade_mode=ident.account_type,
        gateway_id=hb.gateway_id, token_id=token_id, status="PENDING_CONFIRM", created_at=now,
    )
    if not repo.add_pending_link(link):
        return None
    repo.append_audit(AuditEntry(
        now, "gateway", "mt5_link.pending", "ACCEPTED",
        {"link_id": link.link_id, "login": link.mt5_login, "server": link.mt5_server,
         "trade_mode": link.trade_mode, "gateway_id": link.gateway_id},
        "Gateway báo danh tính MT5, chờ chủ tài khoản xác nhận", account_id,
    ))
    log.info("%s: MT5 login %s / %s chờ xác nhận liên kết", account_id, ident.login,
             ident.server)
    return link
