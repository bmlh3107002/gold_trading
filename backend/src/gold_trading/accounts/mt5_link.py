"""MT-13 + MT-14: liên kết tài khoản giao dịch ↔ MT5 ``(login, server)``.

Luồng (``docs/thiet-ke/00-xac-thuc-phan-quyen.md`` mục 14.3, 14.5, 14.6):

1. Gateway gửi nhịp tim có ``identity`` (MT-12) → ``observe_identity`` tạo liên kết
   ``PENDING_CONFIRM`` cho đúng tài khoản của token (không bao giờ cho tài khoản khác).
2. USER (chủ tài khoản) xác nhận bằng cách gõ lại số login → ``ACTIVE`` (MT-C11: một MT5 chỉ
   được giữ ở một tài khoản, có index DB).
3. MT-14, khi đã có liên kết đang giữ:
   - terminal báo MT5 KHÁC (login/server/loại tài khoản) → ``MISMATCH``: chặn ghi nến, cảnh báo,
     **không** tự chuyển sang MT5 mới, không tạo liên kết chờ. Chỉ thoát khi chủ tài khoản xác
     minh lại (terminal phải đang báo đúng MT5 cũ) hoặc gỡ liên kết.
   - terminal đăng xuất (``identity`` null) → ``DISCONNECTED``; báo lại đúng MT5 cũ → tự về
     ``ACTIVE`` (cùng danh tính, không phải MT5 mới).
   - Nhịp tim quá hạn (Gateway tắt/mất mạng) không ghi vào DB; giao diện hiện "mất kết nối".
4. Ghi nến (``check_candle_identity``): chỉ khi lô nến mang danh tính MT5 khớp liên kết ACTIVE
   của tài khoản. Lô nến là bằng chứng mạnh nhất: Gateway đọc danh tính ngay trước và sau khi
   lấy nến.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
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


def held_link(repo: Repository, account_id: str) -> Mt5Link | None:
    return next((x for x in reversed(repo.mt5_links(account_id)) if x.held), None)


@dataclass(frozen=True)
class Observed:
    """Danh tính MT5 terminal báo trong một lần đọc."""

    login: int
    server: str
    trade_mode: str

    def payload(self) -> dict[str, object]:
        return {"observed_login": self.login, "observed_server": self.server,
                "observed_trade_mode": self.trade_mode}


def _audit(repo: Repository, now: datetime, action: str, link: Mt5Link, detail: str,
           extra: dict[str, object] | None = None) -> None:
    repo.append_audit(AuditEntry(
        now, "gateway", action, "ACCEPTED",
        {"link_id": link.link_id, "login": link.mt5_login, "server": link.mt5_server,
         "trade_mode": link.trade_mode, **(extra or {})},
        detail, link.account_id,
    ))


def _to_mismatch(repo: Repository, link: Mt5Link, seen: Observed, now: datetime,
                 source: str) -> None:
    if repo.transition_link(link.account_id, link.link_id, link.status, "MISMATCH", now):
        _audit(repo, now, "mt5_link.mismatch", link,
               "Terminal đang đăng nhập MT5 khác liên kết: chặn ghi, cần chủ tài khoản xác minh",
               {**seen.payload(), "source": source})
        log.warning("%s: MT5 KHÔNG KHỚP liên kết (liên kết %s/%s, terminal báo %s/%s) — chặn ghi",
                    link.account_id, link.mt5_login, link.mt5_server, seen.login, seen.server)


def _reconnect(repo: Repository, link: Mt5Link, now: datetime, source: str) -> None:
    if repo.transition_link(link.account_id, link.link_id, "DISCONNECTED", "ACTIVE", now):
        _audit(repo, now, "mt5_link.reconnected", link,
               "Terminal báo lại đúng MT5 đã liên kết", {"source": source})


def observe_identity(repo: Repository, account_id: str, hb: Heartbeat, token_id: str | None,
                     now: datetime) -> Mt5Link | None:
    """Gọi sau mỗi nhịp tim đã xác thực. Trả liên kết chờ mới tạo (nếu có)."""
    ident = hb.identity
    held = held_link(repo, account_id)
    if held is not None:
        if ident is None:
            if held.status == "ACTIVE" and repo.transition_link(
                    account_id, held.link_id, "ACTIVE", "DISCONNECTED", now):
                _audit(repo, now, "mt5_link.disconnected", held,
                       "Terminal không báo danh tính MT5 (đăng xuất / mất kết nối broker)")
            return None
        seen = Observed(ident.login, ident.server, ident.account_type)
        if not held.same_identity(seen.login, seen.server, seen.trade_mode):
            if held.status != "MISMATCH":
                _to_mismatch(repo, held, seen, now, "heartbeat")
        elif held.status == "DISCONNECTED":
            _reconnect(repo, held, now, "heartbeat")
        return None  # MISMATCH + đúng MT5 cũ: vẫn chờ chủ tài khoản xác minh lại
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


# Mã lý do đứng đầu ``detail`` của lỗi 409 khi ghi nến, để Gateway nhận biết và chờ (không thoát).
LINK_REQUIRED = "MT5_LINK_REQUIRED"
LINK_MISMATCH = "MT5_LINK_MISMATCH"


class CandleLinkError(Exception):
    def __init__(self, code: str, msg: str) -> None:
        super().__init__(f"{code}: {msg}")
        self.code = code


def link_status_for(held: Mt5Link | None, seen: Observed | None,
                    pending: bool) -> str:
    """Trạng thái liên kết nhìn từ một lô nến (không ghi gì). Dùng cho ``dry_run`` / báo cáo."""
    if held is None:
        return "PENDING_CONFIRM" if pending else "NONE"
    if seen is not None and not held.same_identity(seen.login, seen.server, seen.trade_mode):
        return "MISMATCH"
    return held.status


def check_candle_identity(repo: Repository, account_id: str, seen: Observed | None,
                          now: datetime) -> Mt5Link:
    """Cho phép ghi nến hay không. Ném ``CandleLinkError`` nếu không (và chuyển MISMATCH nếu
    lô nến đến từ MT5 khác). Trả liên kết ACTIVE khi được ghi."""
    held = held_link(repo, account_id)
    if seen is None:
        raise CandleLinkError(LINK_REQUIRED, "Lô nến không có danh tính MT5 (Gateway cũ): cập "
                                             "nhật MT5 Gateway lên bản ≥ 0.4.0")
    if held is None:
        raise CandleLinkError(LINK_REQUIRED, "Tài khoản chưa liên kết MT5. Vào trang Tài khoản "
                                             "trên web, xác nhận MT5 rồi Gateway tự gửi tiếp")
    if not held.same_identity(seen.login, seen.server, seen.trade_mode):
        if held.status != "MISMATCH":
            _to_mismatch(repo, held, seen, now, "candles")
        raise CandleLinkError(LINK_MISMATCH, "MT5 đang đăng nhập khác MT5 đã liên kết: không ghi "
                                             "nến. Đăng nhập lại đúng MT5 hoặc liên kết lại")
    if held.status == "MISMATCH":
        raise CandleLinkError(LINK_MISMATCH, "Liên kết đang bị chặn do đã thấy MT5 khác: chủ tài "
                                             "khoản cần xác minh lại trên trang Tài khoản")
    if held.status == "DISCONNECTED":
        _reconnect(repo, held, now, "candles")
    return held
