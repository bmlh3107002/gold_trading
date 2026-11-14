"""GĐ2 bước 4d — vòng làn nhanh 2 giây + ngân sách độ trễ 10 giây (FAST-02, 2-C09).

Case: vừa bật chưa chạy xong lần nào → chặn; chạy đều → không chặn; vòng dừng > 10 giây → chặn
``FAST_LANE_STALLED`` tới khi chạy lại; sự kiện làn nhanh chờ > 10 giây (bộ xử lý lỗi / thử lại) →
``FAST_LANE_BACKLOG`` tới khi xong; vòng chạy xong nhưng quá ngân sách → không báo nhịp; độ trễ ghi
lệnh cấm > 10 giây → cảnh báo; vòng spread ghi / gỡ lệnh cấm theo nguồn; Safety qua API.
"""

from datetime import UTC, datetime, timedelta

from gold_trading.market.quotes import QuoteSecond
from gold_trading.orchestrator import runner as R
from gold_trading.orchestrator.dispatcher import Handler
from gold_trading.orchestrator.model import Event, EventType, OrchestratorStore
from gold_trading.risk import fast_lane as FL
from gold_trading.risk.blocks import BlockKind, BlockStore
from gold_trading.risk.fast_lane_loop import FastLaneMonitor, SpreadLoop
from gold_trading.storage.quotes import InMemoryQuoteStore

S = timedelta(seconds=1)
M = timedelta(minutes=1)
T0 = datetime(2026, 12, 10, 13, 0, tzinfo=UTC)


def codes(mon, at):
    return [b.reason_code for b in mon.blocks(at)]


def test_monitor_starting_ok_stalled():
    m = FastLaneMonitor()
    assert m.blocks(T0) == []                      # chưa bật làn nào
    m.start("spread", T0)
    assert codes(m, T0) == ["FAST_LANE_STARTING"]  # bật mà chưa chạy xong lần nào → chặn
    m.ok("spread", T0 + 2 * S)
    assert m.blocks(T0 + 12 * S) == []
    b = m.blocks(T0 + 12 * S + timedelta(milliseconds=1))
    assert [x.reason_code for x in b] == ["FAST_LANE_STALLED"]
    assert b[0].kind is BlockKind.LATENCY and b[0].start_at == T0 + 12 * S and b[0].end_at is None
    m.ok("spread", T0 + 20 * S)
    assert m.blocks(T0 + 21 * S) == []


def test_monitor_backlog_and_latency_breach():
    m = FastLaneMonitor()
    m.start("events", T0)
    m.ok("events", T0)
    m.backlog("events", T0 - 5 * S)
    assert m.blocks(T0 + 4 * S) == []
    assert codes(m, T0 + 6 * S) == ["FAST_LANE_BACKLOG"]
    m.backlog("events", None)
    m.ok("events", T0 + 6 * S)
    assert m.blocks(T0 + 7 * S) == []
    m.latency(9_999)
    m.latency(10_001)
    assert m.budget_breaches == 1 and m.last_latency_ms == 10_001


def q(t, sp, feed="pf_a"):
    return QuoteSecond(feed, t, 2400.0, 2400.0, 2400.0, 2400.0, sp, sp, 3, (), t + S, t + S)


def test_spread_loop_blocks_and_lifts_per_feed():
    qs, bs, mon = InMemoryQuoteStore(), BlockStore(), FastLaneMonitor()
    qs.append([q(T0 - 60 * M + k * S, 20) for k in range(3600)]
              + [q(T0 - 60 * M + k * S, 20, "pf_b") for k in range(3600)]
              + [q(T0 + k * S, 80) for k in range(6)]
              + [q(T0 + k * S, 20, "pf_b") for k in range(6)])
    loop = SpreadLoop(quote_store=qs, block_store=bs, feeds=lambda: ["pf_a", "pf_b", ""],
                      monitor=mon)
    st = loop.tick(T0 + 7 * S)
    assert st == {"pf_a": "WIDE", "pf_b": "NORMAL"}
    assert [b.reason_code for b in bs.active(T0 + 7 * S, "pf_a")] == ["SPREAD_WIDE"]
    assert bs.active(T0 + 7 * S, "pf_b") == []
    assert mon.blocks(T0 + 8 * S) == []
    qs.append([q(T0 + 6 * S + k * S, 20) for k in range(125)])
    loop.tick(T0 + 131 * S)
    assert bs.active(T0 + 131 * S, "pf_a") == []


def test_spread_loop_over_budget_does_not_beat():
    ticks = iter([0.0, 11.0])
    mon = FastLaneMonitor()
    loop = SpreadLoop(quote_store=InMemoryQuoteStore(), block_store=BlockStore(),
                      feeds=lambda: ["pf_a"], monitor=mon, clock=lambda: next(ticks))
    loop.tick(T0)
    assert codes(mon, T0 + S) == ["FAST_LANE_STARTING"]


def test_orchestrator_backlog_when_fast_lane_handler_keeps_failing():
    """2-C09: bộ xử lý làn nhanh lỗi / thử lại → sự kiện chờ quá 10 giây → Safety chặn tới khi
    xong; lỗi áp luật vẫn ghi lệnh cấm mặc định ``FAST_LANE_ERROR``."""
    orch, bs, mon = OrchestratorStore(), BlockStore(), FastLaneMonitor()
    calls = {"n": 0}

    class Flaky:
        def as_of(self, *a, **k):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise RuntimeError("db down")
            return []

    h = FL.fast_lane_handler(bs, Flaky(), None, clock=lambda: T0, monitor=mon)
    fast = Handler(h.version, h.run, deadline=h.deadline, max_attempts=5,
                   retry_base=timedelta(seconds=8))
    r = R.OrchestratorRunner(orch=orch, candle_store=None, record_store=None, analyst_store=None,
                             handlers={"FAST_LANE": fast}, monitor=mon)
    e = Event(EventType.NEWS_PUBLISHED, "fed_rss_monetary:n:x", "r0", occurred_at=T0,
              known_at=T0, payload={"source": "fed_rss_monetary", "logical_key": "n:x"})
    orch.record_event(e, recorded_at=T0)
    r.tick(T0 + S)                                           # lỗi lần 1
    assert [b.reason_code for b in bs.active(T0 + S)] == ["FAST_LANE_ERROR"]
    assert mon.blocks(T0 + 5 * S) == []
    r.tick(T0 + 11 * S)                                      # chờ backoff, chưa xong
    assert codes(mon, T0 + 11 * S) == ["FAST_LANE_BACKLOG"]
    r.tick(T0 + 20 * S)                                      # lỗi lần 2
    r.tick(T0 + 40 * S)                                      # lần 3: xong
    assert mon.blocks(T0 + 40 * S) == []
    # lệnh cấm mặc định lúc lỗi vẫn còn hạn (15 phút) cùng lệnh cấm đúng luật
    assert sorted(b.reason_code for b in bs.active(T0 + 41 * S)) == [
        "FAST_LANE_ERROR", "FED_UNSCHEDULED_POLICY"]


def test_orchestrator_blocked_clock_stops_heartbeat():
    mon = FastLaneMonitor()
    r = R.OrchestratorRunner(orch=OrchestratorStore(), candle_store=None, record_store=None,
                             analyst_store=None, handlers={}, monitor=mon,
                             blocked=lambda: "đồng hồ lệch")
    mon.start("events", T0)
    r.tick(T0)
    assert codes(mon, T0 + S) == ["FAST_LANE_STARTING"]


def test_safety_api_latency_block():
    from tests.test_risk_blocks import _active_client

    c = _active_client()
    mon = FastLaneMonitor()
    from gold_trading.common.time import utcnow
    now = utcnow()
    mon.start("events", now - 30 * S)
    mon.ok("events", now - 20 * S)
    c.app.state.fast_lane["monitor"] = mon
    body = c.get("/api/accounts/default/status").json()
    assert body["allows_new_orders"] is False and body["safety_state"] == "ACTIVE"
    assert [b["reason_code"] for b in body["entry_blocks"]] == ["FAST_LANE_STALLED"]
    (w,) = body["entry_block_windows"]
    assert w["end_at"] is None
    mon.ok("events", utcnow())
    assert c.get("/api/accounts/default/status").json()["allows_new_orders"] is True
