"""Gate GĐ2 — chạy lại nhật ký sự kiện từ dữ liệu đã lưu cho kết quả giống hệt (replay).

"Chạy thật" giả lập: nến dữ liệu mẫu tới dần, số liệu CPI + DOL + thông cáo Fed ngoài lịch tới
giữa chừng, nhịp bộ điều phối **không đều** (2–9 giây), có một lần backend **tắt 40 phút**, job
Technical + FAST_LANE chạy thật. Rồi chạy lại (chỉ đọc) → sự kiện, kết quả làn nhanh, lệnh cấm,
kết quả phân tích kỹ thuật trùng hết; không job nào thành công hai lần. Sửa lén nhật ký / lệnh
cấm / kết quả → công cụ phát hiện.
"""

import random
from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.analysts.runner import TechnicalRunner
from gold_trading.contracts.candle import DataSource
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.ingestion.sample_feed import SampleFeed
from gold_trading.market.hours import REFERENCE
from gold_trading.market.service import MarketDataService
from gold_trading.orchestrator import replay as RP
from gold_trading.orchestrator import runner as R
from gold_trading.orchestrator.model import Event, EventType, OrchestratorStore
from gold_trading.risk import fast_lane as FL
from gold_trading.risk.blocks import ALL, Block, BlockKind, BlockStore
from gold_trading.storage.analyst_outputs import InMemoryAnalystOutputStore, SqlAnalystOutputStore
from gold_trading.storage.candles import InMemoryCandleStore, SqlCandleStore
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.orchestrator import SqlOrchestratorStore
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.risk_blocks import SqlBlockStore

from .test_fast_lane import CPI_AT, dol_value, load_calendars, news, value

S = timedelta(seconds=1)
M = timedelta(minutes=1)
START = CPI_AT - 50 * M          # thứ Năm 10/12, 12:40 UTC — thị trường mở


@pytest.fixture(params=["memory", "sqlite"])
def stores(request, tmp_path):
    if request.param == "memory":
        return (InMemoryCandleStore(), InMemoryAnalystOutputStore(),
                load_calendars(PointInTimeStore()), OrchestratorStore(), BlockStore())
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'rp.db'}")
    repo.create_all()
    e = repo.engine
    return (SqlCandleStore(e), SqlAnalystOutputStore(e),
            load_calendars(SqlExternalRecordStore(e)), SqlOrchestratorStore(e), SqlBlockStore(e))


def _append_once(rs, items, t, done):
    for at, r in items:
        if at <= t and r.record_id not in done:
            rs.append(r)
            done.add(r.record_id)


def live_run_clean(stores, seed=1):
    cs, ast, rs, orch, bs = stores
    market = MarketDataService(cs, source=DataSource.SAMPLE, calendar=REFERENCE)
    tech = TechnicalRunner(market, ast)
    feed = SampleFeed(cs, history_days=3)
    clock = {"t": START}
    handlers = {"TECHNICAL": R.technical_handler(tech, lambda: [""]),
                "FAST_LANE": FL.fast_lane_handler(bs, rs, REFERENCE, clock=lambda: clock["t"])}
    arrivals = [
        (CPI_AT + 50 * S, dol_value(CPI_AT + 50 * S)),
        (CPI_AT + 80 * S, value("CUUR0000SA0", "CPI:2026-11", CPI_AT + 80 * S)),
        (CPI_AT + 95 * S, value("CUUR0000SA0L1E", "CPI:2026-11", CPI_AT + 95 * S)),
        (CPI_AT + 30 * M, news("n:emerg", CPI_AT + 22 * M, CPI_AT + 30 * M)),
        (CPI_AT + 31 * M, news("n:speech", CPI_AT + 25 * M, CPI_AT + 31 * M,
                               source="fed_rss_speeches")),
    ]
    done: set[str] = set()
    rng = random.Random(seed)
    runner = R.OrchestratorRunner(orch=orch, candle_store=cs, record_store=rs,
                                  analyst_store=ast, handlers=handlers)
    t, end = START, START + 100 * M
    down = (START + 35 * M, START + 75 * M)
    restarted = False
    while t < end:
        clock["t"] = t
        feed.tick(t)
        _append_once(rs, arrivals, t, done)
        if down[0] <= t < down[1]:
            pass                                      # backend tắt: không quét, không chạy job
        else:
            if t >= down[1] and not restarted:
                runner = R.OrchestratorRunner(orch=orch, candle_store=cs, record_store=rs,
                                              analyst_store=ast, handlers=handlers)
                restarted = True
            runner.tick(t)
        t += rng.randint(2, 9) * S
    return market, rs, t


def do_replay(stores, market, now, **kw):
    cs, ast, rs, orch, bs = stores
    return RP.run(live=orch, live_blocks=bs, candle_store=cs, record_store=rs,
                  analyst_store=ast, market=market,
                  handler_factory=lambda b: FL.fast_lane_handler(b, rs, REFERENCE),
                  now=now + RP.SETTLE, **kw)


def test_replay_identical_after_irregular_ticks_and_restart(stores):
    market, rs, now = live_run_clean(stores)
    rep = do_replay(stores, market, now)
    txt = RP.report_text(rep)
    assert rep.ok, txt
    assert rep.live_events["CANDLE_CLOSED"] > 0 and rep.live_events["ACTUAL_RELEASED"] == 3
    assert rep.live_events["NEWS_PUBLISHED"] == 2
    assert rep.fast_lane_compared == 5 and rep.blocks_compared >= 2
    assert rep.technical_compared >= 5
    assert "KẾT LUẬN: ĐẠT" in txt
    # bước quét khác (1 phút / 15 phút) → vẫn cùng kết quả
    for step in (M, 15 * M):
        assert do_replay(stores, market, now, step=step).ok


def test_replay_detects_tampering(stores):
    cs, ast, rs, orch, bs = stores
    market, rs, now = live_run_clean(stores, seed=2)
    # 1) sự kiện giả trong nhật ký (không suy ra được từ dữ liệu)
    orch.record_event(Event(EventType.NEWS_PUBLISHED, "fake:x", "r0", occurred_at=now - M,
                            known_at=now - M, payload={"source": "fake"}), recorded_at=now)
    # 2) lệnh cấm sai giờ hết (như do code cũ / lỗi tính)
    bs.add(Block(BlockKind.RELEASE, ALL, "RELEASE_HIGH_RECEIVED", CPI_AT + 80 * S,
                 CPI_AT + 80 * S + 5 * M, "release:bls_schedule:CPI:2026-11:x", CPI_AT + 2 * M,
                 FL.POLICY_VERSION))
    rep = do_replay(stores, market, now, technical_check=False)
    assert not rep.ok
    assert [e.subject for e in rep.only_live] == ["fake:x"]
    assert len(rep.blocks_diff) == 1 and rep.blocks_diff[0][1] is None
    assert "KHÔNG ĐẠT" in RP.report_text(rep)


def test_replay_detects_missing_event_and_wrong_technical():
    stores = (InMemoryCandleStore(), InMemoryAnalystOutputStore(),
              load_calendars(PointInTimeStore()), OrchestratorStore(), BlockStore())
    market, rs, now = live_run_clean(stores, seed=3)
    cs, ast, rs, orch, bs = stores
    # Sự kiện có trong dữ liệu nhưng nhật ký thật thiếu → "chỉ có khi chạy lại"
    rs.append(news("n:late", now - 3 * M, now - 2 * M))
    rep = do_replay(stores, market, now, technical_check=False)
    assert [e.subject for e in rep.only_replay] == ["fed_rss_monetary:n:late"]
    # Kết quả kỹ thuật thật khác kết quả tính lại → phát hiện
    first = ast.computed_between(START - M, now)[0]
    orig = ast.computed_between
    ast.computed_between = lambda lo, hi: [(*first[:5], first[5][:-4] + "beef", first[6])] \
        + orig(lo, hi)[1:]
    rep = do_replay(stores, market, now)
    assert len(rep.technical_diff) == 1


def test_no_double_success_detected():
    orch = OrchestratorStore()
    from gold_trading.orchestrator.model import Attempt, Job, JobState, job_key_for
    t = datetime(2026, 12, 10, tzinfo=UTC)
    e = Event(EventType.NEWS_PUBLISHED, "x", "r0", occurred_at=t, known_at=t)
    orch.record_event(e, recorded_at=t)
    j = Job(job_key_for(e, "FAST_LANE", "v"), e.event_id, "FAST_LANE", "v", e.event_id, t)
    orch.create_job(j)
    orch.append_attempt(Attempt(j.job_key, JobState.SUCCEEDED, 1, t))
    assert orch.multi_success_jobs() == []
    orch.append_attempt(Attempt(j.job_key, JobState.SUCCEEDED, 2, t + S))
    assert orch.multi_success_jobs() == [j.job_key]


def test_empty_log_returns_none():
    assert RP.run(live=OrchestratorStore(), live_blocks=BlockStore(), candle_store=None,
                  record_store=None, analyst_store=None, market=None,
                  handler_factory=lambda b: None, now=START) is None
