"""GĐ2 bước 4b — làn nhanh: chặn theo số liệu HIGH + thông cáo Fed ngoài lịch (FAST-01..03).

Lịch thật Fed / BEA / BLS / DOL (``tests/fixtures``, nạp qua bộ nạp thật). Case: cửa sổ lịch,
15 phút từ lúc nhận số HIGH, số không khớp lịch → HIGH, mức thấp chỉ gắn cờ, thông cáo Fed trên /
ngoài lịch, tin khác chỉ gắn cờ, tin cũ, bài sửa, hai công bố cùng phút gộp một cửa sổ (2-C08),
sự kiện lúc thị trường đóng (2-C07), lỗi đọc lịch → mặc định chặn, idempotent / replay,
point-in-time.
"""

from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.common.enums import SourceStatus
from gold_trading.contracts.records import NormalizedRecord
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.ingestion.source_status import SourceCheckLog
from gold_trading.ingestion.sources import bea as B
from gold_trading.ingestion.sources import bls as L
from gold_trading.ingestion.sources import dol as D
from gold_trading.ingestion.sources import fed_fomc as F
from gold_trading.market.hours import REFERENCE
from gold_trading.orchestrator.dispatcher import Dispatcher
from gold_trading.orchestrator.model import Event, EventType, JobState, OrchestratorStore
from gold_trading.orchestrator.scanner import record_event
from gold_trading.risk import fast_lane as FL
from gold_trading.risk.blocks import ALL, Block, BlockKind, BlockStore
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.orchestrator import SqlOrchestratorStore
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.risk_blocks import SqlBlockStore

from .test_economic_calendar import BEA, FED, NOW

M = timedelta(minutes=1)
S = timedelta(seconds=1)
CPI_AT = datetime(2026, 12, 10, 13, 30, tzinfo=UTC)       # CPI + trợ cấp thất nghiệp cùng 8:30 ET
FOMC_AT = datetime(2026, 12, 9, 19, 0, tzinfo=UTC)        # tuyên bố; họp báo 19:30


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def load_calendars(st):
    log = SourceCheckLog()
    F.run_once(store=st, log=log, get=lambda p: FED[p], now=NOW)
    B.run_schedule_once(store=st, log=log, get=lambda u, p=None: BEA[u], now=NOW)
    D.run_schedule_once(store=st, log=log, now=NOW)
    L.run_schedule_once(store=st, log=log, now=NOW)
    return st


@pytest.fixture(params=["memory", "sqlite"])
def env(request, tmp_path):
    if request.param == "memory":
        return load_calendars(PointInTimeStore()), BlockStore(), OrchestratorStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'f.db'}")
    repo.create_all()
    return (load_calendars(SqlExternalRecordStore(repo.engine)), SqlBlockStore(repo.engine),
            SqlOrchestratorStore(repo.engine))


def value(series, ref, known, *, source="bls_values", rev=0, release_at=CPI_AT, key=None):
    return NormalizedRecord(
        record_id=f"{source}:{key or series}:r{rev}", source=source, kind="macro",
        logical_key=key or f"{series}:2026-11", revision=rev, event_time=utc(2026, 10, 31),
        ingested_at=known, available_at=release_at if ref else None,
        source_status=SourceStatus.HEALTHY, payload_version="t", raw_ref="t",
        payload={"series": series, "value": "1.0", "release_ref": ref})


def dol_value(known, week="2026-12-05"):
    return NormalizedRecord(
        record_id=f"dol_claims:ICSA:{week}:r0", source="dol_claims", kind="macro",
        logical_key=f"ICSA:{week}", revision=0,
        event_time=datetime.fromisoformat(week + "T00:00+00:00"),
        ingested_at=known, available_at=CPI_AT, source_status=SourceStatus.HEALTHY,
        payload_version="t", raw_ref="t",
        payload={"series": "ICSA", "week_ending": week, "value": "220000"})


def news(key, published, seen, *, source="fed_rss_monetary", rev=0):
    return NormalizedRecord(
        record_id=f"{source}:{key}:r{rev}", source=source, kind="news", logical_key=key,
        revision=rev, event_time=published, ingested_at=seen,
        source_status=SourceStatus.HEALTHY, payload_version="t", raw_ref="t",
        payload={"title": "x", "first_seen_at": seen.isoformat()})


def active_codes(blocks, at):
    return sorted(b.reason_code for b in blocks if b.start_at <= at
                  and (b.end_at is None or at < b.end_at) and b.created_at <= at)


# ================================================================ giờ giữ chặn (2-C07)

def test_hold_end_open_market_is_plain_15_minutes():
    t = utc(2026, 12, 10, 13, 31, 20)
    assert FL.hold_end(t, FL.RELEASE_HOLD, REFERENCE) == t + 15 * M
    assert FL.hold_end(t, FL.RELEASE_HOLD, None) == t + 15 * M


def test_hold_end_weekend_starts_counting_at_open():
    # Thứ Bảy → thị trường mở 18:00 ET Chủ nhật (23:00 UTC, giờ mùa đông) → hết 23:15.
    sat = utc(2026, 12, 12, 15, 0)
    assert FL.hold_end(sat, FL.NEWS_HOLD, REFERENCE) == utc(2026, 12, 13, 23, 15)


def test_hold_end_spans_daily_break():
    # 16:55 ET → 5 phút trước giờ nghỉ 17:00–18:00, 10 phút sau khi mở lại → 18:10 ET.
    t = utc(2026, 12, 8, 21, 55)
    assert FL.hold_end(t, FL.RELEASE_HOLD, REFERENCE) == utc(2026, 12, 8, 23, 10)


def test_hold_end_long_closure_is_capped_safely():
    class Closed:
        def is_open(self, _t):
            return False

    t = utc(2026, 12, 25, 12)
    assert FL.hold_end(t, FL.RELEASE_HOLD, Closed()) == t + FL.MAX_CLOSED_SEARCH


# ================================================================ gộp cửa sổ (2-C08)

def blk(start, end, code="X", cause=None):
    return Block(BlockKind.RELEASE, ALL, code, start, end, cause or f"{code}:{start}",
                 start - M, "t")


def test_merge_same_minute_releases_one_window():
    w = FL.merge_windows([blk(CPI_AT - 15 * M, CPI_AT + 15 * M, "CALENDAR_HIGH"),
                          blk(CPI_AT - 5 * M, CPI_AT + 10 * M, "CALENDAR_MEDIUM"),
                          blk(CPI_AT + 80 * S, CPI_AT + 80 * S + 15 * M,
                              "RELEASE_HIGH_RECEIVED")])
    assert len(w) == 1
    assert (w[0].start_at, w[0].end_at) == (CPI_AT - 15 * M, CPI_AT + 80 * S + 15 * M)
    assert w[0].reason_codes == ("CALENDAR_HIGH", "CALENDAR_MEDIUM", "RELEASE_HIGH_RECEIVED")


def test_merge_touching_disjoint_and_open_ended():
    a, b = blk(utc(2026, 1, 1, 10), utc(2026, 1, 1, 10, 15)), blk(utc(2026, 1, 1, 10, 15),
                                                                  utc(2026, 1, 1, 10, 30))
    c = blk(utc(2026, 1, 1, 12), utc(2026, 1, 1, 12, 5))
    w = FL.merge_windows([c, b, a])
    assert [(x.start_at, x.end_at) for x in w] == [
        (utc(2026, 1, 1, 10), utc(2026, 1, 1, 10, 30)), (c.start_at, c.end_at)]
    open_ = blk(utc(2026, 1, 1, 10, 5), None, "SPREAD")
    w = FL.merge_windows([a, open_, c])
    assert len(w) == 1 and w[0].end_at is None
    assert FL.merge_windows([]) == []


def test_dedupe_prefers_first_same_cause():
    a = blk(CPI_AT, CPI_AT + 15 * M, "RELEASE_HIGH_RECEIVED", cause="release:bls:CPI")
    b = Block(a.kind, a.scope, a.reason_code, a.start_at, a.end_at, a.cause_ref,
              a.created_at + M, "other")
    assert FL.dedupe([a, b]) == [a]


# ================================================================ cửa sổ lịch (tính khi đọc)

def test_calendar_cpi_and_claims_same_minute(env):
    st, _, _ = env
    cb = FL.CalendarBlocks(st, None, REFERENCE)
    assert active_codes(cb.active(CPI_AT - 16 * M), CPI_AT - 16 * M) == []
    at = CPI_AT - 10 * M
    assert active_codes(cb.active(at), at) == ["CALENDAR_HIGH"]
    at = CPI_AT - M
    assert active_codes(cb.active(at), at) == ["CALENDAR_HIGH", "CALENDAR_MEDIUM"]
    w = FL.merge_windows(cb.active(at))
    assert len(w) == 1 and (w[0].start_at, w[0].end_at) == (CPI_AT - 15 * M, CPI_AT + 15 * M)


def test_received_high_adds_15_minutes_from_receipt(env):
    st, _, _ = env
    got = CPI_AT + 80 * S
    st.append(value("CUUR0000SA0", "CPI:2026-11", got))
    st.append(dol_value(CPI_AT + 50 * S))
    cb = FL.CalendarBlocks(st, None, REFERENCE, ttl=timedelta(0))
    # Trước lúc biết số: không có lệnh cấm "đã nhận" (point-in-time).
    assert "RELEASE_HIGH_RECEIVED" not in active_codes(cb.active(got - S), got - S)
    at = CPI_AT + 15 * M + S                          # hết cửa sổ lịch ±15
    assert active_codes(cb.active(at), at) == ["RELEASE_HIGH_RECEIVED"]
    at = got + 15 * M - S
    assert active_codes(cb.active(at), at) == ["RELEASE_HIGH_RECEIVED"]
    assert cb.active(got + 15 * M) == []
    w = FL.merge_windows(cb.active(CPI_AT + 2 * M))
    assert len(w) == 1 and (w[0].start_at, w[0].end_at) == (CPI_AT - 15 * M, got + 15 * M)


def test_medium_release_only_calendar_window(env):
    st, _, _ = env
    ppi = utc(2026, 11, 13, 13, 30)
    st.append(value("WPSFD4", "PPI:2026-10", ppi + M, release_at=ppi, key="WPSFD4:2026-10"))
    cb = FL.CalendarBlocks(st, None, REFERENCE, ttl=timedelta(0))

    def ppi_codes(at):
        return active_codes([b for b in cb.active(at) if "PPI" in b.cause_ref], at)

    assert ppi_codes(ppi + 2 * M) == ["CALENDAR_MEDIUM"]       # mức trung bình: không +15 phút
    assert ppi_codes(ppi + 10 * M) == []


def test_fomc_statement_and_press_conference_adjacent_merge(env):
    st, _, _ = env
    cb = FL.CalendarBlocks(st, None, REFERENCE)
    w = FL.merge_windows(cb.active(FOMC_AT + 14 * M) + cb.active(FOMC_AT + 16 * M))
    assert len(w) == 1 and (w[0].start_at, w[0].end_at) == (FOMC_AT - 15 * M, FOMC_AT + 45 * M)


def test_calendar_cache_and_error_propagates():
    calls = []

    class Store:
        def as_of(self, *a, **k):
            calls.append(1)
            return []

    cb = FL.CalendarBlocks(Store(), None, REFERENCE)
    cb.active(CPI_AT)
    n = len(calls)
    cb.active(CPI_AT + 2 * S)
    assert len(calls) == n                     # trong TTL: không đọc lại
    cb.active(CPI_AT + 6 * S)
    assert len(calls) > n

    class Broken:
        def as_of(self, *a, **k):
            raise RuntimeError("db down")

    with pytest.raises(RuntimeError):
        FL.CalendarBlocks(Broken(), None, REFERENCE).active(CPI_AT)


# ================================================================ quyết định cho sự kiện

def ev_of(r):
    return record_event(r)


def test_release_high_block_from_receipt_with_latency(env):
    st, _, _ = env
    got = CPI_AT + 80 * S
    r = value("CUUR0000SA0", "CPI:2026-11", got)
    st.append(r)
    d = FL.decide_release(ev_of(r), st, got + 3 * S, REFERENCE)
    (b,) = d.blocks
    assert (b.kind, b.reason_code, b.start_at, b.end_at) == (
        BlockKind.RELEASE, "RELEASE_HIGH_RECEIVED", got, got + 15 * M)
    assert b.cause_ref == "release:bls_schedule:CPI:2026-11" and b.latency_ms == 3000
    assert b.created_at == got + 3 * S
    # Cùng khóa với lệnh cấm tính từ lịch → gộp, không đếm hai lần.
    cal = [x for x in FL.CalendarBlocks(st, None, REFERENCE).active(got + M)
           if x.reason_code == "RELEASE_HIGH_RECEIVED"]
    assert [x.block_id for x in cal] == [b.block_id]


def test_release_second_series_same_release_same_block(env):
    st, _, _ = env
    got = CPI_AT + 80 * S
    a, b = (value("CUUR0000SA0", "CPI:2026-11", got),
            value("CUUR0000SA0L1E", "CPI:2026-11", got + 40 * S))
    st.append(a)
    st.append(b)
    da = FL.decide_release(ev_of(a), st, got + S, REFERENCE)
    db = FL.decide_release(ev_of(b), st, got + 41 * S, REFERENCE)
    assert da.blocks[0].block_id == db.blocks[0].block_id
    assert db.blocks[0].start_at == got                  # tính từ số đầu tiên


def test_release_medium_only_flag(env):
    st, _, _ = env
    ppi = utc(2026, 11, 13, 13, 30)
    r = value("WPSFD4", "PPI:2026-10", ppi + M, release_at=ppi, key="WPSFD4:2026-10")
    st.append(r)
    d = FL.decide_release(ev_of(r), st, ppi + M, REFERENCE)
    assert d.blocks == () and d.flag == "RELEASE_MEDIUM"


def test_release_unmatched_counts_as_high(env):
    st, _, _ = env
    t = utc(2026, 12, 1, 15, 2, 10)
    r = value("CUUR0000SA0", None, t)
    st.append(r)
    (b,) = FL.decide_release(ev_of(r), st, t, REFERENCE).blocks
    assert b.reason_code == "RELEASE_UNMATCHED" and b.end_at == t + 15 * M
    # release_ref trỏ tới lần công bố không có trên lịch → cũng HIGH
    r2 = value("X", "CPI:2099-01", t, key="X:1")
    st.append(r2)
    assert FL.decide_release(ev_of(r2), st, t, REFERENCE).blocks[0].reason_code == \
        "RELEASE_UNMATCHED"
    # Nạp bù nhiều số cùng phút → cùng một lệnh cấm
    r3 = value("Y", None, t + 20 * S, key="Y:1")
    assert FL.decide_release(ev_of(r3), st, t + 20 * S, REFERENCE).blocks[0].block_id == \
        b.block_id


def test_release_dol_unlinked_is_medium_flag(env):
    st, _, _ = env
    r = dol_value(CPI_AT + M)
    assert FL.decide_release(ev_of(r), st, CPI_AT + M, REFERENCE).flag == "RELEASE_MEDIUM"


def test_fed_statement_on_calendar_is_release_block(env):
    st, _, _ = env
    seen = FOMC_AT + 7 * M                     # RSS 15 phút / lần → biết trễ vài phút
    r = news("n:stmt", FOMC_AT, seen)
    (b,) = FL.decide_news(ev_of(r), st, seen + 2 * S, REFERENCE).blocks
    assert (b.kind, b.reason_code, b.start_at, b.end_at) == (
        BlockKind.RELEASE, "FOMC_RECEIVED", seen, seen + 15 * M)


def test_fed_unscheduled_policy_blocks_15_minutes(env):
    st, _, _ = env
    pub = utc(2026, 12, 2, 16, 0)                 # thứ Tư, không có FOMC trên lịch
    r = news("n:emergency", pub, pub + 9 * M)
    (b,) = FL.decide_news(ev_of(r), st, pub + 9 * M, REFERENCE).blocks
    assert (b.kind, b.reason_code, b.end_at) == (
        BlockKind.NEWS, "FED_UNSCHEDULED_POLICY", pub + 24 * M)


def test_fed_minutes_on_calendar_only_flag(env):
    st, _, _ = env
    at = utc(2026, 11, 18, 19, 0)
    d = FL.decide_news(ev_of(news("n:min", at, at + 4 * M)), st, at + 4 * M, REFERENCE)
    assert d.blocks == () and d.flag == "FED_POLICY_SCHEDULED_MEDIUM"
    # Cùng ngày biên bản nhưng cách giờ trên lịch > 60 phút → ngoài lịch → chặn.
    far = at - 4 * timedelta(hours=1)
    d = FL.decide_news(ev_of(news("n:other", far, far + M)), st, far + M, REFERENCE)
    assert d.blocks[0].reason_code == "FED_UNSCHEDULED_POLICY"


def test_fed_unscheduled_on_weekend_applies_after_open(env):
    """2-C07: thông cáo thứ Bảy → vẫn xử lý; lệnh cấm còn 15 phút đầu khi mở cửa Chủ nhật."""
    st, _, _ = env
    pub = utc(2026, 12, 12, 15, 0)
    (b,) = FL.decide_news(ev_of(news("n:sat", pub, pub + 5 * M)), st, pub + 5 * M,
                          REFERENCE).blocks
    assert b.end_at == utc(2026, 12, 13, 23, 15)


@pytest.mark.parametrize("source,flag", [("fed_rss_speeches", "NEWS_FED_RSS_SPEECHES"),
                                         ("treasury_press", "NEWS_TREASURY_PRESS")])
def test_other_news_only_flag(env, source, flag):
    st, _, _ = env
    pub = utc(2026, 12, 2, 16, 0)
    d = FL.decide_news(ev_of(news("n:s", pub, pub + M, source=source)), st, pub + M, REFERENCE)
    assert d.blocks == () and d.flag == flag


def test_old_or_revised_fed_item_only_flag(env):
    st, _, _ = env
    pub = utc(2026, 11, 1, 16, 0)
    d = FL.decide_news(ev_of(news("n:old", pub, pub + 40 * timedelta(hours=1))), st,
                       pub + 40 * timedelta(hours=1), REFERENCE)
    assert d.flag == "FED_POLICY_OLD_ITEM" and d.blocks == ()
    d = FL.decide_news(ev_of(news("n:rev", pub, pub + M, rev=1)), st, pub + M, REFERENCE)
    assert d.flag == "NEWS_REVISION"


# ================================================================ bộ xử lý + bộ điều phối

def test_handler_via_dispatcher_idempotent_and_replay(env):
    st, blocks, orch = env
    got = CPI_AT + 80 * S
    r = value("CUUR0000SA0", "CPI:2026-11", got)
    st.append(r)
    pub = utc(2026, 12, 10, 15, 0)
    n = news("n:unsched", pub, pub + 2 * M)
    st.append(n)
    sp = news("n:speech", pub, pub + 2 * M, source="fed_rss_speeches")
    st.append(sp)
    now = [pub + 2 * M + 3 * S]
    h = FL.fast_lane_handler(blocks, st, REFERENCE, clock=lambda: now[0])
    orch.record_events(sorted([ev_of(r), ev_of(n), ev_of(sp)], key=Event.order_key),
                       recorded_at=now[0])
    d = Dispatcher(orch, {"FAST_LANE": h})
    d.tick(now[0], since=CPI_AT - timedelta(days=1))
    jobs = [j for j in orch.jobs_created_since(CPI_AT - timedelta(days=1))
            if j.job_type == "FAST_LANE"]
    assert len(jobs) == 3
    refs = {j.event_id: orch.latest(j.job_key) for j in jobs}
    assert all(a.state is JobState.SUCCEEDED for a in refs.values())
    assert refs[ev_of(sp).event_id].output_ref == "flag:NEWS_FED_RSS_SPEECHES"
    assert refs[ev_of(r).event_id].output_ref.startswith("block:")
    act = blocks.active(pub + 3 * M)
    assert [b.reason_code for b in act] == ["FED_UNSCHEDULED_POLICY"]
    # Replay: bộ điều phối mới, quét lại → không job mới, không lệnh cấm mới.
    before = len(blocks.active(got + M)) + len(act)
    d2 = Dispatcher(orch, {"FAST_LANE": h})
    res = d2.tick(now[0] + M, since=CPI_AT - timedelta(days=1))
    assert res.created == 0
    assert len(blocks.active(got + M)) + len(blocks.active(pub + 3 * M)) == before
    # Chạy thẳng lần nữa → add trả False (cùng nguyên nhân)
    h.run(ev_of(n), now[0])
    assert len(blocks.active(pub + 3 * M)) == 1


def test_handler_error_blocks_by_default_then_raises():
    class Broken:
        def as_of(self, *a, **k):
            raise RuntimeError("db down")

    bs = BlockStore()
    t = utc(2026, 12, 2, 16, 0)
    h = FL.fast_lane_handler(bs, Broken(), REFERENCE, clock=lambda: t + 2 * S)
    e = ev_of(news("n:x", t, t))
    with pytest.raises(RuntimeError):
        h.run(e, t)
    (b,) = bs.active(t + M)
    assert b.reason_code == "FAST_LANE_ERROR" and b.end_at == t + 15 * M
    # tin không phải chính sách tiền tệ: không đọc lịch → không lỗi, chỉ cờ
    assert h.run(ev_of(news("n:y", t, t, source="treasury_press")), t) == \
        "flag:NEWS_TREASURY_PRESS"
    # sự kiện sai loại → lỗi không thử lại
    bad = Event(EventType.CANDLE_CLOSED, "MT5:f:XAUUSD:M15", "v", occurred_at=t, known_at=t)
    with pytest.raises(FL.NotFastLaneEvent):
        h.run(bad, t)
    assert issubclass(FL.NotFastLaneEvent, h.fatal)


def test_block_written_late_only_effective_from_write_time():
    """Point-in-time: lệnh cấm ghi lúc làn nhanh chạy — trước đó Safety chưa biết."""
    bs = BlockStore()
    t = utc(2026, 12, 2, 16, 0)
    h = FL.fast_lane_handler(bs, load_calendars(PointInTimeStore()), REFERENCE,
                             clock=lambda: t + 8 * S)
    h.run(ev_of(news("n:z", t, t)), t + 8 * S)
    assert bs.active(t + 7 * S) == [] and len(bs.active(t + 8 * S)) == 1
    assert bs.active(t + 8 * S)[0].latency_ms == 8000


# ================================================================ Safety qua API tài khoản

def test_api_calendar_window_blocks_and_merged_windows():
    """Cửa sổ lịch + lệnh cấm đã lưu cùng lúc → không mở lệnh mới; API trả một cửa sổ gộp."""
    from gold_trading.common.time import utcnow
    from tests.test_risk_blocks import _active_client

    c = _active_client()
    now = utcnow()

    class FakeCal:
        def active(self, at):
            return [Block(BlockKind.RELEASE, ALL, "CALENDAR_HIGH", now - 5 * M, now + 25 * M,
                          "cal:bls_schedule:CPI:x", now - 5 * M, FL.POLICY_VERSION)]

    c.app.state.fast_lane["calendar"] = FakeCal()
    c.app.state.block_store.add(Block(BlockKind.RELEASE, ALL, "RELEASE_HIGH_RECEIVED", now - M,
                                      now + 14 * M, "release:bls_schedule:CPI:x", now - M,
                                      FL.POLICY_VERSION))
    body = c.get("/api/accounts/default/status").json()
    assert body["allows_new_orders"] is False and body["safety_state"] == "ACTIVE"
    assert sorted(b["reason_code"] for b in body["entry_blocks"]) == [
        "CALENDAR_HIGH", "RELEASE_HIGH_RECEIVED"]
    (w,) = body["entry_block_windows"]
    assert w["reason_codes"] == ["CALENDAR_HIGH", "RELEASE_HIGH_RECEIVED"]
    assert datetime.fromisoformat(w["end_at"].replace("Z", "+00:00")) == now + 25 * M


def test_api_calendar_read_error_blocks():
    from tests.test_risk_blocks import _active_client

    c = _active_client()

    class Broken:
        def active(self, at):
            raise RuntimeError("db down")

    c.app.state.fast_lane["calendar"] = Broken()
    body = c.get("/api/accounts/default/status").json()
    assert body["allows_new_orders"] is False and body["entry_block_windows"] == []
    c.app.state.fast_lane["calendar"] = None
    assert c.get("/api/accounts/default/status").json()["allows_new_orders"] is True
