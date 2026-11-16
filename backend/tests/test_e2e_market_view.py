"""KN-14 (đánh giá độc lập, F-09) — test hồi quy ĐẦU-CUỐI được commit.

Nến mẫu → ``create_app`` thật (orchestrator + Technical / Regime / Lịch sự kiện / Macro / COT /
Tin tức **thật**, nối đúng như chạy trên máy) → Snapshot → Quality Gate → Fusion → MarketView.
Khác ``test_fusion_runner.py`` (output analyst tự dựng): ở đây mọi output do analyst thật tạo, nên
lỗi kiểu bước 5b (id Technical không chứa nguồn giá → không bao giờ có MarketView) sẽ làm test đỏ.

Lịch Fed / BEA / BLS / DOL thật (fixtures) nạp qua bộ nạp thật như ``test_event_analyst.py``.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from gold_trading.analysts.framework import Scope
from gold_trading.common.enums import SourceStatus
from gold_trading.contracts.candle import DataSource
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.ingestion.sample_feed import SampleFeed
from gold_trading.ingestion.source_status import CheckOutcome, SourceCheck
from gold_trading.storage.analyst_outputs import InMemoryAnalystOutputStore
from gold_trading.storage.candles import InMemoryCandleStore
from gold_trading.storage.repository import InMemoryRepository

from .auth_helpers import make_app
from .test_economic_calendar import NOW
from .test_event_analyst import calendar_record, load, revise

SCOPE = Scope("XAUUSD", "M15", "SAMPLE", "")
T = NOW + timedelta(hours=1, seconds=5)          # thứ Sáu 13/11/2026 13:00:05 UTC — giờ mở cửa
S10 = timedelta(seconds=10)
REQUIRED = {"technical", "regime", "event"}


def latest_outputs(outs):
    """Output mới nhất của từng analyst (theo thời điểm tính)."""
    last = {}
    for *_, so in outs._rows:
        last[so.output.analyst_id] = so
    return {k: v.output for k, v in last.items()}


@pytest.fixture
def pipeline():
    st, log = load(PointInTimeStore())
    candles, outs = InMemoryCandleStore(), InMemoryAnalystOutputStore()
    SampleFeed(candles).tick(T)                 # 90 ngày nến M15 mẫu tới T
    ext = SimpleNamespace(store=st, check_log=log, start=lambda: None, stop=lambda: None)
    app, _ = make_app(InMemoryRepository(), candle_store=candles, analyst_store=outs,
                      data_source=DataSource.SAMPLE, run_sample_feed=False, run_analysts=True,
                      external_runner=ext, run_clock=False, ingest_token=None)
    orch = app.state.orchestrator
    assert orch is not None, "orchestrator phải được nối khi có analyst"
    for k in range(4):
        orch.tick(T + k * S10)
    return SimpleNamespace(app=app, orch=orch, views=app.state.market_views, outs=outs,
                           st=st, log=log)


def test_real_analysts_produce_market_view(pipeline):
    outs = latest_outputs(pipeline.outs)
    assert REQUIRED <= set(outs), set(outs)
    for a in REQUIRED:
        assert outs[a].source_status is SourceStatus.HEALTHY, (a, outs[a].quality_flags)
    view = pipeline.views.current(SCOPE, T + 3 * S10)
    assert view is not None, "analyst thật khỏe → phải có MarketView (lỗi kiểu 5b nếu không)"
    assert view.model_version == "fusion-rules-1.0.0"
    assert view.source == "SAMPLE" and "SAMPLE_DATA" in view.quality_flags
    assert {"UNCALIBRATED", "UNVALIDATED_RULES"} <= set(view.quality_flags)
    assert view.p_up is None and view.p_down is None
    assert view.as_of <= T + 3 * S10 < view.expires_at
    # Không nhìn trước: hạn MarketView không vượt hạn output bắt buộc nào.
    assert view.expires_at <= min(outs[a].expires_at for a in REQUIRED)


def test_idempotent_ticks_do_not_duplicate(pipeline):
    n = len(pipeline.views._views)
    for k in range(4, 8):
        pipeline.orch.tick(T + k * S10)
    assert len(pipeline.views._views) == n


def test_broken_calendar_invalidates_then_no_fallback(pipeline):
    view = pipeline.views.current(SCOPE, T + 3 * S10)
    assert view is not None
    # Nguồn lịch Fed hỏng, rồi lịch có cập nhật → analyst Lịch tính lại → không khỏe.
    b = T + timedelta(minutes=2)
    pipeline.log.record(SourceCheck("fed_fomc", b, CheckOutcome.INVALID, error_code="PARSE_ERROR"))
    c = b + timedelta(minutes=1)
    r = calendar_record(pipeline.st, "")
    assert pipeline.st.append(revise(r, c, note="e2e")).reason is None
    for k in range(3):
        pipeline.orch.tick(c + k * S10)
    ev = latest_outputs(pipeline.outs)["event"]
    assert ev.source_status is not SourceStatus.HEALTHY
    # MarketView cũ còn hạn bị VÔ HIỆU ngay, không đợi hết hạn.
    assert pipeline.views.current(SCOPE, c + 2 * S10) is None
    inv = pipeline.views._inv[view.market_view_id]
    assert inv[1] == "QUALITY_REJECTED" and inv[0] <= c + 2 * S10
    # Qua hạn, lịch vẫn hỏng → vẫn không có MarketView (không lùi về bản cũ).
    later = view.expires_at + timedelta(seconds=5)
    for k in range(3):
        pipeline.orch.tick(later + k * S10)
    assert pipeline.views.current(SCOPE, later + 2 * S10) is None


def test_no_market_view_without_calendar():
    """Lịch trống (chưa nạp gì) → Event MISSING → Gate REJECTED → không có MarketView."""
    candles, outs = InMemoryCandleStore(), InMemoryAnalystOutputStore()
    SampleFeed(candles).tick(T)
    from gold_trading.ingestion.source_status import SourceCheckLog
    ext = SimpleNamespace(store=PointInTimeStore(), check_log=SourceCheckLog(),
                          start=lambda: None, stop=lambda: None)
    app, _ = make_app(InMemoryRepository(), candle_store=candles, analyst_store=outs,
                      data_source=DataSource.SAMPLE, run_sample_feed=False, run_analysts=True,
                      external_runner=ext, run_clock=False, ingest_token=None)
    for k in range(4):
        app.state.orchestrator.tick(T + k * S10)
    assert latest_outputs(outs)["technical"].source_status is SourceStatus.HEALTHY
    assert app.state.market_views.current(SCOPE, T + 3 * S10) is None
    assert app.state.market_views._views == {}


def test_mt5_feed_scope_end_to_end(monkeypatch):
    """Nguồn MT5 có tên nguồn giá (feed) — đúng trường hợp lỗi bước 5b: output Technical thật
    phải được nhận đúng phạm vi nguồn giá, nếu không sẽ không bao giờ có MarketView."""
    from gold_trading.api import app as app_mod
    from gold_trading.market.timeframes import Timeframe
    from gold_trading.ingestion.sources import sample
    from gold_trading.ingestion.candles import CandleIngestor
    from gold_trading.market.feeds import feed_id_for

    feed = feed_id_for("Broker-Demo", "XAUUSD")
    monkeypatch.setattr(app_mod, "account_feed", lambda repo, account_id: feed)
    st, log = load(PointInTimeStore())
    candles, outs = InMemoryCandleStore(), InMemoryAnalystOutputStore()
    bars = list(sample.generate(start=T - timedelta(days=90), end=T, tf=Timeframe.M15,
                                prev_close=2400.0, seed=20260101))
    CandleIngestor(candles).ingest(bars, symbol="XAUUSD", timeframe=Timeframe.M15,
                                   source=DataSource.MT5, ingested_at=T, backfill=True, feed=feed)
    ext = SimpleNamespace(store=st, check_log=log, start=lambda: None, stop=lambda: None)
    app, _ = make_app(InMemoryRepository(), candle_store=candles, analyst_store=outs,
                      data_source=DataSource.MT5, run_analysts=True, external_runner=ext,
                      run_clock=False, ingest_token=None)
    for k in range(4):
        app.state.orchestrator.tick(T + k * S10)
    tech = latest_outputs(outs)["technical"]
    assert tech.source_status is SourceStatus.HEALTHY
    view = app.state.market_views.current(Scope("XAUUSD", "M15", "MT5", feed), T + 3 * S10)
    assert view is not None, "output Technical thật của nguồn MT5 phải được Fusion nhận"
    assert view.source == "MT5" and view.feed_id == feed
    assert "SAMPLE_DATA" not in view.quality_flags
    # Nguồn khác (feed khác) không thấy MarketView này.
    other = feed_id_for("Other-Demo", "XAUUSD")
    assert app.state.market_views.current(Scope("XAUUSD", "M15", "MT5", other), T + 3 * S10) is None
