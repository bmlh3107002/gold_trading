import pytest
from fastapi.testclient import TestClient

from gold_trading.common.enums import SafetyState
from gold_trading.safety.supervisor import SafetySupervisor
from gold_trading.storage.repository import SqlRepository
from tests.auth_helpers import admin_client

KW = {"trigger_source": "t", "actor": "t"}


@pytest.fixture
def repo(tmp_path) -> SqlRepository:
    r = SqlRepository.from_url(f"sqlite:///{tmp_path / 'gt.db'}")
    r.create_all()
    return r


def post(c: TestClient, action: str, **extra):
    return c.post(
        "/api/accounts/default/safety", json={"action": action, "reason_code": "R", **extra}
    )


def test_halted_survives_restart(repo):
    c = admin_client(repo)
    post(c, "halt")
    # "Restart": app mới, cùng database
    c2 = admin_client(repo)
    body = c2.get("/api/accounts/default/status").json()
    assert body["safety_state"] == "HALTED"
    assert c2.get("/api/status").json()["storage"] == "sqlite"
    assert [t["to_state"] for t in body["safety_history"]] == ["HALTED"]


def test_active_downgraded_to_paused_on_restart(repo):
    c = admin_client(repo)
    post(c, "resume")
    body = admin_client(repo).get("/api/accounts/default/status").json()
    assert body["safety_state"] == "PAUSED"
    last = body["safety_history"][-1]
    assert last["reason_code"] == "STARTUP_REQUIRES_REVIEW"
    assert last["actor"] == "system"


def test_mode_persisted_and_live_never_restored(repo):
    c = admin_client(repo)
    c.post("/api/accounts/default/mode", json={"mode": "SHADOW"})
    assert admin_client(repo).get("/api/accounts/default/status").json()["mode"] == "SHADOW"

    from gold_trading.modes.manager import ModeChange

    # giả lập lần chạy trước ở LIVE
    repo.append_mode("default", ModeChange("SHADOW", "LIVE", "a", "b"))
    assert admin_client(repo).get("/api/accounts/default/status").json()["mode"] == "PAPER"


def test_audit_records_accepted_and_rejected(repo):
    c = admin_client(repo)
    post(c, "halt")
    assert post(c, "resume").status_code == 409
    c.post("/api/accounts/default/mode", json={"mode": "LIVE"})
    entries = [
        e for e in c.get("/api/accounts/default/audit").json()
        if e["action"] in ("mode.set", "safety.resume", "safety.halt")
    ]
    assert [(e["action"], e["outcome"], e["actor"]) for e in entries] == [
        ("mode.set", "REJECTED", "admin"),
        ("safety.resume", "REJECTED", "admin"),
        ("safety.halt", "ACCEPTED", "admin"),
    ]


def test_persist_failure_keeps_state():
    def boom(_):
        raise RuntimeError("db down")

    s = SafetySupervisor("p0", persist=boom)
    with pytest.raises(RuntimeError):
        s.halt("KILL", **KW)
    assert s.state is SafetyState.PAUSED
    assert s.history == ()


def test_health_reports_storage(repo):
    assert admin_client(repo).get("/api/health").json() == {
        "status": "ok",
        "storage": "sqlite",
    }


def test_restore_mode_normalizes_string_live():
    """Lỗi tìm được khi soát: chuỗi "LIVE" từng lọt qua phép so sánh `is TradingMode.LIVE`."""
    from gold_trading.common.enums import TradingMode
    from gold_trading.storage.repository import InMemoryRepository, restore_mode

    assert restore_mode("LIVE", TradingMode.PAPER) == (TradingMode.PAPER, True)  # type: ignore[arg-type]
    r = InMemoryRepository()
    from gold_trading.modes.manager import ModeChange

    r.append_mode("default", ModeChange("PAPER", "LIVE", "a", "b"))  # type: ignore[arg-type]
    assert r.last_mode("default") is TradingMode.LIVE
