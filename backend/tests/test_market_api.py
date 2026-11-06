from datetime import UTC, datetime, timedelta

from gold_trading.common.enums import TradingMode
from gold_trading.contracts.candle import DataSource
from gold_trading.ingestion.sample_feed import SampleFeed
from gold_trading.modes.manager import ModeChange
from gold_trading.storage.candles import InMemoryCandleStore
from gold_trading.storage.repository import InMemoryRepository
from tests.auth_helpers import admin_client


def sample_app(repo=None, days=5):
    store = InMemoryCandleStore()
    SampleFeed(store, history_days=days).tick()
    c = admin_client(
        repo or InMemoryRepository(),
        candle_store=store,
        data_source=DataSource.SAMPLE,
        run_sample_feed=False,
    )
    return c, store


def test_candles_endpoint_with_indicators():
    c, _ = sample_app()
    body = c.get("/api/market/candles?limit=100").json()
    assert body["is_sample"] is True and body["source"] == "SAMPLE"
    assert len(body["candles"]) == 100
    assert len(body["ema20"]) == len(body["ema50"]) == len(body["rsi14"]) == 100
    # Có warm-up phía trước nên 100 giá trị hiển thị đều đã có EMA50
    assert all(v is not None for v in body["ema50"])
    assert "BACKFILL" in body["candles"][0]["flags"]


def test_summary_and_quality():
    c, _ = sample_app()
    s = c.get("/api/market/summary").json()
    assert s["is_sample"] and s["last_price"] > 0 and s["symbol"] == "XAUUSD"
    assert s["freshness"] in {"FRESH", "MARKET_CLOSED"}
    q = c.get("/api/market/quality").json()
    assert q["candle_count"] > 0 and q["quarantined"] == 0


def test_no_source_configured_returns_empty():
    c = admin_client(InMemoryRepository(), data_source=None)
    assert c.get("/api/market/candles").json()["candles"] == []
    s = c.get("/api/market/summary").json()
    assert s["freshness"] == "NO_DATA" and s["last_price"] is None
    st = c.get("/api/status").json()
    assert st["data_source"] is None and st["data_is_sample"] is False


def test_sample_data_blocks_shadow_and_live():
    c, _ = sample_app()
    assert c.get("/api/status").json()["data_is_sample"] is True
    r = c.post("/api/accounts/default/mode", json={"mode": "SHADOW"})
    assert r.status_code == 409
    assert c.post("/api/accounts/default/mode", json={"mode": "BACKTEST"}).status_code == 200


def test_restored_shadow_downgraded_when_sample():
    repo = InMemoryRepository()
    repo.append_mode(
        "default", ModeChange(TradingMode.PAPER, TradingMode.SHADOW, "op", None)
    )
    c, _ = sample_app(repo)
    assert c.get("/api/accounts/default/status").json()["mode"] == "PAPER"
    assert any(e.action == "mode.startup" for e in repo.audit())


def test_feed_appends_new_bar_as_live_not_backfill():
    store = InMemoryCandleStore()
    now = datetime(2026, 1, 6, 14, 1, tzinfo=UTC)
    feed = SampleFeed(store, history_days=2)
    feed.tick(now)
    later = now + timedelta(minutes=15)
    r = feed.tick(later)
    assert r.accepted == 1
    last = store.query("XAUUSD", feed.tf, DataSource.SAMPLE, as_of=later, limit=1)[0]
    assert "BACKFILL" not in last.flags and last.available_at == later
    assert feed.tick(later).accepted == 0  # idempotent
