"""Ngày lễ liên bang Mỹ theo luật (5 U.S.C. 6103) — dùng cho lịch công bố của cơ quan chính phủ.

Khác bảng ngày lễ **thị trường** (``holidays.py``): chính phủ nghỉ cả Columbus Day và Veterans Day
(thị trường vẫn mở), không nghỉ Good Friday. Bước 8f (DOL) cần bảng này: tuần có ngày lễ liên bang
thì DOL có thể dời ngày công bố số trợ cấp thất nghiệp.

Quy tắc (5 U.S.C. 6103(a), (b); Executive Order 11582): ngày cố định rơi thứ Bảy → nghỉ bù thứ Sáu
trước đó; rơi Chủ nhật → nghỉ bù thứ Hai sau đó. Ngày Nhậm chức (20/01 sau năm bầu cử, chỉ khu vực
Washington DC — trụ sở DOL) cũng tính; rơi Chủ nhật → 21/01.

**Không** biết được ngày nghỉ đột xuất theo sắc lệnh (vd. tổng thống cho nghỉ đêm Giáng sinh):
nơi dùng bảng phải đối chiếu sau khi công bố (DOL: giờ ghi trong bản tin). Bảng chưa đối chiếu với
trang OPM (OPM chặn máy chủ đám mây) — đã đối chiếu chéo với bảng ngày lễ thị trường (test).
"""

from __future__ import annotations

from datetime import date, timedelta

FEDERAL_HOLIDAYS_VERSION = "us-federal-5usc6103-2026.11.13"


def _nth_weekday(y: int, m: int, weekday: int, n: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(y: int, m: int, weekday: int) -> date:
    d = date(y + (m == 12), 1 if m == 12 else m + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def federal_holidays(year: int) -> dict[date, str]:
    """Ngày nghỉ (đã tính nghỉ bù) **thuộc năm dương lịch** ``year`` → tên."""
    if not 1990 <= year <= 2100:
        raise ValueError("năm ngoài phạm vi")
    out: dict[date, str] = {}
    for y in (year, year + 1):  # 01/01 năm sau rơi thứ Bảy → nghỉ bù 31/12 năm nay
        fixed = {
            date(y, 1, 1): "New Year's Day",
            date(y, 6, 19): "Juneteenth National Independence Day",
            date(y, 7, 4): "Independence Day",
            date(y, 11, 11): "Veterans Day",
            date(y, 12, 25): "Christmas Day",
        }
        if y < 2021:
            fixed.pop(date(y, 6, 19))  # Juneteenth thành ngày lễ liên bang từ 2021
        for d, name in fixed.items():
            o = _observed(d)
            out[o] = name + (" (observed)" if o != d else "")
        if (y - 1) % 4 == 0:  # năm sau năm bầu cử
            d = date(y, 1, 20)
            out[d + timedelta(days=1) if d.weekday() == 6 else d] = "Inauguration Day"
        out[_nth_weekday(y, 1, 0, 3)] = "Birthday of Martin Luther King, Jr."
        out[_nth_weekday(y, 2, 0, 3)] = "Washington's Birthday"
        out[_last_weekday(y, 5, 0)] = "Memorial Day"
        out[_nth_weekday(y, 9, 0, 1)] = "Labor Day"
        out[_nth_weekday(y, 10, 0, 2)] = "Columbus Day"
        out[_nth_weekday(y, 11, 3, 4)] = "Thanksgiving Day"
    # Inauguration rơi thứ Bảy: luật không cho nghỉ bù → bỏ.
    return {d: n for d, n in sorted(out.items()) if d.year == year and d.weekday() < 5}


def holidays_between(start: date, end: date) -> dict[date, str]:
    """Ngày lễ liên bang trong ``[start, end]``."""
    out: dict[date, str] = {}
    for y in range(start.year, end.year + 1):
        out.update({d: n for d, n in federal_holidays(y).items() if start <= d <= end})
    return out
