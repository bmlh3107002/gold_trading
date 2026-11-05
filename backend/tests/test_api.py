from fastapi.testclient import TestClient

from gold_trading.api.app import create_app


def client() -> TestClient:
    return TestClient(create_app())


def test_status_defaults_safe():
    body = client().get("/api/status").json()
    assert body["mode"] == "PAPER"
    assert body["live_unlocked"] is False
    assert body["safety_state"] == "PAUSED"
    assert body["allows_new_orders"] is False


def test_kill_switch_and_resume_flow():
    c = client()
    c.post("/api/safety", json={"action": "halt", "reason_code": "KILL", "actor": "op"})
    r = c.post("/api/safety", json={"action": "resume", "reason_code": "X", "actor": "op"})
    assert r.status_code == 409
    r = c.post(
        "/api/safety",
        json={
            "action": "resume",
            "reason_code": "REVIEWED",
            "actor": "op",
            "operator_approved": True,
        },
    )
    assert r.json()["safety_state"] == "ACTIVE"


def test_live_mode_refused():
    r = client().post("/api/mode", json={"mode": "LIVE", "actor": "a", "approver": "b"})
    assert r.status_code == 409
