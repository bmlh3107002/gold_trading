"""Tạo/xóa người dùng trên Keycloak qua Admin REST API (MT-20).

Dùng service account của chính client ``gold-trading-dashboard`` (client_credentials), chỉ có
quyền ``realm-management: manage-users, view-users`` trong realm ``gold-trading``
(``ops/keycloak/sync-client.sh`` cấp). Không bao giờ gán realm role (ADMIN...) cho ai.

- Mật khẩu ban đầu là **tạm thời**: Keycloak bắt người dùng đổi ở lần đăng nhập đầu; chính sách
  mật khẩu của realm (≥ 12 ký tự, khác username/email) do Keycloak kiểm.
- Không ghi mật khẩu vào log hay lỗi trả về.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from gold_trading.auth.config import AuthConfig
from gold_trading.auth.oidc import ProviderUnavailable

log = logging.getLogger("gold_trading.auth")


class AdminApiError(Exception):
    """Lỗi khi gọi Keycloak Admin API."""


class AdminNotConfigured(AdminApiError):
    """Service account chưa được bật/cấp quyền: chạy ``sync-client.sh``."""


class UserExists(AdminApiError):
    """Tên đăng nhập hoặc email đã có trên Keycloak."""


class InvalidUser(AdminApiError):
    """Keycloak từ chối dữ liệu (thường là mật khẩu không đạt chính sách)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason  # "password_policy" | "invalid"


@dataclass(frozen=True)
class NewUser:
    username: str
    email: str
    first_name: str
    last_name: str
    password: str = field(repr=False)


def admin_base(config: AuthConfig) -> str:
    """``.../auth/realms/gold-trading`` → ``.../auth/admin/realms/gold-trading``."""
    base = config.internal_issuer_url.rstrip("/")
    head, sep, realm = base.rpartition("/realms/")
    if not sep or not realm or "/" in realm:
        raise AdminApiError(f"GT_OIDC_INTERNAL_URL không có dạng .../realms/<realm>: {base!r}")
    return f"{head}/admin/realms/{realm}"


class KeycloakAdmin:
    def __init__(self, config: AuthConfig, http: httpx.Client | None = None) -> None:
        self.config = config
        self._http = http or httpx.Client(timeout=10.0)
        self._base = admin_base(config)

    def _call(self, method: str, url: str, **kw: Any) -> httpx.Response:
        try:
            r = self._http.request(method, url, **kw)
        except httpx.HTTPError as e:
            raise ProviderUnavailable("Không kết nối được Keycloak") from e
        if r.status_code >= 500:
            raise ProviderUnavailable(f"Keycloak lỗi {r.status_code}")
        return r

    def _token(self) -> str:
        r = self._call(
            "POST",
            self.config.token_endpoint,
            data={
                "grant_type": "client_credentials",
                # Keycloak ≥ 26.8: Admin API chỉ nhận token có audience của scope kc-admin-api.
                # Scope này là TÙY CHỌN trên client: token đăng nhập của người dùng không có.
                "scope": "kc-admin-api",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
            },
        )
        if r.status_code != 200:
            # unauthorized_client: chưa bật service account trên client
            raise AdminNotConfigured(f"client_credentials bị từ chối ({r.status_code})")
        tok = r.json().get("access_token")
        if not isinstance(tok, str) or not tok:
            raise AdminNotConfigured("Keycloak không trả access_token")
        return tok

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}"}

    def create_user(self, u: NewUser) -> str:
        """Tạo người dùng, trả ``sub`` (id Keycloak)."""
        body = {
            "username": u.username,
            "email": u.email,
            "firstName": u.first_name,
            "lastName": u.last_name,
            "enabled": True,
            "emailVerified": True,
            "credentials": [{"type": "password", "value": u.password, "temporary": True}],
        }
        r = self._call("POST", f"{self._base}/users", json=body, headers=self._headers())
        if r.status_code == 201:
            loc = r.headers.get("location", "")
            sub = loc.rstrip("/").rsplit("/users/", 1)[-1] if "/users/" in loc else ""
            if not sub:
                raise AdminApiError("Keycloak không trả Location của người dùng mới")
            return sub
        if r.status_code == 409:
            raise UserExists("Tên đăng nhập hoặc email đã có")
        if r.status_code in (401, 403):
            raise AdminNotConfigured(f"Service account thiếu quyền manage-users ({r.status_code})")
        if r.status_code == 400:
            msg = _error_text(r)
            log.warning("Keycloak từ chối tạo người dùng %s: %s", u.username, msg)
            reason = "password_policy" if "password" in msg.lower() else "invalid"
            raise InvalidUser(reason)
        raise AdminApiError(f"Keycloak trả {r.status_code} khi tạo người dùng")

    def delete_user(self, sub: str) -> None:
        r = self._call("DELETE", f"{self._base}/users/{sub}", headers=self._headers())
        if r.status_code not in (204, 404):
            raise AdminApiError(f"Keycloak trả {r.status_code} khi xóa người dùng")


def _error_text(r: httpx.Response) -> str:
    try:
        j = r.json()
    except ValueError:
        return r.text[:200]
    if isinstance(j, dict):
        return str(j.get("errorMessage") or j.get("error") or j)[:200]
    return str(j)[:200]
