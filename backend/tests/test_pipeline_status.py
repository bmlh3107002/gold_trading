"""GĐ2 bước 5 — DSH-08: trạng thái pipeline / job / dead-letter.

Case: đọc job + lần thử mới nhất bằng một truy vấn (bộ nhớ = SQLite), đếm theo loại × trạng thái
24 giờ, dead-letter 7 ngày, job kẹt > 2 phút, nhịp làn nhanh; API cần đăng nhập, không lộ thông
điệp lỗi; orchestrator tắt → báo tắt, không lỗi.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from gold_trading.orchestrator import overview as OV
from gold_trading.orchestrator.dispatcher import Dispatcher, Handler
from gold_trading.orchestrator.model import Event, EventType, JobState, OrchestratorStore
from gold_trading.risk.fast_lane_loop import FastLaneMonitor
from gold_trading.storage.orchestrator import SqlOrchestratorStore
from gold_trading.storage.repository import InMemoryRepository, SqlRepository
from tests.auth_helpers import admin_client, make_app, user_client

T0 = datetime(2026, 12, 10, 13, 0, tzinfo=UTC)
S = timedelta(seconds=1)


@pytest.fixture(params=["memory", "sqlite"])
def orch(request, tmp_path):
    if request.param == "memory":
        return OrchestratorStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'p.db'}")
    repo.create_all()
    return SqlOrchestratorStore(repo.engine)


class Boom(Exception):
    pass


def fill(orch):
    """3 sự kiện: một job thành công, một job lỗi tới dead-letter, một job chưa có bộ xử lý,
    một job đang mở (chưa tới lượt thử lại)."""
    evs = [Event(EventType.ACTUAL_RELEASED, f"bls_values:CPI{i}", "r0", occurred_at=T0,
                 known_at=T0 + i * S, payload={"source": "bls_values"}) for i in range(3)]
    orch.record_events(evs, recorded_at=T0 + 3 * S)
    calls = {"n": 0}

    def run(e, now):
        calls["n"] += 1
        if e.subject.endswith("CPI1"):
            raise Boom("https://x/?api_key=SECRET")    # thông điệp không bao giờ được ghi
        if e.subject.endswith("CPI2") and now < T0 + 50 * S:
            raise RuntimeError("tạm thời")
        return "block:abc"

    h = {"FAST_LANE": Handler("fl-1", run, max_attempts=2, retry_base=timedelta(seconds=30),
                              fatal=(Boom,))}
    d = Dispatcher(orch, h)
    d.tick(T0 + 4 * S, since=T0 - S)
    return d


def test_job_rows_and_overview(orch):
    fill(orch)
    rows = orch.job_rows(T0 - timedelta(hours=1))
    by = {(r.subject, r.job.job_type): r for r in rows}
    assert by[("bls_values:CPI0", "FAST_LANE")].last.state is JobState.SUCCEEDED
    assert by[("bls_values:CPI0", "FAST_LANE")].last.output_ref == "block:abc"
    dead = by[("bls_values:CPI1", "FAST_LANE")]
    assert dead.last.state is JobState.DEAD and dead.last.error_code == "BOOM"
    assert dead.attempts == 1 and dead.event_type == "ACTUAL_RELEASED"
    assert by[("bls_values:CPI2", "FAST_LANE")].last.state is JobState.FAILED
    assert by[("bls_values:CPI0", "EVENT_CALENDAR")].last.state is JobState.NO_HANDLER
    assert [r.job.created_at for r in rows] == sorted((r.job.created_at for r in rows),
                                                       reverse=True)
    assert orch.job_rows(T0 + timedelta(hours=1)) == []
    assert [r.subject for r in orch.job_rows(T0 - S, states=[JobState.DEAD])] == [
        "bls_values:CPI1"]
    assert len(orch.job_rows(T0 - S, limit=2)) == 2

    ov = OV.build(orch, T0 + 10 * S)
    assert ov.counts[("FAST_LANE", "SUCCEEDED")] == 1
    assert ov.counts[("FAST_LANE", "DEAD")] == 1
    assert ov.counts[("EVENT_CALENDAR", "NO_HANDLER")] == 3
    assert [r.subject for r in ov.dead] == ["bls_values:CPI1"]
    assert [r.subject for r in ov.open] == ["bls_values:CPI2"] and ov.stuck == 0
    assert OV.build(orch, T0 + 3 * timedelta(minutes=1)).stuck == 1
    # ngoài cửa sổ 24 giờ: không đếm; dead-letter vẫn hiện trong 7 ngày
    later = OV.build(orch, T0 + timedelta(days=2))
    assert later.counts == {} and [r.subject for r in later.dead] == ["bls_values:CPI1"]
    assert OV.build(orch, T0 + timedelta(days=8)).dead == []


def test_monitor_snapshot():
    m = FastLaneMonitor()
    m.start("spread", T0)
    m.start("events", T0)
    m.ok("events", T0 + S)
    m.backlog("events", T0 - 20 * S)
    snap = {x["lane"]: x for x in m.snapshot(T0 + 2 * S)}
    assert snap["spread"]["ok"] is False and snap["spread"]["last_ok_at"] is None
    assert snap["events"]["ok"] is False and snap["events"]["backlog_since"] == T0 - 20 * S
    m.backlog("events", None)
    m.ok("spread", T0 + 2 * S)
    assert all(x["ok"] for x in m.snapshot(T0 + 3 * S))


def test_api_pipeline_user_and_admin():
    c = user_client()
    orch = OrchestratorStore()
    fill(orch)

    class Runner:          # như OrchestratorRunner: chỉ cần thuộc tính .orch
        pass

    c.app.state.orchestrator = Runner()
    c.app.state.orchestrator.orch = orch
    mon = FastLaneMonitor()
    mon.start("events", T0)
    c.app.state.fast_lane["monitor"] = mon
    r = c.get("/api/pipeline")
    assert r.status_code == 200
    b = r.json()
    assert b["orchestrator_enabled"] is True and b["window_hours"] == 24
    assert b["dead_window_days"] == 7
    assert [x["subject"] for x in b["dead_letter"]] == ["bls_values:CPI1"]
    assert b["dead_letter"][0]["error_code"] == "BOOM"
    assert b["lanes"][0]["lane"] == "events" and b["lanes"][0]["ok"] is False
    assert "SECRET" not in r.text and "https://x" not in r.text
    assert admin_client().get("/api/pipeline").status_code == 200


def test_api_pipeline_orchestrator_off_and_login_required():
    c = user_client()
    c.app.state.orchestrator = None
    b = c.get("/api/pipeline").json()
    assert b["orchestrator_enabled"] is False and b["recent"] == [] and b["counts"] == []
    app, _ = make_app(InMemoryRepository())
    assert TestClient(app).get("/api/pipeline").status_code == 401
