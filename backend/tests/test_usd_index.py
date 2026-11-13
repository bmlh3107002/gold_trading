"""Bước 9d — chỉ số USD tự tính từ nến M15 của 6 cặp trên MT5 (ING-24, DEC-03, DEC-14).

Case: công thức so với tính tay độc lập, thiếu cặp, nến không cùng thời điểm, nến chưa đóng /
chưa biết (point-in-time), cuối tuần (STALE), giá vô lý (nhầm symbol), hai broker không trộn,
hai symbol cùng cặp (mơ hồ), cờ nến đầu vào.
"""

import math
from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.contracts.candle import Candle, CandleFlag, DataSource
from gold_trading.market import usd_index as U
from gold_trading.market.feeds import USD_INDEX_PAIRS, feed_id_for
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.candles import InMemoryCandleStore, SqlCandleStore
from gold_trading.storage.repository import InMemoryRepository, PriceFeed, SqlRepository

SERVER = "MetaQuotes-Demo"
T0 = datetime(2026, 11, 12, 14, 0, tzinfo=UTC)   # thứ Năm
M15 = timedelta(minutes=15)
PRICES = {"EURUSD": 1.0800, "USDJPY": 150.00, "GBPUSD": 1.2700, "USDCAD": 1.3600,
          "USDSEK": 10.500, "USDCHF": 0.8800}


def utc(*a):
    return datetime(*a, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def env(request, tmp_path):
    if request.param == "memory":
        return InMemoryRepository(), InMemoryCandleStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'u.db'}")
    repo.create_all()
    return repo, SqlCandleStore(repo.engine)


def feed(pair, server=SERVER, suffix=""):
    return feed_id_for(server, pair + suffix)


def bar(pair, open_time, close, *, server=SERVER, suffix="", known=None, flags=(), rev=0):
    close_time = open_time + M15
    return Candle(symbol=pair, timeframe=Timeframe.M15, source=DataSource.MT5,
                  feed_id=feed(pair, server, suffix), open_time=open_time,
                  close_time=close_time, open=close, high=close * 1.001, low=close * 0.999,
                  close=close, ingested_at=known or close_time, available_at=known or close_time,
                  flags=frozenset(flags), revision=rev)


def load(env, times, prices=PRICES, server=SERVER, suffix="", skip=()):
    repo, store = env
    items = []
    for pair, p in prices.items():
        repo.ensure_price_feed(PriceFeed(feed(pair, server, suffix), server, pair + suffix, T0))
        items += [bar(pair, t, p, server=server, suffix=suffix) for t in times
                  if (pair, t) not in skip]
    store.append(items, [])


def feeds(server=SERVER, suffix=""):
    return {p: feed(p, server, suffix) for p in USD_INDEX_PAIRS}


# ------------------------------------------------------------------ công thức

def test_formula_against_independent_hand_calc():
    # Tính tay độc lập bằng lũy thừa trực tiếp (không qua log)
    hand = 50.14348112 * (1.08 ** -0.576) * (150.0 ** 0.136) * (1.27 ** -0.119) * \
        (1.36 ** 0.091) * (10.5 ** 0.042) * (0.88 ** 0.036)
    assert math.isclose(U.compute(PRICES), hand, rel_tol=1e-12)
    assert 100 < hand < 107  # mức chỉ số USD đầu 2024 với các tỷ giá này (~103–104)
    assert math.isclose(U.compute(dict.fromkeys(U.WEIGHTS, 1.0)), 50.14348112, rel_tol=1e-15)
    assert sum(abs(w) for w in U.WEIGHTS.values()) == pytest.approx(1.0)
    assert set(U.WEIGHTS) == set(USD_INDEX_PAIRS)
    # USD mạnh lên (EURUSD giảm, USDJPY tăng) → chỉ số tăng
    stronger = {**PRICES, "EURUSD": 1.05, "USDJPY": 155.0}
    assert U.compute(stronger) > U.compute(PRICES)
    with pytest.raises(KeyError):
        U.compute({k: v for k, v in PRICES.items() if k != "USDSEK"})
    with pytest.raises(ValueError):
        U.compute({**PRICES, "USDSEK": float("nan")})


# ------------------------------------------------------------------ tính từ nến

def test_index_from_closed_common_bar(env):
    repo, store = env
    times = [T0 + i * M15 for i in range(4)]
    load(env, times)
    at = T0 + 4 * M15 + timedelta(minutes=1)
    ix = U.usd_index(store, feeds(), at)
    assert ix.status == "OK" and ix.bar_open_time == times[-1]
    assert ix.value == round(U.compute(PRICES), 4)
    assert ix.components == PRICES and ix.flags == ()
    assert "không phải DXY chính thức" in ix.label
    # Qua repo: tự tìm nguồn của server (không phân biệt hoa/thường)
    assert U.usd_index_for_server(repo, store, SERVER.upper(), at).value == ix.value


def test_missing_pair_or_no_data(env):
    repo, store = env
    load(env, [T0], prices={k: v for k, v in PRICES.items() if k != "USDSEK"})
    at = T0 + M15
    ix = U.usd_index(store, feeds(), at)
    assert (ix.status, ix.reason, ix.detail) == ("INSUFFICIENT_DATA", "PAIR_NO_DATA", "USDSEK")
    ix = U.usd_index_for_server(repo, store, SERVER, at)
    assert (ix.reason, ix.detail) == ("PAIR_MISSING", "USDSEK")
    assert ix.value is None


def test_not_same_time_never_mixed(env):
    """Một cặp thiếu nến mới nhất → dùng nến chung trước đó (cùng thời điểm cho cả 6 cặp)."""
    _, store = env
    times = [T0, T0 + M15]
    load(env, times, skip={("USDJPY", T0 + M15)})
    at = T0 + 2 * M15
    ix = U.usd_index(store, feeds(), at)
    assert ix.bar_open_time == T0
    assert "EURUSD:NEWER_BAR_NOT_COMMON" in ix.flags
    # Không có nến chung nào → không đủ dữ liệu (không lấy nến của từng cặp ở thời điểm khác)
    _, s2 = env[0], InMemoryCandleStore()
    s2.append([bar(p, T0 if p != "USDJPY" else T0 + M15, v) for p, v in PRICES.items()], [])
    assert U.usd_index(s2, feeds(), at).reason == "NO_COMMON_BAR"


def test_point_in_time_unclosed_and_unknown_bars(env):
    _, store = env
    load(env, [T0])
    # Đang trong nến (chưa đóng) → chưa có nến nào
    assert U.usd_index(store, feeds(), T0 + timedelta(minutes=10)).reason == "PAIR_NO_DATA"
    # Nến đã đóng nhưng hệ thống biết muộn 2 phút → trước lúc biết vẫn chưa thấy
    _, s2 = env[0], InMemoryCandleStore()
    s2.append([bar(p, T0, v, known=T0 + M15 + timedelta(minutes=2)) for p, v in PRICES.items()],
              [])
    assert U.usd_index(s2, feeds(), T0 + M15 + timedelta(minutes=1)).reason == "PAIR_NO_DATA"
    assert U.usd_index(s2, feeds(), T0 + M15 + timedelta(minutes=2)).status == "OK"
    # Bản sửa nến (revision 1, biết sau) không viết lại quá khứ
    s2.append([bar("EURUSD", T0, 1.0900, known=T0 + timedelta(hours=1), rev=1,
                   flags=[CandleFlag.REVISED])], [])
    before = U.usd_index(s2, feeds(), T0 + timedelta(minutes=30))
    after = U.usd_index(s2, feeds(), T0 + timedelta(hours=1))
    assert before.components["EURUSD"] == 1.08 and before.status == "OK"
    assert after.reason == "STALE"  # nến chung đóng 45 phút trước → quá 30 phút


def test_stale_weekend(env):
    _, store = env
    fri = utc(2026, 11, 13, 21, 45)  # nến cuối thứ Sáu
    load(env, [fri])
    assert U.usd_index(store, feeds(), fri + M15 + timedelta(minutes=30)).status == "OK"
    ix = U.usd_index(store, feeds(), fri + M15 + timedelta(minutes=31))
    assert (ix.status, ix.reason, ix.bar_open_time) == ("INSUFFICIENT_DATA", "STALE", fri)
    assert U.usd_index(store, feeds(), utc(2026, 11, 14, 12)).reason == "STALE"  # thứ Bảy


@pytest.mark.parametrize("pair,price", [
    ("USDJPY", 0.0066),   # báo giá đảo chiều (JPYUSD)
    ("EURUSD", 108.0),    # sai đơn vị / nhầm symbol
    ("USDSEK", 1.08),     # nhầm sang EURUSD
])
def test_implausible_price_rejected(env, pair, price):
    _, store = env
    load(env, [T0], prices={**PRICES, pair: price})
    ix = U.usd_index(store, feeds(), T0 + M15)
    assert (ix.reason, ix.detail, ix.value) == ("PAIR_OUT_OF_RANGE", pair, None)


def test_two_brokers_never_mixed(env):
    repo, store = env
    load(env, [T0])
    other = {k: v * 1.01 for k, v in PRICES.items()}
    load(env, [T0, T0 + M15], prices=other, server="OtherBroker-Live")
    at = T0 + 2 * M15
    a = U.usd_index_for_server(repo, store, SERVER, at)
    b = U.usd_index_for_server(repo, store, "OtherBroker-Live", at)
    # Broker A chỉ có nến T0 → dùng nến của chính A, không mượn nến mới hơn của broker B
    assert a.status == "OK" and a.bar_open_time == T0 and a.components == PRICES
    assert b.status == "OK" and b.components == other
    assert U.usd_index_for_server(repo, store, "NoSuchServer", at).reason == "PAIR_MISSING"


def test_two_symbols_same_pair_newest_wins_or_ambiguous(env):
    repo, store = env
    load(env, [T0])                       # tên cũ: EURUSD…
    load(env, [T0, T0 + M15], suffix=".r")  # đổi hậu tố: EURUSD.r… có nến mới hơn
    at = T0 + 2 * M15
    ix = U.usd_index_for_server(repo, store, SERVER, at)
    assert ix.status == "OK" and ix.bar_open_time == T0 + M15
    load(env, [T0 + M15])                 # tên cũ cũng có nến mới nhất → không biết dùng cái nào
    ix = U.usd_index_for_server(repo, store, SERVER, at)
    assert (ix.status, ix.reason) == ("INSUFFICIENT_DATA", "AMBIGUOUS_FEED")


def test_gold_feed_on_same_server_ignored(env):
    repo, store = env
    repo.ensure_price_feed(PriceFeed(feed_id_for(SERVER, "XAUUSD"), SERVER, "XAUUSD", T0))
    load(env, [T0])
    assert U.usd_index_for_server(repo, store, SERVER, T0 + M15).status == "OK"


def test_input_flags_propagated(env):
    _, store = env
    load(env, [T0], prices={k: v for k, v in PRICES.items() if k != "GBPUSD"})
    store.append([bar("GBPUSD", T0, 1.27, flags=[CandleFlag.PRICE_JUMP])], [])
    ix = U.usd_index(store, feeds(), T0 + M15)
    assert ix.status == "OK" and ix.flags == ("GBPUSD:PRICE_JUMP",)


def test_naive_time_rejected(env):
    repo, store = env
    with pytest.raises(ValueError):
        U.usd_index(store, feeds(), datetime(2026, 11, 12, 14))
    with pytest.raises(ValueError):
        U.usd_index_for_server(repo, store, SERVER, datetime(2026, 11, 12, 14))


def test_cli_usd(env, capsys):
    from gold_trading.ingestion import cli
    repo, store = env
    load(env, [T0])
    at = T0 + M15
    assert cli._usd(SERVER, repo=repo, store=store, now=at) == 0
    out = capsys.readouterr().out
    assert f"{SERVER}: {U.compute(PRICES):.4f}" in out and "không phải DXY chính thức" in out
    assert cli._usd(SERVER, repo=repo, store=store, now=at + timedelta(hours=2)) == 1
    assert "không đủ dữ liệu (STALE)" in capsys.readouterr().out
    if hasattr(repo, "engine"):  # tự tìm server từ bảng price_feeds
        assert cli._usd(None, repo=repo, store=store, now=at) == 0
        assert SERVER in capsys.readouterr().out
    assert cli._usd(None, env={}) == 2
