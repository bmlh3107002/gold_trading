"""Bước 2 GĐ1 — lịch ngày lễ / đóng sớm (CAL-03, CAL-04, CAL-05, 1B-C01..C04).

Giá trị tham chiếu tính tay (XAUUSD, broker MetaQuotes-Demo: Quotes Mon–Fri 00:00–23:00 giờ server
Europe/Athens). Labor Day 07/09/2026 (thứ Hai, NY = UTC−4, Athens = UTC+3):

- Ngày giao dịch 07/09 chạy từ CN 06/09 18:00 NY (22:00 UTC) tới T2 17:00 NY (21:00 UTC).
- Ngày thường: broker ngừng 23:00 server = 20:00 UTC → 22:00 → 20:00 UTC = 22 giờ = **88 nến**.
- Labor Day: ngừng 14:30 NY = 18:30 UTC → 22:00 → 18:30 UTC = 20,5 giờ = **82 nến**.
- Chênh 6 nến = đúng số nến dữ liệu thật thiếu thêm (GĐ0); so với lịch tham chiếu (92 nến) là 10.
"""

from datetime import UTC, date, datetime, time, timedelta
from math import sin

import pytest

from gold_trading.analysts import technical
from gold_trading.api.app import _warn_holiday_coverage, calendar_from_env, create_app
from gold_trading.contracts.candle import Candle, CandleFlag, DataSource
from gold_trading.ingestion.candles import CandleIngestor, RawBar
from gold_trading.ingestion.sources import sample
from gold_trading.ingestion.sources.csv_file import check_sessions
from gold_trading.market.holidays import (
    US_HOLIDAYS,
    Holiday,
    HolidayKind,
    HolidayTable,
    trade_date,
)
from gold_trading.market.hours import (
    REFERENCE,
    WEEKLY_ONLY,
    BrokerSessions,
    BrokerSpecialHours,
    MarketCalendar,
    MarketSession,
)
from gold_trading.market.quality import assess_window, expected_open_times
from gold_trading.market.service import Freshness, MarketDataService
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.candles import InMemoryCandleStore
from gold_trading.storage.repository import InMemoryRepository

TF = Timeframe.M15
ATHENS = "Europe/Athens"
BROKER = BrokerSessions.parse("Mon-Fri 00:00-23:00", ATHENS)
MQ = MarketCalendar(BROKER)  # lịch thật: tham chiếu ∩ broker − ngày lễ
MQ_NO_HOLIDAY = MarketCalendar(BROKER, holidays=None)  # như trước bước 2


def u(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def special(spec, label=""):
    return MarketCalendar(BROKER, special=BrokerSpecialHours.parse(spec, label))


# ---------------------------------------------------------------------------
# CAL-03: bảng ngày lễ đúng với quy tắc lịch Mỹ (tính độc lập trong test)
# ---------------------------------------------------------------------------


def _easter(y):  # thuật toán Gregorian ẩn danh (Meeus/Jones/Butcher)
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = (h + l_ - 7 * m + 114) % 31 + 1
    return date(y, month, day)


def _nth(y, m, weekday, n):
    d = date(y, m, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last(y, m, weekday):
    d = date(y, m + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d):
    return (
        d - timedelta(days=1)
        if d.weekday() == 5
        else d + timedelta(days=1)
        if d.weekday() == 6
        else d
    )


def _expected(y):
    out = {}
    nyd = date(y, 1, 1)
    if nyd.weekday() != 5:  # rơi thứ Bảy: không nghỉ bù 31/12 năm trước
        out[_observed(nyd)] = "CLOSED"
    out[_nth(y, 1, 0, 3)] = time(14, 30)
    out[_nth(y, 2, 0, 3)] = time(14, 30)
    out[_easter(y) - timedelta(days=2)] = "CLOSED"
    out[_last(y, 5, 0)] = time(14, 30)
    out[_observed(date(y, 6, 19))] = time(14, 30)
    out[_observed(date(y, 7, 4))] = time(14, 30)
    out[_nth(y, 9, 0, 1)] = time(14, 30)
    tg = _nth(y, 11, 3, 4)
    out[tg] = time(14, 30)
    out[tg + timedelta(days=1)] = time(13, 45)
    xmas = _observed(date(y, 12, 25))
    out[xmas] = "CLOSED"
    if xmas == date(y, 12, 25) and date(y, 12, 24).weekday() < 5:
        out[date(y, 12, 24)] = time(13, 45)
    return out


@pytest.mark.parametrize("year", [2024, 2025, 2026, 2027])
def test_table_matches_us_calendar_rules(year):
    table = {
        h.day: ("CLOSED" if h.kind is HolidayKind.CLOSED else h.close_ny)
        for h in US_HOLIDAYS.holidays
        if h.day.year == year
    }
    assert table == _expected(year)


def test_known_dates_hand_checked():
    # 1B-C02: lễ rơi cuối tuần → nghỉ bù theo bảng năm đó
    assert US_HOLIDAYS.on(date(2026, 7, 3)).name == "Independence Day (observed)"  # 04/07 thứ Bảy
    assert US_HOLIDAYS.on(date(2026, 7, 4)) is None
    assert US_HOLIDAYS.on(date(2027, 7, 5)).name == "Independence Day (observed)"  # 04/07 CN
    assert US_HOLIDAYS.on(date(2027, 6, 18)) is not None  # Juneteenth 19/06/2027 thứ Bảy
    assert US_HOLIDAYS.on(date(2027, 12, 24)).kind is HolidayKind.CLOSED  # Giáng sinh thứ Bảy
    assert US_HOLIDAYS.on(date(2027, 12, 31)) is None  # năm mới 2028 thứ Bảy: không nghỉ bù
    assert US_HOLIDAYS.on(date(2026, 4, 3)).name == "Good Friday"
    assert US_HOLIDAYS.on(date(2026, 9, 7)).source == "BROKER_DATA"
    assert {h.source for h in US_HOLIDAYS.holidays} == {"BROKER_DATA", "CME_PATTERN"}


def test_table_validation_rejects_bad_rows():
    with pytest.raises(ValueError, match="cuối tuần"):
        Holiday(date(2026, 7, 4), "x", HolidayKind.CLOSED)
    with pytest.raises(ValueError):
        Holiday(date(2026, 9, 7), "x", HolidayKind.EARLY_CLOSE)  # thiếu giờ
    with pytest.raises(ValueError):
        Holiday(date(2026, 9, 7), "x", HolidayKind.CLOSED, time(13, 0))
    with pytest.raises(ValueError):
        Holiday(date(2026, 9, 7), "x", HolidayKind.EARLY_CLOSE, time(17, 30))
    h = Holiday(date(2026, 9, 7), "x", HolidayKind.CLOSED)
    with pytest.raises(ValueError, match="Trùng"):
        HolidayTable("v", frozenset({2026}), (h, h))
    with pytest.raises(ValueError, match="ngoài"):
        HolidayTable("v", frozenset({2025}), (h,))


def test_trade_date_starts_18h_new_york():
    assert trade_date(u(2026, 9, 6, 21, 59)) == date(2026, 9, 6)  # 17:59 NY CN
    assert trade_date(u(2026, 9, 6, 22, 0)) == date(2026, 9, 7)  # 18:00 NY CN → phiên thứ Hai


# ---------------------------------------------------------------------------
# Khoảng nghỉ cụ thể (giờ UTC tính tay)
# ---------------------------------------------------------------------------


def test_labor_day_reference_counts():
    start, end = u(2026, 9, 6, 22), u(2026, 9, 7, 21)  # trọn ngày giao dịch 07/09

    def n(cal):
        return len(expected_open_times(start, end - TF.delta, TF, cal))

    assert n(MQ_NO_HOLIDAY) == 88
    assert n(MQ) == 82
    assert n(WEEKLY_ONLY) == 92
    assert n(REFERENCE) == 82
    # nến cuối là 18:15 UTC (14:15 NY), mở lại 22:00 UTC (18:00 NY)
    assert MQ.is_open(u(2026, 9, 7, 18, 15)) and not MQ.is_open(u(2026, 9, 7, 18, 30))
    assert MQ.is_open(u(2026, 9, 7, 22, 0))


def test_good_friday_closed_whole_day():
    assert MQ.is_open(u(2026, 4, 2, 19, 45))  # thứ Năm 15:45 NY
    for t in (u(2026, 4, 2, 22), u(2026, 4, 3, 12), u(2026, 4, 3, 20, 45)):
        assert not MQ.is_open(t)
        assert MQ.session_at(t) is MarketSession.HOLIDAY
    assert MQ.session_at(u(2026, 4, 4, 12)) is MarketSession.WEEKEND
    assert MQ.is_open(u(2026, 4, 5, 22))  # CN 18:00 NY mở lại


def test_christmas_new_year_closures_2026():
    # Đêm Giáng sinh thứ Năm đóng 13:45 NY (18:45 UTC), nghỉ tới CN 27/12 18:00 NY (23:00 UTC)
    assert MQ.is_open(u(2026, 12, 24, 18, 30))
    assert not MQ.is_open(u(2026, 12, 24, 18, 45))
    assert MQ.session_at(u(2026, 12, 24, 19)) is MarketSession.HOLIDAY
    assert MQ.session_at(u(2026, 12, 25, 15)) is MarketSession.HOLIDAY
    assert not MQ.is_open(u(2026, 12, 27, 22, 45)) and MQ.is_open(u(2026, 12, 27, 23))
    # 31/12 thứ Năm bình thường; 01/01/2027 thứ Sáu nghỉ, mở lại CN 03/01 18:00 NY
    assert MQ.is_open(u(2026, 12, 31, 19, 45))
    assert not MQ.is_open(u(2026, 12, 31, 23, 30)) and not MQ.is_open(u(2027, 1, 1, 15))
    assert MQ.is_open(u(2027, 1, 3, 23))


def test_independence_observed_friday_2026():
    assert MQ.is_open(u(2026, 7, 3, 18, 15)) and not MQ.is_open(u(2026, 7, 3, 18, 30))
    assert MQ.is_open(u(2026, 7, 2, 19, 45))  # thứ Năm bình thường


def test_outside_table_years_no_holiday_and_flagged():
    # Good Friday 2028 = 14/04: bảng chưa có → không đoán, coi như ngày thường (R2 có thể chặn)
    assert MQ.is_open(u(2028, 4, 14, 12))
    assert not MQ.covers(u(2028, 4, 14, 12)) and MQ.covers(u(2026, 4, 3))
    assert _warn_holiday_coverage(MQ, u(2026, 11, 7)) is False
    assert _warn_holiday_coverage(MQ, u(2027, 11, 15)) is True  # 60 ngày nữa là 2028
    assert _warn_holiday_coverage(MQ, u(2028, 2, 1)) is True


def test_description_carries_versions():
    assert "us-holidays-2026.11.07" in MQ.description
    d = special("2026-12-24 00:00-20:45", "thong-bao-12-2026").description
    assert "giờ đặc biệt [thong-bao-12-2026#" in d


# ---------------------------------------------------------------------------
# Dữ liệu tổng hợp như broker thật + analyst (1B-C01, C03, C04)
# ---------------------------------------------------------------------------


def rows_for(cal, start, end, extra=()):
    """Nến tất định ở mọi chỗ ``cal`` mở (+ ``extra``), giá đều (không spike/đóng băng)."""
    times = sorted(set(expected_open_times(start, end, TF, cal)) | set(extra))
    out = []
    for i, t in enumerate(times):
        o = 4000 + 5 * sin(i / 7) + i * 0.01
        c = o + 0.3 * sin(i / 3 + 1)
        out.append(
            Candle(
                symbol="XAUUSD",
                timeframe=TF,
                source=DataSource.MT5,
                open_time=t,
                close_time=t + TF.delta,
                open=o,
                high=max(o, c) + 1,
                low=min(o, c) - 1,
                close=c,
                spread_points=20,
                ingested_at=t + TF.delta,
                available_at=t + TF.delta,
            )
        )
    return out


def analyze(rows, cal):
    return technical.analyze(
        rows,
        symbol="XAUUSD",
        timeframe=TF,
        source=DataSource.MT5,
        expected_last_close=rows[-1].close_time,
        correlation_id="t",
        calendar=cal,
    )


LD_START, LD_END = u(2026, 9, 1), u(2026, 9, 8, 12)


def test_1b_c01_labor_day_early_close_not_missing():
    rows = rows_for(MQ, LD_START, LD_END)  # broker thật: ngừng 14:30 NY
    q = assess_window(rows[-300:], TF, MQ)
    assert q.coverage == 1.0 and not q.outside_session
    out = analyze(rows, MQ)
    assert out.source_status.value == "HEALTHY"
    assert "LOW_COVERAGE" not in out.quality_flags
    assert "Labor Day 2026-09-07" in out.features["input"]["holidays_in_window"]
    assert out.version == technical.VERSION
    # Trước bước 2 (không có ngày lễ): cùng dữ liệu bị chặn oan
    old = analyze(rows, MQ_NO_HOLIDAY)
    assert "LOW_COVERAGE" in old.quality_flags
    assert len(assess_window(rows[-300:], TF, MQ_NO_HOLIDAY).missing) == 6


def test_real_gap_on_holiday_still_blocks():
    rows = rows_for(MQ, LD_START, LD_END)
    # mất 4 nến giữa buổi sáng Labor Day (trước giờ đóng sớm) → R2 vẫn chặn
    lost = {u(2026, 9, 7, 14), u(2026, 9, 7, 14, 15), u(2026, 9, 7, 14, 30), u(2026, 9, 7, 14, 45)}
    out = analyze([c for c in rows if c.open_time not in lost], MQ)
    assert "LOW_COVERAGE" in out.quality_flags and out.confidence == 0.0


def test_1b_c03_broker_open_when_table_closed_mismatch_then_special_fix():
    # Broker vẫn báo giá Good Friday cả ngày (bảng ghi đóng) → có nến lúc "đóng cửa"
    gf = expected_open_times(u(2026, 4, 2, 22), u(2026, 4, 3, 19, 45), TF, MQ_NO_HOLIDAY)
    rows = rows_for(MQ, u(2026, 3, 30), u(2026, 4, 3, 20), extra=gf)
    out = analyze(rows, MQ)
    assert "CALENDAR_MISMATCH" in out.quality_flags
    assert "HOLIDAY_TABLE_MISMATCH" in out.quality_flags
    assert out.source_status.value == "INVALID"
    assert "Good Friday 2026-04-03" in out.features["input"]["holidays_in_window"]
    # Người dùng nhập giờ đặc biệt theo thông báo broker (giờ server) → hết lệch
    fixed = special("2026-04-03 00:00-23:00")
    assert fixed.is_open(u(2026, 4, 3, 12))
    out2 = analyze(rows, fixed)
    assert "CALENDAR_MISMATCH" not in out2.quality_flags
    assert "HOLIDAY_TABLE_MISMATCH" not in out2.quality_flags
    assert out2.source_status.value == "HEALTHY"


def test_1b_c03_broker_closed_earlier_than_table_r2_blocks_with_hint():
    rows = rows_for(MQ, LD_START, LD_END)
    # broker ngừng 13:30 NY thay vì 14:30 → thiếu 4 nến 17:30–18:15 UTC ngày 07/09
    lost = {u(2026, 9, 7, 17, 30) + TF.delta * k for k in range(4)}
    out = analyze([c for c in rows if c.open_time not in lost], MQ)
    assert {"LOW_COVERAGE", "HOLIDAY_TABLE_MISMATCH"} <= out.quality_flags


def test_mismatch_hint_not_raised_on_normal_days():
    rows = rows_for(MQ, u(2026, 10, 12), u(2026, 10, 16, 12))
    lost = {u(2026, 10, 15, 10) + TF.delta * k for k in range(5)}
    out = analyze([c for c in rows if c.open_time not in lost], MQ)
    assert "LOW_COVERAGE" in out.quality_flags
    assert "HOLIDAY_TABLE_MISMATCH" not in out.quality_flags


def test_1b_c04_christmas_new_year_low_liquidity_flag():
    rows = rows_for(MQ, u(2026, 12, 21), u(2026, 12, 29, 12))
    out = analyze(rows, MQ)
    assert out.source_status.value == "HEALTHY"  # nghỉ Giáng sinh không bị coi là thiếu nến
    assert "LOW_LIQUIDITY_HOLIDAY" in out.risk_flags
    assert analyze(rows, MQ_NO_HOLIDAY).source_status.value == "INVALID"  # trước bước 2
    normal = analyze(rows_for(MQ, u(2026, 12, 14), u(2026, 12, 21, 12)), MQ)
    assert "LOW_LIQUIDITY_HOLIDAY" not in normal.risk_flags
    for t, low in [
        (u(2026, 12, 23, 12), False),
        (u(2026, 12, 23, 23, 30), True),  # 18:30 NY 23/12 = ngày giao dịch 24/12
        (u(2027, 1, 2, 12), True),
        (u(2027, 1, 4, 12), False),
        (u(2026, 11, 27, 15), True),  # ngày sau Lễ Tạ ơn
        (u(2026, 9, 7, 12), True),
    ]:
        assert MQ.low_liquidity(t) is low, t


# ---------------------------------------------------------------------------
# Độ mới dữ liệu / phiên trên Dashboard
# ---------------------------------------------------------------------------


def _service(cal, rows):
    store = InMemoryCandleStore()
    store.append(rows, [])
    return MarketDataService(store, source=DataSource.MT5, calendar=cal)


def test_freshness_on_holiday_is_market_closed_not_stale():
    now = u(2026, 9, 7, 19, 30)
    rows = rows_for(MQ, LD_START, now - TF.delta)
    assert rows[-1].close_time == u(2026, 9, 7, 18, 30)
    s = _service(MQ, rows).summary(now)
    assert s.session is MarketSession.HOLIDAY and s.freshness is Freshness.MARKET_CLOSED
    assert _service(MQ_NO_HOLIDAY, rows).summary(now).freshness is Freshness.STALE


def test_feed_dying_before_holiday_close_still_stale():
    now = u(2026, 9, 7, 19, 30)
    rows = [c for c in rows_for(MQ, LD_START, now) if c.close_time <= u(2026, 9, 7, 16)]
    assert _service(MQ, rows).summary(now).freshness is Freshness.STALE


# ---------------------------------------------------------------------------
# CAL-05: giờ đặc biệt của broker
# ---------------------------------------------------------------------------


def test_special_parse_and_version():
    s = BrokerSpecialHours.parse("2026-12-24 00:00-20:45;  2026-12-25 CLOSED", "v1")
    assert s.windows_on(date(2026, 12, 24)) == ((0, 1245),)
    assert s.windows_on(date(2026, 12, 25)) == ()
    assert s.windows_on(date(2026, 12, 23)) is None
    assert s.version.startswith("v1#")
    other = BrokerSpecialHours.parse("2026-12-24 00:00-20:30; 2026-12-25 CLOSED", "v1")
    assert other.version != s.version  # đổi nội dung là đổi phiên bản dù giữ nhãn


@pytest.mark.parametrize(
    "spec",
    [
        "",
        "24/12/2026 CLOSED",
        "2026-02-30 CLOSED",
        "2026-12-24",
        "2026-12-24 20:00-19:00",
        "2026-12-24 00:00-12:00, 11:00-13:00",
        "2026-12-24 CLOSED; 2026-12-24 00:00-10:00",
        "2026-12-24 25:00-26:00",
        "2026-12-24 0000-1000",
    ],
)
def test_special_parse_rejects(spec):
    with pytest.raises(ValueError):
        BrokerSpecialHours.parse(spec)


def test_special_requires_broker():
    with pytest.raises(ValueError):
        MarketCalendar(special=BrokerSpecialHours.parse("2026-12-24 CLOSED"))


def test_special_hours_in_server_time_winter_and_summer():
    cal = special("2026-12-24 00:00-20:45; 2026-07-02 00:00-21:30")
    # 20:45 Athens mùa đông (UTC+2) = 18:45 UTC
    assert cal.is_open(u(2026, 12, 24, 18, 30)) and not cal.is_open(u(2026, 12, 24, 18, 45))
    # 21:30 Athens mùa hè (UTC+3) = 18:30 UTC, ngày thường (thứ Năm) đóng sớm theo thông báo
    assert cal.is_open(u(2026, 7, 2, 18, 15)) and not cal.is_open(u(2026, 7, 2, 18, 30))
    assert cal.session_at(u(2026, 7, 2, 19)) is MarketSession.HOLIDAY
    # vẫn giao với lịch tham chiếu: 17:00–18:00 NY luôn đóng dù giờ đặc biệt mở
    wide = special("2026-07-02 00:00-24:00")
    assert not wide.is_open(u(2026, 7, 2, 21, 30))


def test_special_closed_day_and_other_days_unchanged():
    cal = special("2026-10-14 CLOSED")
    assert not cal.is_open(u(2026, 10, 14, 10))
    assert cal.session_at(u(2026, 10, 14, 10)) is MarketSession.HOLIDAY
    assert cal.is_open(u(2026, 10, 15, 10))
    assert not cal.is_open(u(2026, 10, 15, 20, 30))  # giờ tuần của broker vẫn áp ngày khác


def test_env_special_hours(monkeypatch):
    monkeypatch.setenv("GT_BROKER_SESSIONS", "Mon-Fri 00:00-23:00")
    monkeypatch.setenv("GT_BROKER_SERVER_TZ", ATHENS)
    monkeypatch.setenv("GT_BROKER_SPECIAL_HOURS", "2026-12-24 00:00-20:45")
    monkeypatch.setenv("GT_BROKER_SPECIAL_HOURS_VERSION", "tb-2026-12")
    cal = calendar_from_env(DataSource.MT5)
    assert cal.special is not None and "tb-2026-12#" in cal.description
    monkeypatch.setenv("GT_BROKER_SPECIAL_HOURS", "2026-12-24 nonsense")
    with pytest.raises(ValueError):
        create_app(InMemoryRepository(), data_source=DataSource.MT5, run_analysts=False)
    monkeypatch.setenv("GT_BROKER_SPECIAL_HOURS", "2026-12-24 CLOSED")
    monkeypatch.delenv("GT_BROKER_SESSIONS")
    with pytest.raises(ValueError, match="GT_BROKER_SESSIONS"):
        create_app(InMemoryRepository(), data_source=DataSource.MT5, run_analysts=False)


# ---------------------------------------------------------------------------
# CAL-04: cờ GAP lúc nạp + R1
# ---------------------------------------------------------------------------


def raw(t):
    return RawBar(open_time=t, open=4000.0, high=4001.0, low=3999.0, close=4000.5, tick_volume=9)


def _ingest(cal, bars, tf=TF, tz=None):
    store = InMemoryCandleStore()
    CandleIngestor(store, cal).ingest(
        bars,
        symbol="XAUUSD",
        timeframe=tf,
        source=DataSource.MT5,
        ingested_at=u(2026, 11, 1),
        backfill=True,
        server_tz=tz,
    )
    return {
        c.open_time: c.flags
        for c in store.query("XAUUSD", tf, DataSource.MT5, as_of=u(2030, 1, 1), limit=100)
    }


def test_ingest_gap_flag_respects_holiday_early_close():
    bars = [raw(u(2026, 9, 7, 18)), raw(u(2026, 9, 7, 18, 15)), raw(u(2026, 9, 7, 22))]
    assert CandleFlag.GAP_BEFORE not in _ingest(MQ, bars)[u(2026, 9, 7, 22)]
    assert CandleFlag.GAP_BEFORE in _ingest(MQ_NO_HOLIDAY, bars)[u(2026, 9, 7, 22)]
    # thiếu nến thật trước giờ đóng sớm vẫn bị gắn GAP
    gap = [raw(u(2026, 9, 7, 17, 30)), raw(u(2026, 9, 7, 18, 15))]
    assert CandleFlag.GAP_BEFORE in _ingest(MQ, gap)[u(2026, 9, 7, 18, 15)]


def test_ingest_d1_good_friday_no_gap():
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(ATHENS)
    days = [datetime(2026, 4, d, tzinfo=tz).astimezone(UTC) for d in (2, 6)]  # T5, T2
    flags = _ingest(MQ, [raw(t) for t in days], Timeframe.D1, tz)
    assert CandleFlag.GAP_BEFORE not in flags[days[1]]
    assert (
        CandleFlag.GAP_BEFORE
        in _ingest(MQ_NO_HOLIDAY, [raw(t) for t in days], Timeframe.D1, tz)[days[1]]
    )


def test_r1_uses_weekly_part_only():
    # Broker báo giá cả Good Friday (bảng ghi đóng): R1 KHÔNG được từ chối cả lô vì ngày lễ
    times = expected_open_times(u(2026, 3, 31), u(2026, 4, 3, 19, 45), TF, MQ_NO_HOLIDAY)
    bars = [raw(t) for t in times]
    assert check_sessions(bars, 15, MQ).outside_fraction == 0.0
    # nhưng có dùng giờ tuần của broker: nến lúc 23:00 server (20:00 UTC mùa hè) là ngoài giờ
    late = [raw(u(2026, 4, 1, 20) + TF.delta * k) for k in range(4)]
    assert check_sessions(late, 15, MQ).outside_fraction == 1.0
    assert check_sessions(late, 15, REFERENCE).outside_fraction == 0.0


def test_api_r1_not_rejected_by_holiday_and_dry_run_uses_calendar():
    from tests.auth_helpers import user_client
    from tests.mt5_helpers import IDENT_FIELDS, link_active

    token = "t" * 32
    repo = InMemoryRepository()
    link_active(repo)
    c = user_client(
        repo,
        candle_store=InMemoryCandleStore(),
        data_source=DataSource.MT5,
        run_sample_feed=False,
        run_analysts=False,
        ingest_token=token,
        calendar=MQ,
    )
    times = expected_open_times(u(2026, 3, 30), u(2026, 4, 3, 19, 45), TF, MQ_NO_HOLIDAY)
    body = {
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "backfill": True,
        "gateway_id": "win-1",
        **IDENT_FIELDS,
        "bars": [
            {
                "open_time": t.isoformat(),
                "open": 4000,
                "high": 4001,
                "low": 3999,
                "close": 4000.5,
                "tick_volume": 1,
                "spread_points": 20,
            }
            for t in times
        ],
    }
    auth = {"Authorization": f"Bearer {token}"}
    for path in ("/api/ingest/mt5/candles?dry_run=true", "/api/ingest/mt5/candles"):
        r = c.post(path, json=body, headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["session_outside_fraction"] == 0.0


# ---------------------------------------------------------------------------
# Dữ liệu mẫu theo cùng lịch (không sinh nến trong ngày lễ)
# ---------------------------------------------------------------------------


def test_sample_generator_skips_holidays():
    bars = list(
        sample.generate(start=u(2026, 4, 2), end=u(2026, 4, 6), tf=TF, prev_close=4000, seed=1)
    )
    assert bars and all(REFERENCE.bar_in_session(b.open_time, b.open_time + TF.delta) for b in bars)
    assert not [b for b in bars if b.open_time.date() == date(2026, 4, 3)]


def test_api_r1_uses_broker_weekly_hours():
    """CAL-04: R1 ở cổng nạp dùng giờ tuần của broker (trước đây chỉ lịch tham chiếu)."""
    from tests.auth_helpers import user_client
    from tests.mt5_helpers import IDENT_FIELDS, link_active

    token = "t" * 32
    repo = InMemoryRepository()
    link_active(repo)
    c = user_client(
        repo,
        candle_store=InMemoryCandleStore(),
        data_source=DataSource.MT5,
        run_sample_feed=False,
        run_analysts=False,
        ingest_token=token,
        calendar=MQ,
    )
    # nến cả lúc 23:00–24:00 server (broker công bố là đóng): 4/92 mỗi ngày ≈ 4% > 1%
    times = expected_open_times(u(2026, 10, 12), u(2026, 10, 16, 12), TF, WEEKLY_ONLY)
    body = {
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "backfill": True,
        "gateway_id": "win-1",
        **IDENT_FIELDS,
        "bars": [
            {
                "open_time": t.isoformat(),
                "open": 4000,
                "high": 4001,
                "low": 3999,
                "close": 4000.5,
                "tick_volume": 1,
                "spread_points": 20,
            }
            for t in times
        ],
    }
    r = c.post("/api/ingest/mt5/candles", json=body, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 422 and "giờ đóng cửa" in r.json()["detail"]
