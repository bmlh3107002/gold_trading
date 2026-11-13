"""GĐ2 bước 1c — sinh sự kiện từ dữ liệu GĐ1 (ORC-02 phần nguồn; 2-C01, 2-C02).

Dữ liệu ngoài: 12 việc thật của bộ chạy GĐ1 trên ``tests/fixtures`` (như test replay ING-34).
Nến: nạp qua ``CandleIngestor`` (cùng một cửa với MT5 / CSV).
"""

from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.contracts.candle import DataSource
from gold_trading.ingestion.candles import CandleIngestor, RawBar
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.ingestion.source_status import SourceCheckLog
from gold_trading.market.timeframes import Timeframe
from gold_trading.orchestrator import scanner as S
from gold_trading.orchestrator.model import Event, EventType, OrchestratorStore
from gold_trading.storage.candles import InMemoryCandleStore, SqlCandleStore
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.orchestrator import SqlOrchestratorStore
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.source_checks import SqlSourceCheckLog
from tests.test_replay import NOW, jobs_for, run_all

M15 = Timeframe.M15


@pytest.fixture(params=["memory", "sqlite"])
def env(request, tmp_path):
    if request.param == "memory":
        return InMemoryCandleStore(), PointInTimeStore(), SourceCheckLog(), OrchestratorStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 's.db'}")
    repo.create_all()
    e = repo.engine
    return (SqlCandleStore(e), SqlExternalRecordStore(e), SqlSourceCheckLog(e),
            SqlOrchestratorStore(e))


def candles(store, start, n, at, backfill=False, close=2401.0):
    bars = [RawBar(open_time=start + timedelta(minutes=15 * i), open=2400.0, high=2402.0,
                   low=2399.0, close=close, tick_volume=100) for i in range(n)]
    return CandleIngestor(store).ingest(bars, symbol="XAUUSD", timeframe=M15,
                                        source=DataSource.CSV, ingested_at=at, backfill=backfill)


def scan(env_, now, since=None):
    cs, rs, _, orch = env_
    return S.scan(orch=orch, candle_store=cs, record_store=rs, now=now, since=since)


def ids(orch, until):
    return [e.event_id for e in orch.events(until=until)]


def test_external_sources_all_types_and_idempotent(env):
    cs, rs, log, orch = env
    jobs, _ = jobs_for(rs, log)
    run_all(jobs, NOW)
    r = scan(env, NOW)
    total = len(rs.known_between(NOW - timedelta(days=3), NOW))
    assert r.new["external"] == r.seen["external"] == total > 100
    types = {e.event_type for e in orch.events(until=NOW)}
    assert types == {EventType.CALENDAR_UPDATED, EventType.ACTUAL_RELEASED,
                     EventType.MACRO_UPDATED, EventType.POSITIONING_UPDATED,
                     EventType.NEWS_PUBLISHED}
    # quét lại / quét sau → không thêm (2-C01)
    assert scan(env, NOW).new["external"] == 0
    assert scan(env, NOW + timedelta(minutes=30)).new["external"] == 0
    e = next(e for e in orch.events(until=NOW) if e.subject == "bls_values:WPSFD4:2026-10")
    assert (e.event_type, e.event_version, e.payload["series"], e.known_at) == (
        EventType.ACTUAL_RELEASED, "r0", "WPSFD4", NOW)
    assert e.payload["record_id"] == "bls_values:WPSFD4:2026-10:r0"


def test_candle_events_and_revision(env):
    cs, _, _, orch = env
    t0 = datetime(2026, 11, 13, 9, tzinfo=UTC)
    candles(cs, t0, 8, at=t0 + timedelta(hours=2, minutes=1))
    now = t0 + timedelta(hours=2, minutes=2)
    r = scan(env, now)
    assert r.new["candles"] == 8
    evs = orch.events(until=now, event_type=EventType.CANDLE_CLOSED)
    assert evs[0].subject == "CSV::XAUUSD:M15"
    assert evs[0].event_version == "2026-11-13T09:00:00+00:00:r0"
    assert evs[0].occurred_at == t0 + timedelta(minutes=15)
    # nguồn sửa nến cũ → revision 1 → sự kiện mới, sự kiện cũ giữ nguyên
    later = now + timedelta(minutes=5)
    candles(cs, t0, 1, at=later, close=2401.5)
    assert scan(env, later).new["candles"] == 1
    vers = [e.event_version for e in orch.events(until=later, event_type=EventType.CANDLE_CLOSED)
            if e.event_version.startswith("2026-11-13T09:00")]
    assert vers == ["2026-11-13T09:00:00+00:00:r0", "2026-11-13T09:00:00+00:00:r1"]


def test_future_known_not_emitted_until_due(env):
    """COT nạp sớm (công bố 15:30 ET thứ Sáu) → chỉ thành sự kiện khi tới giờ."""
    from gold_trading.ingestion.sources import cftc_cot as C
    from tests.test_cftc_cot import PAGE
    _, rs, log, orch = env
    early = datetime(2026, 11, 6, 18, tzinfo=UTC)          # trước 20:30 UTC
    C.run_once(store=rs, log=log, get=lambda: PAGE, now=early)
    assert scan(env, early).new["external"] == 0
    rel = datetime(2026, 11, 6, 20, 30, tzinfo=UTC)
    assert scan(env, rel - timedelta(seconds=1)).new["external"] == 0
    r = scan(env, rel + timedelta(seconds=30))
    assert r.new["external"] == 1
    e = orch.events(until=rel + timedelta(minutes=1))[0]
    assert e.event_type is EventType.POSITIONING_UPDATED and e.known_at == rel


def test_first_scan_lookback_then_replay_since(env):
    cs, _, _, orch = env
    t0 = datetime(2026, 11, 1, tzinfo=UTC)
    candles(cs, t0, 4, at=t0 + timedelta(hours=2))               # 12 ngày trước
    now = datetime(2026, 11, 13, tzinfo=UTC)
    candles(cs, now - timedelta(hours=2), 4, at=now)
    assert scan(env, now).new["candles"] == 4                    # lần đầu: 2 ngày gần nhất
    r = scan(env, now, since=t0)                                  # replay có mốc → đủ
    assert r.new["candles"] == 4 and len(orch.events(until=now)) == 8


def test_replay_any_chunking_same_log(env, tmp_path):
    """Gate GĐ2 (nền): quét một lần hay quét nhiều lần theo thời gian → cùng nhật ký sự kiện,
    cùng thứ tự."""
    cs, rs, log, orch = env
    jobs, _ = jobs_for(rs, log)
    t0 = datetime(2026, 11, 13, 6, tzinfo=UTC)
    for k in range(6):                                            # nến tới dần theo giờ
        candles(cs, t0 + timedelta(hours=k), 4, at=t0 + timedelta(hours=k + 1, minutes=1))
    run_all(jobs, NOW)
    # A: quét từng 7 phút từ t0
    t = t0
    while t <= NOW:
        scan(env, t, since=None if t > t0 else t0 - timedelta(hours=1))
        t += timedelta(minutes=7)
    scan(env, NOW)
    # B: một lần quét replay
    ref = OrchestratorStore()
    S.scan(orch=ref, candle_store=cs, record_store=rs, now=NOW, since=t0 - timedelta(days=3))
    assert ids(orch, NOW) == ids(ref, NOW)
    assert len(ids(ref, NOW)) > 100


def test_overlap_catches_late_commit(env):
    """Bản ghi có known_at cũ hơn mốc nhưng ghi sau (commit chậm, trong 15 phút) vẫn được bắt."""
    cs, _, _, orch = env
    t0 = datetime(2026, 11, 13, 9, tzinfo=UTC)
    candles(cs, t0, 2, at=t0 + timedelta(minutes=40))
    now = t0 + timedelta(minutes=41)
    scan(env, now)
    # nến 08:45 (đóng 09:00) biết lúc 09:30 (< mốc 09:40, trong 15 phút) nhưng ghi sau lần quét
    candles(cs, t0 - timedelta(minutes=15), 1, at=t0 + timedelta(minutes=30))
    assert scan(env, now + timedelta(minutes=1)).new["candles"] == 1


def test_event_mapping():
    m = S.external_event_type
    assert m("fed_fomc", "calendar") is EventType.CALENDAR_UPDATED
    assert m("bls_values", "macro") is EventType.ACTUAL_RELEASED
    assert m("census_marts", "macro") is EventType.ACTUAL_RELEASED
    assert m("fed_h15", "macro") is EventType.MACRO_UPDATED
    assert m("cftc_cot_gold", "positioning") is EventType.POSITIONING_UPDATED
    assert m("treasury_press", "news") is EventType.NEWS_PUBLISHED
    assert isinstance(S.record_event, object) and Event
