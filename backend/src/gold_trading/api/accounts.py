"""API theo tài khoản giao dịch (MT-03, MT-06, DEC-16).

Mọi endpoint có ``{account_id}`` đi qua ``Guard.check`` (đọc DB mỗi request) trước khi đọc hay
ghi bất cứ thứ gì của tài khoản đó: chỉ USER đang ACTIVE là chủ tài khoản mới qua được.
ADMIN hoặc không phải chủ → 404; USER bị khóa → 403; cả hai đều ghi audit.
ADMIN chỉ có các endpoint ``/api/admin/live-requests`` để duyệt/từ chối bật LIVE.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from gold_trading.accounts.access import decide, owns
from gold_trading.accounts.runtime import AccountRegistry, AccountRuntime
from gold_trading.api.ingest import GatewayMonitors, GatewayStatus
from gold_trading.auth.web import CurrentUser, Principal
from gold_trading.common.enums import SafetyState, TradingMode
from gold_trading.common.ids import new_id
from gold_trading.common.time import utcnow
from gold_trading.contracts.market_view import MarketView
from gold_trading.contracts.safety import SafetyTransition
from gold_trading.modes.manager import LIVE_CHECKLIST, ModeChangeError
from gold_trading.safety.supervisor import SafetyTransitionError
from gold_trading.storage.repository import (
    AuditEntry,
    Repository,
    StaleStateError,
    TradingAccount,
)

LIVE_REQUEST_TTL = timedelta(minutes=15)


# ---------- Contract ----------


class AccountSummary(BaseModel):
    account_id: str
    name: str
    safety_state: SafetyState
    mode: TradingMode


class AccountStatus(AccountSummary):
    live_unlocked: bool
    live_checklist: list[str]
    allows_new_orders: bool
    safety_history: list[SafetyTransition]
    market_view: MarketView | None


class SafetyCommand(BaseModel):
    """Người thực hiện lấy từ phiên đăng nhập; gửi thêm trường lạ (vd. actor) → 422."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["pause", "halt", "resume"]
    reason_code: str = Field(min_length=1, max_length=128)
    operator_approved: bool = False


class ModeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: TradingMode
    checklist: dict[str, bool] = Field(default_factory=dict)


class LiveRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checklist: dict[str, bool] = Field(default_factory=dict)


class LiveRequestOut(BaseModel):
    request_id: str
    account_id: str
    account_name: str
    requested_by: str
    requested_at: datetime
    expires_at: datetime
    checklist: dict[str, bool]


class GatewayTokenInfo(BaseModel):
    has_token: bool = Field(description="Đã có token tạo trên giao diện")
    legacy_token_active: bool = Field(
        description="Token cũ GT_INGEST_TOKEN còn được nhận (chỉ tài khoản mặc định)"
    )
    price_feed: bool = Field(description="Gateway của tài khoản này được ghi nến dùng chung")


class AuditRecord(BaseModel):
    at: datetime
    actor: str
    action: str
    outcome: Literal["ACCEPTED", "REJECTED", "NOOP"]
    payload: dict[str, Any]
    detail: str | None = None
    account_id: str | None = None


# ---------- Kiểm quyền ----------


@dataclass(frozen=True)
class Access:
    account: TradingAccount
    runtime: AccountRuntime


class Guard:
    def __init__(self, repo: Repository, registry: AccountRegistry) -> None:
        self.repo = repo
        self.registry = registry

    def audit(self, p: Principal, action: str, outcome: str, payload: dict[str, Any],
              detail: str | None = None, account_id: str | None = None) -> None:
        self.repo.append_audit(
            AuditEntry(utcnow(), p.username, action, outcome, payload, detail, account_id, p.sub)
        )

    def check(self, account_id: str, p: Principal, action: str) -> Access:
        acc = self.repo.account(account_id)
        u = self.repo.user(p.sub)
        d = decide(is_admin=p.is_admin, owns=acc is not None and owns(self.repo, account_id, p.sub),
                   status=u.status if u else None)
        if d == "not_found" or acc is None:
            # Ghi audit hệ thống (account_id=None) để không lộ tài khoản có tồn tại hay không.
            self.audit(p, "access.denied", "REJECTED",
                       {"account_id": account_id[:64], "action": action},
                       "ADMIN không vào tài khoản giao dịch" if p.is_admin
                       else "Không phải chủ tài khoản")
            raise HTTPException(404, "Không tìm thấy tài khoản")
        if d == "locked":
            self.audit(p, "access.denied", "REJECTED", {"action": action},
                       "Người dùng bị khóa", account_id)
            raise HTTPException(403, "Tài khoản người dùng đang bị khóa")
        rt = self.registry.get(account_id)
        assert rt is not None
        return Access(acc, rt)

    def require_admin(self, p: Principal, action: str) -> None:
        if not p.is_admin:
            self.audit(p, action, "REJECTED", {}, "Chỉ ADMIN")
            raise HTTPException(403, "Chỉ quản trị hệ thống")


# ---------- Yêu cầu bật LIVE: USER xin, ADMIN duyệt hoặc từ chối (DEC-16) ----------


@dataclass(frozen=True)
class LiveRequest:
    request_id: str
    account_id: str
    requester_sub: str
    requester: str
    requested_at: datetime
    checklist: dict[str, bool]

    def out(self, account_name: str) -> LiveRequestOut:
        return LiveRequestOut(
            request_id=self.request_id, account_id=self.account_id, account_name=account_name,
            requested_by=self.requester, requested_at=self.requested_at,
            expires_at=self.requested_at + LIVE_REQUEST_TTL, checklist=self.checklist,
        )


class LiveRequests:
    """Lưu trong bộ nhớ: khởi động lại thì yêu cầu mất (phải yêu cầu lại) — mặc định an toàn."""

    def __init__(self) -> None:
        self._items: dict[str, LiveRequest] = {}
        self._lock = threading.Lock()

    def add(self, r: LiveRequest) -> None:
        with self._lock:
            # Mỗi tài khoản một yêu cầu đang chờ.
            for k, v in list(self._items.items()):
                if v.account_id == r.account_id:
                    del self._items[k]
            self._items[r.request_id] = r

    def pending(self, now: datetime, account_id: str | None = None) -> list[LiveRequest]:
        with self._lock:
            return [v for v in self._items.values()
                    if (account_id is None or v.account_id == account_id)
                    and now - v.requested_at <= LIVE_REQUEST_TTL]

    def pop(self, request_id: str, now: datetime) -> LiveRequest | None:
        with self._lock:
            r = self._items.pop(request_id, None)
        return r if r is not None and now - r.requested_at <= LIVE_REQUEST_TTL else None


# ---------- Router ----------


def accounts_router(
    repo: Repository,
    registry: AccountRegistry,
    *,
    market_view: Callable[[], MarketView | None],
    monitors: GatewayMonitors,
    legacy_token_configured: bool,
) -> APIRouter:
    r = APIRouter(tags=["accounts"])
    guard = Guard(repo, registry)
    live_requests = LiveRequests()

    def summary(acc: TradingAccount) -> AccountSummary:
        rt = registry.get(acc.account_id)
        assert rt is not None
        return AccountSummary(account_id=acc.account_id, name=acc.name,
                              safety_state=rt.safety.state, mode=rt.modes.mode)

    def status(a: Access) -> AccountStatus:
        acc_id = a.account.account_id
        registry.sync(acc_id)
        rt = a.runtime
        return AccountStatus(
            **summary(a.account).model_dump(),
            live_unlocked=rt.modes.live_unlocked,
            live_checklist=list(LIVE_CHECKLIST),
            allows_new_orders=registry.allows_new_orders(acc_id),
            safety_history=list(rt.safety.history)[-200:],
            market_view=market_view(),
        )

    def account_name(account_id: str) -> str:
        acc = repo.account(account_id)
        return acc.name if acc else account_id

    @r.get("/api/accounts", response_model=list[AccountSummary])
    def list_accounts(p: CurrentUser) -> list[AccountSummary]:
        """Tài khoản giao dịch của chính USER. ADMIN không có tài khoản giao dịch → []."""
        if p.is_admin:
            return []
        u = repo.user(p.sub)
        if u is None or u.status != "ACTIVE":
            return []
        out = []
        for m in repo.memberships(p.sub):
            if m.role != "OWNER":
                continue
            acc = repo.account(m.account_id)
            if acc is not None:
                out.append(summary(acc))
        return sorted(out, key=lambda a: a.account_id)

    @r.get("/api/accounts/{account_id}/status", response_model=AccountStatus)
    def account_status(account_id: str, p: CurrentUser) -> AccountStatus:
        return status(guard.check(account_id, p, "status"))

    @r.get("/api/accounts/{account_id}/audit", response_model=list[AuditRecord])
    def account_audit(account_id: str, p: CurrentUser, limit: int = 100) -> list[AuditRecord]:
        guard.check(account_id, p, "audit")
        rows = repo.audit(min(max(limit, 1), 500), account_id=account_id)
        return [AuditRecord(**{k: getattr(e, k) for k in AuditRecord.model_fields}) for e in rows]

    @r.post("/api/accounts/{account_id}/safety", response_model=AccountStatus)
    def safety_command(account_id: str, cmd: SafetyCommand, p: CurrentUser) -> AccountStatus:
        a = guard.check(account_id, p, f"safety.{cmd.action}")
        registry.sync(account_id)
        sup = a.runtime.safety
        kwargs = {"trigger_source": "dashboard", "actor": p.username}
        payload = cmd.model_dump()
        try:
            if cmd.action == "pause":
                event = sup.pause(cmd.reason_code, **kwargs)
            elif cmd.action == "halt":
                event = sup.halt(cmd.reason_code, **kwargs)
            else:
                event = sup.resume(cmd.reason_code, operator_approved=cmd.operator_approved,
                                   **kwargs)
        except StaleStateError as e:
            registry.sync(account_id)
            guard.audit(p, f"safety.{cmd.action}", "REJECTED", payload,
                        "Trạng thái vừa thay đổi ở nơi khác (ví dụ HALT từ CLI)", account_id)
            raise HTTPException(409, "Trạng thái Safety vừa thay đổi, vui lòng xem lại") from e
        except SafetyTransitionError as e:
            guard.audit(p, f"safety.{cmd.action}", "REJECTED", payload, str(e), account_id)
            raise HTTPException(409, str(e)) from e
        guard.audit(p, f"safety.{cmd.action}", "ACCEPTED" if event else "NOOP", payload, None,
                    account_id)
        return status(a)

    @r.post("/api/accounts/{account_id}/mode", response_model=AccountStatus)
    def mode_command(account_id: str, cmd: ModeCommand, p: CurrentUser) -> AccountStatus:
        a = guard.check(account_id, p, "mode.set")
        payload = cmd.model_dump(mode="json")
        if cmd.mode is TradingMode.LIVE:
            msg = "Bật LIVE cần gửi yêu cầu và quản trị duyệt"
            guard.audit(p, "mode.set", "REJECTED", payload, msg, account_id)
            raise HTTPException(409, msg)
        try:
            change = a.runtime.modes.set_mode(cmd.mode, actor=p.username, checklist=cmd.checklist)
        except ModeChangeError as e:
            guard.audit(p, "mode.set", "REJECTED", payload, str(e), account_id)
            raise HTTPException(409, str(e)) from e
        guard.audit(p, "mode.set", "ACCEPTED" if change else "NOOP", payload, None, account_id)
        return status(a)

    @r.get("/api/accounts/{account_id}/mode/live-requests", response_model=list[LiveRequestOut])
    def pending_live(account_id: str, p: CurrentUser) -> list[LiveRequestOut]:
        a = guard.check(account_id, p, "mode.live_requests")
        return [x.out(a.account.name) for x in live_requests.pending(utcnow(), account_id)]

    @r.post("/api/accounts/{account_id}/mode/live-requests", response_model=LiveRequestOut,
            status_code=201)
    def request_live(account_id: str, cmd: LiveRequestCreate, p: CurrentUser) -> LiveRequestOut:
        a = guard.check(account_id, p, "mode.live_request")
        req = LiveRequest(new_id("lr"), account_id, p.sub, p.username, utcnow(),
                          dict(cmd.checklist))
        live_requests.add(req)
        guard.audit(p, "mode.live_request", "ACCEPTED", {"request_id": req.request_id,
                    "checklist": req.checklist}, None, account_id)
        return req.out(a.account.name)

    # ---------- ADMIN duyệt / từ chối bật LIVE ----------

    @r.get("/api/admin/live-requests", response_model=list[LiveRequestOut])
    def admin_pending_live(p: CurrentUser) -> list[LiveRequestOut]:
        guard.require_admin(p, "mode.live_requests")
        return [x.out(account_name(x.account_id)) for x in live_requests.pending(utcnow())]

    @r.post("/api/admin/live-requests/{request_id}/approve", response_model=LiveRequestOut)
    def approve_live(request_id: str, p: CurrentUser) -> LiveRequestOut:
        guard.require_admin(p, "mode.live_approve")
        payload = {"request_id": request_id[:64]}
        req = live_requests.pop(request_id, utcnow())
        if req is None:
            guard.audit(p, "mode.live_approve", "REJECTED", payload,
                        "Yêu cầu không tồn tại hoặc đã hết hạn")
            raise HTTPException(409, "Yêu cầu bật LIVE không tồn tại hoặc đã hết hạn")
        acc_id = req.account_id
        requester = repo.user(req.requester_sub)
        if req.requester_sub == p.sub:
            # 0-C16: so theo danh tính đã xác thực, không theo tên gõ tay.
            guard.audit(p, "mode.live_approve", "REJECTED", payload,
                        "Người duyệt trùng người yêu cầu", acc_id)
            raise HTTPException(409, "Người duyệt phải khác người yêu cầu")
        if (requester is None or requester.status != "ACTIVE"
                or not owns(repo, acc_id, req.requester_sub)):
            guard.audit(p, "mode.live_approve", "REJECTED", payload,
                        "Người yêu cầu không còn là chủ tài khoản hoặc đang bị khóa", acc_id)
            raise HTTPException(409, "Người yêu cầu không còn quyền bật LIVE")
        rt = registry.get(acc_id)
        assert rt is not None
        try:
            rt.modes.set_mode(TradingMode.LIVE, actor=req.requester, approver=p.username,
                              checklist=req.checklist)
        except ModeChangeError as e:
            guard.audit(p, "mode.live_approve", "REJECTED", payload, str(e), acc_id)
            raise HTTPException(409, str(e)) from e
        guard.audit(p, "mode.live_approve", "ACCEPTED", {**payload, "requester": req.requester},
                    None, acc_id)
        return req.out(account_name(acc_id))

    @r.post("/api/admin/live-requests/{request_id}/reject", response_model=LiveRequestOut)
    def reject_live(request_id: str, p: CurrentUser) -> LiveRequestOut:
        guard.require_admin(p, "mode.live_reject")
        req = live_requests.pop(request_id, utcnow())
        if req is None:
            raise HTTPException(409, "Yêu cầu bật LIVE không tồn tại hoặc đã hết hạn")
        guard.audit(p, "mode.live_reject", "ACCEPTED",
                    {"request_id": req.request_id, "requester": req.requester}, None,
                    req.account_id)
        return req.out(account_name(req.account_id))

    # ---------- Gateway (MT-04): USER chỉ xem; token do ADMIN cấp ----------

    @r.get("/api/accounts/{account_id}/gateway/status", response_model=GatewayStatus)
    def gateway_status(account_id: str, p: CurrentUser) -> GatewayStatus:
        guard.check(account_id, p, "gateway.status")
        return monitors.get(account_id).status(utcnow())

    @r.get("/api/accounts/{account_id}/gateway/token", response_model=GatewayTokenInfo)
    def gateway_token_info(account_id: str, p: CurrentUser) -> GatewayTokenInfo:
        a = guard.check(account_id, p, "gateway.token_info")
        has = repo.has_gateway_tokens(account_id)
        return GatewayTokenInfo(
            has_token=has,
            legacy_token_active=(
                legacy_token_configured and account_id == "default" and not has
            ),
            price_feed=a.account.price_feed,
        )

    return r
