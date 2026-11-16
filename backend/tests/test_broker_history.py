"""KN-05 (GW-09): lịch sử thông số broker + số liệu tài khoản — chỉ thêm, point-in-time."""

from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.storage.broker_history import (
    EQUITY_FIELDS,
    SPEC_FIELDS,
    InMemoryBrokerHistoryStore,
    SpecKey,
    SqlBrokerHistoryStore,
)
from gold_trading.storage.repository import SqlRepository

T0 = datetime(2026, 11, 16, 10, 5, tzinfo=UTC)
KEY = SpecKey("default", 51234567, "Broker-Demo", "XAUUSD")
SPEC = {"digits": 2, "point": 0.01, "contract_size": 100.0, "volume_min": 0.01,
        "volume_max": 100.0, "volume_step": 0.01, "currency_profit": "USD", "stops_level": 0,
        "freeze_level": 0, "swap_mode": 1, "swap_long": -45.2, "swap_short": 12.1,
        "swap_rollover3days": 3, "leverage": 500, "account_currency": "USD"}
EQ = {"currency": "USD", "balance": 10000.0, "equity": 10012.5, "margin": 0.0,
      "margin_free": 10012.5, "margin_level": None, "leverage": 500}
H = timedelta(hours=1)


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryBrokerHistoryStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'b.db'}")
    repo.create_all()
    return SqlBrokerHistoryStore(repo.engine)


def test_fields_cover_spec():
    assert set(SPEC) == set(SPEC_FIELDS) and set(EQ) == set(EQUITY_FIELDS)


def test_records_only_on_change_and_a_b_a(store):
    assert store.record_spec(KEY, SPEC, observed_at=T0, gateway_version="0.10.3") is True
    assert store.record_spec(KEY, SPEC, observed_at=T0 + H, gateway_version="0.10.3") is False
    b = SPEC | {"swap_long": -47.0}
    assert store.record_spec(KEY, b, observed_at=T0 + 2 * H, gateway_version="0.10.3") is True
    assert store.record_spec(KEY, SPEC, observed_at=T0 + 3 * H, gateway_version="0.10.3") is True
    rows = store.specs("default")
    assert [r.spec["swap_long"] for r in rows] == [-45.2, -47.0, -45.2]


def test_spec_at_point_in_time(store):
    store.record_spec(KEY, SPEC, observed_at=T0, gateway_version="g")
    store.record_spec(KEY, SPEC | {"swap_long": -50.0}, observed_at=T0 + 24 * H,
                      gateway_version="g")
    assert store.spec_at("default", "XAUUSD", T0 - timedelta(seconds=1)) is None
    assert store.spec_at("default", "XAUUSD", T0).spec["swap_long"] == -45.2
    assert store.spec_at("default", "XAUUSD", T0 + 23 * H).spec["swap_long"] == -45.2
    assert store.spec_at("default", "XAUUSD", T0 + 24 * H).spec["swap_long"] == -50.0
    assert store.spec_at("other", "XAUUSD", T0 + 48 * H) is None
    assert store.spec_at("default", "XAUUSDm", T0 + 48 * H) is None


def test_none_kept_as_unknown_not_zero(store):
    s = SPEC | {"swap_long": None, "stops_level": None, "leverage": None}
    store.record_spec(KEY, s, observed_at=T0, gateway_version="g")
    r = store.spec_at("default", "XAUUSD", T0)
    assert r.spec["swap_long"] is None and r.spec["stops_level"] is None
    assert r.spec["leverage"] is None
    # Không đọc được → đọc được 0 là một THAY ĐỔI, phải ghi.
    assert store.record_spec(KEY, s | {"swap_long": 0.0}, observed_at=T0 + H,
                             gateway_version="g") is True


def test_identity_and_symbol_separate(store):
    other = SpecKey("default", 99, "Broker-Demo", "XAUUSD")
    assert store.record_spec(KEY, SPEC, observed_at=T0, gateway_version="g")
    assert store.record_spec(other, SPEC, observed_at=T0, gateway_version="g")
    assert len(store.specs("default")) == 2


@pytest.mark.parametrize("bad", [
    {k: v for k, v in SPEC.items() if k != "swap_long"},      # thiếu trường
    SPEC | {"commission": 3.5},                                 # trường lạ (không đoán phí)
])
def test_wrong_fields_rejected(store, bad):
    with pytest.raises(ValueError):
        store.record_spec(KEY, bad, observed_at=T0, gateway_version="g")


def test_naive_time_and_time_going_back_rejected(store):
    with pytest.raises(ValueError):
        store.record_spec(KEY, SPEC, observed_at=datetime(2026, 11, 16), gateway_version="g")
    store.record_spec(KEY, SPEC, observed_at=T0, gateway_version="g")
    with pytest.raises(ValueError):
        store.record_spec(KEY, SPEC | {"swap_long": 1.0}, observed_at=T0 - H, gateway_version="g")


def test_equity_first_per_hour(store):
    assert store.record_equity("default", 1, "S", EQ, observed_at=T0) is True
    assert store.record_equity("default", 1, "S", EQ | {"equity": 1.0},
                               observed_at=T0 + timedelta(minutes=50)) is False
    assert store.record_equity("default", 1, "S", EQ | {"equity": 9990.0},
                               observed_at=T0 + H) is True
    assert store.record_equity("default", 2, "S", EQ, observed_at=T0) is True   # login khác
    rows = store.equity_rows("default")
    assert [(r["mt5_login"], r["equity"]) for r in rows] == [(1, 10012.5), (2, 10012.5),
                                                            (1, 9990.0)]
    assert rows[0]["hour"] == datetime(2026, 11, 16, 10, tzinfo=UTC)
    assert rows[0]["margin_level"] is None


def test_equity_wrong_fields_and_naive_rejected(store):
    with pytest.raises(ValueError):
        store.record_equity("default", 1, "S", {"equity": 1.0}, observed_at=T0)
    with pytest.raises(ValueError):
        store.record_equity("default", 1, "S", EQ, observed_at=datetime(2026, 11, 16))


def test_sql_check_constraint_not_swallowed(tmp_path):
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'c.db'}")
    repo.create_all()
    st = SqlBrokerHistoryStore(repo.engine)
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        st.record_equity("default", 1, "S", EQ | {"margin": -5.0}, observed_at=T0)
    with pytest.raises(IntegrityError):
        st.record_spec(KEY, SPEC | {"contract_size": 0.0}, observed_at=T0, gateway_version="g")


# ------------------------------------------------------------------ qua nhịp tim Gateway (API)

def _hb(**over):
    from tests.test_mt5_links import hb
    body = hb() | {"gateway_version": "0.10.3"}
    body["symbol"] = body["symbol"] | {"swap_long": -45.2, "swap_short": 12.1, "swap_mode": 1,
                                       "stops_level": 0, "freeze_level": 0,
                                       "swap_rollover3days": 3, "currency_profit": "USD"}
    body["account"] = {"currency": "USD", "balance": 10000.0, "equity": 10012.5, "margin": 0.0,
                       "margin_free": 10012.5, "margin_level": None, "leverage": 500,
                       "trade_allowed": True}
    return body | over


def test_heartbeat_records_history():
    from tests.test_ingest_api import AUTH, client
    c, _ = client()
    st = c.app.state.broker_history
    assert c.post("/api/ingest/mt5/heartbeat", json=_hb(), headers=AUTH).status_code == 200
    assert c.post("/api/ingest/mt5/heartbeat", json=_hb(), headers=AUTH).status_code == 200
    rows = st.specs("default")
    assert len(rows) == 1
    r = rows[0]
    assert r.key.mt5_login == 51234567 and r.key.broker_symbol == "XAUUSD"
    assert r.spec["swap_long"] == -45.2 and r.spec["leverage"] == 500
    assert r.spec["contract_size"] == 100 and r.gateway_version == "0.10.3"
    assert len(st.equity_rows("default")) == 1
    changed = _hb()
    changed["symbol"] = changed["symbol"] | {"swap_long": -60.0}
    c.post("/api/ingest/mt5/heartbeat", json=changed, headers=AUTH)
    assert [x.spec["swap_long"] for x in st.specs("default")] == [-45.2, -60.0]


def test_heartbeat_without_identity_or_starting_records_nothing():
    from tests.test_ingest_api import AUTH, HB, client
    c, _ = client()
    st = c.app.state.broker_history
    assert c.post("/api/ingest/mt5/heartbeat", json=HB, headers=AUTH).status_code == 200
    assert c.post("/api/ingest/mt5/heartbeat", json=_hb(phase="STARTING"),
                  headers=AUTH).status_code == 200
    assert st.specs("default") == [] and st.equity_rows("default") == []


def test_heartbeat_survives_storage_error():
    from sqlalchemy.exc import OperationalError

    from tests.test_ingest_api import AUTH, client
    c, _ = client()

    def boom(*a, **k):
        raise OperationalError("x", {}, Exception("disk full"))

    c.app.state.broker_history.record_spec = boom
    r = c.post("/api/ingest/mt5/heartbeat", json=_hb(), headers=AUTH)
    assert r.status_code == 200 and r.json()["state"] == "CONNECTED"
