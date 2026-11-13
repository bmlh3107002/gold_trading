"""GĐ2 bước 1b — nhật ký sự kiện + job (ORC-03, ORC-06, ORC-08; 2-C01, 2-C02, 2-C05)."""

import random
from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.orchestrator.model import (
    TERMINAL,
    Attempt,
    Event,
    EventType,
    Job,
    JobState,
    OrchestratorStore,
    event_id_for,
    job_key_for,
)
from gold_trading.storage.orchestrator import SqlOrchestratorStore
from gold_trading.storage.repository import SqlRepository

T = datetime(2026, 11, 13, 12, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return OrchestratorStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'o.db'}")
    repo.create_all()
    return SqlOrchestratorStore(repo.engine)


def ev(subject="mt5:pf_x:XAUUSD:M15", version="2026-11-13T11:45:00+00:00:r0", known=T,
       typ=EventType.CANDLE_CLOSED, **kw):
    return Event(typ, subject, version, occurred_at=known - timedelta(minutes=1), known_at=known,
                 **kw)


def test_event_identity_and_correlation():
    e = ev()
    assert e.event_id == event_id_for("CANDLE_CLOSED", e.subject, e.event_version)
    assert len(e.event_id) == 40 and e.correlation_id == e.event_id
    assert ev(correlation_id="abc").correlation_id == "abc"
    assert ev().event_id == e.event_id and ev(version="v2").event_id != e.event_id


@pytest.mark.parametrize("kw", [
    {"subject": ""}, {"subject": "x" * 257}, {"subject": "a\x00b"}, {"version": ""},
    {"version": "v" * 65}, {"payload": {"x": "y" * 20000}}, {"typ": "LẠ"},
])
def test_event_validation(kw):
    with pytest.raises(ValueError):
        ev(**kw)


def test_event_naive_time_rejected():
    with pytest.raises(ValueError):
        Event(EventType.NEWS_PUBLISHED, "s", "v", datetime(2026, 1, 1), T)


def test_record_once(store):
    e = ev(payload={"ref": "candles:1"})
    assert store.record_event(e, recorded_at=T) is True
    assert store.record_event(e, recorded_at=T + timedelta(hours=1)) is False
    # cùng khóa mà payload khác → vẫn là cùng sự kiện, giữ bản đầu
    assert store.record_event(ev(payload={"ref": "khác"}), recorded_at=T) is False
    got = store.events(until=T)
    assert len(got) == 1 and got[0].payload == {"ref": "candles:1"}
    assert got[0].correlation_id == e.event_id


def test_order_stable_regardless_of_write_order(store):
    """2-C02: thứ tự nhân quả = (known_at, loại, chủ thể, phiên bản), không theo thứ tự ghi."""
    evs = [ev(subject=f"s{i % 3}", version=f"v{i}", known=T + timedelta(seconds=i // 4),
              typ=list(EventType)[i % 6]) for i in range(40)]
    ref = sorted(evs, key=Event.order_key)
    shuffled = evs[:]
    random.Random(5).shuffle(shuffled)
    for e in shuffled:
        store.record_event(e, recorded_at=T)
    assert [e.event_id for e in store.events(until=T + timedelta(hours=1))] == \
        [e.event_id for e in ref]


def test_window_filters_and_future_hidden(store):
    for i in range(5):
        store.record_event(ev(version=f"v{i}", known=T + timedelta(minutes=i)), recorded_at=T)
    store.record_event(ev(version="tuong-lai", known=T + timedelta(days=1)), recorded_at=T)
    got = store.events(since=T + timedelta(minutes=1), until=T + timedelta(minutes=3))
    assert [e.event_version for e in got] == ["v2", "v3"]
    assert store.max_known_at(EventType.CANDLE_CLOSED, T + timedelta(minutes=10)) == \
        T + timedelta(minutes=4)
    assert store.max_known_at(EventType.NEWS_PUBLISHED, T + timedelta(days=2)) is None
    assert store.events(until=T, event_type=EventType.NEWS_PUBLISHED) == []
    with pytest.raises(ValueError):
        store.events(until=datetime(2026, 1, 1))


def test_round_trip_times_utc(store):
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    e = Event(EventType.ACTUAL_RELEASED, "bls_values:CES0000000001:2026-11", "r0",
              datetime(2026, 12, 4, 8, 30, tzinfo=ny), datetime(2026, 12, 4, 8, 31, tzinfo=ny))
    store.record_event(e, recorded_at=T)
    g = store.events(until=datetime(2026, 12, 5, tzinfo=UTC))[0]
    assert g.known_at == datetime(2026, 12, 4, 13, 31, tzinfo=UTC) and g.event_id == e.event_id


# ------------------------------------------------------------------ job

def job(e=None, jt="TECHNICAL", ver="technical-1"):
    e = e or ev()
    return Job(job_key_for(e, jt, ver), e.event_id, jt, ver, e.correlation_id, T)


def test_job_key_format():
    e = ev()
    assert job_key_for(e, "TECHNICAL", "t-1") == \
        f"CANDLE_CLOSED|{e.subject}|{e.event_version}|TECHNICAL@t-1"


def test_job_created_once_and_attempt_log(store):
    j = job()
    assert store.create_job(j) is True and store.create_job(j) is False
    assert store.job(j.job_key) == j and store.job("không có") is None
    assert store.latest(j.job_key) is None
    store.append_attempt(Attempt(j.job_key, JobState.PENDING, 0, T))
    store.append_attempt(Attempt(j.job_key, JobState.RUNNING, 1, T + timedelta(seconds=1),
                                 deadline_at=T + timedelta(seconds=31)))
    store.append_attempt(Attempt(j.job_key, JobState.FAILED, 1, T + timedelta(seconds=2),
                                 error_code="TIMEOUT"))
    store.append_attempt(Attempt(j.job_key, JobState.SUCCEEDED, 2, T + timedelta(seconds=9),
                                 output_ref="analyst_outputs:abc"))
    rows = store.attempts(j.job_key)
    assert [a.state for a in rows] == ["PENDING", "RUNNING", "FAILED", "SUCCEEDED"]
    assert store.latest(j.job_key).state in TERMINAL
    assert rows[1].deadline_at == T + timedelta(seconds=31)


def test_same_time_attempts_keep_write_order(store):
    j = job()
    store.create_job(j)
    store.append_attempt(Attempt(j.job_key, JobState.RUNNING, 1, T))
    store.append_attempt(Attempt(j.job_key, JobState.SUCCEEDED, 1, T))
    assert store.latest(j.job_key).state is JobState.SUCCEEDED


def test_attempt_for_unknown_job_rejected(store):
    with pytest.raises(ValueError):
        store.append_attempt(Attempt("không-có", JobState.PENDING, 0, T))


@pytest.mark.parametrize("kw", [
    {"state": JobState.FAILED},                                   # thiếu mã lỗi
    {"state": JobState.DEAD},
    {"state": JobState.FAILED, "error_code": "https://x/?key=SECRET"},
    {"state": JobState.FAILED, "error_code": "timeout"},
    {"state": "LẠ"},
    {"attempt": -1},
    {"output_ref": "x" * 300},
])
def test_attempt_validation(kw):
    base = {"job_key": "k", "state": JobState.PENDING, "attempt": 0, "at": T}
    with pytest.raises(ValueError):
        Attempt(**(base | kw))


@pytest.mark.parametrize("jt", ["technical", "", "X" * 49, "TECH-1"])
def test_job_type_validation(jt):
    with pytest.raises(ValueError):
        job(jt=jt)


def test_append_only_triggers_exist_in_migration():
    from pathlib import Path
    src = (Path(__file__).parents[1] / "migrations" / "versions" / "0014_orchestrator.py"
           ).read_text(encoding="utf-8")
    for t in ("orchestrator_events", "orchestrator_jobs", "orchestrator_job_attempts"):
        assert t in src
    assert "forbid_mutation" in src
