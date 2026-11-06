"""Cấu hình đăng nhập (OIDC, mô hình BFF). Xem docs/thiet-ke/00-xac-thuc-phan-quyen.md.

Thiếu cấu hình hoặc cấu hình không an toàn → lỗi khi khởi động, không chạy "tạm không đăng nhập".
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import urlsplit

REALM = "gold-trading"
MIN_SECRET_LEN = 16
LOCAL_HOSTS = ("localhost", "127.0.0.1")


class AuthConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AuthConfig:
    public_url: str
    """Địa chỉ mở trên trình duyệt, ví dụ https://may.tailnet.ts.net (không có / cuối)."""
    internal_issuer_url: str
    """URL realm mà backend gọi qua mạng nội bộ (đổi code, JWKS, làm mới)."""
    client_id: str
    client_secret: str = field(repr=False)
    session_max: timedelta = timedelta(hours=8)
    session_idle: timedelta = timedelta(minutes=30)
    refresh_interval: timedelta = timedelta(seconds=60)
    clock_leeway_s: int = 5
    extra_origins: tuple[str, ...] = ()
    multi_user_enabled: bool = False
    """DEC-12 chưa có câu trả lời → không cho thêm người thứ hai vào tài khoản giao dịch."""

    def __post_init__(self) -> None:
        if not self.client_secret or len(self.client_secret) < MIN_SECRET_LEN:
            raise AuthConfigError(
                f"GT_OIDC_CLIENT_SECRET thiếu hoặc ngắn hơn {MIN_SECRET_LEN} ký tự"
            )
        parts = urlsplit(self.public_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise AuthConfigError(f"GT_PUBLIC_URL không hợp lệ: {self.public_url!r}")
        if parts.path not in ("", "/") or parts.query or parts.fragment:
            raise AuthConfigError("GT_PUBLIC_URL chỉ gồm scheme://host[:port], không có đường dẫn")
        if parts.scheme == "http" and parts.hostname not in LOCAL_HOSTS:
            # Cookie Secure không gửi qua http (trừ localhost): truy cập từ máy khác phải HTTPS.
            raise AuthConfigError(
                "GT_PUBLIC_URL dùng http chỉ được cho localhost. Truy cập từ máy khác phải dùng "
                "HTTPS (Tailscale Serve: https://<máy>.<tailnet>.ts.net)"
            )
        if self.session_idle > self.session_max:
            raise AuthConfigError("Thời gian không hoạt động không được dài hơn thời gian phiên")

    @property
    def origin(self) -> str:
        p = urlsplit(self.public_url)
        return f"{p.scheme}://{p.netloc}"

    @property
    def public_host(self) -> str:
        return urlsplit(self.public_url).hostname or ""

    @property
    def issuer(self) -> str:
        """`iss` mà Keycloak ghi vào token (theo KC_HOSTNAME = public_url + /auth)."""
        return f"{self.origin}/auth/realms/{REALM}"

    @property
    def redirect_uri(self) -> str:
        return f"{self.origin}/api/auth/callback"

    @property
    def authorize_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/auth"

    @property
    def end_session_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/logout"

    @property
    def token_endpoint(self) -> str:
        return f"{self.internal_issuer_url}/protocol/openid-connect/token"

    @property
    def jwks_endpoint(self) -> str:
        return f"{self.internal_issuer_url}/protocol/openid-connect/certs"

    @property
    def allowed_origins(self) -> frozenset[str]:
        return frozenset((self.origin, *self.extra_origins))

    @property
    def secure_cookies(self) -> bool:
        # Trình duyệt coi http://localhost là ngữ cảnh an toàn nên vẫn nhận cookie Secure.
        return True

    @classmethod
    def from_env(cls) -> AuthConfig:
        def req(name: str) -> str:
            v = os.environ.get(name, "").strip()
            if not v:
                raise AuthConfigError(f"Thiếu biến môi trường {name} (cấu hình đăng nhập)")
            return v

        extra = tuple(
            o.strip().rstrip("/")
            for o in os.environ.get("GT_EXTRA_ORIGINS", "").split(",")
            if o.strip()
        )
        try:
            max_h = float(os.environ.get("GT_SESSION_MAX_HOURS", "8"))
            idle_m = float(os.environ.get("GT_SESSION_IDLE_MINUTES", "30"))
        except ValueError as e:
            raise AuthConfigError(f"Thời gian phiên không hợp lệ: {e}") from e
        return cls(
            public_url=req("GT_PUBLIC_URL").rstrip("/"),
            internal_issuer_url=req("GT_OIDC_INTERNAL_URL").rstrip("/"),
            client_id=req("GT_OIDC_CLIENT_ID"),
            client_secret=req("GT_OIDC_CLIENT_SECRET"),
            session_max=timedelta(hours=max_h),
            session_idle=timedelta(minutes=idle_m),
            extra_origins=extra,
            multi_user_enabled=os.environ.get("GT_MULTI_USER_ENABLED", "0") == "1",
        )
