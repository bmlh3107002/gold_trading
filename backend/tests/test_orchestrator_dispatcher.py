"""GĐ2 bước 2 — bộ điều phối job (ORC-02, ORC-04, ORC-05; 2-C01..C05)."""

from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.orchestrator import dispatcher as D
from gold_trading.orchestrator.model import (
    Attempt,
    Event,
    EventType,
    JobState,
    OrchestratorStore,
)
from gold_trading.storage.orchestrator import SqlOrchestratorStore
from gold_trading.storage.repository import SqlRepository

T = datetime(2026, 11, 16, 14, tzinfo=UTC)
GOLD = "MT5:pf_a:XAUUSD:M15"


@pytest.fixture(params=["memory", "sqlite"])
def orch(request, tmp_path):
    if request.param == "memory":
        return OrchestratorStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'd.db'}")
    repo.create_all()
    return SqlOrchestratorStore(repo.engine)


def candle(i, subject=GOLD, known=None):
    open_t = T + timedelta(minutes=15 * i)
    return Event(EventType.CANDLE_CLOSED, subject, f"{open_t.isoformat()}:r0",
                 occurred_at=open_t + timedelta(minutes=15),
                 known_at=known or open_t + timedelta(minutes=15, seconds=5))


def actual(key="bls_values:CES0000000001:2026-11", rev=0, known=T):
    return Event(EventType.ACTUAL_RELEASED, key, f"r{rev}", occurred_at=known, known_at=known,
                 payload={"series": "CES0000000001"})


class Rec:
    """Bộ xử lý giả: ghi lại thứ tự sự kiện được xử lý; có thể lỗi theo kịch bản."""

    def __init__(self, fail=0, exc=RuntimeError):
        self.calls, self.fail, self.exc = [], fail, exc

    def __call__(self, e, now):
        self.calls.append((e.subject, e.event_version))
        if self.fail:
            self.fail -= 1
            raise self.exc("https://x/?api_key=SECRET")    # thông điệp không được ghi
        return f"out:{e.event_version}"


def put(orch, *evs, at=None):
    for e in evs:
        orch.record_event(e, recorded_at=at or e.known_at)


def latest_states(orch, d, job_type):
    out = {}
    for j in orch.jobs_created_since(T - timedelta(days=10)):
        if j.job_type == job_type:
            out[j.job_key] = orch.latest(j.job_key).state
    return out


# ------------------------------------------------------------------ định tuyến

def test_routes():
    r = D.routes_for
    assert [x.job_type for x in r(candle(0))] == ["TECHNICAL", "REGIME"]
    assert [x.job_type for x in r(candle(0, "MT5:pf_a:EURUSD:M15"))] == ["MACRO"]
    assert r(candle(0, "MT5:pf_a:XAUUSD:H1")) == ()
    assert [x.job_type for x in r(actual())] == ["FAST_LANE", "EVENT_CALENDAR"]
    assert all(not x.debounce for x in r(actual()))             # không bao giờ bỏ công bố
    news = Event(EventType.NEWS_PUBLISHED, "fed_rss:n:1", "r0", T, T)
    assert [x.job_type for x in r(news)] == ["FAST_LANE", "NEWS"]


def test_error_code_from_type_only():
    class FeedTimeoutError(Exception):
        pass
    assert D.error_code(FeedTimeoutError("https://x/?key=S")) == "FEED_TIMEOUT_ERROR"
    assert D.error_code(KeyError("x")) == "KEY_ERROR"
    assert D.error_code(OSError()) == "O_S_ERROR"


# ------------------------------------------------------------------ chạy, không nhân đôi

def test_run_once_no_duplicate_and_no_handler(orch):
    """2-C01: cùng sự kiện tới nhiều lần → một job, một output. Loại job chưa có bộ xử lý →
    NO_HANDLER (không giả kết quả)."""
    tech = Rec()
    d = D.Dispatcher(orch, {"TECHNICAL": D.Handler("technical-1", tech)})
    put(orch, candle(0))
    put(orch, candle(0))                                          # tới lần nữa
    now = T + timedelta(minutes=16)
    r = d.tick(now)
    assert r.created == 2 and r.ran == {"SUCCEEDED": 1, "NO_HANDLER": 1}
    assert tech.calls == [(GOLD, candle(0).event_version)]
    assert d.tick(now + timedelta(minutes=1)).created == 0       # quét lại: không job mới
    # khởi động lại (dispatcher mới, cùng store) → không chạy lại job đã xong
    d2 = D.Dispatcher(orch, {"TECHNICAL": D.Handler("technical-1", tech)})
    r2 = d2.tick(now + timedelta(minutes=2))
    assert r2.created == 0 and r2.ran == {} and len(tech.calls) == 1
    st = latest_states(orch, d, "TECHNICAL")
    assert list(st.values()) == [JobState.SUCCEEDED]
    job = orch.jobs_created_since(T - timedelta(days=1))[0]
    assert job.correlation_id == candle(0).event_id                 # ORC-06


def test_causal_order_regardless_of_arrival(orch):
    """2-C02: sự kiện ghi lộn xộn → xử lý theo (known_at, loại, chủ thể, phiên bản)."""
    rec = Rec()
    d = D.Dispatcher(orch, {"EVENT_CALENDAR": D.Handler("ev-1", rec)})
    evs = [actual(f"bls_values:S{i}:2026-11", known=T + timedelta(seconds=10 * (5 - i)))
           for i in range(5)]
    put(orch, *evs)
    d.tick(T + timedelta(minutes=5))
    assert [c[0] for c in rec.calls] == [f"bls_values:S{i}:2026-11" for i in (4, 3, 2, 1, 0)]


def test_debounce_candles_but_never_releases(orch):
    """2-C03: nạp bù 20 nến → Technical chỉ chạy nến mới nhất; 20 công bố → đủ 20 lần."""
    tech, ev = Rec(), Rec()
    d = D.Dispatcher(orch, {"TECHNICAL": D.Handler("t-1", tech),
                            "EVENT_CALENDAR": D.Handler("e-1", ev)})
    k = T + timedelta(hours=6)
    put(orch, *[candle(i, known=k) for i in range(20)])
    put(orch, *[actual(f"bea_nipa:X{i}:2026-10", known=k) for i in range(20)])
    r = d.tick(k + timedelta(seconds=1))
    assert tech.calls == [(GOLD, candle(19).event_version)]
    assert len(ev.calls) == 20 and r.superseded == 19 + 19         # TECHNICAL + REGIME
    # nến cũ trong cùng lô không sinh job (debounce khi tạo) → chỉ 1 job TECHNICAL
    st = latest_states(orch, d, "TECHNICAL")
    assert list(st.values()) == [JobState.SUCCEEDED]


def test_debounce_per_subject(orch):
    tech = Rec()
    d = D.Dispatcher(orch, {"TECHNICAL": D.Handler("t-1", tech)})
    k = T + timedelta(hours=2)
    put(orch, candle(0, known=k), candle(1, known=k),
        candle(0, "MT5:pf_b:XAUUSD:M15", known=k))
    d.tick(k)
    assert sorted(tech.calls) == sorted([(GOLD, candle(1).event_version),
                                         ("MT5:pf_b:XAUUSD:M15", candle(0).event_version)])


# ------------------------------------------------------------------ lỗi, retry, dead-letter

def test_retry_backoff_then_success(orch):
    rec = Rec(fail=2)
    h = D.Handler("e-1", rec, max_attempts=3, retry_base=timedelta(seconds=10))
    d = D.Dispatcher(orch, {"EVENT_CALENDAR": h})
    put(orch, actual())
    d.tick(T)                                         # lần 1 lỗi
    d.tick(T + timedelta(seconds=9))                  # chưa tới backoff 10 s
    assert len(rec.calls) == 1
    d.tick(T + timedelta(seconds=10))                 # lần 2 lỗi → backoff 20 s
    d.tick(T + timedelta(seconds=29))
    assert len(rec.calls) == 2
    d.tick(T + timedelta(seconds=30))                 # lần 3 thành công
    key = next(j.job_key for j in orch.jobs_created_since(T - timedelta(days=1))
               if j.job_type == "EVENT_CALENDAR")
    rows = orch.attempts(key)
    assert [(a.state.value, a.attempt) for a in rows] == [
        ("PENDING", 0), ("RUNNING", 1), ("FAILED", 1), ("RUNNING", 2), ("FAILED", 2),
        ("RUNNING", 3), ("SUCCEEDED", 3)]
    assert {a.error_code for a in rows if a.error_code} == {"RUNTIME_ERROR"}   # không thông điệp


def test_dead_letter_after_max_attempts_and_fatal(orch):
    rec = Rec(fail=99)
    d = D.Dispatcher(orch, {"EVENT_CALENDAR": D.Handler("e-1", rec, max_attempts=2,
                                                        retry_base=timedelta(seconds=1))})
    put(orch, actual())
    for s in range(0, 30, 2):
        d.tick(T + timedelta(seconds=s))
    assert len(rec.calls) == 2                        # không retry vô hạn (2-C04)
    st = latest_states(orch, d, "EVENT_CALENDAR")
    assert list(st.values()) == [JobState.DEAD]
    # lỗi "không thử lại" → DEAD ngay lần đầu
    fat = Rec(fail=1, exc=ValueError)
    o2 = OrchestratorStore()
    d2 = D.Dispatcher(o2, {"EVENT_CALENDAR": D.Handler("e-1", fat, fatal=(ValueError,))})
    put(o2, actual())
    d2.tick(T)
    j = o2.jobs_created_since(T - timedelta(days=1))
    assert [o2.latest(x.job_key).state for x in j if x.job_type == "EVENT_CALENDAR"] == [
        JobState.DEAD]


def test_deadline_exceeded_output_not_used(orch):
    clock = iter([0.0, 31.0, 100.0, 100.5])
    rec = Rec()
    d = D.Dispatcher(orch, {"EVENT_CALENDAR": D.Handler("e-1", rec, max_attempts=2,
                                                        retry_base=timedelta(seconds=1))},
                     clock=lambda: next(clock))
    put(orch, actual())
    d.tick(T)                                         # chạy 31 s > 30 s → FAILED
    d.tick(T + timedelta(seconds=2))                  # lần 2 nhanh → SUCCEEDED
    key = next(j.job_key for j in orch.jobs_created_since(T - timedelta(days=1))
               if j.job_type == "EVENT_CALENDAR")
    rows = orch.attempts(key)
    assert [(a.state.value, a.error_code) for a in rows][2] == ("FAILED", "DEADLINE_EXCEEDED")
    assert rows[-1].state is JobState.SUCCEEDED and rows[-1].attempt == 2


def test_restart_mid_run_retries_safely(orch):
    """2-C05: backend tắt khi job đang RUNNING → khởi động lại: quá deadline → thất bại có mã,
    rồi thử lại; không chạy song song lần cũ chưa quá hạn."""
    rec = Rec()
    h = D.Handler("e-1", rec, max_attempts=3, retry_base=timedelta(seconds=5))
    d = D.Dispatcher(orch, {"EVENT_CALENDAR": h})
    put(orch, actual())
    d.create_jobs(T)
    key = next(j.job_key for j in orch.jobs_created_since(T - timedelta(days=1))
               if j.job_type == "EVENT_CALENDAR")
    orch.append_attempt(Attempt(key, JobState.RUNNING, 1, T, deadline_at=T + timedelta(
        seconds=30)))                                 # "đang chạy" rồi backend chết
    d2 = D.Dispatcher(orch, {"EVENT_CALENDAR": h})
    d2.tick(T + timedelta(seconds=20))                # chưa quá deadline → không chạy
    assert rec.calls == []
    d3 = D.Dispatcher(orch, {"EVENT_CALENDAR": h})
    d3.tick(T + timedelta(seconds=31))                # quá deadline → FAILED
    d3.tick(T + timedelta(seconds=36))                # backoff 5 s → chạy lại
    assert len(rec.calls) == 1 and orch.latest(key).state is JobState.SUCCEEDED
    assert [a.state.value for a in orch.attempts(key)] == [
        "PENDING", "RUNNING", "FAILED", "RUNNING", "SUCCEEDED"]
    assert orch.attempts(key)[2].error_code == "DEADLINE_EXCEEDED"


def test_handler_version_change(orch):
    """Đổi phiên bản bộ xử lý: job cũ không chạy bằng code mới; sự kiện quét lại → job mới."""
    rec = Rec()
    put(orch, actual())
    d = D.Dispatcher(orch, {})
    d.tick(T)                                         # chưa có bộ xử lý → NO_HANDLER
    d2 = D.Dispatcher(orch, {"EVENT_CALENDAR": D.Handler("e-2", rec)})
    r = d2.tick(T + timedelta(minutes=1))
    assert r.created == 1 and rec.calls == [("bls_values:CES0000000001:2026-11", "r0")]


def test_replay_same_outcome(orch):
    """Gate GĐ2 (nền): cùng nhật ký sự kiện → cùng tập job + cùng trạng thái cuối, dù chạy một
    nhịp hay nhiều nhịp."""
    def build(store, steps):
        tech, ev = Rec(), Rec()
        d = D.Dispatcher(store, {"TECHNICAL": D.Handler("t-1", tech),
                                 "EVENT_CALENDAR": D.Handler("e-1", ev)})
        evs = [candle(i) for i in range(12)] + [actual(f"bea_nipa:X{i}:2026-10",
                                                       known=T + timedelta(minutes=20 * i))
                                                for i in range(6)]
        put(store, *evs)
        end = T + timedelta(hours=4)
        for t in steps(end):
            d.tick(t)
        return ({j.job_key: store.latest(j.job_key).state.value
                 for j in store.jobs_created_since(T - timedelta(days=1))}, tech.calls, ev.calls)
    one = build(OrchestratorStore(), lambda end: [end])
    many = build(orch, lambda end: [T + timedelta(minutes=m) for m in range(0, 241, 7)] + [end])
    # job không debounce (công bố) giống hệt; job debounce: nến mới nhất có ở cả hai
    def nodeb(keys):
        return {k for k in keys if "CANDLE_CLOSED" not in k}
    assert nodeb(one[0]) == nodeb(many[0])
    last = f"{candle(11).event_version}|TECHNICAL@t-1"
    assert any(k.endswith(last) for k in one[0]) and any(k.endswith(last) for k in many[0])
    assert one[1][-1] == many[1][-1] == (GOLD, candle(11).event_version)
    assert all(v in ("SUCCEEDED", "SUPERSEDED", "NO_HANDLER") for v in many[0].values())
    assert sorted(one[2]) == sorted(many[2])           # mọi công bố đều được xử lý ở cả hai


def test_memory_bounded_after_jobs_finish(orch):
    """Sự kiện của job đã kết thúc không còn giữ trong RAM."""
    d = D.Dispatcher(orch, {"TECHNICAL": D.Handler("t-1", Rec()),
                            "EVENT_CALENDAR": D.Handler("e-1", Rec())})
    put(orch, *[candle(i) for i in range(30)], *[actual(f"bea_nipa:X{i}") for i in range(30)])
    d.tick(T + timedelta(hours=9))
    assert d._events_by_id == {} and d._open == {}


def test_bulk_create_scales(orch):
    """Nạp bù lớn: 3.000 nến / 3 nguồn → chỉ 1 job / (loại, nguồn); 300 công bố → 300 job."""
    d = D.Dispatcher(orch, {})
    k = T + timedelta(days=1)
    subs = ["MT5:a:XAUUSD:M15", "MT5:b:XAUUSD:M15", "MT5:a:EURUSD:M15"]
    put(orch, *[candle(i, s, known=k) for s in subs for i in range(1000)],
        *[actual(f"bea_nipa:X{i}", known=k) for i in range(300)])
    r = d.tick(k)
    assert r.created == 2 + 2 + 1 + 300 * 2
    assert r.superseded == 999 * 5
