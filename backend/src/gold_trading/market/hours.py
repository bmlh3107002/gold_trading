"""Lịch giao dịch vàng giao ngay (XAUUSD) theo quy ước phổ biến của thị trường FX/kim loại.

- Mở cửa tuần: Chủ nhật 18:00 giờ New York. Đóng cửa tuần: thứ Sáu 17:00 giờ New York.
- Nghỉ hằng ngày: 17:00–18:00 giờ New York (thứ Hai–thứ Năm).

Dùng giờ New York để tự xử lý DST. Broker có thể lệch vài phút hoặc nghỉ lễ riêng:
đây là lịch tham chiếu, không thay thế lịch của broker (sau này lấy từ MT5).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
_ROLL = time(17, 0)
_REOPEN = time(18, 0)


class MarketSession(StrEnum):
    OPEN = "OPEN"
    DAILY_BREAK = "DAILY_BREAK"
    WEEKEND = "WEEKEND"


def session_at(t: datetime) -> MarketSession:
    ny = t.astimezone(NY)
    wd = ny.weekday()  # Mon=0 … Sun=6
    tod = ny.time()
    if wd == 5:  # thứ Bảy
        return MarketSession.WEEKEND
    if wd == 4 and tod >= _ROLL:  # thứ Sáu sau 17:00
        return MarketSession.WEEKEND
    if wd == 6 and tod < _REOPEN:  # Chủ nhật trước 18:00
        return MarketSession.WEEKEND
    if _ROLL <= tod < _REOPEN:
        return MarketSession.DAILY_BREAK
    return MarketSession.OPEN


def is_open(t: datetime) -> bool:
    return session_at(t) is MarketSession.OPEN


def bar_in_session(open_time: datetime, close_time: datetime) -> bool:
    """Nến có nằm trọn trong giờ mở cửa không (dùng cho dữ liệu mẫu và phát hiện gap)."""
    return is_open(open_time) and is_open(close_time - timedelta(microseconds=1))
