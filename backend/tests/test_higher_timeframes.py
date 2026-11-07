"""ING-14 + 1A-C19: khung H1/H4/D1 căn theo giờ server broker, không tự cắt lại theo UTC.

Giá trị tham chiếu tính tay (Europe/Athens: EET = UTC+2, EEST = UTC+3;
2026 đổi giờ lúc 01:00 UTC ngày 29/03 (03:00→04:00) và 25/10 (04:00→03:00)).
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from gold_trading.contracts.candle import Candle, CandleFlag, DataSource
from gold_trading.ingestion.candles import CandleIngestor, RawBar
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.candles import InMemoryCandleStore, SqlCandleStore
from gold_trading.storage.repository import SqlRepository

ATHENS = ZoneInfo("Europe/Athens")
H = timedelta(hours=1)
D1, H4, H1 = Timeframe.D1, Timeframe.H4, Timeframe.H1


def u(*a) -> datetime:
    return datetime(*a, tzinfo=UTC)


# ---- Ranh giới nến (giá trị tính tay) ----


@pytest.mark.parametrize(
    ("tf", "open_utc", "close_utc", "hours"),
    [
        # Ngày thường mùa đông: D1 00:00 Athens = 22:00 UTC hôm trước
        (D1, u(2026, 1, 13, 22), u(2026, 1, 14, 22), 24),
        # Mùa hè: 00:00 Athens = 21:00 UTC
        (D1, u(2026, 7, 14, 21), u(2026, 7, 15, 21), 24),
        # Ngày tiến giờ 29/03: 00:00 EET (22:00 UTC) → 00:00 EEST 30/03 (21:00 UTC) = 23 giờ
        (D1, u(2026, 3, 28, 22), u(2026, 3, 29, 21), 23),
        # Ngày lùi giờ 25/10: 00:00 EEST (21:00 UTC 24/10) → 00:00 EET 26/10 (22:00 UTC) = 25 giờ
        (D1, u(2026, 10, 24, 21), u(2026, 10, 25, 22), 25),
        # H4 00:00–04:00 ngày tiến giờ: 22:00 UTC → 04:00 EEST = 01:00 UTC = 3 giờ
        (H4, u(2026, 3, 28, 22), u(2026, 3, 29, 1), 3),
        # H4 00:00–04:00 ngày lùi giờ: 21:00 UTC → 04:00 EET = 02:00 UTC = 5 giờ
        (H4, u(2026, 10, 24, 21), u(2026, 10, 25, 2), 5),
        # H4 ngay sau đổi giờ trở lại 4 giờ
        (H4, u(2026, 10, 25, 2), u(2026, 10, 25, 6), 4),
    ],
)
def test_close_time_follows_server_clock(tf, open_utc, close_utc, hours):
    assert tf.is_aligned_in(open_utc, ATHENS)
    assert tf.close_time(open_utc, ATHENS) == close_utc
    assert close_utc - open_utc == timedelta(hours=hours)


def test_utc_broker_d1_is_utc_midnight():
    tz = ZoneInfo("UTC")
    assert D1.is_aligned_in(u(2026, 1, 11, 0), tz)  # Chủ nhật: broker GMT+0 có nến CN
    assert D1.close_time(u(2026, 1, 11, 0), tz) == u(2026, 1, 12, 0)


def test_nonexistent_boundary_uses_moment_clock_passes_it():
    # America/Santiago tiến giờ lúc 00:00 → 01:00 ngày 06/09/2026: 00:00 không tồn tại.
    tz = ZoneInfo("America/Santiago")
    open_ = datetime(2026, 9, 5, 0, 0, tzinfo=tz).astimezone(UTC)  # 04:00 UTC (−04)
    assert open_ == u(2026, 9, 5, 4)
    close = D1.close_time(open_, tz)
    # Đồng hồ server nhảy 00:00 −04 → 01:00 −03 lúc 04:00 UTC ngày 06/09
    assert close == u(2026, 9, 6, 4)
    assert close.astimezone(tz).hour == 1


def test_ambiguous_boundary_takes_later_never_early():
    # America/Havana lùi giờ 01:00 CDT → 00:00 CST ngày 01/11/2026: 00:00 xuất hiện 2 lần
    tz = ZoneInfo("America/Havana")
    open_ = u(2026, 10, 31, 4)  # 00:00 CDT
    first, second = u(2026, 11, 1, 4), u(2026, 11, 1, 5)
    assert first.astimezone(tz).replace(tzinfo=None) == second.astimezone(tz).replace(tzinfo=None)
    assert D1.close_time(open_, tz) == second  # muộn hơn: không coi nến đã đóng sớm


def test_alignment_needs_server_tz_and_rejects_utc_cut():
    winter_utc_midnight = u(2026, 1, 14, 0)  # = 02:00 Athens: KHÔNG phải ranh giới D1 broker
    assert not D1.is_aligned_in(winter_utc_midnight, ATHENS)
    assert not D1.is_aligned_in(u(2026, 1, 13, 22), None)  # thiếu tz → không chấp nhận
    # H4 căn theo UTC (00:00 UTC = 02:00 Athens) là SAI với broker
    assert not H4.is_aligned_in(u(2026, 1, 14, 0), ATHENS)
    assert H4.is_aligned_in(u(2026, 1, 14, 2), ATHENS)  # 04:00 Athens
    assert not H4.is_aligned_in(u(2026, 1, 14, 2, 15), ATHENS)
    assert H1.is_aligned_in(u(2026, 1, 14, 2), None)
    assert not H1.is_aligned_in(u(2026, 1, 14, 2, 30), None)
    with pytest.raises(ValueError):
        D1.close_time(u(2026, 1, 13, 22))
    with pytest.raises(ValueError):
        H4.floor(u(2026, 1, 13, 22))


def test_contract_accepts_dst_length_only_within_one_hour():
    def candle(tf, o, c):
        return Candle(
            symbol="XAUUSD",
            timeframe=tf,
            source=DataSource.MT5,
            open_time=o,
            close_time=c,
            open=1,
            high=2,
            low=0.5,
            close=1.5,
            ingested_at=c,
            available_at=c,
        )

    candle(D1, u(2026, 3, 28, 22), u(2026, 3, 29, 21))  # 23 giờ hợp lệ
    candle(D1, u(2026, 10, 24, 21), u(2026, 10, 25, 22))  # 25 giờ hợp lệ
    for bad_close in (u(2026, 3, 29, 20), u(2026, 3, 29, 23, 15)):  # 22 giờ / 25h15
        with pytest.raises(ValidationError):
            candle(D1, u(2026, 3, 28, 22), bad_close)
    with pytest.raises(ValidationError):
        candle(H1, u(2026, 1, 14, 2), u(2026, 1, 14, 3, 15))  # H1 phải đúng 1 giờ


# ---- Cửa nạp ----


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryCandleStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'c.db'}")
    repo.create_all()
    return SqlCandleStore(repo.engine)


def bar(t, o=2400.0, c=2401.0, v=100):
    hi, lo = max(o, c) + 1, min(o, c) - 1
    return RawBar(open_time=t, open=o, high=hi, low=lo, close=c, tick_volume=v)


def athens_days(*dates):
    return [datetime(y, m, d, tzinfo=ATHENS).astimezone(UTC) for y, m, d in dates]


NOV_1 = u(2026, 11, 1)


def ingest(ing, bars, tf=D1, at=NOV_1, backfill=True, tz=ATHENS):
    return ing.ingest(
        bars,
        symbol="XAUUSD",
        timeframe=tf,
        source=DataSource.MT5,
        ingested_at=at,
        backfill=backfill,
        server_tz=tz,
    )


def all_bars(store, tf=D1):
    return store.query("XAUUSD", tf, DataSource.MT5, as_of=u(2030, 1, 1), limit=1000)


def test_server_aligned_requires_tz(store):
    with pytest.raises(ValueError):
        ingest(CandleIngestor(store), [bar(u(2026, 1, 13, 22))], tz=None)


def test_d1_across_dst_stored_with_true_close_and_backfill_available_at(store):
    ing = CandleIngestor(store)
    days = athens_days((2026, 3, 27), (2026, 3, 30), (2026, 3, 31))  # T6, T2 (sau tiến giờ), T3
    r = ingest(ing, [bar(t) for t in days])
    assert (r.accepted, r.quarantined) == (3, 0)
    got = all_bars(store)
    opens = [u(2026, 3, 26, 22), u(2026, 3, 29, 21), u(2026, 3, 30, 21)]
    closes = [u(2026, 3, 27, 22), u(2026, 3, 30, 21), u(2026, 3, 31, 21)]
    assert [c.open_time for c in got] == opens
    assert [c.close_time for c in got] == closes
    assert all(c.available_at == c.close_time and CandleFlag.BACKFILL in c.flags for c in got)
    # Cuối tuần (T7, CN đóng cửa) không phải thiếu nến
    assert all(CandleFlag.GAP_BEFORE not in c.flags for c in got)


def test_utc_cut_d1_is_quarantined_not_recut(store):
    # 1A-C19: nến D1 cắt theo nửa đêm UTC (sai với broker Athens) → cách ly, không tự sửa
    r = ingest(CandleIngestor(store), [bar(u(2026, 1, 14, 0)), bar(u(2026, 1, 13, 22))])
    assert r.reasons == {"MISALIGNED_TIME": 1} and r.accepted == 1
    assert [c.open_time for c in all_bars(store)] == [u(2026, 1, 13, 22)]


def test_d1_not_closed_uses_true_25h_length(store):
    open_ = u(2026, 10, 24, 21)  # D1 ngày lùi giờ, dài 25 giờ, đóng 22:00 UTC 25/10
    ing = CandleIngestor(store)
    r = ingest(ing, [bar(open_)], at=u(2026, 10, 25, 21, 30), backfill=False)  # sau 24h30
    assert r.reasons == {"BAR_NOT_CLOSED": 1}
    r = ingest(ing, [bar(open_)], at=u(2026, 10, 25, 22), backfill=False)
    assert r.accepted == 1
    c = all_bars(store)[0]
    assert c.close_time == u(2026, 10, 25, 22) and c.available_at == u(2026, 10, 25, 22)


def test_h4_not_closed_on_spring_short_bar(store):
    ing = CandleIngestor(store)
    open_ = u(2026, 3, 28, 22)  # dài 3 giờ (đóng 01:00 UTC)
    assert ingest(ing, [bar(open_)], tf=H4, at=u(2026, 3, 29, 0, 59), backfill=False).reasons == {
        "BAR_NOT_CLOSED": 1
    }
    assert ingest(ing, [bar(open_)], tf=H4, at=u(2026, 3, 29, 1), backfill=False).accepted == 1


def test_missing_weekday_d1_flags_gap(store):
    ing = CandleIngestor(store)
    days = athens_days((2026, 1, 12), (2026, 1, 13), (2026, 1, 15))  # thiếu thứ Tư 14/01
    ingest(ing, [bar(t) for t in days])
    flags = [CandleFlag.GAP_BEFORE in c.flags for c in all_bars(store)]
    assert flags == [False, False, True]


def test_h4_weekend_no_gap_midweek_missing_gap(store):
    ing = CandleIngestor(store)
    fri_20 = datetime(2026, 1, 16, 20, tzinfo=ATHENS).astimezone(UTC)
    mon_00 = datetime(2026, 1, 19, 0, tzinfo=ATHENS).astimezone(UTC)
    mon_04 = datetime(2026, 1, 19, 4, tzinfo=ATHENS).astimezone(UTC)
    mon_12 = datetime(2026, 1, 19, 12, tzinfo=ATHENS).astimezone(UTC)  # thiếu 08:00
    ingest(ing, [bar(t) for t in (fri_20, mon_00, mon_04, mon_12)], tf=H4)
    flags = [CandleFlag.GAP_BEFORE in c.flags for c in all_bars(store, H4)]
    assert flags == [False, False, False, True]


def test_d1_duplicate_revision_conflict(store):
    ing = CandleIngestor(store)
    t = athens_days((2026, 1, 13))[0]
    ingest(ing, [bar(t)])
    again = ingest(ing, [bar(t)])
    assert (again.accepted, again.duplicates) == (0, 1)
    rev = ingest(ing, [bar(t, c=2410.0)], at=u(2026, 11, 2))
    assert rev.revised == 1
    latest = all_bars(store)[-1]
    assert latest.revision == 1 and latest.available_at == u(2026, 11, 2)
    conflict = ingest(ing, [bar(t + timedelta(days=1), c=1.0), bar(t + timedelta(days=1), c=2.0)])
    assert conflict.reasons == {"CONFLICTING_DUPLICATE": 2}


def test_timeframes_are_separate_series(store):
    ing = CandleIngestor(store)
    t = athens_days((2026, 1, 13))[0]  # 22:00 UTC: hợp lệ cho cả D1, H4, H1
    for tf in (D1, H4, H1):
        assert ingest(ing, [bar(t)], tf=tf).accepted == 1
    for tf in (D1, H4, H1):
        assert len(all_bars(store, tf)) == 1
    assert all_bars(store, Timeframe.M15) == []
    assert all_bars(store, H1)[0].close_time == t + H
