"""GĐ3 bước 3 — Regime bằng luật (REG-01, REG-02; 3-C01..C07). Thiết kế: docs/thiet-ke/29."""

import math
import random
from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.analysts import regime as R
from gold_trading.analysts.framework import Scope
from gold_trading.analysts.indicators import adx
from gold_trading.common.enums import SourceStatus
from gold_trading.contracts.candle import Candle, DataSource
from gold_trading.ingestion.sources import sample
from gold_trading.market.service import MarketDataService
from gold_trading.market.timeframes import Timeframe
from gold_trading.orchestrator.dispatcher import Dispatcher, routes_for
from gold_trading.orchestrator.model import OrchestratorStore
from gold_trading.orchestrator.scanner import candle_event, expired_event
from gold_trading.storage.analyst_outputs import (
    ExpiredOutput,
    InMemoryAnalystOutputStore,
    SqlAnalystOutputStore,
)
from gold_trading.storage.candles import InMemoryCandleStore
from gold_trading.storage.repository import SqlRepository

TF = Timeframe.M15
NOW = datetime(2026, 1, 30, 12, 1, tzinfo=UTC)          # thứ Sáu, thị trường mở


def times(n=R.WINDOW, end=NOW):
    ts = [b.open_time for b in sample.generate(start=end - timedelta(days=30), end=end, tf=TF,
                                                prev_close=2400.0, seed=1)]
    assert len(ts) >= n
    return ts[-n:]


def mk(t, o, h, lo, c, source=DataSource.CSV):
    return Candle(symbol="XAUUSD", timeframe=TF, source=source, open_time=t,
                  close_time=t + TF.delta, open=o, high=h, low=lo, close=c, spread_points=20,
                  ingested_at=t + TF.delta, available_at=t + TF.delta)


def series(kind="range", n=R.WINDOW, seed=3, vol_tail=0, tail_mult=4.0, source=DataSource.CSV):
    """range: nhiễu quanh mức cố định; trend: trôi đều một chiều; ``vol_tail`` nến cuối có
    biên độ × ``tail_mult``."""
    rnd = random.Random(seed)
    out, p = [], 2400.0
    for i, t in enumerate(times(n)):
        o = p
        if kind == "trend":
            p = p + 1.2 + rnd.gauss(0, 0.6)
        elif kind == "down":
            p = p - 1.2 + rnd.gauss(0, 0.6)
        else:
            p = 2400 + rnd.gauss(0, 2.0)          # nhiễu quanh một mức: không có hướng
        w = (tail_mult if i >= n - vol_tail else 1.0) * (1.5 + abs(rnd.gauss(0, 0.5)))
        out.append(mk(t, o, max(o, p) + w, min(o, p) - w, p, source))
    return out


def run(rows, expected=None, source=DataSource.CSV, feed="f1"):
    return R.analyze(rows, symbol="XAUUSD", timeframe=TF, source=source, feed=feed,
                     expected_last_close=expected or rows[-1].close_time, correlation_id="t")


# ------------------------------------------------------------------ chỉ báo ADX (tham chiếu)

def test_adx_matches_reference_library_values():
    """Giá trị tham chiếu tính bằng thư viện ``ta`` 0.11 (ADXIndicator, window=14) — khớp tới
    1e-9; soát riêng 20 chuỗi ngẫu nhiên × 600 nến: chênh lớn nhất 3,6e-14."""
    C = [2000 + 10 * math.sin(i / 5) + 0.3 * i for i in range(60)]
    H = [c + 1.5 + (i % 3) * 0.5 for i, c in enumerate(C)]
    L = [c - 1.2 - (i % 4) * 0.4 for i, c in enumerate(C)]
    a, p, m = adx(H, L, C, 14)
    ref = {27: (15.437388215920858, 14.682223260757363, 14.868407215214136),
           40: (39.57934004522368, 30.201785172335168, 5.594450557208212),
           59: (26.209062027337048, 16.572214158880488, 14.714400645101797)}
    for i, (ra, rp, rm) in ref.items():
        assert a[i] == pytest.approx(ra, abs=1e-9)
        assert p[i] == pytest.approx(rp, abs=1e-9) and m[i] == pytest.approx(rm, abs=1e-9)
    assert a[26] is None and a[27] is not None                # ADX đầu ở chỉ số 2·14 − 1


def test_adx_edge_cases():
    assert adx([1.0] * 10, [1.0] * 10, [1.0] * 10) == ([None] * 10,) * 3
    flat = adx([1.0] * 40, [1.0] * 40, [1.0] * 40)
    assert flat[0][-1] == 0.0                                  # không chia cho 0
    up = list(range(100, 160))
    a, p, m = adx([x + 1 for x in up], [x - 1 for x in up], up)
    assert a[-1] > 90 and p[-1] > m[-1]                        # đi lên đều → xu hướng rất mạnh
    with pytest.raises(ValueError):
        adx([1.0], [1.0, 2.0], [1.0])


# ------------------------------------------------------------------ phân loại

@pytest.mark.parametrize("adx_v,ratio,want", [
    (30, 1.0, ("TREND", False)), (10, 1.0, ("RANGE", False)),
    (30, 2.5, ("HIGH_VOL", False)), (10, 2.0, ("HIGH_VOL", True)),
    (23, 1.0, ("TREND", True)), (21, 1.0, ("RANGE", True)),
    (25, 1.0, ("TREND", False)), (20, 1.0, ("RANGE", False)),
    (30, 1.9, ("TREND", True)),
])
def test_classify_thresholds(adx_v, ratio, want):
    assert R.classify(adx_v, ratio) == want


def test_range_market():
    o = run(series("range"))
    assert o.source_status is SourceStatus.HEALTHY
    f = o.features
    assert f["regime"] == "RANGE" and f["direction"] is None and not f["ambiguous"]
    assert f["adx14"] < 20 and f["risk_off"] == "NOT_EVALUATED"
    assert "RISK_OFF_NOT_EVALUATED" in o.drivers
    assert o.confidence == 1.0


@pytest.mark.parametrize("kind,direction", [("trend", "UP"), ("down", "DOWN")])
def test_trend_market_with_direction(kind, direction):
    f = run(series(kind)).features
    assert f["regime"] == "TREND" and f["direction"] == direction and f["adx14"] >= 25


def test_high_vol_tail_and_transition_tracking():
    o = run(series("range", vol_tail=20))
    f = o.features
    assert f["regime"] == "HIGH_VOL" and f["vol_ratio"] >= 2
    assert "HIGH_VOLATILITY_REGIME" in o.risk_flags
    assert f["previous_regime"] == "RANGE" and 1 <= f["bars_in_regime"] <= 20
    assert f["regime_since"] is not None and not f["bars_in_regime_capped"]
    calm = run(series("range")).features
    assert calm["bars_in_regime_capped"] and calm["previous_regime"] is None


def test_ambiguous_caps_confidence():
    o = run(series("range", vol_tail=14, tail_mult=3.0))      # biến động 1,92× — sát ngưỡng 2×
    f = o.features
    assert f["regime"] == "RANGE" and 1.8 <= f["vol_ratio"] < 2.0 and f["ambiguous"]
    assert o.confidence == R.AMBIGUOUS_CONFIDENCE_CAP and "AMBIGUOUS_REGIME" in o.drivers


def test_fusion_weights_are_neutral_and_marked_uncalibrated():
    w = run(series("trend")).features["fusion_weights"]
    assert w["calibrated"] is False and w["version"] == R.WEIGHTS_VERSION
    assert set(w["weights"].values()) == {1.0}


# ------------------------------------------------------------------ đầu vào xấu (3-C01..C05)

def test_insufficient_history():
    o = run(series("range")[-500:])
    assert o.source_status is SourceStatus.INVALID
    assert o.drivers == ("INSUFFICIENT_HISTORY:candles",) and set(o.features) == {"input"}


def test_no_rows_returns_none():
    assert R.analyze([], symbol="XAUUSD", timeframe=TF, source=DataSource.CSV, feed="",
                     expected_last_close=NOW, correlation_id="t") is None


def test_stale_input():
    rows = series("range")
    o = run(rows, expected=rows[-1].close_time + TF.delta)
    assert o.source_status is SourceStatus.STALE and "STALE_INPUT:candles" in o.drivers


def test_frozen_feed_is_stale():
    rows = series("range")
    last = rows[-1]
    frozen = [mk(c.open_time, last.close, last.close, last.close, last.close) for c in rows[-12:]]
    o = run(rows[:-12] + frozen)
    assert o.source_status is SourceStatus.STALE and "FROZEN_FEED" in o.quality_flags


def test_recent_gap_low_coverage_invalid():
    rows = series("range")
    o = run(rows[:-60] + rows[-60:][::3])
    assert o.source_status is SourceStatus.INVALID and "LOW_COVERAGE:candles" in o.drivers


def test_spike_flag_caps_confidence():
    rows = series("range")
    s = rows[-200]
    rows[-200] = mk(s.open_time, s.open, s.high + 400, s.low, s.close)
    o = run(rows)
    assert "SPIKE_IN_INPUT:candles" in o.quality_flags and o.confidence <= 0.5


def test_sample_flag():
    o = run(series("range", source=DataSource.SAMPLE), source=DataSource.SAMPLE, feed="")
    assert "SAMPLE_DATA" in o.quality_flags
    assert o.output_id.startswith("regime:regime-1.0.0:SAMPLE::XAUUSD:M15:")


# ---------------------------------------------------------- 3-C06 / 3-C07 / không nhìn trước

def test_future_bars_do_not_change_past_result():
    rows = series("trend", n=R.WINDOW + 50)
    past = run(rows[:-50])
    store = InMemoryCandleStore()
    store.append(rows, [])
    m = MarketDataService(store, source=DataSource.CSV)
    again = m.candles(as_of=rows[-51].close_time, limit=R.WINDOW)
    assert run(again) == past


def test_last_bar_change_changes_id_and_version_in_id():
    rows = series("range")
    a = run(rows)
    last = rows[-1]
    rows[-1] = mk(last.open_time, last.open, last.high, last.low, last.close + 0.5)
    b = run(rows)
    assert a.output_id != b.output_id and f":{R.VERSION}:" in a.output_id


# ------------------------------------------------------------------ orchestrator

@pytest.fixture(params=["memory", "sqlite"])
def outs(request, tmp_path):
    if request.param == "memory":
        return InMemoryAnalystOutputStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'r.db'}")
    repo.create_all()
    return SqlAnalystOutputStore(repo.engine)


def test_router_regime_recompute_on_expiry():
    e = expired_event(ExpiredOutput("regime", "XAUUSD", "M15", "MT5", "f1", "id", NOW))
    assert [r.job_type for r in routes_for(e)] == ["INVALIDATE_MARKETVIEW", "REGIME"]


def test_handler_runs_per_feed_and_is_idempotent(outs):
    rows = series("trend")
    candles = InMemoryCandleStore()
    candles.append(rows, [])
    market = MarketDataService(candles, source=DataSource.CSV)
    runner = R.RegimeRunner(market, outs)
    feed = market.feed
    h = R.regime_handler(runner, lambda: [feed])
    orch = OrchestratorStore()
    ev = candle_event(rows[-1])
    orch.record_events([ev], recorded_at=rows[-1].close_time)
    d = Dispatcher(orch, {"REGIME": h})
    now = rows[-1].close_time + timedelta(seconds=5)
    d.tick(now)
    got = outs.latest_scoped("regime", Scope.of_feed("XAUUSD", TF, DataSource.CSV, feed))
    assert got is not None and got.output.features["regime"] == "TREND"
    assert runner.run_feed(feed, now) is False                 # cùng dữ liệu → không ghi lại
    assert h.run(ev, now) == "regime:unchanged"
    assert R.regime_handler(runner, lambda: []).run(ev, now) == "skipped:feed_inactive"
