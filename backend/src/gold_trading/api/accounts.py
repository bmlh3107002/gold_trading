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
    Mt5Link,
    Mt5LinkError,
    Repository,
    StaleStateError,
    TokenRequestEvent,
    TradingAccount,
)

LIVE_REQUEST_TTL = timedelta(minutes=15)


# ---------- Contract ----------


class AccountSummary(BaseModel):
    account_id: str
    name: str
    safety_state: SafetyState
    mode: TradingMode


class EntryBlockOut(BaseModel):
    """Lệnh cấm mở lệnh mới có hạn của làn nhanh (GĐ2, DEC-20)."""

    kind: Literal["RELEASE", "NEWS", "SPREAD", "LATENCY"]
    reason_code: str
    scope: str
    start_at: datetime
    end_at: datetime | None = Field(description="None: tới khi được gỡ (spread)")
    cause_ref: str


class AccountStatus(AccountSummary):
    live_unlocked: bool
    live_checklist: list[str]
    allows_new_orders: bool
    entry_blocks: list[EntryBlockOut] = Field(default_factory=list)
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
    has_token: bool = Field(description="Đang có token còn hiệu lực (ADMIN đã cấp)")
    legacy_token_active: bool = Field(
        description="Token cũ GT_INGEST_TOKEN còn được nhận (chỉ tài khoản mặc định)"
    )
    price_feed: bool = Field(
        description="Tài khoản chính (tài khoản đầu tiên). Không còn quyết định được ghi nến hay "
        "không (MT-05: theo liên kết MT5)")
    request_status: Literal["NONE", "PENDING", "REJECTED"] = Field(
        description="DEC-17: PENDING = đã xin cấp token, chờ ADMIN; REJECTED = ADMIN từ chối "
                    "lần xin gần nhất (xin lại được)"
    )
    requested_at: datetime | None = Field(description="Thời điểm xin (khi PENDING/REJECTED)")


class AuditRecord(BaseModel):
    at: datetime
    actor: str
    action: str
    outcome: Literal["ACCEPTED", "REJECTED", "NOOP"]
    payload: dict[str, Any]
    detail: str | None = None
    account_id: str | None = None


class Mt5LinkOut(BaseModel):
    """MT-13: một liên kết MT5. Danh tính = ``(login, server)`` do terminal báo."""

    link_id: str
    status: Literal["PENDING_CONFIRM", "ACTIVE", "MISMATCH", "DISCONNECTED", "REVOKED",
                    "CANCELLED"]
    login: int
    server: str
    company: str | None
    trade_mode: Literal["DEMO", "CONTEST", "REAL"]
    gateway_id: str
    created_at: datetime
    verified_at: datetime | None
    verified_by: str | None
    ended_at: datetime | None
    end_reason: str | None
    broker_symbol: str | None = Field(
        default=None, description="MT-05: symbol broker khóa ở lô nến đầu tiên (None = chưa ghi)")


class TerminalIdentity(BaseModel):
    login: int
    server: str
    trade_mode: Literal["DEMO", "CONTEST", "REAL", "UNKNOWN"]


class Mt5LinkState(BaseModel):
    current: Mt5LinkOut | None = Field(
        description="Liên kết đang giữ (ACTIVE/MISMATCH/DISCONNECTED); None = chưa liên kết")
    pending: Mt5LinkOut | None = Field(description="Liên kết chờ chủ tài khoản xác nhận")
    terminal_matches_pending: bool = Field(
        description="Nhịp tim mới nhất (còn hạn) đang báo đúng MT5 của liên kết chờ: chỉ khi "
                    "True mới xác nhận được")
    history: list[Mt5LinkOut] = Field(description="Liên kết đã kết thúc, mới nhất trước")
    # MT-14
    current_effective: Literal["ACTIVE", "MISMATCH", "DISCONNECTED"] | None = Field(
        default=None,
        description="Trạng thái hiển thị của liên kết đang giữ: ACTIVE mà nhịp tim quá hạn "
                    "(Gateway tắt / mất mạng) → DISCONNECTED")
    terminal: TerminalIdentity | None = Field(
        default=None, description="MT5 terminal đang báo trong nhịp tim còn hạn (None = không có)")
    terminal_matches_current: bool = Field(
        default=False, description="Terminal đang báo đúng MT5 của liên kết đang giữ: điều kiện "
                                   "để xác minh lại khi MISMATCH")


class Mt5LinkConfirm(BaseModel):
    """USER gõ lại số login (và gửi server đang thấy) để xác nhận đúng MT5 của mình."""

    model_config = ConfigDict(extra="forbid")

    link_id: str = Field(min_length=1, max_length=64)
    login: int = Field(gt=0, le=2**63 - 1)
    server: str = Field(min_length=1, max_length=256)
    acknowledge_real: bool = Field(
        default=False, description="Bắt buộc True khi MT5 là tài khoản tiền thật (REAL)")


class Mt5LinkRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link_id: str = Field(min_length=1, max_length=64)


def link_out(x: Mt5Link) -> Mt5LinkOut:
    return Mt5LinkOut(
        link_id=x.link_id, status=x.status, login=x.mt5_login, server=x.mt5_server,
        company=x.mt5_company, trade_mode=x.trade_mode, gateway_id=x.gateway_id,
        created_at=x.created_at, verified_at=x.verified_at, verified_by=x.verified_by,
        ended_at=x.ended_at, end_reason=x.end_reason, broker_symbol=x.broker_symbol,
    )


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
            entry_blocks=entry_blocks_out(acc_id),
            safety_history=list(rt.safety.history)[-200:],
            market_view=market_view(),
        )

    def entry_blocks_out(acc_id: str) -> list[EntryBlockOut]:
        try:
            blocks = registry.entry_blocks(acc_id)
        except Exception:
            return []      # allows_new_orders đã False (đọc lỗi → chặn)
        return [EntryBlockOut(kind=b.kind.value, reason_code=b.reason_code, scope=b.scope,
                              start_at=b.start_at, end_at=b.end_at, cause_ref=b.cause_ref)
                for b in blocks]

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

    # ---------- Gateway (MT-04): USER xem + xin cấp token; token do ADMIN cấp (DEC-17) ----------

    def token_info(a: Access) -> GatewayTokenInfo:
        account_id = a.account.account_id
        has = repo.has_active_gateway_token(account_id)
        last = repo.last_token_request(account_id)
        st: Literal["NONE", "PENDING", "REJECTED"] = "NONE"
        at = None
        if last is not None and last.event == "REQUESTED":
            st, at = "PENDING", last.at
        elif last is not None and last.event == "REJECTED":
            st, at = "REJECTED", last.at
        return GatewayTokenInfo(
            has_token=has,
            legacy_token_active=(
                legacy_token_configured and account_id == "default"
                and not repo.has_gateway_tokens(account_id)
            ),
            price_feed=a.account.price_feed,
            request_status=st,
            requested_at=at,
        )

    @r.get("/api/accounts/{account_id}/gateway/status", response_model=GatewayStatus)
    def gateway_status(account_id: str, p: CurrentUser) -> GatewayStatus:
        guard.check(account_id, p, "gateway.status")
        st = monitors.get(account_id).status(utcnow())
        links = repo.mt5_links(account_id)
        held = next((x for x in reversed(links) if x.held), None)
        if held is not None:
            link = held.status
        elif any(x.status == "PENDING_CONFIRM" for x in links):
            link = "PENDING_CONFIRM"
        else:
            link = "NONE"
        return st.model_copy(update={"link_status": link})

    @r.get("/api/accounts/{account_id}/gateway/token", response_model=GatewayTokenInfo)
    def gateway_token_info(account_id: str, p: CurrentUser) -> GatewayTokenInfo:
        return token_info(guard.check(account_id, p, "gateway.token_info"))

    @r.post("/api/accounts/{account_id}/gateway/token-request", response_model=GatewayTokenInfo)
    def request_token(account_id: str, p: CurrentUser) -> GatewayTokenInfo:
        """USER xin cấp (hoặc cấp lại) token Gateway. Đã đang chờ → không tạo thêm (NOOP)."""
        a = guard.check(account_id, p, "gateway.token_request")
        last = repo.last_token_request(account_id)
        if last is not None and last.event == "REQUESTED":
            guard.audit(p, "gateway.token_request", "NOOP", {}, "Đang chờ quản trị", account_id)
            return token_info(a)
        repo.add_token_request_event(
            TokenRequestEvent(account_id, p.sub, "REQUESTED", utcnow(), p.username))
        guard.audit(p, "gateway.token_request", "ACCEPTED", {}, None, account_id)
        return token_info(a)

    # ---------- Liên kết MT5 (MT-13) ----------

    def terminal_identity(account_id: str) -> tuple[int, str, str] | None:
        """Danh tính MT5 trong nhịp tim CÒN HẠN gần nhất (None nếu mất kết nối/chưa đăng nhập)."""
        st = monitors.get(account_id).status(utcnow())
        hb = st.heartbeat
        if st.state != "CONNECTED" or hb is None or hb.identity is None:
            return None
        return hb.identity.login, hb.identity.server, hb.identity.account_type

    def link_state(account_id: str) -> Mt5LinkState:
        links = repo.mt5_links(account_id)
        current = next((x for x in reversed(links) if x.held), None)
        pending = next((x for x in reversed(links) if x.status == "PENDING_CONFIRM"), None)
        ended = [x for x in reversed(links) if not x.held and x.status != "PENDING_CONFIRM"]
        ident = terminal_identity(account_id)
        effective = None
        if current is not None:
            effective = current.status
            if current.status == "ACTIVE" and ident is None:
                effective = "DISCONNECTED"  # nhịp tim quá hạn / đăng xuất chưa kịp ghi
        return Mt5LinkState(
            current=link_out(current) if current else None,
            pending=link_out(pending) if pending else None,
            terminal_matches_pending=bool(
                pending and ident and pending.same_identity(*ident)),
            history=[link_out(x) for x in ended[:20]],
            current_effective=effective,
            terminal=TerminalIdentity(login=ident[0], server=ident[1], trade_mode=ident[2])
            if ident else None,
            terminal_matches_current=bool(current and ident and current.same_identity(*ident)),
        )

    @r.get("/api/accounts/{account_id}/mt5-link", response_model=Mt5LinkState)
    def mt5_link(account_id: str, p: CurrentUser) -> Mt5LinkState:
        guard.check(account_id, p, "mt5_link.view")
        return link_state(account_id)

    @r.post("/api/accounts/{account_id}/mt5-link/confirm", response_model=Mt5LinkState)
    def confirm_mt5_link(account_id: str, cmd: Mt5LinkConfirm, p: CurrentUser) -> Mt5LinkState:
        guard.check(account_id, p, "mt5_link.confirm")
        payload = cmd.model_dump()

        def reject(code: int, msg: str) -> HTTPException:
            guard.audit(p, "mt5_link.confirm", "REJECTED", payload, msg, account_id)
            return HTTPException(code, msg)

        link = next((x for x in repo.mt5_links(account_id) if x.link_id == cmd.link_id), None)
        if link is None:
            raise reject(404, "Không có liên kết MT5 này")
        if link.status != "PENDING_CONFIRM":
            raise reject(409, "Liên kết này không còn chờ xác nhận")
        if (cmd.login, cmd.server) != (link.mt5_login, link.mt5_server):
            # So với danh tính terminal báo; dữ liệu gõ tay chỉ để xác nhận, không bao giờ thay.
            raise reject(409, "Số login hoặc server bạn nhập không khớp MT5 mà Gateway báo")
        ident = terminal_identity(account_id)
        if ident is None or not link.same_identity(*ident):
            raise reject(409, "Terminal hiện không còn đăng nhập đúng MT5 này (hoặc Gateway mất "
                              "kết nối). Mở MT5 đúng tài khoản, chờ vài giây rồi thử lại")
        if link.trade_mode == "REAL" and not cmd.acknowledge_real:
            raise reject(409, "Đây là tài khoản TIỀN THẬT: phải đánh dấu xác nhận đã hiểu")
        try:
            done = repo.confirm_link(account_id, link.link_id, p.username, utcnow())
        except Mt5LinkError as e:
            msg = {
                "IDENTITY_HELD": "MT5 này đã được liên kết ở một tài khoản giao dịch khác. Mỗi "
                                 "MT5 chỉ liên kết được với một tài khoản",
                "ACCOUNT_HELD": "Tài khoản đã có liên kết MT5. Gỡ liên kết cũ trước",
            }.get(e.code, str(e))
            raise reject(409, msg) from e
        guard.audit(p, "mt5_link.confirm", "ACCEPTED",
                    {**payload, "trade_mode": done.trade_mode, "gateway_id": done.gateway_id},
                    None, account_id)
        return link_state(account_id)

    @r.post("/api/accounts/{account_id}/mt5-link/reverify", response_model=Mt5LinkState)
    def reverify_mt5_link(account_id: str, cmd: Mt5LinkConfirm, p: CurrentUser) -> Mt5LinkState:
        """MT-14: MISMATCH → ACTIVE khi terminal đã quay về ĐÚNG MT5 cũ và chủ tài khoản gõ lại
        số login. Muốn dùng MT5 mới thì gỡ liên kết rồi liên kết mới (không có đường tắt)."""
        guard.check(account_id, p, "mt5_link.reverify")
        payload = cmd.model_dump()

        def reject(code: int, msg: str) -> HTTPException:
            guard.audit(p, "mt5_link.reverify", "REJECTED", payload, msg, account_id)
            return HTTPException(code, msg)

        link = next((x for x in repo.mt5_links(account_id) if x.link_id == cmd.link_id), None)
        if link is None:
            raise reject(404, "Không có liên kết MT5 này")
        if link.status != "MISMATCH":
            raise reject(409, "Liên kết này không ở trạng thái cần xác minh lại")
        if (cmd.login, cmd.server) != (link.mt5_login, link.mt5_server):
            raise reject(409, "Số login hoặc server bạn nhập không khớp MT5 đã liên kết")
        ident = terminal_identity(account_id)
        if ident is None or not link.same_identity(*ident):
            raise reject(409, "Terminal chưa đăng nhập lại đúng MT5 đã liên kết (hoặc Gateway mất "
                              "kết nối). Đăng nhập lại MT5 cũ, chờ vài giây rồi thử lại")
        if link.trade_mode == "REAL" and not cmd.acknowledge_real:
            raise reject(409, "Đây là tài khoản TIỀN THẬT: phải đánh dấu xác nhận đã hiểu")
        if not repo.transition_link(account_id, link.link_id, "MISMATCH", "ACTIVE", utcnow(),
                                    verified_by=p.username):
            raise reject(409, "Liên kết vừa thay đổi, tải lại trang")
        guard.audit(p, "mt5_link.reverify", "ACCEPTED", payload, None, account_id)
        return link_state(account_id)

    @r.post("/api/accounts/{account_id}/mt5-link/revoke", response_model=Mt5LinkState)
    def revoke_mt5_link(account_id: str, cmd: Mt5LinkRevoke, p: CurrentUser) -> Mt5LinkState:
        """Gỡ liên kết đang giữ (→ REVOKED) hoặc bỏ liên kết chờ (→ CANCELLED)."""
        a = guard.check(account_id, p, "mt5_link.revoke")
        payload = cmd.model_dump()
        link = next((x for x in repo.mt5_links(account_id) if x.link_id == cmd.link_id), None)
        if link is None:
            guard.audit(p, "mt5_link.revoke", "REJECTED", payload, "Không có", account_id)
            raise HTTPException(404, "Không có liên kết MT5 này")
        if link.held and a.runtime.modes.mode is TradingMode.LIVE:
            msg = "Đang giao dịch thật (LIVE): chuyển khỏi LIVE trước khi gỡ liên kết MT5"
            guard.audit(p, "mt5_link.revoke", "REJECTED", payload, msg, account_id)
            raise HTTPException(409, msg)
        status = "REVOKED" if link.held else "CANCELLED"
        try:
            repo.end_link(account_id, link.link_id, status, p.username, utcnow(),
                          "OWNER_REVOKED" if link.held else "OWNER_DECLINED")
        except Mt5LinkError as e:
            guard.audit(p, "mt5_link.revoke", "REJECTED", payload, str(e), account_id)
            raise HTTPException(409, "Liên kết này đã kết thúc") from e
        guard.audit(p, "mt5_link.revoke", "ACCEPTED",
                    {**payload, "login": link.mt5_login, "server": link.mt5_server,
                     "status": status}, None, account_id)
        return link_state(account_id)

    return r
