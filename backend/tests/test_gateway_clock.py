"""ING-16 + 1A-C20: backend đo lệch đồng hồ máy Gateway (so với đồng hồ backend) và hiển thị lệch
đồng hồ server MT5 do Gateway đo. Backend luôn dùng đồng hồ của mình cho dữ liệu."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.api.ingest import GatewayMonitor, Heartbeat, clock_state
from gold_trading.common.time import utcnow
from tests.test_ingest_api import AUTH, HB, client

NOW = datetime(2026, 1, 14, 10, 0, tzinfo=UTC)
ST = "/api/accounts/default/gateway/status"


def test_clock_state_thresholds():
    assert clock_state(None, 2, 30) == "UNKNOWN"
    assert clock_state(2.0, 2, 30) == "OK"  # đúng biên: chưa vượt
    assert clock_state(-2.1, 2, 30) == "WARN"
    assert clock_state(30.0, 2, 30) == "WARN"
    assert clock_state(-30.1, 2, 30) == "BAD"
    assert clock_state(29.9, None, 30) == "OK"


@pytest.mark.parametrize("delta, state", [(0, "OK"), (5, "WARN"), (-45, "BAD"), (3600, "BAD")])
def test_skew_measured_from_gateway_time(delta, state):
    m = GatewayMonitor()
    hb = Heartbeat.model_validate(HB | {"gateway_time": (NOW + timedelta(seconds=delta))
                                        .isoformat()})
    m.record(hb, NOW)
    st = m.status(NOW)
    assert st.gateway_clock_skew_s == delta and st.gateway_clock == state


def test_old_gateway_unknown_and_mt5_residual():
    m = GatewayMonitor()
    m.record(Heartbeat.model_validate(HB), NOW)
    assert m.status(NOW).gateway_clock == "UNKNOWN" and m.status(NOW).mt5_clock == "UNKNOWN"
    m.record(Heartbeat.model_validate(HB | {"mt5_clock_residual_s": -40.26}), NOW)
    st = m.status(NOW)
    assert st.mt5_clock_residual_s == -40.3 and st.mt5_clock == "BAD"
    m.record(Heartbeat.model_validate(HB | {"mt5_clock_residual_s": 4.0}), NOW)
    assert m.status(NOW).mt5_clock == "OK"


def test_api_reports_skew_and_rejects_absurd_values():
    c, _ = client()
    hb = HB | {"gateway_time": (utcnow() + timedelta(seconds=40)).isoformat(),
               "mt5_clock_residual_s": 1.5}
    assert c.post("/api/ingest/mt5/heartbeat", json=hb, headers=AUTH).status_code == 200
    s = c.get(ST).json()
    assert s["gateway_clock"] == "BAD" and 39 <= s["gateway_clock_skew_s"] <= 41
    assert s["mt5_clock"] == "OK"
    for bad in ({"mt5_clock_residual_s": 5000}, {"gateway_time": "2026-01-14T10:00:00"}):
        assert c.post("/api/ingest/mt5/heartbeat", json=HB | bad, headers=AUTH).status_code == 422


def test_bad_clock_logged_once_per_change(caplog):
    m = GatewayMonitor()
    hb = Heartbeat.model_validate(HB | {"gateway_time": (NOW + timedelta(seconds=60))
                                        .isoformat()})
    caplog.set_level("WARNING")
    for _ in range(3):
        m.record(hb, NOW)
    assert sum("Đồng hồ lệch" in r.message for r in caplog.records) == 1


# ---------- 1A-C10: lý do mất kết nối ----------


@pytest.mark.parametrize("over, age, state, reason", [
    ({}, 0, "CONNECTED", None),
    ({}, 31, "DISCONNECTED", "NO_HEARTBEAT"),
    ({}, 30, "CONNECTED", None),  # đúng 30 giây: chưa quá hạn
    ({"terminal_connected": False}, 0, "DISCONNECTED", "TERMINAL_OFFLINE"),
    ({"identity": None, "account": None, "gateway_version": "0.9.0"}, 0, "DISCONNECTED",
     "NOT_LOGGED_IN"),
    ({"identity": None, "account": None, "gateway_version": "0.2.0"}, 0, "CONNECTED", None),
    ({"identity": None, "account": None, "gateway_version": "dev"}, 0, "CONNECTED", None),
])
def test_disconnect_reasons(over, age, state, reason):
    m = GatewayMonitor()
    base = HB | {"identity": {"login": 1, "server": HB["server"], "company": None,
                              "account_type": HB["account_type"]}, "gateway_version": "0.9.0"}
    m.record(Heartbeat.model_validate(base | over), NOW)
    st = m.status(NOW + timedelta(seconds=age))
    assert (st.state, st.reason) == (state, reason)
