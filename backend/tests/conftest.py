from datetime import UTC, datetime, timedelta

import pytest

T0 = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)


@pytest.fixture
def t0() -> datetime:
    return T0


def minutes(n: float) -> timedelta:
    return timedelta(minutes=n)
