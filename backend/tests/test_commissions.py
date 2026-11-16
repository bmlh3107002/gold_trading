"""RSK-11 / Q3: phí hoa hồng / lot do người dùng nhập — chỉ thêm, có phiên bản, point-in-time."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from gold_trading.storage.commissions import (
    Commission,
    InMemoryCommissionStore,
    SqlCommissionStore,
)
from gold_trading.storage.repository import SqlRepository

T = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryCommissionStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'c.db'}")
    repo.create_all()
    return SqlCommissionStore(repo.engine)


def c(v, t=T, acc="a1", **kw):
    return Commission(acc, Decimal(v), kw.get("currency", "USD"), t, kw.get("by", "sub-u"),
                      kw.get("reason", "theo trang phí của sàn"))


def test_none_until_entered_and_zero_only_if_entered(store):
    assert store.at("a1", T) is None                 # chưa nhập → không đoán là 0
    store.record(c("0", T))
    got = store.at("a1", T)
    assert got is not None and got.per_lot == 0


def test_versions_point_in_time(store):
    store.record(c("7", T))
    store.record(c("6.5", T + timedelta(days=1)))
    assert store.at("a1", T - timedelta(seconds=1)) is None
    assert store.at("a1", T + timedelta(hours=1)).per_lot == Decimal("7")
    assert store.at("a1", T + timedelta(days=2)).per_lot == Decimal("6.5")
    assert store.at("a2", T + timedelta(days=2)) is None      # tài khoản khác
    assert [x.per_lot for x in store.history("a1")] == [Decimal("7"), Decimal("6.5")]


def test_decimal_exact_round_trip(store):
    store.record(c("3.123456", T))
    assert store.at("a1", T).per_lot == Decimal("3.123456")


@pytest.mark.parametrize("bad", [
    dict(v="-1"), dict(v="1000.01"), dict(v="NaN"), dict(v="1.1234567"),
    dict(v="7", currency="EUR"), dict(v="7", by=""), dict(v="7", reason=""),
])
def test_invalid_rejected(store, bad):
    bad = dict(bad)
    v = bad.pop("v")
    with pytest.raises(ValueError):
        store.record(c(v, **bad))
    assert store.at("a1", T) is None


def test_naive_time_rejected(store):
    with pytest.raises(ValueError):
        store.record(c("7", T.replace(tzinfo=None)))


def test_float_rejected(store):
    with pytest.raises(ValueError):
        store.record(Commission("a1", 7.0, "USD", T, "u", "r"))  # type: ignore[arg-type]
