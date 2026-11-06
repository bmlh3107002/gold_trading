"""ADMIN quản lý tài khoản USER (MT-20, DEC-16).

ADMIN chỉ làm được các việc ở đây: xem danh sách USER, tạo USER, khóa, mở khóa, đặt lại mật khẩu,
cấp lại token Gateway. ADMIN không vào được tài khoản giao dịch nào (xem ``accounts/access.py``).

Tạo USER = MỘT lệnh: tạo người dùng trên Keycloak (mật khẩu tạm, bắt đổi lần đầu) → ghi DB trong
MỘT giao dịch: hồ sơ USER + tài khoản giao dịch riêng + quyền sở hữu + token Gateway (chỉ lưu
SHA-256). Ghi DB lỗi → xóa lại người dùng trên Keycloak, báo lỗi rõ; không có nửa vời (không có
USER thiếu token, không có token mồ côi) → gọi lại an toàn.

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
from gold_trading.common.time import utcnow
from gold_trading.storage.repository import (
    AuditEntry,
    ConflictError,
    Member,
    Repository,
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
    account_name: str | None = Field(default=None, min_length=1, max_length=128,
                                     description="Tên tài khoản giao dịch riêng")


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
    account_id: str
    account_name: str
    gateway: GatewayCredential
    gateway_status: GatewayState = Field(
        description="WAITING = token đã đăng ký ở backend, chờ Gateway gửi nhịp tim đầu tiên"
    )
    temporary_password: str | None = Field(
        default=None, description="Chỉ có khi hệ thống tự sinh mật khẩu tạm. CHỈ HIỆN MỘT LẦN"
    )


class AccountAdminOut(BaseModel):
    account_id: str
    name: str
    price_feed: bool
    gateway_status: GatewayState
    gateway_last_seen_at: datetime | None


class UserAdminOut(BaseModel):
    """Không có token hay mật khẩu."""

    sub: str
    username: str
    email: str | None
    display_name: str | None
    status: Literal["ACTIVE", "LOCKED"]
    first_login_at: datetime | None
    last_login_at: datetime | None
    updated_at: datetime | None
    accounts: list[AccountAdminOut]


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
        if u is None or u.role != "USER" or sub == p.sub:
            audit(p, action, "REJECTED", {"sub": sub[:255]}, "Không phải USER")
            raise HTTPException(404, "Không tìm thấy người dùng")
        return u

    def owned_accounts(sub: str) -> list[TradingAccount]:
        out = []
        for m in repo.memberships(sub):
            if m.role == OWNER and (acc := repo.account(m.account_id)) is not None:
                out.append(acc)
        return sorted(out, key=lambda a: a.account_id)

    def gateway_state(account_id: str, locked: bool) -> tuple[GatewayState, datetime | None]:
        st = monitors.get(account_id).status(utcnow())
        if locked:
            return "BLOCKED", st.last_seen_at
        if not repo.has_gateway_tokens(account_id):
            return "NO_TOKEN", None
        if st.state == "NEVER":
            return "WAITING", None
        return st.state, st.last_seen_at  # type: ignore[return-value]

    def kc_error(e: Exception) -> HTTPException:
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
            if u.role != "USER" or u.sub == p.sub:
                continue
            locked = u.status != ACTIVE
            accs = []
            for a in owned_accounts(u.sub):
                state, seen = gateway_state(a.account_id, locked)
                accs.append(AccountAdminOut(account_id=a.account_id, name=a.name,
                                            price_feed=a.price_feed, gateway_status=state,
                                            gateway_last_seen_at=seen))
            out.append(UserAdminOut(
                sub=u.sub, username=u.username, email=u.email, display_name=u.display_name,
                status=u.status, first_login_at=u.first_login_at,  # type: ignore[arg-type]
                last_login_at=u.last_login_at, updated_at=u.updated_at, accounts=accs,
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
            acc_id = account_id_for(cmd.username)
            if repo.account(acc_id) is not None:
                audit(p, "user.create", "REJECTED", payload, "Mã tài khoản đã tồn tại")
                raise HTTPException(409, "Tên đăng nhập hoặc email đã có")
            display0 = f"{cmd.first_name} {cmd.last_name}".strip()
            acc_name = cmd.account_name or f"Tài khoản của {display0}"
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
        raw = new_gateway_token()
        user = UserRecord(sub, cmd.username, cmd.email, display, None, None,
                          role="USER", status=ACTIVE, updated_at=now)
        owner = Member(acc_id, sub, OWNER, now, p.username)
        try:
            token_id = repo.provision_user(user, new_acc, owner, raw, now)
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

        registry.add(acc_id)
        # Không ghi token: chỉ token_id.
        audit(p, "user.create", "ACCEPTED",
              {**payload, "sub": sub, "token_id": token_id, "password_generated": generated},
              None, acc_id)
        response.headers["Cache-Control"] = "no-store"
        return UserCreated(
            sub=sub, username=cmd.username, email=cmd.email, display_name=display, status=ACTIVE,
            account_id=acc_id, account_name=acc_name,
            gateway=GatewayCredential(account_id=acc_id, token_id=token_id, token=raw,
                                      created_at=now),
            gateway_status="WAITING",
            temporary_password=password if generated else None,
        )

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

    # ---------- Cấp lại token Gateway (khi làm mất / nghi lộ) ----------

    @r.post("/api/admin/users/{sub}/accounts/{account_id}/gateway-token",
            response_model=GatewayCredential)
    def reissue_token(sub: str, account_id: str, p: CurrentUser, response: Response
                      ) -> GatewayCredential:
        payload = {"sub": sub[:255], "account_id": account_id[:64]}
        require_admin(p, "gateway.rotate_token", payload)
        target_user(p, sub, "gateway.rotate_token")
        if repo.role(account_id, sub) != OWNER:
            audit(p, "gateway.rotate_token", "REJECTED", payload, "Tài khoản không thuộc USER")
            raise HTTPException(404, "Không tìm thấy tài khoản của người dùng này")
        raw = new_gateway_token()
        now = utcnow()
        token_id = repo.rotate_gateway_token(account_id, raw, p.username, now)
        audit(p, "gateway.rotate_token", "ACCEPTED", {**payload, "token_id": token_id}, None,
              account_id)
        response.headers["Cache-Control"] = "no-store"
        return GatewayCredential(account_id=account_id, token_id=token_id, token=raw,
                                 created_at=now)

    return r
