from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from gold_trading.contracts.candle import Candle, CandleFlag, DataSource
from gold_trading.ingestion.candles import CandleIngestor, RawBar
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.candles import InMemoryCandleStore, SqlCandleStore
from gold_trading.storage.repository import SqlRepository

TF = Timeframe.M15
# Thứ Ba 06/01/2026 14:00 UTC — thị trường mở cửa
T0 = datetime(2026, 1, 6, 14, 0, tzinfo=UTC)
M = timedelta(minutes=15)


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryCandleStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'c.db'}")
    repo.create_all()
    return SqlCandleStore(repo.engine)


def bar(t, o=2400.0, h=2402.0, lo=2399.0, c=2401.0, v=100):
    return RawBar(open_time=t, open=o, high=h, low=lo, close=c, tick_volume=v)


def ingest(store, bars, *, at, backfill=False, source=DataSource.CSV):
    return CandleIngestor(store).ingest(
        bars, symbol="XAUUSD", timeframe=TF, source=source, ingested_at=at, backfill=backfill
    )


def visible(store, as_of, **kw):
    return store.query("XAUUSD", TF, DataSource.CSV, as_of=as_of, **kw)


# ---- Contract ----


def test_candle_rejects_unclosed_and_bad_ohlc():
    base = dict(
        symbol="XAUUSD",
        timeframe=TF,
        source=DataSource.CSV,
        open_time=T0,
        close_time=T0 + M,
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        ingested_at=T0 + M,
        available_at=T0 + M,
    )
    Candle(**base)
    with pytest.raises(ValidationError):
        Candle(**base | {"available_at": T0, "ingested_at": T0})  # chưa đóng
    with pytest.raises(ValidationError):
        Candle(**base | {"high": 1.2})  # high < close
    with pytest.raises(ValidationError):
        Candle(
            **base
            | {"open_time": T0 + timedelta(minutes=1), "close_time": T0 + M + timedelta(minutes=1)}
        )


# ---- Ingest ----


def test_accept_then_duplicate_is_idempotent(store):
    r1 = ingest(store, [bar(T0), bar(T0 + M)], at=T0 + 3 * M)
    r2 = ingest(store, [bar(T0), bar(T0 + M)], at=T0 + 4 * M)
    assert (r1.accepted, r2.accepted, r2.duplicates) == (2, 0, 2)
    assert len(visible(store, T0 + 5 * M)) == 2


def test_revision_does_not_rewrite_past(store):
    ingest(store, [bar(T0, c=2401.0)], at=T0 + M)
    r = ingest(store, [bar(T0, c=2401.5)], at=T0 + 10 * M)
    assert r.revised == 1
    before = visible(store, T0 + 5 * M)
    after = visible(store, T0 + 10 * M)
    assert before[0].close == 2401.0 and before[0].revision == 0
    assert after[0].close == 2401.5 and after[0].revision == 1
    assert CandleFlag.REVISED in after[0].flags
    assert after[0].available_at == T0 + 10 * M


def test_live_bar_invisible_before_it_arrives(store):
    ingest(store, [bar(T0)], at=T0 + 2 * M)  # đến muộn 15 phút sau khi đóng
    assert visible(store, T0 + M) == []
    assert len(visible(store, T0 + 2 * M)) == 1


def test_backfill_available_at_close_time(store):
    ingest(store, [bar(T0)], at=T0 + 100 * M, backfill=True)
    c = visible(store, T0 + M)[0]
    assert c.available_at == T0 + M
    assert c.ingested_at == T0 + 100 * M
    assert CandleFlag.BACKFILL in c.flags


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (bar(T0, h=2399.5), "INVALID_OHLC"),
        (bar(T0, lo=2401.5), "INVALID_OHLC"),
        (bar(T0 + timedelta(minutes=3)), "MISALIGNED_TIME"),
        (bar(T0, o=-1.0), "NON_POSITIVE_PRICE"),
        (bar(T0, c=float("nan")), "NON_FINITE_PRICE"),
        (bar(T0.replace(tzinfo=None)), "NAIVE_TIME"),
        (bar(T0 + 2 * M), "BAR_NOT_CLOSED"),
    ],
)
def test_bad_bars_quarantined_not_stored(store, raw, reason):
    r = ingest(store, [raw], at=T0 + 2 * M)
    assert r.quarantined == 1 and r.reasons == {reason: 1}
    assert visible(store, T0 + 10 * M) == []
    q = store.quarantine()
    assert q[0].reason == reason
    assert store.stats("XAUUSD", TF, DataSource.CSV).quarantined == 1


def test_gap_flag_in_session_but_not_over_weekend(store):
    ingest(store, [bar(T0), bar(T0 + 3 * M)], at=T0 + 10 * M)
    rows = visible(store, T0 + 10 * M)
    assert CandleFlag.GAP_BEFORE in rows[1].flags

    fri_last = datetime(2026, 1, 9, 21, 45, tzinfo=UTC)  # 16:45 New York, nến cuối tuần
    sun_first = datetime(2026, 1, 11, 23, 0, tzinfo=UTC)  # 18:00 New York Chủ nhật
    ingest(store, [bar(fri_last), bar(sun_first)], at=sun_first + M)
    rows = visible(store, sun_first + M)
    assert CandleFlag.GAP_BEFORE not in rows[-1].flags


def test_price_jump_flagged(store):
    ingest(store, [bar(T0), bar(T0 + M, o=2600, h=2601, lo=2599, c=2600)], at=T0 + 3 * M)
    assert CandleFlag.PRICE_JUMP in visible(store, T0 + 3 * M)[1].flags


def test_sources_are_isolated(store):
    ingest(store, [bar(T0)], at=T0 + M, source=DataSource.SAMPLE)
    assert visible(store, T0 + M) == []  # CSV không thấy dữ liệu SAMPLE
    assert len(store.query("XAUUSD", TF, DataSource.SAMPLE, as_of=T0 + M)) == 1


def test_query_limit_returns_latest(store):
    ingest(store, [bar(T0 + i * M) for i in range(10)], at=T0 + 20 * M)
    rows = visible(store, T0 + 20 * M, limit=3)
    assert [r.open_time for r in rows] == [T0 + 7 * M, T0 + 8 * M, T0 + 9 * M]
