"""Bảng ngày lễ / đóng sớm của thị trường vàng Mỹ, có phiên bản (CAL-03, 1B).

Quy ước (giờ New York, giống lịch tham chiếu ``hours.py``):

- ``CLOSED`` ngày D: nghỉ trọn phiên của ngày giao dịch D, tức ``[D-1 17:00, D 18:00)`` giờ NY.
  Thị trường mở lại lúc 18:00 NY ngày D (phiên của ngày D+1), hoặc Chủ nhật 18:00 nếu D là thứ Sáu.
- ``EARLY_CLOSE`` ngày D lúc ``c``: nghỉ ``[D c, D 18:00)`` giờ NY, mở lại bình thường lúc 18:00.

Nguồn (ghi theo từng dòng ở cột ``source``):

- ``BROKER_DATA``: đã đối chiếu với dữ liệu thật của broker người dùng (MetaQuotes-Demo).
  Labor Day 07/09/2026: broker ngừng báo giá lúc 14:30 NY (13:30 giờ Chicago), thiếu thêm đúng
  6 nến M15 so với ngày thường (GĐ0, nhật ký 2026-11-05).
- ``CME_PATTERN``: theo lịch nghỉ lễ thường lệ của CME Globex cho kim loại (cmegroup.com →
  Holiday Calendar): ngày lễ thứ Hai và ngày lễ giữa tuần ngừng 13:30 CT = 14:30 NY; ngày sau Lễ Tạ
  ơn và đêm Giáng sinh đóng sớm 12:45 CT = 13:45 NY; Good Friday, Giáng sinh, năm mới nghỉ trọn
  ngày. **Chưa đối chiếu dữ liệu broker**; broker giao ngay có thể lệch. CME chốt giờ lễ khoảng 2
  tuần trước mỗi ngày lễ, nên mỗi năm phải soát lại.

Bảng sai theo hướng nào cũng bị chặn, không cho phép âm thầm (docs/thiet-ke/03, mục "Lịch giao
dịch"): ghi đóng mà broker vẫn báo giá → có nến lúc "đóng cửa" → ``CALENDAR_MISMATCH``; ghi mở mà
broker đóng → thiếu nến → R2. Sửa bằng ``GT_BROKER_SPECIAL_HOURS`` (CAL-05) hoặc sửa bảng.

Ngoài các năm có trong bảng: không biết ngày lễ → coi như không có ngày lễ (mọi nến đều "lẽ ra
phải có", R2 có thể chặn oan — hướng an toàn), và ``covers`` trả ``False`` để cảnh báo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

# Giống ``hours.py`` (không import để tránh vòng lặp: hours.py dùng module này).
NY = ZoneInfo("America/New_York")
ROLL = time(17, 0)
REOPEN = time(18, 0)

# Đổi bảng (thêm năm, sửa giờ) → tăng phiên bản. Phiên bản đi vào ``MarketCalendar.description``
# và được ghi kèm mỗi kết quả analyst (``features.input.calendar``).
US_HOLIDAYS_VERSION = "us-holidays-2026.11.07"

# Thời gian thanh khoản thấp cuối năm theo ngày giao dịch NY (1B-C04): 24/12 → 02/01.
_YEAR_END_FROM = (12, 24)
_YEAR_END_TO = (1, 2)


class HolidayKind(StrEnum):
    CLOSED = "CLOSED"
    EARLY_CLOSE = "EARLY_CLOSE"


@dataclass(frozen=True)
class Holiday:
    day: date  # ngày giao dịch theo giờ New York (ngày được nghỉ bù nếu lễ rơi cuối tuần)
    name: str
    kind: HolidayKind
    close_ny: time | None = None  # chỉ cho EARLY_CLOSE
    source: str = "CME_PATTERN"

    def __post_init__(self) -> None:
        if self.day.weekday() >= 5:
            raise ValueError(f"Ngày lễ {self.name} {self.day} rơi vào cuối tuần: ghi ngày nghỉ bù")
        if (self.kind is HolidayKind.EARLY_CLOSE) != (self.close_ny is not None):
            raise ValueError(f"{self.name} {self.day}: EARLY_CLOSE cần close_ny, CLOSED thì không")
        if self.close_ny is not None and not (time(0, 0) < self.close_ny < ROLL):
            raise ValueError(f"{self.name} {self.day}: giờ đóng sớm phải trước 17:00 NY")

    def closure_ny(self) -> tuple[datetime, datetime]:
        """Khoảng nghỉ [bắt đầu, kết thúc) theo giờ NY (datetime có tz)."""
        end = datetime.combine(self.day, REOPEN, NY)
        if self.kind is HolidayKind.CLOSED:
            start = datetime.combine(self.day - timedelta(days=1), ROLL, NY)
        else:
            assert self.close_ny is not None
            start = datetime.combine(self.day, self.close_ny, NY)
        return start, end


def trade_date(t: datetime) -> date:
    """Ngày giao dịch NY: phiên bắt đầu 18:00 hôm trước, nên cộng 6 giờ rồi lấy ngày."""
    return (t.astimezone(NY) + timedelta(hours=6)).date()


@dataclass(frozen=True)
class HolidayTable:
    version: str
    years: frozenset[int]
    holidays: tuple[Holiday, ...]
    _by_day: dict[date, Holiday] = field(init=False, repr=False, compare=False, hash=False)

    def __post_init__(self) -> None:
        by_day: dict[date, Holiday] = {}
        for h in self.holidays:
            if h.day.year not in self.years:
                raise ValueError(
                    f"{h.name} {h.day} nằm ngoài các năm của bảng {sorted(self.years)}"
                )
            if h.day in by_day:
                raise ValueError(f"Trùng ngày lễ {h.day}")
            by_day[h.day] = h
        object.__setattr__(self, "_by_day", by_day)

    def covers(self, t: datetime) -> bool:
        return trade_date(t).year in self.years

    def on(self, d: date) -> Holiday | None:
        return self._by_day.get(d)

    def closure_at(self, t: datetime) -> Holiday | None:
        """Ngày lễ đang làm thị trường đóng tại ``t`` (None nếu không)."""
        ny = t.astimezone(NY)
        # CLOSED ngày D bắt đầu từ 17:00 ngày D-1 → xét cả ngày hôm nay và ngày mai.
        for d in (ny.date(), ny.date() + timedelta(days=1)):
            h = self._by_day.get(d)
            if h is not None:
                start, end = h.closure_ny()
                if start <= ny < end:
                    return h
        return None

    def low_liquidity(self, t: datetime) -> bool:
        """1B-C04: ngày lễ / đóng sớm, hoặc 24/12 → 02/01 (theo ngày giao dịch NY)."""
        d = trade_date(t)
        if d in self._by_day:
            return True
        md = (d.month, d.day)
        return md >= _YEAR_END_FROM or md <= _YEAR_END_TO


def _h(y: int, m: int, d: int, name: str, close: time | None = None, src: str = "CME_PATTERN"):
    kind = HolidayKind.CLOSED if close is None else HolidayKind.EARLY_CLOSE
    return Holiday(date(y, m, d), name, kind, close, src)


_HALT = time(14, 30)  # 13:30 CT
_EARLY = time(13, 45)  # 12:45 CT

# Ngày lễ rơi cuối tuần: thứ Bảy → nghỉ bù thứ Sáu, Chủ nhật → nghỉ bù thứ Hai (1B-C02).
# Ngoại lệ theo thông lệ sàn Mỹ: năm mới rơi thứ Bảy thì KHÔNG nghỉ bù thứ Sáu 31/12.
US_HOLIDAYS = HolidayTable(
    version=US_HOLIDAYS_VERSION,
    years=frozenset({2024, 2025, 2026, 2027}),
    holidays=(
        # 2024
        _h(2024, 1, 1, "New Year's Day"),
        _h(2024, 1, 15, "Martin Luther King Jr. Day", _HALT),
        _h(2024, 2, 19, "Presidents' Day", _HALT),
        _h(2024, 3, 29, "Good Friday"),
        _h(2024, 5, 27, "Memorial Day", _HALT),
        _h(2024, 6, 19, "Juneteenth", _HALT),
        _h(2024, 7, 4, "Independence Day", _HALT),
        _h(2024, 9, 2, "Labor Day", _HALT),
        _h(2024, 11, 28, "Thanksgiving Day", _HALT),
        _h(2024, 11, 29, "Day after Thanksgiving", _EARLY),
        _h(2024, 12, 24, "Christmas Eve", _EARLY),
        _h(2024, 12, 25, "Christmas Day"),
        # 2025
        _h(2025, 1, 1, "New Year's Day"),
        _h(2025, 1, 20, "Martin Luther King Jr. Day", _HALT),
        _h(2025, 2, 17, "Presidents' Day", _HALT),
        _h(2025, 4, 18, "Good Friday"),
        _h(2025, 5, 26, "Memorial Day", _HALT),
        _h(2025, 6, 19, "Juneteenth", _HALT),
        _h(2025, 7, 4, "Independence Day", _HALT),
        _h(2025, 9, 1, "Labor Day", _HALT),
        _h(2025, 11, 27, "Thanksgiving Day", _HALT),
        _h(2025, 11, 28, "Day after Thanksgiving", _EARLY),
        _h(2025, 12, 24, "Christmas Eve", _EARLY),
        _h(2025, 12, 25, "Christmas Day"),
        # 2026
        _h(2026, 1, 1, "New Year's Day"),
        _h(2026, 1, 19, "Martin Luther King Jr. Day", _HALT),
        _h(2026, 2, 16, "Presidents' Day", _HALT),
        _h(2026, 4, 3, "Good Friday"),
        _h(2026, 5, 25, "Memorial Day", _HALT),
        _h(2026, 6, 19, "Juneteenth", _HALT),
        _h(2026, 7, 3, "Independence Day (observed)", _HALT),  # 04/07 là thứ Bảy
        _h(2026, 9, 7, "Labor Day", _HALT, "BROKER_DATA"),
        _h(2026, 11, 26, "Thanksgiving Day", _HALT),
        _h(2026, 11, 27, "Day after Thanksgiving", _EARLY),
        _h(2026, 12, 24, "Christmas Eve", _EARLY),
        _h(2026, 12, 25, "Christmas Day"),
        # 2027
        _h(2027, 1, 1, "New Year's Day"),
        _h(2027, 1, 18, "Martin Luther King Jr. Day", _HALT),
        _h(2027, 2, 15, "Presidents' Day", _HALT),
        _h(2027, 3, 26, "Good Friday"),
        _h(2027, 5, 31, "Memorial Day", _HALT),
        _h(2027, 6, 18, "Juneteenth (observed)", _HALT),  # 19/06 là thứ Bảy
        _h(2027, 7, 5, "Independence Day (observed)", _HALT),  # 04/07 là Chủ nhật
        _h(2027, 9, 6, "Labor Day", _HALT),
        _h(2027, 11, 25, "Thanksgiving Day", _HALT),
        _h(2027, 11, 26, "Day after Thanksgiving", _EARLY),
        _h(2027, 12, 24, "Christmas Day (observed)"),  # 25/12 là thứ Bảy
        # 01/01/2028 là thứ Bảy: không nghỉ bù 31/12/2027 (thông lệ sàn Mỹ)
    ),
)
