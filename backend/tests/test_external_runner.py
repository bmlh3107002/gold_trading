"""Bước 8g — chạy tự động FOMC / BEA / DOL trong backend (``ingestion/external_runner.py``).

Dùng trang / file thật đã lưu ở ``tests/fixtures/{fed,bea,dol}`` qua ``httpx.MockTransport``
(không gọi mạng). Case: nhịp không gọi dồn, lỗi tạm thử lại có giãn cách, thiếu khóa không gọi
BEA, khởi động lại không mất nhịp, đồng hồ bị chặn → không nạp, lỗi bất ngờ một việc không làm
chết việc khác, cửa sổ công bố đã có số → thôi gọi.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from gold_trading.ingestion import external_runner as R
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.ingestion.source_status import (
    CheckOutcome,
    CheckSummary,
    SourceCheck,
    SourceCheckLog,
)
from gold_trading.ingestion.sources import bea as B
from gold_trading.ingestion.sources import dol as D
from gold_trading.ingestion.sources import fed_fomc as F
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.source_checks import SqlSourceCheckLog

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
KEY_VALUE = "ABCDEF12-3456-7890-ABCD-EF1234567890"
FED_PAGES = {
    F.MEETINGS_PATH: (FIX / "fed" / "fomccalendars-2026-11-13.html").read_text(encoding="utf-8"),
    F.CALENDAR_INDEX_PATH: (FIX / "fed" / "calendar-2026-11-13.html").read_text(encoding="utf-8"),
    **{f"/newsevents/2026-{m}.htm": (FIX / "fed" / f"2026-{m}.html").read_text(encoding="utf-8")
       for m in ("october", "november", "december")},
    "/releases/h15/": (FIX / "fed" / "h15-2026-11-12.html").read_text(encoding="utf-8"),
}
RSS = {f"/feeds/{n}.xml": (FIX / "fed" / "rss" / f"{n}.xml").read_bytes()
       for n in ("press_monetary", "speeches_and_testimony")}
TREASURY = (FIX / "treasury" / "press-releases-2026-11-13.xml").read_bytes()
BLS_JSON = (FIX / "bls" / "timeseries-2026-11-13.json").read_text(encoding="utf-8")
BLS_KEY = "0123456789abcdef0123456789abcdef"
BEA_FILES = {
    B.ICS_URL: (FIX / "bea" / "schedule-2026-11-13.ics").read_text(encoding="utf-8"),
    B.DATES_URL: (FIX / "bea" / "release_dates-2026-11-13.json").read_text(encoding="utf-8"),
}
NIPA = {t: (FIX / "bea" / f"nipa-{t}-2026-11-13.json").read_text(encoding="utf-8")
        for t in B.TABLES}
PDF = (FIX / "dol" / "ui-data-2026-11-12.pdf").read_bytes()
COT = (FIX / "cftc" / "deacmxsf-2026-11-03-gold.txt").read_text(encoding="utf-8")


class Net:
    """Máy chủ giả cho cả ba nhà cung cấp; ghi lại mọi lượt gọi; ``down`` = host trả 503."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.down: set[str] = set()

    def handler(self, req: httpx.Request) -> httpx.Response:
        host, path = req.url.host, req.url.path
        self.calls.append(f"{host}{path}")
        if host in self.down:
            return httpx.Response(503)
        url = str(req.url).split("?")[0]
        if host == "api.bls.gov" and path == "/publicAPI/v2/timeseries/data/":
            import json as _json
            assert req.method == "POST" and BLS_KEY not in str(req.url)
            assert _json.loads(req.content)["registrationkey"] == BLS_KEY
            return httpx.Response(200, text=BLS_JSON)
        if host == "home.treasury.gov" and path == "/news/press-releases/index.xml":
            return httpx.Response(200, content=TREASURY)
        if host == "www.federalreserve.gov" and path in RSS:
            return httpx.Response(200, content=RSS[path])
        if host == "www.federalreserve.gov" and path in FED_PAGES:
            return httpx.Response(200, text=FED_PAGES[path])
        if url in BEA_FILES:
            return httpx.Response(200, text=BEA_FILES[url])
        if url == B.API_URL:
            assert req.url.params["UserID"] == KEY_VALUE
            return httpx.Response(200, text=NIPA[req.url.params["TableName"]])
        if url == D.PDF_URL:
            return httpx.Response(200, content=PDF)
        if host == "www.cftc.gov" and path == "/dea/futures/deacmxsf.htm":
            return httpx.Response(200, text=COT)
        return httpx.Response(404)

    def count(self, host: str) -> int:
        return sum(1 for c in self.calls if c.startswith(host))


@pytest.fixture(params=["memory", "sqlite"])
def stores(request, tmp_path):
    if request.param == "memory":
        return PointInTimeStore(), SourceCheckLog(), None
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'r.db'}")
    repo.create_all()
    return SqlExternalRecordStore(repo.engine), SqlSourceCheckLog(repo.engine), repo.engine


def make(stores, net, env=None, sources=R.DEFAULT_SOURCES, **kw):
    store, check_log, _ = stores
    client = httpx.Client(transport=httpx.MockTransport(net.handler))
    jobs, _ = R.build_jobs(sources, store=store, check_log=check_log, env=env or {},
                           client=client)
    return R.ExternalSourceRunner(jobs, check_log, **kw)


def by_source(checks):
    return {c.source: c for c in checks}


def summary(last=None, last_ok_at=None):
    return CheckSummary(last, last_ok_at, 0, None, None, None)


def chk(at, ok=True, code=None):
    return SourceCheck("x", at, CheckOutcome.OK if ok else CheckOutcome.ERROR,
                       None if ok else code or "HTTP_503")


# ------------------------------------------------------------------ cấu hình

def test_parse_sources():
    assert R.parse_sources(None) == ("fed_fomc", "bea", "dol", "bls", "fed_h15", "cftc_cot",
                                     "news")
    assert R.parse_sources("  ") == R.DEFAULT_SOURCES
    for off in ("0", "off", "OFF", "none", "false"):
        assert R.parse_sources(off) == ()
    assert R.parse_sources("dol, fed_fomc,dol") == ("dol", "fed_fomc")
    with pytest.raises(ValueError, match="census"):
        R.parse_sources("fed_fomc,census")  # Census đang hoãn → không âm thầm bỏ qua
    with pytest.raises(ValueError, match="fred"):
        R.parse_sources("fred")  # FRED BLOCKED (9a) → không có trong bộ chạy


def test_runner_from_env_silences_url_logging(caplog):
    import logging
    logging.getLogger("httpx").setLevel(logging.INFO)
    r = R.runner_from_env(None, {"GT_BEA_API_KEY": KEY_VALUE})
    r.stop()
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


def test_runner_logs_never_contain_key(stores, caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    logging.getLogger("httpx").setLevel(logging.DEBUG)  # như khi chưa có bộ chạy
    net = Net()
    r = make(stores, net, env={"GT_BEA_API_KEY": KEY_VALUE})
    r.tick(NOW)
    assert any("/api/data" in c for c in net.calls)
    assert KEY_VALUE not in caplog.text


def test_runner_from_env():
    assert R.runner_from_env(None, {"GT_EXTERNAL_SOURCES": "0"}) is None
    r = R.runner_from_env(None, {})
    try:
        assert r.sources == ["fed_fomc", "bea_schedule", "dol_claims_schedule", "bls_schedule",
                             "bea_nipa", "dol_claims", "bls_values", "fed_h15",
                             "cftc_cot_gold", "fed_rss_monetary",
                             "fed_rss_speeches", "treasury_press"]  # lịch trước, số sau, tin cuối
    finally:
        r.stop()
    with pytest.raises(ValueError):
        R.runner_from_env(None, {"GT_EXTERNAL_SOURCES": "census"})


# ------------------------------------------------------------------ quy tắc đến hạn (hàm thuần)

def test_schedule_due_rules():
    assert R.schedule_due(NOW, summary()) == "REFRESH"  # chưa thử lần nào
    ok1h = NOW - timedelta(hours=1)
    assert R.schedule_due(NOW, summary(chk(ok1h), ok1h)) is None
    ok21h = NOW - timedelta(hours=21)
    assert R.schedule_due(NOW, summary(chk(ok21h), ok21h)) == "REFRESH"
    # Lỗi 10 phút trước (OK cuối 25 giờ trước) → chưa thử lại; 30 phút → thử lại
    ok25h = NOW - timedelta(hours=25)
    assert R.schedule_due(NOW, summary(chk(NOW - timedelta(minutes=10), False), ok25h)) is None
    assert R.schedule_due(NOW, summary(chk(NOW - timedelta(minutes=30), False), ok25h)) == "RETRY"
    # Chưa OK lần nào, lỗi 5 phút trước → chưa thử lại (không gọi dồn)
    assert R.schedule_due(NOW, summary(chk(NOW - timedelta(minutes=5), False))) is None
    # Lỗi mới nhưng lần OK cuối còn mới → không cần gọi
    assert R.schedule_due(NOW, summary(chk(NOW - timedelta(hours=40), False), ok1h)) is None


def test_values_job_due_rules():
    s_none = summary()
    assert R.values_job_due(NOW, s_none, None) is None
    assert R.values_job_due(NOW, s_none, "RELEASE_WINDOW") == "RELEASE_WINDOW"
    s30 = summary(chk(NOW - timedelta(seconds=30)))
    assert R.values_job_due(NOW, s30, "RELEASE_WINDOW") is None
    s60 = summary(chk(NOW - timedelta(seconds=60)))
    assert R.values_job_due(NOW, s60, "RELEASE_WINDOW") == "RELEASE_WINDOW"
    s1h = summary(chk(NOW - timedelta(hours=1), False, "KEY_MISSING"))
    assert R.values_job_due(NOW, s1h, "RECONCILE") is None
    s6h = summary(chk(NOW - timedelta(hours=6), False, "KEY_MISSING"))
    assert R.values_job_due(NOW, s6h, "RECONCILE") == "RECONCILE"
    assert R.values_job_due(NOW, s_none, "RECONCILE") == "RECONCILE"


# ------------------------------------------------------------------ chạy với trang thật

def test_first_tick_runs_all_and_missing_key_never_calls_bea_api(stores):
    net = Net()
    r = make(stores, net)
    got = by_source(r.tick(NOW))
    assert list(got) == ["fed_fomc", "bea_schedule", "dol_claims_schedule", "bls_schedule",
                         "bea_nipa", "dol_claims", "bls_values", "fed_h15", "cftc_cot_gold",
                         "fed_rss_monetary", "fed_rss_speeches", "treasury_press"]
    for s in ("fed_fomc", "bea_schedule", "dol_claims_schedule", "bls_schedule", "dol_claims",
              "fed_h15", "cftc_cot_gold", "fed_rss_monetary", "fed_rss_speeches",
              "treasury_press"):
        assert got[s].outcome is CheckOutcome.OK and got[s].inserted > 0, s
    assert got["bea_nipa"].outcome is CheckOutcome.ERROR
    assert got["bea_nipa"].error_code == "KEY_MISSING"
    assert got["bls_values"].error_code == "KEY_MISSING"
    assert not any("api.bls.gov" in c for c in net.calls)  # thiếu khóa → không gọi API BLS
    assert not any("/api/data" in c for c in net.calls)  # thiếu khóa → không gọi API BEA
    store = stores[0]
    assert store.as_of(NOW, source="fed_fomc") and store.as_of(NOW, source="dol_claims")


def test_no_burst_calls_then_retry_and_refresh_on_schedule(stores):
    net = Net()
    r = make(stores, net, sources=("fed_fomc", "bea", "dol"))  # H.15: test riêng (tải 4 giờ/lần)
    r.tick(NOW)
    n = len(net.calls)
    # 30 giây sau và 5 giờ sau: không gì đến hạn (thiếu khóa BEA thử lại sau 6 giờ)
    assert r.tick(NOW + timedelta(seconds=30)) == []
    assert r.tick(NOW + timedelta(hours=5)) == []
    assert len(net.calls) == n
    got = by_source(r.tick(NOW + timedelta(hours=6, seconds=1)))
    assert list(got) == ["bea_nipa"] and got["bea_nipa"].error_code == "KEY_MISSING"
    assert len(net.calls) == n
    # 21 giờ sau: tải lại cả ba lịch, nạp lại không thêm bản ghi mới (idempotent)
    got = by_source(r.tick(NOW + timedelta(hours=21)))
    assert {"fed_fomc", "bea_schedule", "dol_claims_schedule"} <= set(got)
    assert all(got[s].outcome is CheckOutcome.OK and got[s].inserted == 0
               for s in ("fed_fomc", "bea_schedule"))


def test_with_key_bea_values_reconcile(stores):
    net = Net()
    r = make(stores, net, env={"GT_BEA_API_KEY": KEY_VALUE})
    got = by_source(r.tick(NOW))
    assert got["bea_nipa"].outcome is CheckOutcome.OK and got["bea_nipa"].inserted > 0
    calls_api = sum(1 for c in net.calls if c.endswith("/api/data"))
    assert calls_api == len(B.TABLES)
    # Ngày hôm sau, không có lần công bố: không gọi lại API (BEA không khuyến khích)
    r.tick(NOW + timedelta(days=1))
    assert sum(1 for c in net.calls if c.endswith("/api/data")) == calls_api


def test_source_down_retries_with_backoff_not_every_tick(stores):
    net = Net()
    net.down.add("www.federalreserve.gov")
    r = make(stores, net, sources=("fed_fomc",))
    got = by_source(r.tick(NOW))
    assert got["fed_fomc"].outcome is CheckOutcome.ERROR
    assert got["fed_fomc"].error_code == "HTTP_503"
    n = net.count("www.federalreserve.gov")
    for m in (1, 10, 29):
        assert r.tick(NOW + timedelta(minutes=m)) == []
    assert net.count("www.federalreserve.gov") == n
    net.down.clear()
    got = by_source(r.tick(NOW + timedelta(minutes=30)))
    assert got["fed_fomc"].outcome is CheckOutcome.OK


def test_restart_keeps_rhythm_from_saved_log(tmp_path):
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'x.db'}")
    repo.create_all()
    stores = (SqlExternalRecordStore(repo.engine), SqlSourceCheckLog(repo.engine), repo.engine)
    net = Net()
    make(stores, net).tick(NOW)
    n = len(net.calls)
    # "Khởi động lại": bộ chạy mới, cùng DB → không gọi lại ngay
    assert make(stores, net).tick(NOW + timedelta(minutes=2)) == []
    assert len(net.calls) == n


def test_clock_blocked_does_not_ingest(stores):
    net = Net()
    reason = ["Ngừng nhận nến: đồng hồ máy chủ lệch"]
    r = make(stores, net, blocked=lambda: reason[0])
    assert r.tick(NOW) == []
    assert net.calls == []
    assert stores[1].summary("fed_fomc", NOW).last_check is None
    reason[0] = None
    assert r.tick(NOW + timedelta(seconds=30))  # hết chặn → chạy


def test_unexpected_error_in_one_job_records_internal_error_and_others_run(stores):
    store, check_log, _ = stores
    calls = []

    def boom(now):
        raise RuntimeError("lỗi lập trình có URL https://x/?api_key=SECRET")

    def fine(now):
        calls.append(now)
        c = SourceCheck("dol_claims_schedule", now, CheckOutcome.OK)
        check_log.record(c)
        return c

    r = R.ExternalSourceRunner([R.Job("fed_fomc", boom, R.schedule_due),
                                R.Job("dol_claims_schedule", fine, R.schedule_due)], check_log)
    got = by_source(r.tick(NOW))
    assert got["fed_fomc"].error_code == "INTERNAL_ERROR" and calls == [NOW]
    s = check_log.summary("fed_fomc", NOW)
    assert s.last_check.error_code == "INTERNAL_ERROR"  # chỉ mã ngắn, không thông điệp
    # Lỗi bất ngờ cũng giãn cách như lỗi khác
    assert r.tick(NOW + timedelta(minutes=5)) == []


def _value(source, key, available_at, payload, kind="macro"):
    from gold_trading.common.enums import SourceStatus
    from gold_trading.contracts.records import NormalizedRecord
    return NormalizedRecord(
        record_id=f"{source}:{key}:r0", source=source, kind=kind, logical_key=key, revision=0,
        event_time=available_at - timedelta(days=5), ingested_at=available_at,
        available_at=available_at, source_status=SourceStatus.HEALTHY, payload_version="t",
        raw_ref="test", payload=payload)


def test_dol_window_stops_once_release_is_stored(stores):
    store, check_log, _ = stores
    D.run_schedule_once(store=store, log=check_log, now=NOW)
    rel = datetime(2026, 11, 19, 13, 30, tzinfo=UTC)  # thứ Năm thường, 8:30 ET
    ok = rel - timedelta(days=1)
    assert D.values_due(rel + timedelta(minutes=1), store, ok) == "RELEASE_WINDOW"
    # Có bản tin phát hành từ 8:30 → thôi gọi (kể cả sau khi khởi động lại: dựa trên DB)
    store.append(_value(D.VALUES_SOURCE, "ICSA:2026-11-14", rel + timedelta(seconds=50),
                        {"series": "ICSA"}))
    assert D.values_due(rel + timedelta(minutes=2), store, ok) is None
    # Tuần lễ Tạ ơn (26/11): gọi thưa trong thứ Tư–Sáu tới khi có số phát hành từ thứ Tư
    wed = datetime(2026, 11, 25, 15, 0, tzinfo=UTC)  # 10:00 ET thứ Tư
    ok = wed - timedelta(days=1)
    assert D.values_due(wed, store, ok) == "RELEASE_DAY"
    assert R.values_job_due(wed, summary(chk(wed - timedelta(minutes=4))), "RELEASE_DAY") is None
    assert R.values_job_due(wed, summary(chk(wed - timedelta(minutes=5))), "RELEASE_DAY") == \
        "RELEASE_DAY"
    store.append(_value(D.VALUES_SOURCE, "ICSA:2026-11-21", wed, {"series": "ICSA"}))
    assert D.values_due(wed + timedelta(minutes=1), store, ok) is None
    assert D.values_due(datetime(2026, 11, 27, 15, 0, tzinfo=UTC), store, ok) is None  # thứ Sáu


def test_bea_window_stops_once_release_is_stored(stores):
    store, check_log, _ = stores
    B.run_schedule_once(store=store, log=check_log, get=lambda u, p=None: BEA_FILES[u], now=NOW)
    rel = datetime(2026, 11, 25, 13, 30, tzinfo=UTC)
    events = [r for r in store.as_of(rel, source=B.SCHEDULE_SOURCE)
              if r.event_time == rel and r.payload.get("time_confirmed")]
    assert len(events) == 2  # GDP + PIO cùng giờ
    ok = rel - timedelta(days=1)
    assert B.values_due(rel + timedelta(minutes=1), store, ok) == "RELEASE_WINDOW"
    first = events[0]
    store.append(_value(B.VALUES_SOURCE, "X:1", rel + timedelta(seconds=80),
                        {"release_ref": first.logical_key}))
    # Mới có số của một lần công bố → vẫn gọi để lấy lần kia
    assert B.values_due(rel + timedelta(minutes=2), store, ok) == "RELEASE_WINDOW"
    store.append(_value(B.VALUES_SOURCE, "X:2", rel + timedelta(seconds=90),
                        {"release_ref": events[1].logical_key}))
    assert B.values_due(rel + timedelta(minutes=3), store, ok) is None


def test_start_stop_thread_and_app_lifespan(monkeypatch):
    from fastapi.testclient import TestClient

    from gold_trading.api.app import create_app
    from gold_trading.contracts.candle import DataSource
    from gold_trading.storage.repository import InMemoryRepository

    events = []

    class Fake:
        def start(self):
            events.append("start")

        def stop(self):
            events.append("stop")

    app = create_app(InMemoryRepository(), data_source=DataSource.SAMPLE,
                     run_sample_feed=False, run_analysts=False, external_runner=Fake())
    with TestClient(app):
        assert events == ["start"]
    assert events == ["start", "stop"]
    # Bộ chạy thật: luồng chạy nhịp đầu rồi dừng gọn
    net = Net()
    r = make((PointInTimeStore(), SourceCheckLog(), None), net, sources=("dol",),
             tick=timedelta(seconds=0.05))
    r.start()
    try:
        for _ in range(100):
            if net.calls:
                break
            import time
            time.sleep(0.02)
    finally:
        r.stop()
    assert any("dol.gov" in c for c in net.calls)


# ------------------------------------------------------------------ bước 10b: nguồn tin RSS

def _feed_calls(net):
    return [c for c in net.calls if "/feeds/" in c]


def test_news_jobs_poll_every_15_min_and_back_off(stores):
    net = Net()
    r = make(stores, net, sources=("news",))
    assert r.sources == ["fed_rss_monetary", "fed_rss_speeches", "treasury_press"]
    got = by_source(r.tick(NOW))
    assert [c.inserted for c in got.values()] == [15, 15, 10]
    assert all(c.outcome is CheckOutcome.OK for c in got.values())
    assert r.tick(NOW + timedelta(minutes=14)) == []
    assert len(_feed_calls(net)) == 2 and net.count("home.treasury.gov") == 1
    got = by_source(r.tick(NOW + timedelta(minutes=15)))
    assert all(c.inserted == 0 and c.duplicate > 0 for c in got.values())
    # Fed trả 503 → Fed giãn 30 phút, rồi 60 phút (không gọi dồn); Bộ Tài chính vẫn 15 phút
    net.down.add("www.federalreserve.gov")
    t = NOW + timedelta(minutes=30)
    got = by_source(r.tick(t))
    assert got["fed_rss_monetary"].error_code == "HTTP_503"
    assert got["treasury_press"].outcome is CheckOutcome.OK
    assert r.tick(t + timedelta(minutes=14)) == []
    assert list(by_source(r.tick(t + timedelta(minutes=15)))) == ["treasury_press"]
    assert list(by_source(r.tick(t + timedelta(minutes=29)))) == []
    assert len(r.tick(t + timedelta(minutes=30))) == 3
    # t+89: Fed chưa tới hạn thử lại (60 phút kể từ t+30); Bộ Tài chính tới hạn thường lệ
    assert list(by_source(r.tick(t + timedelta(minutes=89)))) == ["treasury_press"]
    got = by_source(r.tick(t + timedelta(minutes=90)))
    assert {"fed_rss_monetary", "fed_rss_speeches"} <= set(got)


def test_news_bad_config_disables_news_only(stores, tmp_path, caplog):
    bad = tmp_path / "ns.json"
    bad.write_text('{"version": 1, "sources": [{"name": "x"}]}', encoding="utf-8")
    net = Net()
    with caplog.at_level("ERROR"):
        r = make(stores, net, env={"GT_NEWS_SOURCES_FILE": str(bad)},
                 sources=("fed_fomc", "news"))
    assert r.sources == ["fed_fomc"]
    assert "Không bật nguồn tin" in caplog.text
    assert by_source(r.tick(NOW))["fed_fomc"].outcome is CheckOutcome.OK


def test_news_disabled_entry_has_no_job(stores, tmp_path):
    p = tmp_path / "ns.json"
    p.write_text(json.dumps({"version": 1, "sources": [
        {"name": "fed_rss_monetary", "provider": "fed",
         "url": "https://www.federalreserve.gov/feeds/press_monetary.xml", "enabled": False,
         "license_note": "x", "poll_minutes": 15, "fetch_ttl_hours": 6}]}), encoding="utf-8")
    net = Net()
    r = make(stores, net, env={"GT_NEWS_SOURCES_FILE": str(p)}, sources=("news",))
    assert r.sources == [] and r.tick(NOW) == [] and net.calls == []
