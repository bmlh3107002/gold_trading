"""GĐ3 bước 2 — analyst Lịch sự kiện (EVT-01..04; 3-C01..C09). Thiết kế: docs/thiet-ke/28.

Lịch thật Fed / BEA / BLS / DOL (fixtures, nạp qua bộ nạp thật — như test làn nhanh).
"""

from datetime import timedelta

import pytest

from gold_trading.analysts import event as EA
from gold_trading.analysts.framework import GLOBAL_SCOPE
from gold_trading.common.enums import SourceStatus
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.ingestion.source_status import SourceCheckLog
from gold_trading.ingestion.sources import bea as B
from gold_trading.ingestion.sources import bls as L
from gold_trading.ingestion.sources import dol as D
from gold_trading.ingestion.sources import fed_fomc as F
from gold_trading.market.hours import REFERENCE
from gold_trading.orchestrator.dispatcher import Dispatcher, routes_for
from gold_trading.orchestrator.model import JobState, OrchestratorStore
from gold_trading.orchestrator.scanner import expired_event, record_event
from gold_trading.risk import fast_lane as FL
from gold_trading.storage.analyst_outputs import (
    ExpiredOutput,
    InMemoryAnalystOutputStore,
    SqlAnalystOutputStore,
)
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.repository import SqlRepository

from .test_economic_calendar import BEA, FED, NOW
from .test_fast_lane import CPI_AT, FOMC_AT, dol_value, utc, value

M = timedelta(minutes=1)
S = timedelta(seconds=1)


def load(st, log=None):
    log = log if log is not None else SourceCheckLog()
    F.run_once(store=st, log=log, get=lambda p: FED[p], now=NOW)
    B.run_schedule_once(store=st, log=log, get=lambda u, p=None: BEA[u], now=NOW)
    D.run_schedule_once(store=st, log=log, now=NOW)
    L.run_schedule_once(store=st, log=log, now=NOW)
    return st, log


@pytest.fixture(params=["memory", "sqlite"])
def st(request, tmp_path):
    if request.param == "memory":
        return load(PointInTimeStore())[0]
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'e.db'}")
    repo.create_all()
    return load(SqlExternalRecordStore(repo.engine))[0]


def run(st, at, **kw):
    return EA.compute(st, at, market_calendar=REFERENCE, **kw)


def calendar_record(st, key_part, source=None):
    rows = [r for r in st.as_of(NOW, kind="calendar") if key_part in r.logical_key
            and (source is None or r.source == source) and r.event_time > NOW + timedelta(days=2)
            and (r.payload.get("status") or "SCHEDULED") == "SCHEDULED"]
    assert rows, key_part
    return sorted(rows, key=lambda r: r.event_time)[0]


def revise(r, known, **payload):
    return r.model_copy(update={"record_id": f"{r.source}:{r.logical_key}:r{r.revision + 1}",
                                "revision": r.revision + 1, "ingested_at": known,
                                "payload": {**r.payload, **payload}})


# ------------------------------------------------------------------ EVT-01 / EVT-02 cửa sổ

def test_quiet_time_no_risk_next_event_listed(st):
    at = CPI_AT - 2 * timedelta(hours=1)
    o = run(st, at)
    assert o.source_status is SourceStatus.HEALTHY and o.analyst_id == "event"
    f = o.features
    assert f["event_risk"] == "NONE" and f["window"] is None and not f["soon"]
    assert f["next_event"]["release_at"] == CPI_AT.isoformat()
    assert f["next_event"]["minutes_until"] == 120.0
    assert {u["event"] for u in f["upcoming"]} >= {"BLS_CPI", "DOL_JOBLESS_CLAIMS"}
    assert "SOURCE_HEALTH_UNKNOWN" in o.quality_flags      # không có nhật ký kiểm nguồn
    assert o.expires_at == at + EA.TTL                      # không có mốc nào sớm hơn 15 phút
    assert o.output_id.startswith("event:event-1.0.0:GLOBAL::*:*:")


def test_soon_flag_before_window(st):
    o = run(st, CPI_AT - 30 * M)
    assert o.features["soon"] and "EVENT_SOON" in o.risk_flags
    assert {"EVENT_SOON:BLS_CPI", "EVENT_SOON:DOL_JOBLESS_CLAIMS"} <= set(o.drivers)
    assert "EVENT_WINDOW" not in o.risk_flags
    assert o.expires_at == CPI_AT - 15 * M                  # mốc: cửa sổ mở


def test_in_window_high_same_minute_merged(st):
    at = CPI_AT - 10 * M
    o = run(st, at)
    f = o.features
    assert f["event_risk"] == "HIGH" and "EVENT_WINDOW" in o.risk_flags
    assert f["active_reasons"] == ["CALENDAR_HIGH"]
    assert (f["window"]["start"], f["window"]["end"]) == (
        (CPI_AT - 15 * M).isoformat(), (CPI_AT + 15 * M).isoformat())
    assert o.expires_at == CPI_AT - 5 * M                   # mốc: cửa sổ MEDIUM (claims) mở
    both = run(st, CPI_AT - M).features
    assert both["active_reasons"] == ["CALENDAR_HIGH", "CALENDAR_MEDIUM"]
    assert both["window"]["end"] == (CPI_AT + 15 * M).isoformat()   # hai cửa sổ gộp một


def test_fomc_statement_and_press_conference_window(st):
    o = run(st, FOMC_AT + 14 * M)
    assert o.features["window"]["end"] == (FOMC_AT + 45 * M).isoformat()


def test_agrees_with_fast_lane_calendar_blocks(st):
    """Cờ của analyst = phần lịch của Safety tại cùng as_of (cùng hàm, cùng dữ liệu)."""
    got = CPI_AT + 80 * S
    st.append(value("CUUR0000SA0", "CPI:2026-11", got))
    st.append(dol_value(CPI_AT + 50 * S))
    cb = FL.CalendarBlocks(st, None, REFERENCE, ttl=timedelta(0))
    t = CPI_AT - 90 * M
    n = 0
    while t < CPI_AT + 60 * M:
        o = run(st, t)
        codes = sorted({b.reason_code for b in cb.active(t)})
        assert o.features["active_reasons"] == codes, t
        assert ("EVENT_WINDOW" in o.risk_flags) == bool(codes), t
        t += 37 * S
        n += 1
    assert n > 200


# ------------------------------------------------------------------ EVT-03 số actual

def test_actual_received_surprise_insufficient(st):
    got = CPI_AT + 80 * S
    st.append(value("CUUR0000SA0", "CPI:2026-11", got))
    before = run(st, got - S)
    cpi = next(r for r in before.features["recent_releases"] if r["event"] == "BLS_CPI")
    assert cpi["actual_status"] == "AWAITING" and cpi["actuals"] == []     # chưa công bố ≠ 0
    after = run(st, CPI_AT + 5 * M)
    cpi = next(r for r in after.features["recent_releases"] if r["event"] == "BLS_CPI")
    assert cpi["actual_status"] == "RECEIVED" and cpi["actuals"] == [["CUUR0000SA0", "1.0"]]
    assert cpi["surprise_status"] == "INSUFFICIENT_DATA"
    assert cpi["forecast_status"] == "INSUFFICIENT_DATA"
    assert "SURPRISE_INSUFFICIENT_DATA" in after.drivers
    assert "RELEASE_HIGH_RECEIVED" in after.features["active_reasons"]


def test_actual_zero_is_a_value_not_missing(st):
    r = value("CUUR0000SA0", "CPI:2026-11", CPI_AT + M)
    st.append(r.model_copy(update={"payload": {**r.payload, "value": "0"}}))
    o = run(st, CPI_AT + 2 * M)
    cpi = next(x for x in o.features["recent_releases"] if x["event"] == "BLS_CPI")
    assert cpi["actual_status"] == "RECEIVED" and cpi["actuals"] == [["CUUR0000SA0", "0"]]


def test_actual_late_flagged_and_window_extended(st):
    o = run(st, CPI_AT + 20 * M)                     # quá 15 phút chưa có số
    cpi = next(x for x in o.features["recent_releases"] if x["event"] == "BLS_CPI")
    assert cpi["actual_status"] == "UNKNOWN_LATE"
    assert "ACTUAL_UNKNOWN:BLS_CPI" in o.drivers and "EVENT_WINDOW" in o.risk_flags


# ------------------------------------------------------------------ EVT-04 hoãn / hủy / đổi giờ

def test_removed_event_reported_and_no_window(st):
    r = calendar_record(st, "CPI", source="bls_schedule")
    known = NOW + timedelta(hours=1)
    st.append(revise(r, known, status="REMOVED"))
    at = r.event_time - 10 * M
    o = run(st, at)
    assert f"EVENT_REMOVED:{r.payload['event']}" in o.drivers
    assert any(x["logical_key"] == r.logical_key for x in o.features["removed"])
    assert not any(c.startswith("cal:bls_schedule:" + r.logical_key)
                   for c in (o.features["window"] or {}).get("causes", []))


def test_moved_event_uses_new_time_point_in_time(st):
    r = calendar_record(st, "FOMC_STATEMENT")
    new_t = r.event_time + timedelta(days=1)
    known = NOW + timedelta(hours=1)
    st.append(revise(r, known).model_copy(update={"event_time": new_t}))
    old = run(st, r.event_time - 10 * M)
    assert "EVENT_WINDOW" not in old.risk_flags or all(
        "FOMC_STATEMENT" not in c or r.logical_key not in c
        for c in old.features["window"]["causes"])
    new = run(st, new_t - 10 * M)
    assert "EVENT_WINDOW" in new.risk_flags
    assert any(u["revision"] == r.revision + 1 for u in new.features["upcoming"])
    # Trước khi biết bản sửa: vẫn giờ cũ (point-in-time)
    assert run(st, NOW + 30 * M).features["next_event"] is not None


# ------------------------------------------------------------------ 3-C08 / 3-C09

def test_sources_disagree_lowers_confidence_and_whole_day(st):
    r = calendar_record(st, "FOMC_STATEMENT")
    st.append(revise(r, NOW + M, flags=["CALENDAR_SOURCES_DISAGREE"]))
    assert "CALENDAR_SOURCES_DISAGREE" not in run(st, NOW + 2 * M).quality_flags  # ngoài tầm 24 giờ
    o = run(st, r.event_time - timedelta(hours=20))
    assert "CALENDAR_SOURCES_DISAGREE" in o.quality_flags and o.confidence == 0.5
    assert "CALENDAR_SOURCES_DISAGREE" in o.drivers
    day = run(st, r.event_time - timedelta(hours=5))       # cả ngày New York → đã trong cửa sổ
    assert "EVENT_WINDOW" in day.risk_flags


def test_release_near_friday_close_hold_counts_after_open(st):
    """3-C09: số HIGH nhận 2 phút trước giờ đóng thứ Sáu → 13 phút còn lại tính sau giờ mở."""
    from .test_economic_calendar import cal_record
    rel, got = utc(2026, 12, 11, 21, 45), utc(2026, 12, 11, 21, 58)
    assert REFERENCE.is_open(got) and not REFERENCE.is_open(utc(2026, 12, 12, 10))
    st.append(cal_record("CPI:TEST", rel, {"event": "BLS_CPI", "time_confirmed": True,
                                           "all_day": False, "status": "SCHEDULED",
                                           "flags": []}, source="bls_schedule"))
    st.append(value("CUUR0000SA0", "CPI:TEST", got, release_at=rel, key="X:TEST"))
    o = run(st, utc(2026, 12, 12, 10))                      # thứ Bảy
    assert "RELEASE_HIGH_RECEIVED" in o.features["active_reasons"]
    end = FL.hold_end(got, FL.RELEASE_HOLD, REFERENCE)
    assert end > utc(2026, 12, 13, 22) and REFERENCE.is_open(end - M)
    assert o.features["window"]["end"] == end.isoformat()


# ------------------------------------------------------------------ đầu vào (3-C01..C03)

def test_empty_calendar_is_missing_not_no_risk():
    o = run(PointInTimeStore(), CPI_AT)
    assert o.source_status is SourceStatus.MISSING and set(o.features) == {"input"}
    assert {"MISSING_INPUT:fed_fomc", "MISSING_INPUT:bls_schedule"} <= set(o.drivers)
    assert "EVENT_WINDOW" not in o.risk_flags and o.confidence == 0.0
    assert o.expires_at == CPI_AT + EA.BLOCKED_TTL


def test_schedule_coverage_gap_is_missing(st):
    o = run(st, utc(2029, 6, 1))                           # lịch đã nạp không phủ tới đây
    assert o.source_status is SourceStatus.MISSING


def test_with_check_log_healthy_then_stale():
    st, log = load(PointInTimeStore())
    ok = EA.compute(st, NOW + timedelta(hours=1), check_log=log, market_calendar=REFERENCE)
    assert ok.source_status is SourceStatus.HEALTHY
    assert "SOURCE_HEALTH_UNKNOWN" not in ok.quality_flags
    assert "OPTIONAL_MISSING:bls_values" in ok.quality_flags     # nguồn số chưa kiểm lần nào
    stale = EA.compute(st, NOW + timedelta(hours=30), check_log=log, market_calendar=REFERENCE)
    assert stale.source_status is SourceStatus.STALE
    assert "STALE_INPUT:fed_fomc" in stale.drivers and set(stale.features) == {"input"}


def test_read_error_raises():
    class Broken:
        def as_of(self, *a, **k):
            raise RuntimeError("db down")

    with pytest.raises(RuntimeError):
        run(Broken(), CPI_AT)


# ------------------------------------------------------------------ 3-C06 / idempotent

def test_future_records_do_not_change_past_output(st):
    at = CPI_AT - 10 * M
    before = run(st, at)
    st.append(value("CUUR0000SA0", "CPI:2026-11", CPI_AT + M))
    r = calendar_record(st, "FOMC_STATEMENT")
    st.append(revise(r, at + S, status="REMOVED"))
    assert run(st, at) == before
    assert run(st, at + 2 * S).output_id != before.output_id


# ------------------------------------------------------------------ orchestrator

@pytest.fixture(params=["memory", "sqlite"])
def outs(request, tmp_path):
    if request.param == "memory":
        return InMemoryAnalystOutputStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'o.db'}")
    repo.create_all()
    return SqlAnalystOutputStore(repo.engine)


def test_router_recomputes_event_on_expiry():
    e = expired_event(ExpiredOutput("event", "*", "*", "GLOBAL", "", "id", CPI_AT))
    assert [r.job_type for r in routes_for(e)] == ["INVALIDATE_MARKETVIEW", "EVENT_CALENDAR"]
    e = expired_event(ExpiredOutput("news", "*", "*", "GLOBAL", "", "id", CPI_AT))
    assert [r.job_type for r in routes_for(e)] == ["INVALIDATE_MARKETVIEW"]


def test_handler_via_dispatcher_stores_once_and_skips_duplicates(st, outs):
    ea = EA.EventAnalyst(st, outs, market_calendar=REFERENCE)
    orch = OrchestratorStore()
    got = CPI_AT + 80 * S
    recs = [value("CUUR0000SA0", "CPI:2026-11", got), dol_value(got)]
    for r in recs:
        st.append(r)
    orch.record_events([record_event(r) for r in recs], recorded_at=got)
    d = Dispatcher(orch, {"EVENT_CALENDAR": EA.event_handler(ea)})
    now = got + 2 * S
    res = d.tick(now)
    assert res.ran.get(JobState.SUCCEEDED.value, res.ran.get(JobState.SUCCEEDED)) == 2
    latest = outs.latest_scoped("event", GLOBAL_SCOPE)
    assert latest.output.as_of == got                      # max(now − 5 giây, lúc biết)
    assert len(outs.computed_between(now - M, now + M)) == 1   # sự kiện thứ hai: bỏ qua
    cpi = next(x for x in latest.output.features["recent_releases"] if x["event"] == "BLS_CPI")
    assert cpi["actual_status"] == "RECEIVED"


def test_ensure_fresh_bootstrap_and_fallback(st, outs):
    ea = EA.EventAnalyst(st, outs, market_calendar=REFERENCE)
    t = CPI_AT - 2 * timedelta(hours=1)
    assert ea.ensure_fresh(t) is True
    o = outs.latest_scoped("event", GLOBAL_SCOPE).output
    assert o.as_of == t - EA.SETTLE
    assert ea.ensure_fresh(t + M) is False                    # còn hạn
    assert ea.ensure_fresh(o.expires_at + 30 * S) is False   # đường chính còn thời gian
    assert ea.ensure_fresh(o.expires_at + EA.FALLBACK_GRACE + S) is True


def test_expiry_event_job_recomputes(st, outs):
    ea = EA.EventAnalyst(st, outs, market_calendar=REFERENCE)
    t = CPI_AT - 2 * timedelta(hours=1)
    ea.run_at(t, t)
    first = outs.latest_scoped("event", GLOBAL_SCOPE).output
    exp = outs.expired_unreplaced(t, first.expires_at)
    assert len(exp) == 1
    ev = expired_event(exp[0])
    orch = OrchestratorStore()
    orch.record_events([ev], recorded_at=first.expires_at)
    d = Dispatcher(orch, {"EVENT_CALENDAR": EA.event_handler(ea)})
    d.tick(first.expires_at + S)
    new = outs.latest_scoped("event", GLOBAL_SCOPE).output
    assert new.as_of == first.expires_at and new.output_id != first.output_id
    assert new.is_valid_at(first.expires_at + S)


# ------------------------------------------------------------------ API (ANA-02)

def test_api_event_latest_requires_login_and_returns_output(st):
    from fastapi.testclient import TestClient

    from gold_trading.storage.repository import InMemoryRepository

    from .auth_helpers import make_app, user_client
    outs = InMemoryAnalystOutputStore()
    c = user_client(InMemoryRepository(), analyst_store=outs, data_source=None,
                    run_analysts=False, external_runner=None)
    body = c.get("/api/analysts/event/latest").json()
    assert body["output"] is None and body["valid_now"] is False
    from gold_trading.common.time import utcnow
    now = utcnow()
    EA.EventAnalyst(st, outs, market_calendar=REFERENCE).run_at(now - EA.SETTLE, now)
    body = c.get("/api/analysts/event/latest").json()
    assert body["output"]["analyst_id"] == "event" and body["observer_only"] is True
    assert body["confidence_meaning"] == "DATA_QUALITY_ONLY"
    app, _ = make_app(InMemoryRepository(), analyst_store=outs, data_source=None,
                      run_analysts=False, external_runner=None)
    assert TestClient(app).get("/api/analysts/event/latest").status_code == 401
