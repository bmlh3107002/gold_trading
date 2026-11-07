"""Lịch giao dịch vàng giao ngay (XAUUSD) theo quy ước phổ biến của thị trường FX/kim loại.

- Mở cửa tuần: Chủ nhật 18:00 giờ New York. Đóng cửa tuần: thứ Sáu 17:00 giờ New York.
- Nghỉ hằng ngày: 17:00–18:00 giờ New York (thứ Hai–thứ Năm).

Dùng giờ New York để tự xử lý DST. Broker có thể lệch vài phút hoặc nghỉ lễ riêng:
đây là lịch tham chiếu, không thay thế lịch của broker.

``MarketCalendar`` = lịch tham chiếu GIAO với giờ báo giá chính thức của broker
(MT5 → Specification → Sessions → Quotes, theo giờ server). Một nến chỉ "lẽ ra phải có"
khi cả hai lịch đều mở. Xem docs/thiet-ke/03-technical-analyst.md, mục "Lịch giao dịch".

Từ CAL-03/CAL-05 lịch còn trừ thêm **ngày lễ / đóng sớm Mỹ** (``holidays.py``, có phiên bản) và
**giờ đặc biệt do broker thông báo** (``BrokerSpecialHours``, theo ngày giờ server, nhập tay).
Vào một ngày server có giờ đặc biệt, giờ đặc biệt thay cho cả giờ tuần của broker lẫn bảng ngày lễ
(thông báo của broker cụ thể hơn bảng chung), nhưng vẫn giao với lịch tham chiếu tuần.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from gold_trading.market.holidays import US_HOLIDAYS, Holiday, HolidayTable, trade_date

NY = ZoneInfo("America/New_York")
_ROLL = time(17, 0)
_REOPEN = time(18, 0)


class MarketSession(StrEnum):
    OPEN = "OPEN"
    DAILY_BREAK = "DAILY_BREAK"
    WEEKEND = "WEEKEND"
    HOLIDAY = "HOLIDAY"  # nghỉ lễ / đóng sớm / giờ đặc biệt của broker


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


# ---------------------------------------------------------------------------
# Lịch của broker (giờ server) và lịch kết hợp
# ---------------------------------------------------------------------------

_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
_HM = re.compile(r"^(\d{1,2}):(\d{2})$")
_EPS = timedelta(microseconds=1)


def _minutes(hm: str) -> int:
    m = _HM.match(hm.strip())
    if not m:
        raise ValueError(f"Giờ không hợp lệ: {hm!r} (cần dạng HH:MM)")
    h, mi = int(m.group(1)), int(m.group(2))
    if mi >= 60 or h > 24 or (h == 24 and mi != 0):
        raise ValueError(f"Giờ không hợp lệ: {hm!r}")
    return h * 60 + mi


def _ranges(text: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for r in text.split(","):
        a, sep, b = r.strip().partition("-")
        if not sep:
            raise ValueError(f"Khoảng giờ không hợp lệ: {r.strip()!r}")
        lo, hi = _minutes(a), _minutes(b)
        if lo >= hi:
            raise ValueError(f"Giờ bắt đầu phải nhỏ hơn giờ kết thúc: {r.strip()!r}")
        out.append((lo, hi))
    out.sort()
    for (_, hi1), (lo2, _) in zip(out, out[1:], strict=False):
        if lo2 < hi1:
            raise ValueError("Các khoảng giờ trong cùng một ngày bị chồng nhau")
    return out


def _local_seconds(local: datetime) -> float:
    return local.hour * 3600 + local.minute * 60 + local.second + local.microsecond / 1e6


def _parse_tz(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name.strip())
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"Múi giờ server không hợp lệ: {tz_name!r}") from e


def _days(spec: str) -> list[int]:
    parts = spec.strip().upper().split("-")
    if len(parts) == 1:
        parts = parts * 2
    if len(parts) != 2 or any(p not in _DAYS for p in parts):
        raise ValueError(f"Ngày không hợp lệ: {spec!r} (dùng Mon..Sun hoặc Mon-Fri)")
    a, b = _DAYS.index(parts[0]), _DAYS.index(parts[1])
    if a > b:
        raise ValueError(f"Khoảng ngày phải tăng dần trong tuần: {spec!r}")
    return list(range(a, b + 1))


@dataclass(frozen=True)
class BrokerSessions:
    """Giờ báo giá của broker theo giờ server. Khoảng [bắt đầu, kết thúc), không qua nửa đêm."""

    tz: ZoneInfo
    windows: tuple[tuple[tuple[int, int], ...], ...]  # 7 phần tử (Mon..Sun), phút trong ngày
    spec: str

    @classmethod
    def parse(cls, spec: str, tz_name: str) -> BrokerSessions:
        """``spec`` ví dụ ``"Mon-Fri 00:00-23:00"`` hoặc ``"Mon 01:00-24:00; Tue-Fri 00:00-23:00"``.

        Ngày không nhắc tới = đóng cửa cả ngày. Sai cú pháp thì báo lỗi, không đoán.
        """
        tz = _parse_tz(tz_name)
        days: list[list[tuple[int, int]]] = [[] for _ in range(7)]
        groups = [g for g in spec.split(";") if g.strip()]
        if not groups:
            raise ValueError("Lịch broker rỗng")
        for g in groups:
            head, _, ranges = g.strip().partition(" ")
            if not ranges.strip():
                raise ValueError(f"Thiếu khoảng giờ: {g.strip()!r}")
            for d in _days(head):
                days[d].extend(_ranges(ranges))
        for d in days:
            d.sort()
            for (_, hi1), (lo2, _) in zip(d, d[1:], strict=False):
                if lo2 < hi1:
                    raise ValueError("Các khoảng giờ trong cùng một ngày bị chồng nhau")
        return cls(tz, tuple(tuple(d) for d in days), " ".join(spec.split()))

    def is_open(self, t: datetime) -> bool:
        local = t.astimezone(self.tz)  # UTC → giờ địa phương luôn xác định, kể cả lúc đổi DST
        sec = _local_seconds(local)
        return any(lo * 60 <= sec < hi * 60 for lo, hi in self.windows[local.weekday()])


_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


@dataclass(frozen=True)
class BrokerSpecialHours:
    """CAL-05: giờ báo giá đặc biệt broker thông báo cho từng ngày (giờ server), nhập tay.

    ``spec`` ví dụ ``"2026-12-24 00:00-20:45; 2026-12-25 CLOSED"``. Ngày có trong danh sách thì
    giờ này THAY cho giờ tuần của broker và bảng ngày lễ (vẫn giao với lịch tham chiếu tuần).
    Sai cú pháp hoặc trùng ngày → lỗi khi khởi động, không đoán.
    """

    days: dict[date, tuple[tuple[int, int], ...]] = field(hash=False, compare=False)
    spec: str
    label: str

    @classmethod
    def parse(cls, spec: str, label: str = "") -> BrokerSpecialHours:
        days: dict[date, tuple[tuple[int, int], ...]] = {}
        groups = [g.strip() for g in spec.split(";") if g.strip()]
        if not groups:
            raise ValueError("Giờ đặc biệt của broker rỗng")
        for g in groups:
            head, _, rest = g.partition(" ")
            m = _DATE.match(head)
            if not m:
                raise ValueError(f"Ngày không hợp lệ: {head!r} (cần dạng YYYY-MM-DD)")
            try:
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError as e:
                raise ValueError(f"Ngày không tồn tại: {head!r}") from e
            if d in days:
                raise ValueError(f"Trùng ngày trong giờ đặc biệt: {head}")
            rest = rest.strip()
            if not rest:
                raise ValueError(f"Thiếu giờ (hoặc CLOSED) cho ngày {head}")
            days[d] = () if rest.upper() == "CLOSED" else tuple(_ranges(rest))
        return cls(days, " ".join(spec.split()), label.strip())

    @property
    def version(self) -> str:
        """Nhãn người dùng đặt + 8 ký tự băm của nội dung (đổi nội dung là đổi phiên bản)."""
        digest = hashlib.sha256(self.spec.encode()).hexdigest()[:8]
        return f"{self.label}#{digest}" if self.label else digest

    def windows_on(self, d: date) -> tuple[tuple[int, int], ...] | None:
        return self.days.get(d)


@dataclass(frozen=True)
class MarketCalendar:
    """Lịch dùng để biết nến nào "lẽ ra phải có".

    = tham chiếu tuần ∩ (giờ đặc biệt của broker nếu ngày đó có; nếu không: broker tuần ∩ không
    phải ngày lễ). ``holidays=None`` chỉ dùng trong test để so sánh với lịch không có ngày lễ.
    """

    broker: BrokerSessions | None = None
    holidays: HolidayTable | None = US_HOLIDAYS
    special: BrokerSpecialHours | None = None

    def __post_init__(self) -> None:
        if self.special is not None and self.broker is None:
            raise ValueError("Giờ đặc biệt của broker cần lịch broker (GT_BROKER_SESSIONS + TZ)")

    @property
    def description(self) -> str:
        base = "NY 18:00 CN → 17:00 T6, nghỉ 17:00–18:00"
        if self.holidays is not None:
            base = f"{base} − lễ [{self.holidays.version}]"
        if self.broker is None:
            return base
        out = f"{base} ∩ broker [{self.broker.spec}, {self.broker.tz.key}]"
        if self.special is not None:
            out = f"{out} + giờ đặc biệt [{self.special.version}]"
        return out

    # --- phần tuần (dùng cho R1: không phụ thuộc bảng ngày lễ, xem docs/thiet-ke/03) ---
    def weekly_is_open(self, t: datetime) -> bool:
        return is_open(t) and (self.broker is None or self.broker.is_open(t))

    def weekly_bar_in_session(self, open_time: datetime, close_time: datetime) -> bool:
        return self.weekly_is_open(open_time) and self.weekly_is_open(close_time - _EPS)

    # --- lịch đầy đủ ---
    def _special_windows(self, t: datetime) -> tuple[datetime, tuple[tuple[int, int], ...] | None]:
        if self.special is None or self.broker is None:
            return t, None
        local = t.astimezone(self.broker.tz)
        return local, self.special.windows_on(local.date())

    def is_open(self, t: datetime) -> bool:
        if not is_open(t):
            return False
        local, windows = self._special_windows(t)
        if windows is not None:
            sec = _local_seconds(local)
            return any(lo * 60 <= sec < hi * 60 for lo, hi in windows)
        if self.holidays is not None and self.holidays.closure_at(t) is not None:
            return False
        return self.broker is None or self.broker.is_open(t)

    def bar_in_session(self, open_time: datetime, close_time: datetime) -> bool:
        return self.is_open(open_time) and self.is_open(close_time - _EPS)

    def holiday_closure_at(self, t: datetime) -> Holiday | None:
        """Ngày lễ trong bảng đang đóng cửa tại ``t`` (bỏ qua nếu ngày đó có giờ đặc biệt)."""
        if self.holidays is None or self._special_windows(t)[1] is not None:
            return None
        return self.holidays.closure_at(t)

    def special_day(self, t: datetime) -> bool:
        return self._special_windows(t)[1] is not None

    def holiday_on(self, t: datetime) -> Holiday | None:
        """Ngày lễ / đóng sớm của ngày giao dịch chứa ``t`` (để giải thích, không để quyết định)."""
        if self.holidays is None:
            return None
        return self.holidays.on(trade_date(t))

    def low_liquidity(self, t: datetime) -> bool:
        return self.holidays is not None and self.holidays.low_liquidity(t)

    def covers(self, t: datetime) -> bool:
        """Bảng ngày lễ có dữ liệu cho năm của ``t`` không."""
        return self.holidays is not None and self.holidays.covers(t)

    def session_at(self, t: datetime) -> MarketSession:
        ref = session_at(t)
        if ref is not MarketSession.OPEN or self.is_open(t):
            return ref
        if self.holiday_closure_at(t) is not None or self.special_day(t):
            return MarketSession.HOLIDAY
        # Broker đóng trong lúc lịch tham chiếu mở: nếu sắp tới cuối tuần thì báo WEEKEND
        # (ví dụ thứ Sáu broker đóng sớm 1 giờ), ngược lại là nghỉ giữa ngày.
        for k in range(1, 13):  # nhìn tới 3 giờ
            if session_at(t + timedelta(minutes=15 * k)) is MarketSession.WEEKEND:
                return MarketSession.WEEKEND
        return MarketSession.DAILY_BREAK


REFERENCE = MarketCalendar()
# Lịch tuần không có ngày lễ: chỉ để so sánh trong test / kịch bản soát lại.
WEEKLY_ONLY = MarketCalendar(holidays=None)
