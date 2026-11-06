"""MT-20: ADMIN tạo người dùng ngay trên Dashboard.

Một lệnh làm ba việc: tạo người dùng trên Keycloak (mật khẩu tạm, bắt đổi ở lần đăng nhập
đầu) → tạo tài khoản giao dịch riêng → người đó là OWNER. Ghi DB lỗi thì xóa lại người dùng vừa
tạo trên Keycloak để không còn tài khoản đăng nhập "mồ côi".

- Chỉ ADMIN (realm role trên Keycloak). Người khác → 403 và ghi audit.
- ``GT_MULTI_USER_ENABLED=0`` (DEC-12) → 409. Không giới hạn số người khi đã bật.
- Mật khẩu không bao giờ vào audit, log hay phản hồi.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from gold_trading.accounts.runtime import AccountRegistry
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

log = logging.getLogger("gold_trading.api")

USERNAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{2,29}$"
MIN_PASSWORD = 12


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    username: str = Field(pattern=USERNAME_PATTERN,
                          description="Chữ thường không dấu, số, . _ - (3–30 ký tự)")
    email: str = Field(min_length=3, max_length=256, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    first_name: str = Field(min_length=1, max_length=64)
    last_name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=MIN_PASSWORD, max_length=128, repr=False,
                          description="Mật khẩu tạm; người dùng phải đổi ở lần đăng nhập đầu")
    account_name: str | None = Field(default=None, min_length=1, max_length=128,
                                     description="Tên tài khoản giao dịch riêng")


class UserCreated(BaseModel):
    sub: str
    username: str
    email: str
    display_name: str
    account_id: str
    account_name: str


def account_id_for(username: str) -> str:
    """``u-<username>``, chỉ dùng ký tự hợp lệ của mã tài khoản (``.`` → ``-``)."""
    return "u-" + username.replace(".", "-")


def users_router(
    repo: Repository,
    registry: AccountRegistry,
    kc_admin: KeycloakAdmin,
    *,
    multi_user_enabled: bool,
) -> APIRouter:
    r = APIRouter(tags=["admin"])

    def audit(p: Principal, outcome: str, payload: dict[str, Any], detail: str | None,
              account_id: str | None = None) -> None:
        repo.append_audit(AuditEntry(utcnow(), p.username, "user.create", outcome, payload,
                                     detail, account_id, p.sub))

    @r.post("/api/admin/users", response_model=UserCreated, status_code=201)
    def create_user(cmd: UserCreate, p: CurrentUser) -> UserCreated:
        # Không bao giờ ghi mật khẩu
        payload = cmd.model_dump(exclude={"password"})
        if not p.is_admin:
            audit(p, "REJECTED", payload, "Chỉ ADMIN")
            raise HTTPException(403, "Chỉ quản trị hệ thống được tạo người dùng")
        if not multi_user_enabled:
            msg = "Chưa nhận người dùng thứ hai (DEC-12). Bật GT_MULTI_USER_ENABLED=1."
            audit(p, "REJECTED", payload, msg)
            raise HTTPException(409, msg)
        if cmd.password.lower() in (cmd.username.lower(), cmd.email.lower()):
            audit(p, "REJECTED", payload, "Mật khẩu trùng tên đăng nhập/email")
            raise HTTPException(422, "Mật khẩu không được trùng tên đăng nhập hoặc email")
        acc_id = account_id_for(cmd.username)
        if repo.account(acc_id) is not None:
            audit(p, "REJECTED", payload, "Mã tài khoản đã tồn tại")
            raise HTTPException(409, "Tên đăng nhập hoặc email đã có")
        display = f"{cmd.first_name} {cmd.last_name}".strip()
        acc_name = cmd.account_name or f"Tài khoản của {display}"

        try:
            sub = kc_admin.create_user(NewUser(cmd.username, cmd.email, cmd.first_name,
                                               cmd.last_name, cmd.password))
        except UserExists:
            audit(p, "REJECTED", payload, "Keycloak: tên đăng nhập hoặc email đã có")
            raise HTTPException(409, "Tên đăng nhập hoặc email đã có") from None
        except InvalidUser as e:
            detail = ("Mật khẩu không đạt chính sách (≥ 12 ký tự, khác tên đăng nhập/email)"
                      if e.reason == "password_policy" else "Keycloak từ chối dữ liệu người dùng")
            audit(p, "REJECTED", payload, detail)
            raise HTTPException(422, detail) from None
        except AdminNotConfigured:
            detail = ("Keycloak chưa cho phép backend tạo người dùng. Chạy: docker compose exec "
                      "keycloak /opt/keycloak/bin/sync-client.sh")
            audit(p, "REJECTED", payload, detail)
            raise HTTPException(503, detail) from None
        except (ProviderUnavailable, AdminApiError) as e:
            log.warning("Tạo người dùng %s thất bại: %s", cmd.username, e)
            audit(p, "REJECTED", payload, "Không gọi được Keycloak")
            raise HTTPException(503, "Không gọi được Keycloak, thử lại sau") from None

        now = utcnow()
        user = UserRecord(sub, cmd.username, cmd.email, display, None, None)
        acc = TradingAccount(acc_id, acc_name, now, p.username, price_feed=False)
        owner = Member(acc_id, sub, "OWNER", now, p.username)
        try:
            repo.provision_user(user, acc, owner)
        except (ConflictError, Exception) as e:
            # Bù trừ: xóa người dùng vừa tạo trên Keycloak (không để lại đăng nhập mồ côi)
            try:
                kc_admin.delete_user(sub)
                cleaned = True
            except Exception:  # pragma: no cover - ghi log để người vận hành xóa tay
                log.error("Không xóa được người dùng %s (%s) trên Keycloak sau lỗi DB",
                          cmd.username, sub)
                cleaned = False
            audit(p, "REJECTED", payload,
                  f"Lỗi lưu DB ({type(e).__name__}); đã xóa trên Keycloak: {cleaned}")
            code = 409 if isinstance(e, ConflictError) else 500
            raise HTTPException(code, "Không lưu được người dùng mới") from None

        registry.add(acc_id)
        audit(p, "ACCEPTED", {**payload, "sub": sub}, None, acc_id)
        return UserCreated(sub=sub, username=cmd.username, email=cmd.email,
                           display_name=display, account_id=acc_id, account_name=acc_name)

    return r
