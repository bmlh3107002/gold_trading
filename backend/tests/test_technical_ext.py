"""GĐ3 bước 7a — Technical 1.4.0: vol_forecast EWMA (TEC-07) + bối cảnh H1/H4/D1 (TEC-09)."""

import math
from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.analysts import technical
from gold_trading.analysts import technical_ext as X
from gold_trading.analysts.runner import TechnicalRunner
from gold_trading.contracts.candle import Candle, DataSource
from gold_trading.market.hours import REFERENCE
from gold_trading.market.service import MarketDataService
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.analyst_outputs import InMemoryAnalystOutputStore
from gold_trading.storage.candles import InMemoryCandleStore

from .test_technical import NOW, sample_rows

H = timedelta(hours=1)


def bars(tf: Timeframe, end: datetime, n: int, *, step=1.0, start=2400.0, known_lag=None):
    """``n`` nến ``tf`` đóng trước ``end`` (chỉ giờ thị trường mở), giá đi đều ``step``."""
    secs = int(tf.delta.total_seconds())
    end = datetime.fromtimestamp(int(end.timestamp()) // secs * secs, UTC)   # căn mốc khung
    out, t = [], end - tf.delta
    while len(out) < n:
        if REFERENCE.is_open(t) and REFERENCE.is_open(t + tf.delta - timedelta(minutes=1)):
            out.append(t)
        t -= tf.delta
    out.reverse()
    rows = []
    for i, ot in enumerate(out):
        c = start + step * i
        known = ot + tf.delta + (known_lag or timedelta(0))
        rows.append(Candle(symbol="XAUUSD", timeframe=tf, source=DataSource.CSV, open_time=ot,
                           close_time=ot + tf.delta, open=c - step,
                           high=max(c, c - step) + 1, low=min(c, c - step) - 1,
                           close=c, ingested_at=known, available_at=known))
    return rows


# ------------------------------------------------------------------ TEC-07

def test_ewma_hand_reference_constant_magnitude():
    """Lợi suất log luôn ±r → mọi r² bằng nhau → phương sai EWMA = r² → σ = r (tính tay)."""
    r = 0.001
    closes = [100.0 * math.exp(r if i % 2 else 0.0) for i in range(200)]
    v = X.ewma_vol(closes)
    assert v["sigma_bar_pct"] == pytest.approx(r * 100, abs=1e-5)
    assert v["sigma_day_pct"] == pytest.approx(r * math.sqrt(96) * 100, abs=1e-4)
    assert "không phải mô hình" in v["method"] and v["returns_used"] == 199


def test_ewma_reacts_and_short_history():
    calm = [100.0 * math.exp(0.0005 if i % 2 else 0) for i in range(150)]
    shock = calm + [calm[-1] * math.exp(0.01 if i % 2 else -0.01) for i in range(5)]
    assert X.ewma_vol(shock)["sigma_bar_pct"] > 2 * X.ewma_vol(calm)["sigma_bar_pct"]
    assert X.ewma_vol(calm[:40]) is None


# ------------------------------------------------------------------ TEC-09

def test_trend_of_up_down_and_short():
    up = bars(Timeframe.H1, NOW, 120, step=2.0)
    down = bars(Timeframe.H1, NOW, 120, step=-2.0)
    assert X.trend_of(up)["trend"] == "UP" and X.trend_of(down)["trend"] == "DOWN"
    assert X.trend_of(up[:50]) is None


def test_mtf_ignores_bars_closing_after_as_of():
    """Point-in-time: nến H4 đóng sau as_of (dù đã gửi tới) không được dùng."""
    h4 = bars(Timeframe.H4, NOW + 4 * H, 120)
    as_of = NOW - 2 * H
    ctx = X.mtf_context({Timeframe.H4: h4}, as_of, REFERENCE)
    assert datetime.fromisoformat(ctx["H4"]["last_close"]) <= as_of


def test_mtf_weekend_not_stale_but_midweek_gap_is():
    fri_close = datetime(2026, 1, 16, 22, 0, tzinfo=UTC)          # thứ Sáu, giờ đóng cửa
    h1 = bars(Timeframe.H1, fri_close, 120)
    mon = datetime(2026, 1, 18, 23, 10, tzinfo=UTC)                 # Chủ nhật sau giờ mở 10 phút
    assert X.mtf_context({Timeframe.H1: h1}, mon, REFERENCE)["H1"]["status"] == "OK"
    wed = datetime(2026, 1, 14, 12, 0, tzinfo=UTC)
    old = bars(Timeframe.H1, wed - 3 * H, 120)                      # trễ 3 giờ giữa tuần
    assert X.mtf_context({Timeframe.H1: old}, wed, REFERENCE)["H1"]["status"] == "STALE"


def test_mtf_missing_insufficient_not_evaluated():
    ctx = X.mtf_context({Timeframe.H1: [], Timeframe.H4: bars(Timeframe.H4, NOW, 20)}, NOW,
                        REFERENCE)
    assert ctx["H1"]["status"] == "MISSING"
    assert ctx["H4"]["status"] == "INSUFFICIENT_HISTORY"
    assert ctx["D1"]["status"] == "NOT_EVALUATED"
    assert X.mtf_context(None, NOW, REFERENCE)["H1"]["status"] == "NOT_EVALUATED"


@pytest.mark.parametrize("m15,trends,want", [
    ("UP", ["UP", "UP", "UP"], "ALIGNED_UP"), ("DOWN", ["DOWN"], "ALIGNED_DOWN"),
    ("UP", ["UP", "DOWN"], "CONFLICT"), ("UP", ["UP", "FLAT"], "MIXED"),
    ("FLAT", ["UP"], "MIXED"), ("UP", [], "NOT_EVALUATED"),
])
def test_alignment(m15, trends, want):
    mtf = {f"T{i}": {"status": "OK", "trend": t} for i, t in enumerate(trends)}
    mtf["X"] = {"status": "STALE"}
    assert X.alignment(m15, mtf) == want


# ------------------------------------------------------------------ tích hợp Technical 1.4.0

def store_with_higher(step=1.0):
    st = InMemoryCandleStore()
    st.append(sample_rows(days=10), [])
    for tf, n in ((Timeframe.H1, 150), (Timeframe.H4, 100), (Timeframe.D1, 80)):
        st.append(bars(tf, NOW - timedelta(minutes=1), n, step=step), [])
    return st


def test_runner_feeds_higher_timeframes_and_is_deterministic():
    st = store_with_higher()
    out = InMemoryAnalystOutputStore()
    market = MarketDataService(st, source=DataSource.CSV)
    r = TechnicalRunner(market, out)
    assert r.run_feed(market.feed, NOW) is True
    o = out.latest("technical", symbol="XAUUSD", tf=Timeframe.M15, source=DataSource.CSV).output
    f = o.features
    assert o.version == "technical-1.4.0" and f"MTF_{f['mtf_alignment']}" in o.drivers
    assert f["mtf"]["H1"]["status"] == "OK" and f["mtf"]["H1"]["trend"] == "UP"
    assert f["vol_forecast"]["sigma_bar_pct"] > 0
    assert f["input"]["higher_timeframes"]["H4"][0] == "OK"
    assert r.run_feed(market.feed, NOW) is False                      # cùng dữ liệu → cùng id


def test_new_higher_bar_changes_output_id_point_in_time():
    st = store_with_higher()
    market = MarketDataService(st, source=DataSource.CSV)
    a = technical.analyze(market.candles(as_of=NOW, limit=500), symbol="XAUUSD",
                          timeframe=Timeframe.M15, source=DataSource.CSV,
                          expected_last_close=market.candles(as_of=NOW, limit=1)[-1].close_time,
                          correlation_id="t", higher=None)
    assert a.features["mtf_alignment"] == "NOT_EVALUATED"
    assert all(v["status"] == "NOT_EVALUATED" for v in a.features["mtf"].values())
