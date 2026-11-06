"""API theo tài khoản giao dịch (MT-03, MT-06, OPS-17).

Mọi endpoint có ``{account_id}`` đi qua ``Guard.check`` (kiểm quyền từ DB mỗi request) trước khi
đọc hay ghi bất cứ thứ gì của tài khoản đó. Không là thành viên → 404, thiếu quyền → 403; cả
hai đều ghi audit.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from gold_trading.accounts.access import Perm, decide, permissions
from gold_trading.accounts.runtime import GLOBAL_KILL_REASON, AccountRegistry, AccountRuntime
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
    ConflictError,
    Member,
    Repository,
    StaleStateError,
    TradingAccount,
)

LIVE_REQUEST_TTL = timedelta(minutes=15)
ACCOUNT_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{2,31}$"


# ---------- Contract ----------


class AccountSummary(BaseModel):
    account_id: str
    name: str
    role: Literal["OWNER", "OPERATOR", "VIEWER"] | None = Field(
        description="Vai trò của người đang đăng nhập; None = ADMIN không là thành viên"
    )
    permissions: list[Perm]
    safety_state: SafetyState
    mode: TradingMode


class AccountStatus(AccountSummary):
    live_unlocked: bool
    live_checklist: list[str]
    allows_new_orders: bool
    safety_history: list[SafetyTransition]
    market_view: MarketView | None


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    name: str = Field(min_length=1, max_length=128)


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


class GatewayTokenIssued(BaseModel):
    token_id: str
    token: str = Field(description="CHỈ HIỆN MỘT LẦN. Dán vào gateway.env (GT_INGEST_TOKEN)")
    created_at: datetime


class MemberOut(BaseModel):
    sub: str
    username: str
    email: str | None
    display_name: str | None
    role: Literal["OWNER", "OPERATOR", "VIEWER"]
    granted_at: datetime
    granted_by: str


class MemberAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: str = Field(min_length=1, max_length=256, description="username hoặc email Keycloak")
    role: Literal["OWNER", "OPERATOR", "VIEWER"]


class MemberRole(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["OWNER", "OPERATOR", "VIEWER"]


class KillSwitchCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: str = Field(min_length=1, max_length=128)


class KillSwitchResult(BaseModel):
    halted: list[str]
    already_halted: list[str]


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
    role: str | None
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

    def check(self, account_id: str, p: Principal, perm: Perm, action: str) -> Access:
        acc = self.repo.account(account_id)
        role = self.repo.role(account_id, p.sub) if acc else None
        d = decide(perm, role, p.is_admin) if acc else "not_found"
        if d == "not_found" or acc is None:
            # Ghi audit hệ thống (account_id=None) để không lộ tài khoản có tồn tại hay không.
            self.audit(p, "access.denied", "REJECTED",
                       {"account_id": account_id[:64], "perm": perm.value, "action": action},
                       "Không có quyền truy cập tài khoản")
            raise HTTPException(404, "Không tìm thấy tài khoản")
        if d == "forbidden":
            self.audit(p, "access.denied", "REJECTED", {"perm": perm.value, "action": action},
                       f"Vai trò {role or 'ADMIN'} không đủ quyền {perm.value}", account_id)
            raise HTTPException(403, "Không đủ quyền")
        rt = self.registry.get(account_id)
        assert rt is not None
        return Access(acc, role, rt)


# ---------- Yêu cầu bật LIVE (hai người khác nhau) ----------


@dataclass(frozen=True)
class LiveRequest:
    request_id: str
    account_id: str
    requester_sub: str
    requester: str
    requested_at: datetime
    checklist: dict[str, bool]

    def out(self) -> LiveRequestOut:
        return LiveRequestOut(
            request_id=self.request_id, account_id=self.account_id, requested_by=self.requester,
            requested_at=self.requested_at, expires_at=self.requested_at + LIVE_REQUEST_TTL,
            checklist=self.checklist,
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

    def pending(self, account_id: str, now: datetime) -> list[LiveRequest]:
        with self._lock:
            return [v for v in self._items.values()
                    if v.account_id == account_id and now - v.requested_at <= LIVE_REQUEST_TTL]

    def pop(self, request_id: str, account_id: str, now: datetime) -> LiveRequest | None:
        with self._lock:
            r = self._items.get(request_id)
            if r is None or r.account_id != account_id:
                return None
            del self._items[request_id]
        return r if now - r.requested_at <= LIVE_REQUEST_TTL else None


# ---------- Router ----------


def accounts_router(
    repo: Repository,
    registry: AccountRegistry,
    *,
    market_view: Callable[[], MarketView | None],
    monitors: GatewayMonitors,
    legacy_token_configured: bool,
    multi_user_enabled: bool = False,
) -> APIRouter:
    r = APIRouter(tags=["accounts"])
    guard = Guard(repo, registry)
    live_requests = LiveRequests()

    def summary(acc: TradingAccount, role: str | None, p: Principal) -> AccountSummary:
        rt = registry.get(acc.account_id)
        assert rt is not None
        return AccountSummary(
            account_id=acc.account_id, name=acc.name, role=role,  # type: ignore[arg-type]
            permissions=permissions(role, p.is_admin),
            safety_state=rt.safety.state, mode=rt.modes.mode,
        )

    def status(a: Access, p: Principal) -> AccountStatus:
        acc_id = a.account.account_id
        registry.sync(acc_id)
        rt = a.runtime
        base = summary(a.account, a.role, p)
        return AccountStatus(
            **base.model_dump(),
            live_unlocked=rt.modes.live_unlocked,
            live_checklist=list(LIVE_CHECKLIST),
            allows_new_orders=registry.allows_new_orders(acc_id),
            safety_history=list(rt.safety.history)[-200:],
            market_view=market_view(),
        )

    @r.get("/api/accounts", response_model=list[AccountSummary])
    def list_accounts(p: CurrentUser) -> list[AccountSummary]:
        """Chỉ các tài khoản người dùng có quyền (ADMIN thấy tất cả để giám sát)."""
        roles = {m.account_id: m.role for m in repo.memberships(p.sub)}
        out = []
        for acc in repo.accounts():
            role = roles.get(acc.account_id)
            if role is None and not p.is_admin:
                continue
            out.append(summary(acc, role, p))
        return out

    @r.post("/api/accounts", response_model=AccountSummary, status_code=201)
    def create_account(cmd: AccountCreate, p: CurrentUser) -> AccountSummary:
        if not p.is_admin:
            guard.audit(p, "account.create", "REJECTED", cmd.model_dump(), "Chỉ ADMIN")
            raise HTTPException(403, "Chỉ quản trị hệ thống được tạo tài khoản")
        acc = TradingAccount(cmd.account_id, cmd.name, utcnow(), p.username, price_feed=False)
        try:
            repo.create_account(acc)
        except ConflictError as e:
            raise HTTPException(409, "Mã tài khoản đã tồn tại") from e
        registry.add(acc.account_id)
        guard.audit(p, "account.create", "ACCEPTED", cmd.model_dump(), None, acc.account_id)
        return summary(acc, None, p)

    @r.get("/api/accounts/{account_id}/status", response_model=AccountStatus)
    def account_status(account_id: str, p: CurrentUser) -> AccountStatus:
        return status(guard.check(account_id, p, Perm.VIEW, "status"), p)

    @r.get("/api/accounts/{account_id}/audit", response_model=list[AuditRecord])
    def account_audit(account_id: str, p: CurrentUser, limit: int = 100) -> list[AuditRecord]:
        guard.check(account_id, p, Perm.VIEW, "audit")
        rows = repo.audit(min(max(limit, 1), 500), account_id=account_id)
        return [AuditRecord(**{k: getattr(e, k) for k in AuditRecord.model_fields}) for e in rows]

    @r.post("/api/accounts/{account_id}/safety", response_model=AccountStatus)
    def safety_command(account_id: str, cmd: SafetyCommand, p: CurrentUser) -> AccountStatus:
        acc = repo.account(account_id)
        rt = registry.get(account_id) if acc else None
        if rt is not None:
            registry.sync(account_id)
        if cmd.action == "resume":
            exiting_halt = rt is not None and rt.safety.state is SafetyState.HALTED
            perm = Perm.EXIT_HALTED if exiting_halt else Perm.RESUME
        else:
            perm = Perm.PAUSE_HALT
        a = guard.check(account_id, p, perm, f"safety.{cmd.action}")
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
        return status(a, p)

    @r.post("/api/accounts/{account_id}/mode", response_model=AccountStatus)
    def mode_command(account_id: str, cmd: ModeCommand, p: CurrentUser) -> AccountStatus:
        a = guard.check(account_id, p, Perm.SET_MODE, "mode.set")
        payload = cmd.model_dump(mode="json")
        if cmd.mode is TradingMode.LIVE:
            msg = "Bật LIVE cần gửi yêu cầu và người thứ hai duyệt"
            guard.audit(p, "mode.set", "REJECTED", payload, msg, account_id)
            raise HTTPException(409, msg)
        try:
            change = a.runtime.modes.set_mode(cmd.mode, actor=p.username, checklist=cmd.checklist)
        except ModeChangeError as e:
            guard.audit(p, "mode.set", "REJECTED", payload, str(e), account_id)
            raise HTTPException(409, str(e)) from e
        guard.audit(p, "mode.set", "ACCEPTED" if change else "NOOP", payload, None, account_id)
        return status(a, p)

    @r.get("/api/accounts/{account_id}/mode/live-requests", response_model=list[LiveRequestOut])
    def pending_live(account_id: str, p: CurrentUser) -> list[LiveRequestOut]:
        guard.check(account_id, p, Perm.VIEW, "mode.live_requests")
        return [x.out() for x in live_requests.pending(account_id, utcnow())]

    @r.post("/api/accounts/{account_id}/mode/live-requests", response_model=LiveRequestOut,
            status_code=201)
    def request_live(account_id: str, cmd: LiveRequestCreate, p: CurrentUser) -> LiveRequestOut:
        guard.check(account_id, p, Perm.REQUEST_LIVE, "mode.live_request")
        req = LiveRequest(new_id("lr"), account_id, p.sub, p.username, utcnow(),
                          dict(cmd.checklist))
        live_requests.add(req)
        guard.audit(p, "mode.live_request", "ACCEPTED", {"request_id": req.request_id,
                    "checklist": req.checklist}, None, account_id)
        return req.out()

    @r.post("/api/accounts/{account_id}/mode/live-requests/{request_id}/approve",
            response_model=AccountStatus)
    def approve_live(account_id: str, request_id: str, p: CurrentUser) -> AccountStatus:
        a = guard.check(account_id, p, Perm.APPROVE_LIVE, "mode.live_approve")
        payload = {"request_id": request_id[:64]}
        req = live_requests.pop(request_id, account_id, utcnow())
        if req is None:
            guard.audit(p, "mode.live_approve", "REJECTED", payload,
                        "Yêu cầu không tồn tại hoặc đã hết hạn", account_id)
            raise HTTPException(409, "Yêu cầu bật LIVE không tồn tại hoặc đã hết hạn")
        if req.requester_sub == p.sub:
            # 0-C16: so theo danh tính đã xác thực, không theo tên gõ tay.
            guard.audit(p, "mode.live_approve", "REJECTED", payload,
                        "Người duyệt trùng người yêu cầu", account_id)
            raise HTTPException(409, "Người duyệt phải khác người yêu cầu")
        if decide(Perm.REQUEST_LIVE, repo.role(account_id, req.requester_sub), False) != "ok":
            guard.audit(p, "mode.live_approve", "REJECTED", payload,
                        "Người yêu cầu không còn quyền", account_id)
            raise HTTPException(409, "Người yêu cầu không còn quyền bật LIVE")
        try:
            a.runtime.modes.set_mode(TradingMode.LIVE, actor=req.requester, approver=p.username,
                                     checklist=req.checklist)
        except ModeChangeError as e:
            guard.audit(p, "mode.live_approve", "REJECTED", payload, str(e), account_id)
            raise HTTPException(409, str(e)) from e
        guard.audit(p, "mode.live_approve", "ACCEPTED", {**payload, "requester": req.requester},
                    None, account_id)
        return status(a, p)

    # ---------- Thành viên (MT-10) ----------

    def member_out(m: Member) -> MemberOut:
        u = repo.user(m.sub)
        return MemberOut(
            sub=m.sub, username=u.username if u else m.sub, email=u.email if u else None,
            display_name=u.display_name if u else None, role=m.role,  # type: ignore[arg-type]
            granted_at=m.granted_at, granted_by=m.granted_by,
        )

    def owners(account_id: str) -> list[str]:
        return [m.sub for m in repo.members(account_id) if m.role == "OWNER"]

    @r.get("/api/accounts/{account_id}/members", response_model=list[MemberOut])
    def list_members(account_id: str, p: CurrentUser) -> list[MemberOut]:
        guard.check(account_id, p, Perm.VIEW, "members.list")
        return [member_out(m) for m in repo.members(account_id)]

    @r.post("/api/accounts/{account_id}/members", response_model=MemberOut, status_code=201)
    def add_member(account_id: str, cmd: MemberAdd, p: CurrentUser) -> MemberOut:
        guard.check(account_id, p, Perm.MANAGE_MEMBERS, "members.add")
        payload = cmd.model_dump()
        user = repo.find_user(cmd.user)
        if user is None:
            guard.audit(p, "members.add", "REJECTED", payload, "Người dùng chưa đăng nhập lần nào",
                        account_id)
            raise HTTPException(
                404, "Không tìm thấy người dùng. Người đó cần đăng nhập Dashboard ít nhất một lần."
            )
        if not multi_user_enabled and user.sub != p.sub:
            msg = ("Chưa nhận người dùng thứ hai (DEC-12: cần ý kiến pháp lý trước). "
                   "Bật GT_MULTI_USER_ENABLED=1 khi đã có câu trả lời.")
            guard.audit(p, "members.add", "REJECTED", payload, msg, account_id)
            raise HTTPException(409, msg)
        if repo.role(account_id, user.sub) is not None:
            raise HTTPException(409, "Người dùng đã là thành viên; hãy đổi vai trò")
        m = Member(account_id, user.sub, cmd.role, utcnow(), p.username)
        repo.set_member(m)
        guard.audit(p, "members.add", "ACCEPTED", {**payload, "sub": user.sub}, None, account_id)
        return member_out(m)

    @r.put("/api/accounts/{account_id}/members/{user_sub}", response_model=MemberOut)
    def change_role(account_id: str, user_sub: str, cmd: MemberRole, p: CurrentUser) -> MemberOut:
        guard.check(account_id, p, Perm.MANAGE_MEMBERS, "members.change_role")
        old = repo.role(account_id, user_sub)
        payload = {"sub": user_sub[:255], "role": cmd.role, "from": old}
        if old is None:
            raise HTTPException(404, "Không phải thành viên của tài khoản")
        if old == "OWNER" and cmd.role != "OWNER" and owners(account_id) == [user_sub]:
            guard.audit(p, "members.change_role", "REJECTED", payload, "OWNER cuối cùng",
                        account_id)
            raise HTTPException(409, "Không thể hạ quyền OWNER cuối cùng của tài khoản")
        m = Member(account_id, user_sub, cmd.role, utcnow(), p.username)
        repo.set_member(m)
        guard.audit(p, "members.change_role", "ACCEPTED", payload, None, account_id)
        return member_out(m)

    @r.delete("/api/accounts/{account_id}/members/{user_sub}", status_code=204)
    def remove_member(account_id: str, user_sub: str, p: CurrentUser) -> Response:
        guard.check(account_id, p, Perm.MANAGE_MEMBERS, "members.remove")
        old = repo.role(account_id, user_sub)
        payload = {"sub": user_sub[:255], "from": old}
        if old is None:
            raise HTTPException(404, "Không phải thành viên của tài khoản")
        if old == "OWNER" and owners(account_id) == [user_sub]:
            guard.audit(p, "members.remove", "REJECTED", payload, "OWNER cuối cùng", account_id)
            raise HTTPException(409, "Không thể gỡ OWNER cuối cùng của tài khoản")
        repo.remove_member(account_id, user_sub)
        guard.audit(p, "members.remove", "ACCEPTED", payload, None, account_id)
        return Response(status_code=204)

    # ---------- Gateway (MT-04) ----------

    @r.get("/api/accounts/{account_id}/gateway/status", response_model=GatewayStatus)
    def gateway_status(account_id: str, p: CurrentUser) -> GatewayStatus:
        guard.check(account_id, p, Perm.VIEW, "gateway.status")
        return monitors.get(account_id).status(utcnow())

    @r.get("/api/accounts/{account_id}/gateway/token", response_model=GatewayTokenInfo)
    def gateway_token_info(account_id: str, p: CurrentUser) -> GatewayTokenInfo:
        a = guard.check(account_id, p, Perm.VIEW, "gateway.token_info")
        has = repo.has_gateway_tokens(account_id)
        return GatewayTokenInfo(
            has_token=has,
            legacy_token_active=(
                legacy_token_configured and account_id == "default" and not has
            ),
            price_feed=a.account.price_feed,
        )

    @r.post("/api/accounts/{account_id}/gateway/token", response_model=GatewayTokenIssued)
    def rotate_gateway_token(account_id: str, p: CurrentUser, response: Response
                             ) -> GatewayTokenIssued:
        guard.check(account_id, p, Perm.ROTATE_TOKEN, "gateway.rotate_token")
        raw = "gtk_" + secrets.token_urlsafe(32)
        now = utcnow()
        token_id = repo.rotate_gateway_token(account_id, raw, p.username, now)
        # Không ghi token vào audit/log: chỉ token_id.
        guard.audit(p, "gateway.rotate_token", "ACCEPTED", {"token_id": token_id}, None,
                    account_id)
        response.headers["Cache-Control"] = "no-store"
        return GatewayTokenIssued(token_id=token_id, token=raw, created_at=now)

    # ---------- Quản trị hệ thống ----------

    @r.post("/api/admin/kill-switch", response_model=KillSwitchResult)
    def kill_switch(cmd: KillSwitchCommand, p: CurrentUser) -> KillSwitchResult:
        if not p.is_admin:
            guard.audit(p, "system.kill_switch", "REJECTED", cmd.model_dump(), "Chỉ ADMIN")
            raise HTTPException(403, "Chỉ quản trị hệ thống được dùng kill switch toàn hệ thống")
        reason = f"{GLOBAL_KILL_REASON}:{cmd.reason_code}"[:128]
        before = {acc: registry.get(acc).safety.state for acc in registry.ids()}  # type: ignore
        halted = registry.halt_all(reason, actor=p.username, trigger_source="dashboard-admin")
        for acc in halted:
            guard.audit(p, "safety.halt", "ACCEPTED", {"reason_code": reason}, None, acc)
        already = [a for a, s in before.items() if s is SafetyState.HALTED]
        guard.audit(p, "system.kill_switch", "ACCEPTED", {**cmd.model_dump(), "halted": halted})
        return KillSwitchResult(halted=halted, already_halted=already)

    @r.get("/api/admin/audit", response_model=list[AuditRecord])
    def system_audit(p: CurrentUser, limit: int = 100) -> list[AuditRecord]:
        if not p.is_admin:
            raise HTTPException(403, "Chỉ quản trị hệ thống")
        rows = repo.audit(min(max(limit, 1), 500), system=True)
        return [AuditRecord(**{k: getattr(e, k) for k in AuditRecord.model_fields}) for e in rows]

    return r
