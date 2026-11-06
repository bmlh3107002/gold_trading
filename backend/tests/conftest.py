from datetime import UTC, datetime, timedelta

import pytest

from tests.auth_helpers import CLIENT_SECRET, INTERNAL, PUBLIC_URL

T0 = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)


@pytest.fixture
def t0() -> datetime:
    return T0


def minutes(n: float) -> timedelta:
    return timedelta(minutes=n)


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch):
    """create_app(auth="env") cần cấu hình đăng nhập; test không gọi Keycloak thật."""
    monkeypatch.setenv("GT_PUBLIC_URL", PUBLIC_URL)
    monkeypatch.setenv("GT_OIDC_INTERNAL_URL", INTERNAL)
    monkeypatch.setenv("GT_OIDC_CLIENT_ID", "gold-trading-dashboard")
    monkeypatch.setenv("GT_OIDC_CLIENT_SECRET", CLIENT_SECRET)
