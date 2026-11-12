"""ING-16 + 1A-C20: backend đo lệch đồng hồ máy Gateway (so với đồng hồ backend) và hiển thị lệch
đồng hồ server MT5 do Gateway đo. Backend luôn dùng đồng hồ của mình cho dữ liệu."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.api.ingest import GatewayMonitor, Heartbeat, clock_state
from gold_trading.common.time import utcnow
from gold_trading.contracts.candle import DataSource
from gold_trading.storage.candles import InMemoryCandleStore
from gold_trading.storage.repository import InMemoryRepository
from tests.auth_helpers import user_client
from tests.mt5_helpers import link_active
from tests.test_ingest_api import AUTH, HB, TOKEN, client

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


# ---------- 2026-11-12 kiểm trên máy: khởi động, "mất kết nối từ lúc", liên kết ----------

START = {"gateway_id": "win-1", "gateway_version": "0.10.3", "read_only": True,
         "terminal_connected": False, "account_type": "UNKNOWN", "server_tz": "Europe/Athens",
         "phase": "STARTING"}
RUN = HB | {"identity": {"login": 1, "server": HB["server"], "company": None,
                         "account_type": HB["account_type"]}, "gateway_version": "0.10.3"}


def hb(d):
    return Heartbeat.model_validate(d)


def test_starting_shows_starting_not_no_heartbeat_during_check():
    """Gateway kiểm tra 1–3 phút trước khi gửi nhịp tim thường: báo "đang khởi động"."""
    m = GatewayMonitor()
    m.record(hb(START), NOW)
    for sec in (0, 31, 179, 300):
        st = m.status(NOW + timedelta(seconds=sec))
        assert (st.state, st.reason, st.reason_since) == ("DISCONNECTED", "GATEWAY_STARTING", NOW)
    # quá hạn khởi động mà không còn tín hiệu → như mất tín hiệu
    assert m.status(NOW + timedelta(seconds=301)).reason == "NO_HEARTBEAT"
    m.record(hb(RUN), NOW + timedelta(seconds=120))
    st = m.status(NOW + timedelta(seconds=121))
    assert (st.state, st.reason, st.reason_since) == ("CONNECTED", None, None)


def test_repeated_restarts_become_start_failed():
    """Task Scheduler chạy lại mỗi phút mà check cứ hỏng → sau 5 phút báo START_FAILED."""
    m = GatewayMonitor()
    for k in range(7):
        m.record(hb(START), NOW + timedelta(minutes=k))
    st = m.status(NOW + timedelta(minutes=6))
    assert (st.reason, st.reason_since) == ("START_FAILED", NOW)
    # chạy được một lần → chuỗi mới
    m.record(hb(RUN), NOW + timedelta(minutes=7))
    m.record(hb(START), NOW + timedelta(minutes=8))
    assert m.status(NOW + timedelta(minutes=8)).reason == "GATEWAY_STARTING"


def test_starting_after_long_gap_is_new_sequence():
    """Khởi động hôm qua, hôm nay khởi động lại: không bị coi là "khởi động mãi không xong"."""
    m = GatewayMonitor()
    m.record(hb(START), NOW)
    m.record(hb(START), NOW + timedelta(hours=10))
    st = m.status(NOW + timedelta(hours=10, minutes=1))
    assert (st.reason, st.reason_since) == ("GATEWAY_STARTING", NOW + timedelta(hours=10))


def test_offline_since_is_first_offline_heartbeat_not_last():
    """MT5 mất mạng: "từ lúc" giữ mốc nhịp tim ĐẦU TIÊN báo mất (không nhảy theo nhịp tim)."""
    m = GatewayMonitor()
    m.record(hb(RUN), NOW)
    off = RUN | {"terminal_connected": False}
    for k in range(1, 5):
        m.record(hb(off), NOW + timedelta(seconds=10 * k))
    st = m.status(NOW + timedelta(seconds=41))
    assert (st.reason, st.reason_since) == ("TERMINAL_OFFLINE", NOW + timedelta(seconds=10))
    assert st.last_seen_at == NOW + timedelta(seconds=40)
    m.record(hb(RUN), NOW + timedelta(seconds=50))
    assert m.status(NOW + timedelta(seconds=50)).reason_since is None
    # đổi lý do (mất mạng → chưa đăng nhập) vẫn giữ mốc mất đầu tiên
    m.record(hb(off), NOW + timedelta(seconds=60))
    m.record(hb(RUN | {"identity": None, "account": None}), NOW + timedelta(seconds=70))
    st = m.status(NOW + timedelta(seconds=71))
    assert (st.reason, st.reason_since) == ("NOT_LOGGED_IN", NOW + timedelta(seconds=60))


def client_repo(linked=True):
    repo = InMemoryRepository()
    if linked:
        link_active(repo)
    c = user_client(repo, candle_store=InMemoryCandleStore(), data_source=DataSource.MT5,
                    run_sample_feed=False, run_analysts=False, ingest_token=TOKEN)
    return c, repo


def test_starting_heartbeat_does_not_touch_link():
    """Nhịp tim STARTING không có danh tính: KHÔNG được chuyển liên kết ACTIVE → DISCONNECTED."""
    c, repo = client_repo()
    assert c.post("/api/ingest/mt5/heartbeat", json=START, headers=AUTH).status_code == 200
    assert [x.status for x in repo.mt5_links("default")] == ["ACTIVE"]
    s = c.get(ST).json()
    assert (s["reason"], s["link_status"]) == ("GATEWAY_STARTING", "ACTIVE")
    assert s["reason_since"] is not None


def test_status_reports_link_state():
    c, repo = client_repo(linked=False)
    assert c.get(ST).json()["link_status"] == "NONE"
    link = link_active(repo)
    assert c.get(ST).json()["link_status"] == "ACTIVE"
    assert repo.transition_link("default", link.link_id, "ACTIVE", "MISMATCH", utcnow())
    assert c.get(ST).json()["link_status"] == "MISMATCH"


def test_starting_rejects_bad_phase():
    assert Heartbeat.model_validate(HB).phase == "RUNNING"  # Gateway cũ: không gửi phase
    with pytest.raises(ValueError):
        Heartbeat.model_validate(HB | {"phase": "PAUSED"})
