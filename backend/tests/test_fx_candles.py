"""5d (chuẩn bị ING-24): nến M15 của 6 cặp tiền chỉ số USD, mỗi cặp một nguồn giá riêng."""

from __future__ import annotations

from gold_trading.contracts.candle import DataSource
from gold_trading.market.feeds import USD_INDEX_PAIRS, feed_id_for
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.candles import InMemoryCandleStore
from gold_trading.storage.repository import InMemoryRepository
from tests.auth_helpers import user_client
from tests.mt5_helpers import FEED, IDENT_FIELDS, SERVER, link_active
from tests.test_ingest_api import TOKEN, bars

URL = "/api/ingest/mt5/fx-candles"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
TF = Timeframe.M15


def setup(linked=True):
    repo, store = InMemoryRepository(), InMemoryCandleStore()
    if linked:
        link_active(repo)
    c = user_client(repo, candle_store=store, data_source=DataSource.MT5, run_sample_feed=False,
                    run_analysts=False, ingest_token=TOKEN)
    return c, store, repo


def body(pair="EURUSD", broker=None, n=50, **over):
    ident = {k: v for k, v in IDENT_FIELDS.items() if k != "broker_symbol"}
    b = {"pair": pair, "broker_symbol": broker or pair, "timeframe": "M15", "backfill": True,
         "gateway_id": "win-1", "bars": bars(n), **ident}
    b.update(over)
    return b


def count(store, pair, feed):
    return store.stats(pair, TF, DataSource.MT5, feed=feed).count


def test_pairs_constant_matches_dxy_components():
    assert USD_INDEX_PAIRS == ("EURUSD", "USDJPY", "GBPUSD", "USDCAD", "USDSEK", "USDCHF")


def test_stores_each_pair_in_own_feed_not_mixed_with_gold():
    c, store, _ = setup()
    r = c.post(URL, json=body("EURUSD"), headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == 50
    assert c.post(URL, json=body("USDJPY", n=40), headers=AUTH).status_code == 200
    eur, jpy = feed_id_for(SERVER, "EURUSD"), feed_id_for(SERVER, "USDJPY")
    assert count(store, "EURUSD", eur) == 50 and count(store, "USDJPY", jpy) == 40
    assert count(store, "EURUSD", jpy) == 0 and count(store, "XAUUSD", FEED) == 0
    # gửi lại → không nhân đôi
    r = c.post(URL, json=body("EURUSD"), headers=AUTH)
    assert (r.json()["accepted"], r.json()["duplicates"]) == (0, 50)


def test_broker_suffix_is_separate_feed():
    c, store, _ = setup()
    assert c.post(URL, json=body("EURUSD", "EURUSD.r"), headers=AUTH).status_code == 200
    assert count(store, "EURUSD", feed_id_for(SERVER, "EURUSD.r")) == 50
    assert count(store, "EURUSD", feed_id_for(SERVER, "EURUSD")) == 0


def test_requires_link_and_same_mt5():
    c, store, _ = setup(linked=False)
    r = c.post(URL, json=body(), headers=AUTH)
    assert r.status_code == 409 and r.json()["detail"].startswith("MT5_LINK_REQUIRED")
    c, store, _ = setup()
    r = c.post(URL, json=body(mt5_login=999), headers=AUTH)
    assert r.status_code == 409 and r.json()["detail"].startswith("MT5_LINK_MISMATCH")
    assert count(store, "EURUSD", feed_id_for(SERVER, "EURUSD")) == 0
    assert c.post(URL, json=body(), headers={"Authorization": "Bearer " + "x" * 32}).status_code \
        == 401


def test_rejects_wrong_mapping_and_unknown_pair():
    c, store, _ = setup()
    r = c.post(URL, json=body("EURUSD", "GBPUSD"), headers=AUTH)  # cấu hình nhầm cặp
    assert r.status_code == 422
    assert c.post(URL, json=body("XAUUSD"), headers=AUTH).status_code == 422
    assert c.post(URL, json=body("AUDUSD"), headers=AUTH).status_code == 422
    assert c.post(URL, json=body(timeframe="H1"), headers=AUTH).status_code == 422
    assert c.post(URL, json=body(broker="EUR USD"), headers=AUTH).status_code == 422
    b = body()
    del b["mt5_login"]
    assert c.post(URL, json=b, headers=AUTH).status_code == 422


def test_bad_bars_quarantined_with_pair_symbol():
    c, store, _ = setup()
    b = body(n=5)
    b["bars"][2]["high"] = b["bars"][2]["low"] - 1  # OHLC sai
    r = c.post(URL, json=b, headers=AUTH)
    assert r.json()["quarantined"] == 1 and r.json()["reasons"] == {"INVALID_OHLC": 1}
    q = store.quarantine(10)
    assert q[0].symbol == "EURUSD" and q[0].feed_id == feed_id_for(SERVER, "EURUSD")
