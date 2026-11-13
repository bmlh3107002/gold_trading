"""Bước 10e — trang "Nguồn dữ liệu" (DSH-09): tổng quan trạng thái + API."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from gold_trading.common.enums import SourceStatus
from gold_trading.contracts.records import NormalizedRecord
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.ingestion.source_overview import overview
from gold_trading.ingestion.source_status import (
    CheckOutcome,
    SourceCheck,
    SourceCheckLog,
    SourceRegistry,
    SourceSpec,
)
from gold_trading.ingestion.source_terms import SourceTerms, TermsStatus
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.repository import InMemoryRepository, SqlRepository
from gold_trading.storage.source_checks import SqlSourceCheckLog
from tests.auth_helpers import admin_client, make_app, user_client

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
H = timedelta(hours=1)
TERMS = {p: SourceTerms(p, TermsStatus.VERIFIED, date(2026, 11, 13), "#")
         for p in ("a", "b", "c", "d", "e")} | {
    "x": SourceTerms("x", TermsStatus.BLOCKED, date(2026, 11, 13), "#")}


def reg():
    return SourceRegistry([
        SourceSpec("a_macro", "macro", fetch_ttl=6 * H, data_ttl=48 * H, provider="a"),
        SourceSpec("b_news", "news", fetch_ttl=6 * H, provider="b"),
        SourceSpec("c_cal", "calendar", fetch_ttl=26 * H, provider="c"),
        SourceSpec("d_fatal", "macro", fetch_ttl=6 * H, provider="d"),
        SourceSpec("e_never", "news", fetch_ttl=6 * H, provider="e"),
        SourceSpec("x_off", "positioning", fetch_ttl=6 * H, provider="x", enabled=False),
    ], terms=TERMS)


@pytest.fixture(params=["memory", "sqlite"])
def env(request, tmp_path):
    if request.param == "memory":
        return PointInTimeStore(), SourceCheckLog()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 's.db'}")
    repo.create_all()
    return SqlExternalRecordStore(repo.engine), SqlSourceCheckLog(repo.engine)


def rec(source, key, event, ingested, kind="macro", value=1, rid=None):
    return NormalizedRecord(
        record_id=rid or f"{source}:{key}", source=source, kind=kind, logical_key=key,
        event_time=event, ingested_at=ingested, source_status=SourceStatus.HEALTHY,
        payload_version="v1", raw_ref="t", payload={"v": value})


def fill(store, log):
    log.record(SourceCheck("a_macro", NOW - 2 * H, CheckOutcome.OK, inserted=1))
    store.append(rec("a_macro", "S:1", NOW - 30 * H, NOW - 2 * H))
    log.record(SourceCheck("b_news", NOW - 7 * H, CheckOutcome.OK))       # quá TTL 6 giờ
    log.record(SourceCheck("c_cal", NOW - H, CheckOutcome.OK))
    log.record(SourceCheck("d_fatal", NOW - 3 * H, CheckOutcome.OK))
    log.record(SourceCheck("d_fatal", NOW - H, CheckOutcome.ERROR, "FORBIDDEN"))
    # cách ly: 1 bản 10 ngày trước, 2 bản hôm nay (xung đột revision), 1 bản sau as_of
    store.append(rec("a_macro", "S:0", NOW - 11 * 24 * H, NOW - 10 * 24 * H),
                 received_at=NOW - 10 * 24 * H)
    store.append(rec("a_macro", "S:0", NOW - 11 * 24 * H, NOW - 10 * 24 * H, value=2,
                     rid="z1"), received_at=NOW - 10 * 24 * H)
    for i, t in enumerate((NOW - H, NOW - H, NOW + H)):
        store.append(rec("a_macro", "S:1", NOW - 30 * H, t, value=9, rid=f"q{i}"),
                     received_at=t)


def by_name(rows):
    return {r.name: r for r in rows}


def test_overview_states(env):
    store, log = env
    fill(store, log)
    rows = by_name(overview(reg(), store, log, NOW, terms=TERMS))
    assert list(rows) == ["a_macro", "b_news", "c_cal", "d_fatal", "e_never", "x_off"]
    a = rows["a_macro"]
    assert (a.status, a.reason, a.terms_status, a.enabled) == ("HEALTHY", "OK", "VERIFIED", True)
    assert a.receive_age_seconds == 2 * 3600 and a.data_age_seconds == 30 * 3600
    assert a.latest_event_at == NOW - 30 * H
    assert (a.fetch_ttl_seconds, a.data_ttl_seconds) == (6 * 3600, 48 * 3600)
    # 3 bản cách ly tới as_of (1 bản 10 ngày trước + 2 bản hôm nay); bản sau as_of không tính
    assert (a.quarantine_7d, a.quarantine_total) == (2, 3)
    assert (rows["b_news"].status, rows["b_news"].reason) == ("STALE", "FETCH_TTL_EXPIRED")
    assert rows["c_cal"].status == "HEALTHY" and rows["c_cal"].data_ttl_seconds is None
    d = rows["d_fatal"]
    assert (d.status, d.reason, d.last_error_code, d.failures_since_ok) == (
        "MISSING", "FORBIDDEN", "FORBIDDEN", 1)
    e = rows["e_never"]
    assert (e.status, e.reason, e.last_check_at, e.receive_age_seconds) == (
        "MISSING", "NEVER_CHECKED", None, None)
    x = rows["x_off"]
    assert (x.status, x.reason, x.terms_status, x.enabled) == (
        "MISSING", "DISABLED", "BLOCKED", False)


def test_overview_point_in_time(env):
    """Tính lại tại as_of cũ: không thấy lần kiểm / bản ghi / cách ly ghi sau đó."""
    store, log = env
    fill(store, log)
    t = NOW - 5 * H
    rows = by_name(overview(reg(), store, log, t, terms=TERMS))
    assert rows["a_macro"].status == "MISSING" and rows["a_macro"].reason == "NEVER_CHECKED"
    assert rows["a_macro"].quarantine_total == 1         # chỉ bản xung đột 10 ngày trước
    assert rows["b_news"].status == "HEALTHY"           # lúc đó lần OK mới 2 giờ
    assert rows["d_fatal"].status == "MISSING" and rows["d_fatal"].reason == "NEVER_CHECKED"


def test_overview_invalid_and_flags(env):
    store, log = env
    log.record(SourceCheck("a_macro", NOW - 2 * H, CheckOutcome.OK, inserted=1, invalid=2))
    store.append(rec("a_macro", "S:1", NOW - 3 * H, NOW - 2 * H))
    log.record(SourceCheck("b_news", NOW - 3 * H, CheckOutcome.OK))
    log.record(SourceCheck("b_news", NOW - H, CheckOutcome.INVALID, "FEED_NOT_XML"))
    log.record(SourceCheck("c_cal", NOW - 3 * H, CheckOutcome.OK))
    log.record(SourceCheck("c_cal", NOW - H, CheckOutcome.ERROR, "HTTP_503"))
    rows = by_name(overview(reg(), store, log, NOW, terms=TERMS))
    assert rows["a_macro"].flags == ("PARTIAL_INVALID",)
    assert (rows["b_news"].status, rows["b_news"].reason) == ("INVALID", "FEED_NOT_XML")
    c = rows["c_cal"]
    assert (c.status, c.flags, c.last_error_code) == ("HEALTHY", ("RECENT_FAILURES",),
                                                      "HTTP_503")


def test_overview_future_check_and_data_ignored(env):
    store, log = env
    log.record(SourceCheck("a_macro", NOW + H, CheckOutcome.OK))
    store.append(rec("a_macro", "S:9", NOW + H, NOW + 2 * H))
    a = by_name(overview(reg(), store, log, NOW, terms=TERMS))["a_macro"]
    assert a.status == "MISSING" and a.latest_event_at is None and a.data_age_seconds is None


# ------------------------------------------------------------------ API

class FakeRunner:
    def __init__(self):
        self.registry = reg()
        self.store = PointInTimeStore()
        self.check_log = SourceCheckLog()
        fill(self.store, self.check_log)

    def start(self):
        pass

    def stop(self):
        pass


def test_api_lists_sources(monkeypatch):
    import gold_trading.ingestion.source_overview as O
    monkeypatch.setattr(O, "SOURCE_TERMS", TERMS)
    from gold_trading.api import data_sources as D
    monkeypatch.setattr(D, "utcnow", lambda: NOW)
    c = user_client(external_runner=FakeRunner())
    r = c.get("/api/data-sources")
    assert r.status_code == 200
    body = r.json()
    assert body["runner_enabled"] is True and body["quarantine_window_days"] == 7
    assert body["as_of"].startswith("2026-11-13T12:00")
    s = {x["name"]: x for x in body["sources"]}
    assert s["a_macro"]["status"] == "HEALTHY" and s["a_macro"]["quarantine_7d"] == 2
    assert s["d_fatal"]["last_error_code"] == "FORBIDDEN"
    assert s["x_off"]["enabled"] is False


def test_api_admin_can_read_and_runner_off():
    c = admin_client(external_runner=None)
    r = c.get("/api/data-sources")
    assert r.status_code == 200
    assert r.json()["runner_enabled"] is False and r.json()["sources"] == []


def test_api_requires_login():
    app, _ = make_app(InMemoryRepository(), external_runner=FakeRunner())
    r = TestClient(app).get("/api/data-sources")
    assert r.status_code == 401


def test_api_never_leaks_key_or_url(monkeypatch):
    """Mã lỗi đã chỉ là mã ngắn (ING-30); phản hồi không chứa URL / khóa."""
    runner = FakeRunner()
    with pytest.raises(ValueError):
        runner.check_log.record(SourceCheck("a_macro", NOW, CheckOutcome.ERROR,
                                            "https://x/?api_key=SECRET"))
    c = user_client(external_runner=runner)
    assert "SECRET" not in c.get("/api/data-sources").text
