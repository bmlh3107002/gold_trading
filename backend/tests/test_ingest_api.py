from datetime import UTC, datetime, timedelta

from gold_trading.contracts.candle import DataSource
from gold_trading.ingestion.sources import sample
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.candles import InMemoryCandleStore
from gold_trading.storage.repository import InMemoryRepository
from tests.auth_helpers import user_client
from tests.mt5_helpers import IDENT_FIELDS, link_active

TOKEN = "t" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}
TF = Timeframe.M15


def client(token=TOKEN, linked=True):
    store = InMemoryCandleStore()
    repo = InMemoryRepository()
    if linked:
        link_active(repo)
    c = user_client(
        repo,
        candle_store=store,
        data_source=DataSource.MT5,
        run_sample_feed=False,
        run_analysts=False,
        ingest_token=token,
    )
    return c, store


def bars(n=300, shift_hours=0, end=datetime(2026, 1, 16, 12, 0, tzinfo=UTC)):
    out = list(
        sample.generate(start=end - timedelta(days=14), end=end, tf=TF, prev_close=2400, seed=5)
    )[-n:]
    return [
        {
            "open_time": (b.open_time + timedelta(hours=shift_hours)).isoformat(),
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "tick_volume": b.tick_volume,
            "spread_points": b.spread_points,
        }
        for b in out
    ]


def batch(b, backfill=True, symbol="XAUUSD"):
    return {
        "symbol": symbol,
        "timeframe": "M15",
        "backfill": backfill,
        "gateway_id": "win-1",
        "bars": b,
        **IDENT_FIELDS,
    }


def test_disabled_without_token_and_rejects_short_token():
    for t in (None, "short"):
        c, _ = client(token=t)
        r = c.post(
            "/api/ingest/mt5/candles", json=batch(bars(5)), headers={"Authorization": f"Bearer {t}"}
        )
        assert r.status_code == 503


def test_wrong_or_missing_token_401():
    c, _ = client()
    assert c.post("/api/ingest/mt5/candles", json=batch(bars(5))).status_code == 401
    bad = {"Authorization": "Bearer " + "x" * 32}
    assert c.post("/api/ingest/mt5/candles", json=batch(bars(5)), headers=bad).status_code == 401


def test_backfill_stored_as_mt5_and_idempotent():
    c, store = client()
    r = c.post("/api/ingest/mt5/candles", json=batch(bars(300)), headers=AUTH).json()
    assert r["accepted"] == 300 and r["quarantined"] == 0 and r["dry_run"] is False
    again = c.post("/api/ingest/mt5/candles", json=batch(bars(300)), headers=AUTH).json()
    assert again["accepted"] == 0 and again["duplicates"] == 300
    st = store.stats("XAUUSD", TF, DataSource.MT5)
    assert st.count == 300
    last = store.query(
        "XAUUSD", TF, DataSource.MT5, as_of=datetime(2027, 1, 1, tzinfo=UTC), limit=1
    )[0]
    assert "BACKFILL" in last.flags


def test_dry_run_does_not_store():
    c, store = client()
    r = c.post("/api/ingest/mt5/candles?dry_run=true", json=batch(bars(300)), headers=AUTH).json()
    assert r["dry_run"] is True and r["accepted"] == 300
    assert store.stats("XAUUSD", TF, DataSource.MT5).count == 0


def test_wrong_server_timezone_rejected_with_hint():
    c, store = client()
    r = c.post("/api/ingest/mt5/candles", json=batch(bars(600, shift_hours=2)), headers=AUTH)
    assert r.status_code == 422 and "-2 giờ" in r.json()["detail"]
    assert store.stats("XAUUSD", TF, DataSource.MT5).count == 0


def test_symbol_timeframe_size_validation():
    c, _ = client()
    assert (
        c.post(
            "/api/ingest/mt5/candles", json=batch(bars(5), symbol="XAUUSDm"), headers=AUTH
        ).status_code
        == 422
    )
    b = batch(bars(5)) | {"timeframe": "M5"}
    assert c.post("/api/ingest/mt5/candles", json=b, headers=AUTH).status_code == 422
    too_many = batch([bars(1)[0]] * 2001)
    assert c.post("/api/ingest/mt5/candles", json=too_many, headers=AUTH).status_code == 422


def test_unclosed_bar_quarantined():
    c, _ = client()
    future = datetime.now(UTC).replace(second=0, microsecond=0)
    future -= timedelta(minutes=future.minute % 15)
    b = [{"open_time": future.isoformat(), "open": 1, "high": 2, "low": 0.5, "close": 1.5}]
    r = c.post("/api/ingest/mt5/candles", json=batch(b, backfill=False), headers=AUTH).json()
    assert r["reasons"] == {"BAR_NOT_CLOSED": 1}


HB = {
    "gateway_id": "win-1",
    "gateway_version": "0.2.0",
    "read_only": True,
    "terminal_connected": True,
    "account_type": "DEMO",
    "server": "Broker-Demo",
    "server_tz": "Europe/Athens",
    "server_offset_hours_now": 2,
    "symbol": {
        "broker_symbol": "XAUUSD",
        "digits": 2,
        "point": 0.01,
        "contract_size": 100,
        "volume_min": 0.01,
        "volume_max": 100,
        "volume_step": 0.01,
    },
}


def test_heartbeat_and_status():
    c, _ = client()
    assert c.get("/api/accounts/default/gateway/status").json()["state"] == "NEVER"
    assert c.post("/api/ingest/mt5/heartbeat", json=HB).status_code == 401
    assert c.post("/api/ingest/mt5/heartbeat", json=HB, headers=AUTH).status_code == 200
    s = c.get("/api/accounts/default/gateway/status").json()
    assert s["state"] == "CONNECTED" and s["heartbeat"]["account_type"] == "DEMO"
    assert s["heartbeat"]["symbol"]["contract_size"] == 100


def test_heartbeat_must_declare_read_only():
    c, _ = client()
    assert (
        c.post(
            "/api/ingest/mt5/heartbeat", json=HB | {"read_only": False}, headers=AUTH
        ).status_code
        == 422
    )


# ---- ING-14 / 1A-C19: khung H1, H4, D1 ----

ATHENS_D1 = [
    # 00:00 giờ Athens (UTC+2 mùa đông) = 22:00 UTC hôm trước; T2 12/01 → T6 16/01/2026
    datetime(2026, 1, d, 22, tzinfo=UTC) for d in (11, 12, 13, 14, 15)
]


def ohlc(t):
    return {"open_time": t.isoformat(), "open": 2400, "high": 2410, "low": 2390, "close": 2405}


def test_d1_requires_valid_server_tz():
    c, store = client()
    b = batch([ohlc(t) for t in ATHENS_D1]) | {"timeframe": "D1"}
    r = c.post("/api/ingest/mt5/candles", json=b, headers=AUTH)
    assert r.status_code == 422 and "server_tz" in r.json()["detail"]
    r = c.post("/api/ingest/mt5/candles", json=b | {"server_tz": "GMT+2"}, headers=AUTH)
    assert r.status_code == 422
    assert store.stats("XAUUSD", Timeframe.D1, DataSource.MT5).count == 0


def test_d1_stored_separately_with_server_aligned_times():
    c, store = client()
    c.post("/api/ingest/mt5/candles", json=batch(bars(300)), headers=AUTH)
    b = batch([ohlc(t) for t in ATHENS_D1]) | {"timeframe": "D1", "server_tz": "Europe/Athens"}
    r = c.post("/api/ingest/mt5/candles", json=b, headers=AUTH).json()
    assert r["accepted"] == 5 and r["quarantined"] == 0
    assert r["session_outside_fraction"] is None  # R1 không áp cho D1
    again = c.post("/api/ingest/mt5/candles", json=b, headers=AUTH).json()
    assert again["duplicates"] == 5
    assert store.stats("XAUUSD", Timeframe.D1, DataSource.MT5).count == 5
    assert store.stats("XAUUSD", TF, DataSource.MT5).count == 300  # M15 không bị ảnh hưởng
    # dry_run không lưu
    dry = batch([ohlc(datetime(2026, 1, 18, 22, tzinfo=UTC))]) | {
        "timeframe": "D1",
        "server_tz": "Europe/Athens",
    }
    assert c.post("/api/ingest/mt5/candles?dry_run=true", json=dry, headers=AUTH).json()[
        "accepted"
    ] == 1
    assert store.stats("XAUUSD", Timeframe.D1, DataSource.MT5).count == 5


def test_d1_cut_at_utc_midnight_quarantined():
    c, store = client()
    utc_cut = [datetime(2026, 1, d, 0, tzinfo=UTC) for d in (12, 13, 14)]
    b = batch([ohlc(t) for t in utc_cut]) | {"timeframe": "D1", "server_tz": "Europe/Athens"}
    r = c.post("/api/ingest/mt5/candles", json=b, headers=AUTH).json()
    assert r["reasons"] == {"MISALIGNED_TIME": 3}
    assert store.stats("XAUUSD", Timeframe.D1, DataSource.MT5).count == 0


def h1_bars(shift_hours=0):
    end = datetime(2026, 1, 16, 12, 0, tzinfo=UTC)
    gen = sample.generate(
        start=end - timedelta(days=21), end=end, tf=Timeframe.H1, prev_close=2400, seed=5
    )
    return [ohlc(b.open_time + timedelta(hours=shift_hours)) for b in gen]


def test_h1_goes_through_session_check():
    c, store = client()
    good = h1_bars()
    ok = c.post("/api/ingest/mt5/candles", json=batch(good) | {"timeframe": "H1"}, headers=AUTH)
    assert ok.status_code == 200 and ok.json()["accepted"] == len(good)
    assert ok.json()["session_outside_fraction"] == 0.0
    # Múi giờ khai báo sai 2 giờ → R1 từ chối cả lô H1, gợi ý độ lệch
    bad = batch(h1_bars(shift_hours=2)) | {"timeframe": "H1"}
    r = c.post("/api/ingest/mt5/candles", json=bad, headers=AUTH)
    assert r.status_code == 422 and "-2 giờ" in r.json()["detail"]
    assert store.stats("XAUUSD", Timeframe.H1, DataSource.MT5).count == len(good)


def test_d1_server_tz_must_match_backend_broker_tz():
    from gold_trading.market.hours import BrokerSessions, MarketCalendar

    cal = MarketCalendar(BrokerSessions.parse("Mon-Fri 01:00-23:55", "Europe/Athens"))
    repo = InMemoryRepository()
    link_active(repo)
    c = user_client(
        repo,
        candle_store=InMemoryCandleStore(),
        data_source=DataSource.MT5,
        run_sample_feed=False,
        run_analysts=False,
        ingest_token=TOKEN,
        calendar=cal,
    )
    b = batch([ohlc(t) for t in ATHENS_D1]) | {"timeframe": "D1"}
    r = c.post("/api/ingest/mt5/candles", json=b | {"server_tz": "Europe/Berlin"}, headers=AUTH)
    assert r.status_code == 422 and "GT_BROKER_SERVER_TZ" in r.json()["detail"]
    r = c.post("/api/ingest/mt5/candles", json=b | {"server_tz": "Europe/Athens"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["accepted"] == 5
