"""GĐ2 bước 3 — Event Orchestrator chạy trong backend (ORC-01, ORC-07; 2-C06)."""

from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.analysts.runner import TechnicalRunner
from gold_trading.contracts.candle import DataSource
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.ingestion.sample_feed import SampleFeed
from gold_trading.market.service import MarketDataService
from gold_trading.market.timeframes import Timeframe
from gold_trading.orchestrator import runner as R
from gold_trading.orchestrator.model import Event, EventType, JobState, OrchestratorStore
from gold_trading.storage.analyst_outputs import InMemoryAnalystOutputStore, SqlAnalystOutputStore
from gold_trading.storage.candles import InMemoryCandleStore, SqlCandleStore
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.orchestrator import SqlOrchestratorStore
from gold_trading.storage.repository import InMemoryRepository, SqlRepository

TF = Timeframe.M15
NOW = datetime(2026, 11, 16, 14, 0, 30, tzinfo=UTC)   # thứ Hai, thị trường mở


@pytest.fixture(params=["memory", "sqlite"])
def stack(request, tmp_path):
    if request.param == "memory":
        cs, ast, rs, orch = (InMemoryCandleStore(), InMemoryAnalystOutputStore(),
                             PointInTimeStore(), OrchestratorStore())
    else:
        repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'r.db'}")
        repo.create_all()
        e = repo.engine
        cs, ast, rs, orch = (SqlCandleStore(e), SqlAnalystOutputStore(e),
                             SqlExternalRecordStore(e), SqlOrchestratorStore(e))
    market = MarketDataService(cs, source=DataSource.SAMPLE)
    tech = TechnicalRunner(market, ast)
    calls = []
    orig = tech.run_feed

    def spy(feed, now):
        calls.append((feed, now))
        return orig(feed, now)
    tech.run_feed = spy
    runner = R.OrchestratorRunner(
        orch=orch, candle_store=cs, record_store=rs, analyst_store=ast,
        handlers={"TECHNICAL": R.technical_handler(tech, lambda: [""])})
    return cs, ast, orch, runner, calls


def latest(ast):
    return ast.latest("technical", symbol="XAUUSD", tf=TF, source=DataSource.SAMPLE)


def test_candle_close_runs_technical_once(stack):
    cs, ast, orch, runner, calls = stack
    feed = SampleFeed(cs, history_days=10)
    feed.tick(NOW)
    runner.tick(NOW)
    assert len(calls) == 1                    # nạp lịch sử 10 ngày → chỉ 1 lần (debounce)
    out = latest(ast)
    assert out is not None and out.output.as_of == TF.floor(NOW)
    runner.tick(NOW + timedelta(seconds=10))  # không có nến mới → không chạy
    assert len(calls) == 1
    later = NOW + TF.delta
    feed.tick(later)
    runner.tick(later)
    assert len(calls) == 2 and latest(ast).output.as_of == TF.floor(later)
    # job ghi đủ nguyên nhân + kết quả
    jobs = [j for j in orch.jobs_created_since(NOW - timedelta(days=30))
            if j.job_type == "TECHNICAL"]
    done = [orch.latest(j.job_key) for j in jobs]
    assert sum(a.state is JobState.SUCCEEDED for a in done) == 2
    assert {a.output_ref for a in done if a.state is JobState.SUCCEEDED} == {"technical:stored"}


def test_output_expired_triggers_recompute_then_stays_expired(stack):
    """ORC-07 / 2-C06: kết quả hết hạn mà không có nến mới (nguồn giá chết) → sự kiện hết hạn,
    tính lại (không ra kết quả mới vì đầu vào cũ) → không có kết quả còn hạn → MarketView (GĐ4)
    không được dùng nó."""
    cs, ast, orch, runner, calls = stack
    SampleFeed(cs, history_days=10).tick(NOW)
    runner.tick(NOW)
    out = latest(ast).output
    exp = out.expires_at
    runner.tick(exp - timedelta(seconds=1))
    assert not orch.events(until=exp, event_type=EventType.OUTPUT_EXPIRED)
    runner.tick(exp + timedelta(seconds=5))
    ev = orch.events(until=exp + timedelta(minutes=1), event_type=EventType.OUTPUT_EXPIRED)
    assert len(ev) == 1 and ev[0].subject == "technical:SAMPLE::XAUUSD:M15"
    assert ev[0].known_at == exp and ev[0].payload["output_id"] == out.output_id
    jobs = {j.job_type: orch.latest(j.job_key) for j in orch.jobs_created_since(
        NOW - timedelta(days=30)) if j.event_id == ev[0].event_id}
    assert jobs["INVALIDATE_MARKETVIEW"].state is JobState.NO_HANDLER    # MarketView: GĐ4
    assert jobs["TECHNICAL"].state is JobState.SUCCEEDED
    assert len(calls) == 2                       # đã tính lại một lần
    cur = latest(ast).output
    assert cur.expires_at <= exp + timedelta(seconds=5) or cur.source_status != "HEALTHY"


def test_expired_but_replaced_no_event(stack):
    """Kết quả cũ hết hạn nhưng đã có kết quả mới hơn trước lúc đó → không sự kiện hết hạn."""
    cs, ast, orch, runner, calls = stack
    feed = SampleFeed(cs, history_days=10)
    feed.tick(NOW)
    runner.tick(NOW)
    first = latest(ast).output
    t = NOW
    while t < first.expires_at + TF.delta:
        t += TF.delta
        feed.tick(t)
        runner.tick(t)
    evs = orch.events(until=t, event_type=EventType.OUTPUT_EXPIRED)
    assert all(e.payload["output_id"] != first.output_id for e in evs)


def test_inactive_feed_skipped():
    cs, ast, orch = InMemoryCandleStore(), InMemoryAnalystOutputStore(), OrchestratorStore()
    tech = TechnicalRunner(MarketDataService(cs, source=DataSource.SAMPLE), ast)
    runner = R.OrchestratorRunner(orch=orch, candle_store=cs, record_store=PointInTimeStore(),
                                  analyst_store=ast,
                                  handlers={"TECHNICAL": R.technical_handler(tech, lambda: [])})
    SampleFeed(cs, history_days=10).tick(NOW)
    runner.tick(NOW)
    assert latest(ast) is None
    st = [orch.latest(j.job_key) for j in orch.jobs_created_since(NOW - timedelta(days=30))
          if j.job_type == "TECHNICAL"]
    assert [a.output_ref for a in st if a.state is JobState.SUCCEEDED] == \
        ["skipped:feed_inactive"]


def test_feed_of():
    t = NOW
    c = Event(EventType.CANDLE_CLOSED, "MT5:pf_ab:XAUUSD:M15", "v", t, t)
    x = Event(EventType.OUTPUT_EXPIRED, "technical:MT5:pf_ab:XAUUSD:M15", "v", t, t)
    n = Event(EventType.NEWS_PUBLISHED, "fed:x", "v", t, t)
    assert (R.feed_of(c), R.feed_of(x), R.feed_of(n)) == ("pf_ab", "pf_ab", None)


def test_blocked_clock_does_nothing():
    cs = InMemoryCandleStore()
    orch = OrchestratorStore()
    runner = R.OrchestratorRunner(orch=orch, candle_store=cs, record_store=PointInTimeStore(),
                                  analyst_store=InMemoryAnalystOutputStore(), handlers={},
                                  blocked=lambda: "lệch đồng hồ")
    SampleFeed(cs, history_days=1).tick(NOW)
    assert runner.tick(NOW) is None and orch.events(until=NOW) == []


def test_enabled_env():
    assert R.enabled({}) and R.enabled({"GT_ORCHESTRATOR": "1"})
    assert not R.enabled({"GT_ORCHESTRATOR": "0"}) and not R.enabled({"GT_ORCHESTRATOR": "off"})


def test_app_uses_orchestrator_by_default_and_fallback(monkeypatch):
    from fastapi.testclient import TestClient

    from gold_trading.api.app import create_app

    monkeypatch.delenv("GT_ORCHESTRATOR", raising=False)
    app = create_app(InMemoryRepository(), data_source=DataSource.SAMPLE, run_sample_feed=False)
    assert app.state.orchestrator is not None
    with TestClient(app):
        assert app.state.orchestrator._thread is not None
        assert app.state.runner._thread is None             # vòng 15 giây cũ không chạy
    monkeypatch.setenv("GT_ORCHESTRATOR", "0")
    app = create_app(InMemoryRepository(), data_source=DataSource.SAMPLE, run_sample_feed=False)
    assert app.state.orchestrator is None
    with TestClient(app):
        assert app.state.runner._thread is not None
