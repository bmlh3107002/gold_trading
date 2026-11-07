"""ADMIN quản lý tài khoản USER (MT-20, DEC-16, DEC-17).

DEC-17: với ADMIN, **một USER = một dòng** (tài khoản giao dịch của USER ẩn bên dưới). ADMIN chỉ
làm được: xem danh sách, thêm, sửa (email/họ/tên), xóa, khóa, mở khóa, đặt lại mật khẩu, cấp token
Gateway (khi USER xin, hoặc cấp lại khi mất) và từ chối yêu cầu xin token. ADMIN không vào được
tài khoản giao dịch nào (xem ``accounts/access.py``).

Tạo USER = MỘT lệnh: tạo người dùng trên Keycloak (mật khẩu tạm, bắt đổi lần đầu) → ghi DB trong
MỘT giao dịch: hồ sơ USER + tài khoản giao dịch riêng + quyền sở hữu. **Không** sinh token: USER
đăng nhập, bấm "Xin cấp token", ADMIN bấm "Cấp token" (token hiện cho ADMIN một lần — DEC-17
lựa chọn B, vì ADMIN cấu hình Gateway trên máy chung, DEC-13). Ghi DB lỗi → xóa lại người dùng
trên Keycloak, báo lỗi rõ → gọi lại an toàn.

Xóa USER (mặc định an toàn): từ chối khi tài khoản của USER đang cấp giá cho cả hệ thống, đang ở
LIVE, hoặc Gateway đang kết nối. Xóa = DB ghi ``DELETED`` (chặn ngay: phiên, Gateway, lệnh mới)
+ thu hồi token + hủy yêu cầu xin token + thu hồi phiên, rồi xóa trên Keycloak. Giữ dòng DB để
còn lịch sử; USER đã xóa không hiện trong danh sách.

- Token gốc và mật khẩu tạm chỉ trả về MỘT lần trong phản hồi (``Cache-Control: no-store``);
  không bao giờ vào audit, log, hay API danh sách.
- Khóa: DB trước (backend chặn ngay ở request kế tiếp, Gateway bị từ chối, không lệnh mới), rồi
  thu hồi phiên, rồi Keycloak. Keycloak lỗi → khóa VẪN có hiệu lực, phản hồi báo
  ``keycloak_synced=false`` để ADMIN bấm lại. Không đóng vị thế, không đổi Safety/Mode.
- Mở khóa: Keycloak trước, DB sau (Keycloak lỗi → vẫn khóa). Không tự bật bot.
- ``GT_MULTI_USER_ENABLED=0`` (DEC-12) → không tạo USER (409).
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from gold_trading.accounts.access import ACTIVE, LOCKED, OWNER
from gold_trading.accounts.runtime import AccountRegistry
from gold_trading.api.ingest import GatewayMonitors
from gold_trading.auth.kc_admin import (
    AdminApiError,
    AdminNotConfigured,
    InvalidUser,
    KeycloakAdmin,
    NewUser,
    UserExists,
)
from gold_trading.auth.oidc import ProviderUnavailable
from gold_trading.auth.web import CurrentUser, Principal
from gold_trading.common.enums import TradingMode
from gold_trading.common.time import utcnow
from gold_trading.storage.repository import (
    AuditEntry,
    ConflictError,
    Member,
    Repository,
    TokenRequestEvent,
    TradingAccount,
    UserRecord,
)
from gold_trading.storage.schema import DEFAULT_ACCOUNT_ID

log = logging.getLogger("gold_trading.api")

USERNAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{2,29}$"
MIN_PASSWORD = 12

GatewayState = Literal["NO_TOKEN", "WAITING", "CONNECTED", "DISCONNECTED", "BLOCKED"]


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    username: str = Field(pattern=USERNAME_PATTERN,
                          description="Chữ thường không dấu, số, . _ - (3–30 ký tự)")
    email: str = Field(min_length=3, max_length=256, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    first_name: str = Field(min_length=1, max_length=64)
    last_name: str = Field(min_length=1, max_length=64)
    password: str | None = Field(
        default=None, min_length=MIN_PASSWORD, max_length=128, repr=False,
        description="Mật khẩu tạm; bỏ trống = hệ thống tự sinh. Phải đổi ở lần đăng nhập đầu",
    )


class UserUpdate(BaseModel):
    """DEC-17: ADMIN sửa thông tin USER. Tên đăng nhập không đổi được."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    email: str = Field(min_length=3, max_length=256, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    first_name: str = Field(min_length=1, max_length=64)
    last_name: str = Field(min_length=1, max_length=64)


class GatewayCredential(BaseModel):
    """Token gốc: CHỈ HIỆN MỘT LẦN. Dán vào gateway.env (GT_INGEST_TOKEN) của Gateway USER."""

    account_id: str
    token_id: str
    token: str
    created_at: datetime


class UserCreated(BaseModel):
    sub: str
    username: str
    email: str
    display_name: str
    status: Literal["ACTIVE", "LOCKED"]
    temporary_password: str | None = Field(
        default=None, description="Chỉ có khi hệ thống tự sinh mật khẩu tạm. CHỈ HIỆN MỘT LẦN"
    )


class UserAdminOut(BaseModel):
    """Một USER = một dòng (DEC-17). Không có token hay mật khẩu."""

    sub: str
    username: str
    email: str | None
    display_name: str | None
    status: Literal["ACTIVE", "LOCKED"]
    first_login_at: datetime | None
    last_login_at: datetime | None
    updated_at: datetime | None
    gateway_status: GatewayState = Field(
        description="NO_TOKEN chưa cấp token; WAITING đã cấp, chờ Gateway; BLOCKED USER bị khóa"
    )
    gateway_last_seen_at: datetime | None
    token_requested_at: datetime | None = Field(
        description="USER đang xin cấp token (chờ ADMIN cấp hoặc từ chối); None = không xin"
    )
    price_feed: bool = Field(
        description="MT5 của USER này đang cấp giá XAUUSD cho cả hệ thống (không xóa được)"
    )


class DeleteResult(BaseModel):
    sub: str
    sessions_revoked: int
    tokens_revoked: int
    keycloak_synced: bool = Field(
        description="False = chưa xóa được trên Keycloak (USER vẫn bị chặn ở backend); bấm lại"
    )


class LockResult(BaseModel):
    sub: str
    status: Literal["ACTIVE", "LOCKED"]
    sessions_revoked: int
    keycloak_synced: bool = Field(
        description="False = Keycloak chưa cập nhật (khóa vẫn có hiệu lực ở backend); bấm lại"
    )


class PasswordReset(BaseModel):
    sub: str
    temporary_password: str = Field(description="CHỈ HIỆN MỘT LẦN; USER phải đổi khi đăng nhập")
    sessions_revoked: int


def account_id_for(username: str) -> str:
    """``u-<username>``, chỉ dùng ký tự hợp lệ của mã tài khoản (``.`` → ``-``)."""
    return "u-" + username.replace(".", "-")


def free_account_id(repo: Repository, username: str) -> str | None:
    """Mã tài khoản chưa dùng: ``u-<username>``, hoặc ``-2``, ``-3``… khi tên đăng nhập được dùng
    lại sau khi xóa USER cũ (tài khoản cũ giữ lại để còn lịch sử)."""
    base = account_id_for(username)
    for i in range(1, 100):
        cand = base if i == 1 else f"{base}-{i}"
        if repo.account(cand) is None:
            return cand
    return None


def new_gateway_token() -> str:
    return "gtk_" + secrets.token_urlsafe(32)


def new_temp_password() -> str:
    """≥ 12 ký tự ngẫu nhiên (realm: length(12), notUsername, notEmail)."""
    return secrets.token_urlsafe(15)  # 20 ký tự, ~120 bit


def users_router(
    repo: Repository,
    registry: AccountRegistry,
    kc_admin: KeycloakAdmin,
    *,
    monitors: GatewayMonitors,
    revoke_sessions: Callable[[str], int],
    multi_user_enabled: bool,
) -> APIRouter:
    r = APIRouter(tags=["admin"])

    def audit(p: Principal, action: str, outcome: str, payload: dict[str, Any],
              detail: str | None, account_id: str | None = None) -> None:
        repo.append_audit(AuditEntry(utcnow(), p.username, action, outcome, payload,
                                     detail, account_id, p.sub))

    def require_admin(p: Principal, action: str, payload: dict[str, Any]) -> None:
        if not p.is_admin:
            audit(p, action, "REJECTED", payload, "Chỉ ADMIN")
            raise HTTPException(403, "Chỉ quản trị hệ thống")

    def target_user(p: Principal, sub: str, action: str) -> UserRecord:
        u = repo.user(sub)
        # Không thao tác lên chính mình (sau migration 0006, dòng của ADMIN ghi "USER" tới lần
        # đăng nhập kế tiếp; không được để ADMIN tự khóa mình).
        if u is None or u.role != "USER" or sub == p.sub or u.status == "DELETED":
            audit(p, action, "REJECTED", {"sub": sub[:255]}, "Không phải USER")
            raise HTTPException(404, "Không tìm thấy người dùng")
        return u

    def owned_accounts(sub: str) -> list[TradingAccount]:
        """Tài khoản cấp giá lên đầu, rồi theo thời gian tạo (tài khoản đầu = tài khoản chính)."""
        out = []
        for m in repo.memberships(sub):
            if m.role == OWNER and (acc := repo.account(m.account_id)) is not None:
                out.append(acc)
        return sorted(out, key=lambda a: (not a.price_feed, a.created_at, a.account_id))

    def primary_account(sub: str) -> TradingAccount | None:
        accs = owned_accounts(sub)
        return accs[0] if accs else None

    def gateway_state(account_id: str, locked: bool) -> tuple[GatewayState, datetime | None]:
        st = monitors.get(account_id).status(utcnow())
        if locked:
            return "BLOCKED", st.last_seen_at
        if not repo.has_active_gateway_token(account_id):
            return "NO_TOKEN", None
        if st.state == "NEVER":
            return "WAITING", None
        return st.state, st.last_seen_at  # type: ignore[return-value]

    def pending_request(account_id: str) -> TokenRequestEvent | None:
        e = repo.last_token_request(account_id)
        return e if e is not None and e.event == "REQUESTED" else None

    def close_request(acc_id: str, event: str, actor: str, at: datetime) -> bool:
        req = pending_request(acc_id)
        if req is None:
            return False
        repo.add_token_request_event(TokenRequestEvent(acc_id, req.sub, event, at, actor))
        return True

    def kc_error(e: Exception) -> HTTPException:
        if isinstance(e, UserExists):
            return HTTPException(409, "Email đã được người khác dùng")
        if isinstance(e, AdminNotConfigured):
            return HTTPException(503, "Keycloak chưa cho phép backend quản lý người dùng. "
                                 "Chạy: docker compose exec keycloak "
                                 "/opt/keycloak/bin/sync-client.sh")
        if isinstance(e, InvalidUser):
            return HTTPException(422, "Mật khẩu không đạt chính sách (≥ 12 ký tự, khác tên đăng "
                                      "nhập/email)" if e.reason == "password_policy"
                                 else "Keycloak từ chối dữ liệu người dùng")
        return HTTPException(503, "Không gọi được Keycloak, thử lại sau")

    # ---------- Danh sách ----------

    @r.get("/api/admin/users", response_model=list[UserAdminOut])
    def list_users(p: CurrentUser) -> list[UserAdminOut]:
        require_admin(p, "user.list", {})
        out = []
        for u in repo.list_users():
            if u.role != "USER" or u.sub == p.sub or u.status not in (ACTIVE, LOCKED):
                continue
            locked = u.status != ACTIVE
            acc = primary_account(u.sub)
            state: GatewayState = "NO_TOKEN"
            seen = req_at = None
            if acc is not None:
                state, seen = gateway_state(acc.account_id, locked)
                req = pending_request(acc.account_id)
                req_at = req.at if req else None
            out.append(UserAdminOut(
                sub=u.sub, username=u.username, email=u.email, display_name=u.display_name,
                status=u.status, first_login_at=u.first_login_at,  # type: ignore[arg-type]
                last_login_at=u.last_login_at, updated_at=u.updated_at,
                gateway_status=state, gateway_last_seen_at=seen, token_requested_at=req_at,
                price_feed=acc.price_feed if acc else False,
            ))
        return out

    # ---------- Tạo ----------

    @r.post("/api/admin/users", response_model=UserCreated, status_code=201)
    def create_user(cmd: UserCreate, p: CurrentUser, response: Response) -> UserCreated:
        # Không bao giờ ghi mật khẩu
        payload = cmd.model_dump(exclude={"password"})
        require_admin(p, "user.create", payload)
        if not multi_user_enabled:
            msg = "Chưa nhận người dùng thứ hai (DEC-12). Bật GT_MULTI_USER_ENABLED=1."
            audit(p, "user.create", "REJECTED", payload, msg)
            raise HTTPException(409, msg)
        generated = cmd.password is None
        password = cmd.password or new_temp_password()
        if password.lower() in (cmd.username.lower(), cmd.email.lower()):
            audit(p, "user.create", "REJECTED", payload, "Mật khẩu trùng tên đăng nhập/email")
            raise HTTPException(422, "Mật khẩu không được trùng tên đăng nhập hoặc email")

        # Tài khoản nguồn giá ("default") chưa có chủ (mới cài) → USER đầu tiên nhận nó, để Gateway
        # của USER này ghi được nến dùng chung. Còn lại: tài khoản riêng u-<username>.
        if not any(m.role == OWNER for m in repo.members(DEFAULT_ACCOUNT_ID)):
            acc_id, new_acc = DEFAULT_ACCOUNT_ID, None
            existing = repo.account(DEFAULT_ACCOUNT_ID)
            acc_name = existing.name if existing else DEFAULT_ACCOUNT_ID
        else:
            if any(u.username.lower() == cmd.username.lower() and u.status != "DELETED"
                   for u in repo.list_users()):
                audit(p, "user.create", "REJECTED", payload, "Tên đăng nhập đã có")
                raise HTTPException(409, "Tên đăng nhập hoặc email đã có")
            free = free_account_id(repo, cmd.username)
            if free is None:
                audit(p, "user.create", "REJECTED", payload, "Hết mã tài khoản cho tên này")
                raise HTTPException(409, "Tên đăng nhập hoặc email đã có")
            acc_id = free
            display0 = f"{cmd.first_name} {cmd.last_name}".strip()
            acc_name = f"Tài khoản của {display0}"
            new_acc = TradingAccount(acc_id, acc_name, utcnow(), p.username, price_feed=False)
        display = f"{cmd.first_name} {cmd.last_name}".strip()

        try:
            sub = kc_admin.create_user(NewUser(cmd.username, cmd.email, cmd.first_name,
                                               cmd.last_name, password))
        except UserExists:
            audit(p, "user.create", "REJECTED", payload, "Keycloak: tên đăng nhập hoặc email đã có")
            raise HTTPException(409, "Tên đăng nhập hoặc email đã có") from None
        except (InvalidUser, AdminNotConfigured, ProviderUnavailable, AdminApiError) as e:
            log.warning("Tạo người dùng %s thất bại: %s", cmd.username, type(e).__name__)
            err = kc_error(e)
            audit(p, "user.create", "REJECTED", payload, str(err.detail))
            raise err from None

        now = utcnow()
        user = UserRecord(sub, cmd.username, cmd.email, display, None, None,
                          role="USER", status=ACTIVE, updated_at=now)
        owner = Member(acc_id, sub, OWNER, now, p.username)
        try:
            # DEC-17: không sinh token lúc tạo; USER xin, ADMIN cấp.
            repo.provision_user(user, new_acc, owner, None, now)
        except Exception as e:
            # Bù trừ: xóa người dùng vừa tạo trên Keycloak (không để lại đăng nhập mồ côi)
            try:
                kc_admin.delete_user(sub)
                cleaned = True
            except Exception:  # pragma: no cover - ghi log để người vận hành xóa tay
                log.error("Không xóa được người dùng %s (%s) trên Keycloak sau lỗi DB",
                          cmd.username, sub)
                cleaned = False
            audit(p, "user.create", "REJECTED", payload,
                  f"Lỗi lưu DB ({type(e).__name__}); đã xóa trên Keycloak: {cleaned}")
            code = 409 if isinstance(e, ConflictError) else 500
            raise HTTPException(code, "Không lưu được người dùng mới, chưa tạo gì; thử lại"
                                ) from None

        if registry.get(acc_id) is None:
            registry.add(acc_id)
        audit(p, "user.create", "ACCEPTED",
              {**payload, "sub": sub, "account_id": acc_id, "password_generated": generated},
              None, acc_id)
        response.headers["Cache-Control"] = "no-store"
        return UserCreated(
            sub=sub, username=cmd.username, email=cmd.email, display_name=display, status=ACTIVE,
            temporary_password=password if generated else None,
        )

    # ---------- Sửa ----------

    @r.put("/api/admin/users/{sub}", response_model=UserAdminOut)
    def update_user(sub: str, cmd: UserUpdate, p: CurrentUser) -> UserAdminOut:
        payload = {"sub": sub[:255], **cmd.model_dump()}
        require_admin(p, "user.update", payload)
        target_user(p, sub, "user.update")
        email = cmd.email.strip()
        first, last = cmd.first_name.strip(), cmd.last_name.strip()
        if not first or not last:
            audit(p, "user.update", "REJECTED", payload, "Họ/tên trống")
            raise HTTPException(422, "Họ và tên không được để trống")
        clash = repo.find_user(email)
        if clash is not None and clash.sub != sub and clash.status != "DELETED":
            audit(p, "user.update", "REJECTED", payload, "Email đã có")
            raise HTTPException(409, "Email đã được người khác dùng")
        try:
            kc_admin.update_profile(sub, email, first, last)
        except (UserExists, InvalidUser, AdminNotConfigured, ProviderUnavailable,
                AdminApiError) as e:
            audit(p, "user.update", "REJECTED", payload, type(e).__name__)
            raise kc_error(e) from None
        repo.update_user_profile(sub, email, f"{first} {last}".strip(), utcnow())
        audit(p, "user.update", "ACCEPTED", payload, None)
        return next(u for u in list_users(p) if u.sub == sub)

    # ---------- Xóa ----------

    @r.delete("/api/admin/users/{sub}", response_model=DeleteResult)
    def delete_user(sub: str, p: CurrentUser) -> DeleteResult:
        payload = {"sub": sub[:255]}
        require_admin(p, "user.delete", payload)
        u = repo.user(sub)
        # Đã DELETED: cho gọi lại để hoàn tất phần Keycloak (nếu lần trước Keycloak lỗi).
        if u is None or u.role != "USER" or sub == p.sub:
            audit(p, "user.delete", "REJECTED", payload, "Không phải USER")
            raise HTTPException(404, "Không tìm thấy người dùng")
        accs = owned_accounts(sub)
        if u.status != "DELETED":
            now = utcnow()
            for acc in accs:
                reason = None
                if acc.price_feed:
                    reason = ("MT5 của người dùng này đang cấp giá cho cả hệ thống, không xóa "
                              "được. Chuyển nguồn giá sang người khác trước.")
                elif (rt := registry.get(acc.account_id)) is not None and (
                        rt.modes.mode is TradingMode.LIVE):
                    reason = "Người dùng đang giao dịch thật (LIVE), không xóa được."
                elif monitors.get(acc.account_id).status(now).state == "CONNECTED":
                    reason = "Gateway của người dùng này đang kết nối. Tắt Gateway trước khi xóa."
                if reason:
                    audit(p, "user.delete", "REJECTED", payload, reason, acc.account_id)
                    raise HTTPException(409, reason)
            # DB trước: chặn ngay phiên, Gateway, lệnh mới.
            repo.set_user_status(sub, "DELETED", now)
        tokens = 0
        for acc in accs:
            tokens += repo.revoke_gateway_tokens(acc.account_id, utcnow())
            close_request(acc.account_id, "CANCELLED", p.username, utcnow())
        revoked = revoke_sessions(sub)
        synced = True
        try:
            kc_admin.delete_user(sub)
        except (AdminApiError, ProviderUnavailable) as e:
            log.warning("Xóa %s: Keycloak chưa cập nhật (%s)", sub, type(e).__name__)
            synced = False
        audit(p, "user.delete", "ACCEPTED",
              {**payload, "username": u.username, "sessions_revoked": revoked,
               "tokens_revoked": tokens},
              None if synced else "Keycloak chưa xóa; USER vẫn bị chặn ở backend")
        return DeleteResult(sub=sub, sessions_revoked=revoked, tokens_revoked=tokens,
                            keycloak_synced=synced)

    # ---------- Khóa / mở khóa ----------

    @r.post("/api/admin/users/{sub}/lock", response_model=LockResult)
    def lock_user(sub: str, p: CurrentUser) -> LockResult:
        require_admin(p, "user.lock", {"sub": sub[:255]})
        target_user(p, sub, "user.lock")
        repo.set_user_status(sub, LOCKED, utcnow())  # có hiệu lực ngay ở backend + Gateway
        revoked = revoke_sessions(sub)
        synced = True
        try:
            kc_admin.set_enabled(sub, False)
            kc_admin.logout(sub)
        except (AdminApiError, ProviderUnavailable) as e:
            log.warning("Khóa %s: Keycloak chưa cập nhật (%s)", sub, type(e).__name__)
            synced = False
        audit(p, "user.lock", "ACCEPTED", {"sub": sub, "sessions_revoked": revoked},
              None if synced else "Keycloak chưa cập nhật; khóa vẫn có hiệu lực ở backend")
        return LockResult(sub=sub, status=LOCKED, sessions_revoked=revoked,
                          keycloak_synced=synced)

    @r.post("/api/admin/users/{sub}/unlock", response_model=LockResult)
    def unlock_user(sub: str, p: CurrentUser) -> LockResult:
        require_admin(p, "user.unlock", {"sub": sub[:255]})
        target_user(p, sub, "user.unlock")
        try:
            kc_admin.set_enabled(sub, True)
        except (AdminApiError, ProviderUnavailable) as e:
            audit(p, "user.unlock", "REJECTED", {"sub": sub}, "Không gọi được Keycloak; vẫn khóa")
            raise kc_error(e) from None
        repo.set_user_status(sub, ACTIVE, utcnow())
        # Không đụng Safety/Mode: bot không tự chạy lại.
        audit(p, "user.unlock", "ACCEPTED", {"sub": sub}, None)
        return LockResult(sub=sub, status=ACTIVE, sessions_revoked=0, keycloak_synced=True)

    # ---------- Đặt lại mật khẩu ----------

    @r.post("/api/admin/users/{sub}/reset-password", response_model=PasswordReset)
    def reset_password(sub: str, p: CurrentUser, response: Response) -> PasswordReset:
        require_admin(p, "user.reset_password", {"sub": sub[:255]})
        target_user(p, sub, "user.reset_password")
        password = new_temp_password()
        try:
            kc_admin.reset_password(sub, password)
            kc_admin.logout(sub)
        except (AdminApiError, ProviderUnavailable) as e:
            audit(p, "user.reset_password", "REJECTED", {"sub": sub}, type(e).__name__)
            raise kc_error(e) from None
        revoked = revoke_sessions(sub)
        # Token Gateway giữ nguyên.
        audit(p, "user.reset_password", "ACCEPTED", {"sub": sub, "sessions_revoked": revoked},
              None)
        response.headers["Cache-Control"] = "no-store"
        return PasswordReset(sub=sub, temporary_password=password, sessions_revoked=revoked)

    # ---------- Token Gateway: cấp (USER xin, hoặc cấp lại khi mất) / từ chối (DEC-17) ----------

    def user_account(p: Principal, sub: str, action: str) -> tuple[UserRecord, TradingAccount]:
        u = target_user(p, sub, action)
        acc = primary_account(sub)
        if acc is None:
            audit(p, action, "REJECTED", {"sub": sub[:255]}, "USER chưa có tài khoản giao dịch")
            raise HTTPException(404, "Người dùng này chưa có tài khoản giao dịch")
        return u, acc

    @r.post("/api/admin/users/{sub}/gateway-token", response_model=GatewayCredential)
    def issue_token(sub: str, p: CurrentUser, response: Response) -> GatewayCredential:
        payload: dict[str, Any] = {"sub": sub[:255]}
        require_admin(p, "gateway.rotate_token", payload)
        u, acc = user_account(p, sub, "gateway.rotate_token")
        if u.status != ACTIVE:
            audit(p, "gateway.rotate_token", "REJECTED", payload, "USER đang bị khóa",
                  acc.account_id)
            raise HTTPException(409, "Người dùng đang bị khóa. Mở khóa trước khi cấp token.")
        raw = new_gateway_token()
        now = utcnow()
        # Thu hồi token cũ + tạo token mới trong cùng giao dịch.
        token_id = repo.rotate_gateway_token(acc.account_id, raw, p.username, now)
        answered = close_request(acc.account_id, "APPROVED", p.username, now)
        audit(p, "gateway.rotate_token", "ACCEPTED",
              {**payload, "token_id": token_id, "answered_request": answered}, None,
              acc.account_id)
        response.headers["Cache-Control"] = "no-store"
        return GatewayCredential(account_id=acc.account_id, token_id=token_id, token=raw,
                                 created_at=now)

    @r.post("/api/admin/users/{sub}/gateway-token/reject", status_code=204)
    def reject_token_request(sub: str, p: CurrentUser) -> Response:
        payload = {"sub": sub[:255]}
        require_admin(p, "gateway.token_reject", payload)
        _, acc = user_account(p, sub, "gateway.token_reject")
        if not close_request(acc.account_id, "REJECTED", p.username, utcnow()):
            audit(p, "gateway.token_reject", "REJECTED", payload, "Không có yêu cầu đang chờ",
                  acc.account_id)
            raise HTTPException(409, "Người dùng này không có yêu cầu xin token đang chờ")
        audit(p, "gateway.token_reject", "ACCEPTED", payload, None, acc.account_id)
        return Response(status_code=204)

    return r
