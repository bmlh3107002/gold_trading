from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from gold_trading.analysts import technical
from gold_trading.analysts.indicators import atr, true_range
from gold_trading.analysts.runner import TechnicalRunner
from gold_trading.api.app import create_app
from gold_trading.contracts.candle import Candle, DataSource
from gold_trading.ingestion.sample_feed import SampleFeed
from gold_trading.ingestion.sources import sample
from gold_trading.market.quality import assess_window
from gold_trading.market.service import MarketDataService
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.analyst_outputs import InMemoryAnalystOutputStore, SqlAnalystOutputStore
from gold_trading.storage.candles import InMemoryCandleStore
from gold_trading.storage.repository import InMemoryRepository, SqlRepository

TF = Timeframe.M15
NOW = datetime(2026, 1, 16, 12, 1, tzinfo=UTC)  # thứ Sáu, thị trường mở


def mk(t, o, h, lo, c, spread=20):
    return Candle(
        symbol="XAUUSD",
        timeframe=TF,
        source=DataSource.CSV,
        open_time=t,
        close_time=t + TF.delta,
        open=o,
        high=h,
        low=lo,
        close=c,
        spread_points=spread,
        ingested_at=t + TF.delta,
        available_at=t + TF.delta,
    )


def sample_rows(days=10, end=NOW, seed=1):
    bars = list(
        sample.generate(
            start=end - timedelta(days=days), end=end, tf=TF, prev_close=2400.0, seed=seed
        )
    )
    return [mk(b.open_time, b.open, b.high, b.low, b.close, b.spread_points) for b in bars]


def run(rows, source=DataSource.CSV, expected=None):
    exp = expected or rows[-1].close_time
    return technical.analyze(
        rows,
        symbol="XAUUSD",
        timeframe=TF,
        source=source,
        expected_last_close=exp,
        correlation_id="t",
    )


# ---- ATR Wilder: giá trị tính tay ----


def test_true_range_and_atr_hand_computed():
    h = [10, 11, 12, 11, 13]
    lo = [9, 10, 10, 9, 11]
    c = [9.5, 10.5, 11.5, 10, 12.5]
    # TR: [1, max(1,1.5,0.5)=1.5, max(2,1.5,0.5)=2, max(2,0.5,2.5)=2.5, max(2,3,1)=3]
    assert true_range(h, lo, c) == [1, 1.5, 2, 2.5, 3]
    out = atr(h, lo, c, 3)
    assert out[:3] == [None, None, None]
    assert out[3] == pytest.approx((1.5 + 2 + 2.5) / 3)  # 2.0
    assert out[4] == pytest.approx((2.0 * 2 + 3) / 3)  # 2.333…


# ---- Swing không nhìn trước ----


def test_swings_need_k_closed_bars_and_do_not_change_with_future():
    rows = sample_rows(days=6)
    cut = len(rows) - 40
    past = [
        s for s in technical.find_swings(rows[:cut]) if s.confirmed_at <= rows[cut - 1].close_time
    ]
    later = [s for s in technical.find_swings(rows) if s.confirmed_at <= rows[cut - 1].close_time]
    assert past == later  # thêm nến tương lai không làm đổi swing đã xác nhận
    for s in technical.find_swings(rows):
        i = next(i for i, c in enumerate(rows) if c.open_time == s.open_time)
        assert s.confirmed_at == rows[i + technical.SWING_K].close_time


def test_output_at_as_of_independent_of_future_bars():
    rows = sample_rows(days=10)
    a = run(rows[:-20])
    b = run(rows[:-20])
    assert a == b and a.features["input"]["input_hash"] == b.features["input"]["input_hash"]
    assert a.as_of == rows[-21].close_time


def test_hash_changes_when_any_price_changes():
    rows = sample_rows(days=6)
    changed = rows[:-1] + [
        rows[-1].model_copy(
            update={
                "close": rows[-1].close + 0.01,
                "high": max(rows[-1].high, rows[-1].close + 0.01),
            }
        )
    ]
    assert technical.input_hash(rows) != technical.input_hash(changed)


# ---- Đặc trưng hợp lý ----


def test_healthy_output_has_features_and_meaning():
    out = run(sample_rows(days=10))
    assert out.source_status == "HEALTHY" and out.confidence == 1.0
    f = out.features
    assert f["trend"] in {"UP", "DOWN", "FLAT"} and 0 <= f["rsi14"] <= 100 and f["atr14"] > 0
    assert out.expires_at == out.as_of + TF.delta + timedelta(minutes=2)
    if f["nearest_support"]:
        assert f["nearest_support"]["high"] < f["close"]
    if f["nearest_resistance"]:
        assert f["nearest_resistance"]["low"] > f["close"]


def test_uptrend_detected_on_rising_series():
    t0 = datetime(2026, 1, 12, 0, 0, tzinfo=UTC)
    rows, p, t = [], 2000.0, t0
    while len(rows) < 320:
        from gold_trading.market.hours import bar_in_session

        if bar_in_session(t, t + TF.delta):
            rows.append(mk(t, p, p + 1.2, p - 0.3, p + 1.0))
            p += 1.0
        t += TF.delta
    out = run(rows)
    assert out.features["trend"] == "UP" and "TREND_UP" in out.drivers


# ---- Cổng chất lượng R2–R6 ----


def test_insufficient_history_blocks():
    out = run(sample_rows(days=2)[:100])
    assert out.source_status == "INVALID" and "INSUFFICIENT_HISTORY" in out.quality_flags
    assert out.confidence == 0.0 and "trend" not in out.features


def test_low_coverage_blocks():
    rows = sample_rows(days=10)
    holed = rows[:-60] + rows[-50:]  # thiếu 10 nến trong giờ mở cửa
    q = assess_window(holed[-300:], TF)
    assert q.coverage < 0.99 and len(q.missing) == 10
    out = run(holed)
    assert "LOW_COVERAGE" in out.quality_flags and "trend" not in out.features


def test_stale_input_blocks():
    rows = sample_rows(days=10)
    out = run(rows, expected=rows[-1].close_time + TF.delta * 3)
    assert out.source_status == "STALE" and "STALE_INPUT" in out.quality_flags


def test_frozen_feed_blocks():
    rows = sample_rows(days=10)
    last = rows[-1]
    frozen = rows[:-4] + [
        mk(rows[-4 + i].open_time, last.open, last.high, last.low, last.close) for i in range(4)
    ]
    out = run(frozen)
    assert out.source_status == "STALE" and "FROZEN_FEED" in out.quality_flags


def test_spike_halves_confidence_but_still_outputs():
    rows = sample_rows(days=10)
    s = rows[-30]
    rows[-30] = mk(s.open_time, s.open, s.high + 200, s.low, s.close)
    out = run(rows)
    assert "SPIKE_IN_WINDOW" in out.quality_flags and out.confidence == 0.5
    assert "trend" in out.features


def test_wide_spread_is_risk_flag():
    rows = sample_rows(days=10)
    s = rows[-1]
    rows[-1] = mk(s.open_time, s.open, s.high, s.low, s.close, spread=500)
    assert "WIDE_SPREAD" in run(rows).risk_flags


def test_sample_source_flagged():
    assert "SAMPLE_DATA" in run(sample_rows(days=10), source=DataSource.SAMPLE).quality_flags


# ---- Runner + lưu trữ + API ----


@pytest.fixture(params=["memory", "sqlite"])
def out_store(request, tmp_path):
    if request.param == "memory":
        return InMemoryAnalystOutputStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'a.db'}")
    repo.create_all()
    return SqlAnalystOutputStore(repo.engine)


def test_runner_is_idempotent_and_stores_latest(out_store):
    candles = InMemoryCandleStore()
    feed = SampleFeed(candles, history_days=10)
    feed.tick(NOW)
    market = MarketDataService(candles, source=DataSource.SAMPLE)
    runner = TechnicalRunner(market, out_store)
    assert runner.tick(NOW) is True
    assert runner.tick(NOW) is False  # cùng đầu vào: không ghi lại
    later = NOW + TF.delta
    feed.tick(later)
    assert runner.tick(later) is True
    got = out_store.latest("technical", symbol="XAUUSD", tf=TF, source=DataSource.SAMPLE)
    assert got.output.as_of == TF.floor(later)
    assert got.output.source_status == "HEALTHY"


def test_api_technical_latest():
    candles = InMemoryCandleStore()
    SampleFeed(candles, history_days=10).tick()
    store = InMemoryAnalystOutputStore()
    app = create_app(
        InMemoryRepository(),
        candle_store=candles,
        analyst_store=store,
        data_source=DataSource.SAMPLE,
        run_sample_feed=False,
        run_analysts=False,
    )
    c = TestClient(app)
    assert c.get("/api/analysts/technical/latest").json()["output"] is None
    TechnicalRunner(MarketDataService(candles, source=DataSource.SAMPLE), store).tick()
    body = c.get("/api/analysts/technical/latest").json()
    assert body["is_sample"] is True and body["confidence_meaning"] == "DATA_QUALITY_ONLY"
    assert "SAMPLE_DATA" in body["output"]["quality_flags"]
