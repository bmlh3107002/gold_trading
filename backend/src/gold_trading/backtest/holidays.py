"""Bảng ngày lễ mở rộng 2020–2027 cho backtest (GĐ6 bước 2 — Q8 = A; thiết kế 39 mục 8 bias 0).

**Không sửa** bảng ngày lễ của hệ thống thật (``market/holidays.py`` — phiên bản bảng đi vào mọi
kết quả analyst; đổi trong lúc kiểm Gate có thể làm lệch replay). Backtest dùng bảng riêng =
bảng thật (2024–2027, nguyên vẹn) + 2020–2023 soạn ở đây, truyền vào
``MarketCalendar(holidays=BACKTEST_HOLIDAYS)``.

Ngày 2020–2023 soạn theo **thông lệ CME Globex kim loại** (như bảng thật: lễ thứ Hai / giữa tuần
ngừng 14:30 NY; ngày sau Lễ Tạ ơn + đêm Giáng sinh đóng 13:45 NY; Good Friday, Giáng sinh, năm mới
nghỉ trọn; lễ rơi cuối tuần → nghỉ bù, trừ năm mới rơi thứ Bảy). Nguồn ``CME_PATTERN_UNVERIFIED``:
**chưa đối chiếu** — bắt buộc đối chiếu với chỗ hở nến thật của sàn người dùng (``compare_gaps``)
trước khi chạy backtest; dòng nào lệch dữ liệu thì sửa theo dữ liệu sàn (nguồn ``BROKER_DATA``).
Các ngày người phát triển **không chắc** ghi chú ``# CHƯA CHẮC`` (Good Friday 2021 / 2023 trùng ngày
ra NFP; 03/07/2023; 24/12/2021).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, time

from gold_trading.market.holidays import (
    US_HOLIDAYS,
    Holiday,
    HolidayKind,
    HolidayTable,
)

UNVERIFIED = "CME_PATTERN_UNVERIFIED"
_HALT = time(14, 30)   # 13:30 CT
_EARLY = time(13, 45)  # 12:45 CT


def _h(y: int, m: int, d: int, name: str, close: time | None = None, src: str = UNVERIFIED):
    kind = HolidayKind.CLOSED if close is None else HolidayKind.EARLY_CLOSE
    return Holiday(date(y, m, d), name, kind, close, src)


HISTORICAL = (
    # 2020
    _h(2020, 1, 1, "New Year's Day"),
    _h(2020, 1, 20, "Martin Luther King Jr. Day", _HALT),
    _h(2020, 2, 17, "Presidents' Day", _HALT),
    _h(2020, 4, 10, "Good Friday"),
    _h(2020, 5, 25, "Memorial Day", _HALT),
    _h(2020, 7, 3, "Independence Day (observed)", _HALT),  # 04/07 là thứ Bảy
    _h(2020, 9, 7, "Labor Day", _HALT),
    _h(2020, 11, 26, "Thanksgiving Day", _HALT),
    _h(2020, 11, 27, "Day after Thanksgiving", _EARLY),
    _h(2020, 12, 24, "Christmas Eve", _EARLY),
    _h(2020, 12, 25, "Christmas Day"),
    # 2021
    _h(2021, 1, 1, "New Year's Day"),
    _h(2021, 1, 18, "Martin Luther King Jr. Day", _HALT),
    _h(2021, 2, 15, "Presidents' Day", _HALT),
    _h(2021, 4, 2, "Good Friday"),                          # CHƯA CHẮC: trùng ngày ra NFP
    _h(2021, 5, 31, "Memorial Day", _HALT),
    _h(2021, 7, 5, "Independence Day (observed)", _HALT),  # 04/07 là Chủ nhật
    _h(2021, 9, 6, "Labor Day", _HALT),
    _h(2021, 11, 25, "Thanksgiving Day", _HALT),
    _h(2021, 11, 26, "Day after Thanksgiving", _EARLY),
    _h(2021, 12, 24, "Christmas Day (observed)"),           # CHƯA CHẮC: 25/12 là thứ Bảy
    # 01/01/2022 là thứ Bảy: không nghỉ bù 31/12/2021
    # 2022
    _h(2022, 1, 17, "Martin Luther King Jr. Day", _HALT),
    _h(2022, 2, 21, "Presidents' Day", _HALT),
    _h(2022, 4, 15, "Good Friday"),
    _h(2022, 5, 30, "Memorial Day", _HALT),
    _h(2022, 6, 20, "Juneteenth (observed)", _HALT),        # năm đầu sàn nghỉ; 19/06 là Chủ nhật
    _h(2022, 7, 4, "Independence Day", _HALT),
    _h(2022, 9, 5, "Labor Day", _HALT),
    _h(2022, 11, 24, "Thanksgiving Day", _HALT),
    _h(2022, 11, 25, "Day after Thanksgiving", _EARLY),
    _h(2022, 12, 26, "Christmas Day (observed)"),           # 25/12 là Chủ nhật
    # 2023
    _h(2023, 1, 2, "New Year's Day (observed)"),            # 01/01 là Chủ nhật
    _h(2023, 1, 16, "Martin Luther King Jr. Day", _HALT),
    _h(2023, 2, 20, "Presidents' Day", _HALT),
    _h(2023, 4, 7, "Good Friday"),                          # CHƯA CHẮC: trùng ngày ra NFP
    _h(2023, 5, 29, "Memorial Day", _HALT),
    _h(2023, 6, 19, "Juneteenth", _HALT),
    _h(2023, 7, 3, "Day before Independence Day", _EARLY),  # CHƯA CHẮC
    _h(2023, 7, 4, "Independence Day", _HALT),
    _h(2023, 9, 4, "Labor Day", _HALT),
    _h(2023, 11, 23, "Thanksgiving Day", _HALT),
    _h(2023, 11, 24, "Day after Thanksgiving", _EARLY),
    _h(2023, 12, 25, "Christmas Day"),
)

BACKTEST_HOLIDAYS = HolidayTable(
    version=f"{US_HOLIDAYS.version}+bt-2020-2023-draft-2026.11.23",
    years=frozenset({2020, 2021, 2022, 2023}) | US_HOLIDAYS.years,
    holidays=tuple(sorted((*HISTORICAL, *US_HOLIDAYS.holidays), key=lambda h: h.day)),
)


# ---------------------------------------------------------------------- đối chiếu dữ liệu thật


@dataclass(frozen=True)
class Mismatch:
    day: date
    kind: str            # TABLE_CLOSED_BUT_DATA / DATA_CLOSED_NOT_IN_TABLE / EARLY_CLOSE_MISMATCH
    detail: str


FULL_DAY_MIN_MISSING = 80   # M15: ngày thường ~92 nến; thiếu ≥ 80 = coi như nghỉ trọn


def compare_gaps(missing_by_day: Mapping[date, int], present_by_day: Mapping[date, int],
                 table: HolidayTable = BACKTEST_HOLIDAYS, *,
                 years: Iterable[int] | None = None) -> list[Mismatch]:
    """Đối chiếu bảng ngày lễ với dữ liệu thật (M15, chỗ hở tính theo lịch **không** có ngày lễ).

    ``missing_by_day`` / ``present_by_day``: ngày giao dịch NY → số nến M15 thiếu / có. Trả các
    chỗ lệch để người phát triển sửa bảng theo dữ liệu sàn — không tự sửa."""
    ys = set(years) if years is not None else set(table.years)
    out: list[Mismatch] = []
    days = sorted(set(missing_by_day) | set(present_by_day))
    for d in days:
        if d.year not in ys:
            continue
        miss, have = missing_by_day.get(d, 0), present_by_day.get(d, 0)
        h = table.on(d)
        if h is not None and h.kind is HolidayKind.CLOSED and have > 0:
            out.append(Mismatch(d, "TABLE_CLOSED_BUT_DATA",
                                f"{h.name}: bảng ghi nghỉ trọn nhưng có {have} nến"))
        elif h is None and miss >= FULL_DAY_MIN_MISSING:
            out.append(Mismatch(d, "DATA_CLOSED_NOT_IN_TABLE",
                                f"thiếu {miss} nến nhưng bảng không có ngày lễ"))
        elif h is not None and h.kind is HolidayKind.EARLY_CLOSE and miss == 0 and have > 0:
            out.append(Mismatch(d, "EARLY_CLOSE_MISMATCH",
                                f"{h.name}: bảng ghi đóng sớm {h.close_ny} nhưng đủ nến"))
    return out
