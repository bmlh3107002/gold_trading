"""GĐ6 bước 2 (Q8 = A) — bảng ngày lễ mở rộng 2020–2023 cho backtest.

Kiểm ngày bằng **quy tắc tính độc lập** (Phục sinh theo thuật toán Gregory ẩn danh, thứ Hai thứ n,
nghỉ bù cuối tuần) — không chép từ bảng. Giờ đóng / nghỉ thật vẫn phải đối chiếu dữ liệu sàn
(``compare_gaps``) trước khi chạy backtest.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from gold_trading.backtest.holidays import (
    BACKTEST_HOLIDAYS,
    HISTORICAL,
    UNVERIFIED,
    compare_gaps,
)
from gold_trading.market.holidays import US_HOLIDAYS, US_HOLIDAYS_VERSION, HolidayKind
from gold_trading.market.hours import REFERENCE, MarketCalendar


def easter(y: int) -> date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    return date(y, month, (h + m - 7 * n + 114) % 31 + 1)


def nth(y: int, month: int, weekday: int, n: int) -> date:
    d = date(y, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def last(y: int, month: int, weekday: int) -> date:
    d = date(y, month + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def observed(d: date) -> date:
    return d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) \
        if d.weekday() == 6 else d


@pytest.mark.parametrize("y", [2020, 2021, 2022, 2023])
def test_dates_follow_independent_rules(y):
    days = {h.day for h in HISTORICAL if h.day.year == y}
    want = {nth(y, 1, 0, 3), nth(y, 2, 0, 3), easter(y) - timedelta(days=2), last(y, 5, 0),
            observed(date(y, 7, 4)), nth(y, 9, 0, 1), nth(y, 11, 3, 4),
            nth(y, 11, 3, 4) + timedelta(days=1), observed(date(y, 12, 25))}
    ny = date(y, 1, 1)
    if ny.weekday() != 5:                                    # năm mới thứ Bảy: không nghỉ bù
        want.add(observed(ny))
    if y >= 2022:
        want.add(observed(date(y, 6, 19)))                  # Juneteenth: sàn nghỉ từ 2022
    xmas_eve = date(y, 12, 24)
    if xmas_eve.weekday() < 5 and observed(date(y, 12, 25)) != xmas_eve:
        want.add(xmas_eve)                                  # đêm Giáng sinh ngày thường: đóng sớm
    extra = {date(2023, 7, 3)} if y == 2023 else set()      # ghi chú CHƯA CHẮC
    assert days == want | extra, (sorted(days - want - extra), sorted(want - days))


def test_good_friday_and_christmas_closed_halts_early_closes():
    for h in HISTORICAL:
        assert h.source == UNVERIFIED and h.day.weekday() < 5
        if h.name.startswith(("Good Friday", "Christmas Day", "New Year")):
            assert h.kind is HolidayKind.CLOSED, h
        if h.name.startswith(("Day after Thanksgiving", "Christmas Eve")):
            assert h.kind is HolidayKind.EARLY_CLOSE and h.close_ny.hour == 13, h


def test_live_table_untouched_and_merged_whole():
    assert US_HOLIDAYS.version == US_HOLIDAYS_VERSION == "us-holidays-2026.11.07"
    assert US_HOLIDAYS.years == frozenset({2024, 2025, 2026, 2027})
    assert set(US_HOLIDAYS.holidays) <= set(BACKTEST_HOLIDAYS.holidays)
    assert BACKTEST_HOLIDAYS.version.startswith(US_HOLIDAYS_VERSION)
    assert len(BACKTEST_HOLIDAYS.holidays) == len(US_HOLIDAYS.holidays) + len(HISTORICAL)


def test_backtest_calendar_covers_2020_live_does_not():
    t = datetime(2020, 4, 10, 14, 0, tzinfo=UTC)            # Good Friday 2020
    cal = MarketCalendar(holidays=BACKTEST_HOLIDAYS)
    assert cal.covers(t) and not REFERENCE.covers(t)
    assert not cal.is_open(t) and REFERENCE.is_open(t)       # bảng thật không biết năm 2020
    assert cal.is_open(datetime(2020, 4, 13, 14, 0, tzinfo=UTC))


def test_compare_gaps_reports_each_kind():
    gf, eve, nobody = date(2021, 4, 2), date(2020, 12, 24), date(2022, 3, 15)
    miss = {gf: 0, eve: 0, nobody: 92, date(2020, 4, 10): 92}
    have = {gf: 92, eve: 92, nobody: 0, date(2020, 4, 10): 0}
    m = {x.day: x.kind for x in compare_gaps(miss, have)}
    assert m == {gf: "TABLE_CLOSED_BUT_DATA", eve: "EARLY_CLOSE_MISMATCH",
                 nobody: "DATA_CLOSED_NOT_IN_TABLE"}
    assert compare_gaps({date(2020, 4, 10): 92}, {date(2020, 4, 10): 0}) == []
    assert compare_gaps(miss, have, years=[2023]) == []
