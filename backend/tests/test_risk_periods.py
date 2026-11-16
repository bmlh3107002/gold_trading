"""GĐ5 bước 4a — mốc ngày / tuần / tháng giao dịch (H4: 17:00 New York), gồm đổi giờ DST."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from gold_trading.risk.periods import Periods

P = Periods.of("America/New_York", "17:00")


def u(*a):
    return datetime(*a, tzinfo=UTC)


def test_day_start_winter_and_summer():
    # Mùa đông (EST, UTC−5): 17:00 NY = 22:00 UTC; mùa hè (EDT, UTC−4) = 21:00 UTC
    assert P.day_start(u(2026, 11, 16, 23, 0)) == u(2026, 11, 16, 22, 0)
    assert P.day_start(u(2026, 11, 16, 21, 59)) == u(2026, 11, 15, 22, 0)
    assert P.day_start(u(2026, 7, 15, 21, 0)) == u(2026, 7, 15, 21, 0)       # đúng mốc → kỳ mới
    assert P.day_start(u(2026, 7, 15, 20, 59, 59)) == u(2026, 7, 14, 21, 0)
    assert P.next_day_start(u(2026, 7, 15, 20, 59)) == u(2026, 7, 15, 21, 0)


def test_dst_transition_days_us():
    # Mỹ đổi giờ 08/03/2026 (02:00) và 01/11/2026. Ngày giao dịch qua đêm đổi giờ dài 23 / 25 giờ.
    s = P.day_start(u(2026, 3, 8, 12, 0))        # mốc 07/03 17:00 EST = 22:00 UTC
    e = P.next_day_start(u(2026, 3, 8, 12, 0))   # mốc 08/03 17:00 EDT = 21:00 UTC
    assert (s, e) == (u(2026, 3, 7, 22, 0), u(2026, 3, 8, 21, 0))
    assert e - s == timedelta(hours=23)
    s2 = P.day_start(u(2026, 11, 1, 12, 0))
    e2 = P.next_day_start(u(2026, 11, 1, 12, 0))
    assert (s2, e2) == (u(2026, 10, 31, 21, 0), u(2026, 11, 1, 22, 0))
    assert e2 - s2 == timedelta(hours=25)


def test_europe_dst_does_not_affect_new_york_boundary():
    # Châu Âu đổi giờ 29/03/2026; Mỹ đã đổi từ 08/03 → mốc vẫn 21:00 UTC cả hai phía
    assert P.day_start(u(2026, 3, 30, 12, 0)) == u(2026, 3, 29, 21, 0)
    assert P.day_start(u(2026, 3, 28, 12, 0)) == u(2026, 3, 27, 21, 0)


def test_trade_date_labels_by_end_boundary():
    assert P.trade_date(u(2026, 11, 16, 23, 0)) == date(2026, 11, 17)   # sau 17:00 thứ Hai
    assert P.trade_date(u(2026, 11, 16, 12, 0)) == date(2026, 11, 16)


def test_week_starts_sunday_17_ny():
    # Thứ Tư 18/11/2026 → tuần bắt đầu CN 15/11 17:00 EST = 22:00 UTC
    assert P.week_start(u(2026, 11, 18, 12, 0)) == u(2026, 11, 15, 22, 0)
    # Đúng CN 15/11 lúc 16:59 NY (thị trường đóng) → còn thuộc tuần trước
    assert P.week_start(u(2026, 11, 15, 21, 59)) == u(2026, 11, 8, 22, 0)
    assert P.week_start(u(2026, 11, 15, 22, 0)) == u(2026, 11, 15, 22, 0)
    # Thứ Sáu sau giờ đóng cửa + thứ Bảy vẫn cùng tuần
    assert P.week_start(u(2026, 11, 21, 15, 0)) == u(2026, 11, 15, 22, 0)
    assert P.next_week_start(u(2026, 11, 18, 12, 0)) == u(2026, 11, 22, 22, 0)


def test_week_across_dst_change():
    # Tuần chứa 01/11/2026 (Mỹ lùi giờ): bắt đầu CN 01/11 17:00 EST = 22:00 UTC
    assert P.week_start(u(2026, 11, 2, 12, 0)) == u(2026, 11, 1, 22, 0)
    assert P.week_start(u(2026, 10, 30, 12, 0)) == u(2026, 10, 25, 21, 0)   # EDT


def test_month_start_is_first_trading_day_boundary():
    # Tháng 12/2026: mốc 30/11 17:00 EST = 22:00 UTC
    assert P.month_start(u(2026, 12, 15, 12, 0)) == u(2026, 11, 30, 22, 0)
    # 30/11 lúc 17:30 NY đã là ngày giao dịch 01/12 → tháng 12
    assert P.month_start(u(2026, 11, 30, 22, 30)) == u(2026, 11, 30, 22, 0)
    assert P.month_start(u(2026, 11, 30, 21, 59)) == u(2026, 10, 31, 21, 0)  # tháng 11 (EDT)
    assert P.next_month_start(u(2026, 12, 15, 12, 0)) == u(2026, 12, 31, 22, 0)
    assert P.next_month_start(u(2026, 12, 31, 22, 30)) == u(2027, 1, 31, 22, 0)


@pytest.mark.parametrize("tz,hm", [("Asia/Ho_Chi_Minh", "00:00"), ("Europe/London", "01:30"),
                                   ("America/New_York", "02:30")])
def test_invariants_random_hours(tz, hm):
    # Bất biến trên 2 năm theo từng giờ: start ≤ t < next; kỳ liên tiếp nối nhau, không chồng
    p = Periods.of(tz, hm)
    t = u(2026, 1, 1)
    prev_next = None
    while t < u(2028, 1, 1):
        s, n = p.day_start(t), p.next_day_start(t)
        assert s <= t < n and timedelta(hours=22) <= n - s <= timedelta(hours=26)
        ws, wn = p.week_start(t), p.next_week_start(t)
        assert ws <= t < wn and ws.astimezone(p.tz).weekday() == 6
        ms, mn = p.month_start(t), p.next_month_start(t)
        assert ms <= t < mn
        if prev_next is not None and s >= prev_next:
            assert s == prev_next           # kỳ mới bắt đầu đúng ở mốc kết thúc kỳ trước
        prev_next = n
        t += timedelta(minutes=53)


def test_naive_time_rejected():
    with pytest.raises(ValueError):
        P.day_start(datetime(2026, 11, 16, 12, 0))
