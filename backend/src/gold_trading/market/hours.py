"""Lịch giao dịch vàng giao ngay (XAUUSD) theo quy ước phổ biến của thị trường FX/kim loại.

- Mở cửa tuần: Chủ nhật 18:00 giờ New York. Đóng cửa tuần: thứ Sáu 17:00 giờ New York.
- Nghỉ hằng ngày: 17:00–18:00 giờ New York (thứ Hai–thứ Năm).

Dùng giờ New York để tự xử lý DST. Broker có thể lệch vài phút hoặc nghỉ lễ riêng:
đây là lịch tham chiếu, không thay thế lịch của broker.

``MarketCalendar`` = lịch tham chiếu GIAO với giờ báo giá chính thức của broker
(MT5 → Specification → Sessions → Quotes, theo giờ server). Một nến chỉ "lẽ ra phải có"
khi cả hai lịch đều mở. Xem docs/thiet-ke/03-technical-analyst.md, mục "Lịch giao dịch".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
        try:
            tz = ZoneInfo(tz_name.strip())
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"Múi giờ server không hợp lệ: {tz_name!r}") from e
        days: list[list[tuple[int, int]]] = [[] for _ in range(7)]
        groups = [g for g in spec.split(";") if g.strip()]
        if not groups:
            raise ValueError("Lịch broker rỗng")
        for g in groups:
            head, _, ranges = g.strip().partition(" ")
            if not ranges.strip():
                raise ValueError(f"Thiếu khoảng giờ: {g.strip()!r}")
            for d in _days(head):
                for r in ranges.split(","):
                    a, sep, b = r.strip().partition("-")
                    if not sep:
                        raise ValueError(f"Khoảng giờ không hợp lệ: {r.strip()!r}")
                    lo, hi = _minutes(a), _minutes(b)
                    if lo >= hi:
                        raise ValueError(f"Giờ bắt đầu phải nhỏ hơn giờ kết thúc: {r.strip()!r}")
                    days[d].append((lo, hi))
        for d in days:
            d.sort()
            for (_, hi1), (lo2, _) in zip(d, d[1:], strict=False):
                if lo2 < hi1:
                    raise ValueError("Các khoảng giờ trong cùng một ngày bị chồng nhau")
        return cls(tz, tuple(tuple(d) for d in days), " ".join(spec.split()))

    def is_open(self, t: datetime) -> bool:
        local = t.astimezone(self.tz)  # UTC → giờ địa phương luôn xác định, kể cả lúc đổi DST
        sec = local.hour * 3600 + local.minute * 60 + local.second + local.microsecond / 1e6
        return any(lo * 60 <= sec < hi * 60 for lo, hi in self.windows[local.weekday()])


@dataclass(frozen=True)
class MarketCalendar:
    """Lịch dùng để biết nến nào "lẽ ra phải có": tham chiếu ∩ broker (nếu có)."""

    broker: BrokerSessions | None = None

    @property
    def description(self) -> str:
        base = "NY 18:00 CN → 17:00 T6, nghỉ 17:00–18:00"
        if self.broker is None:
            return base
        return f"{base} ∩ broker [{self.broker.spec}, {self.broker.tz.key}]"

    def is_open(self, t: datetime) -> bool:
        return is_open(t) and (self.broker is None or self.broker.is_open(t))

    def bar_in_session(self, open_time: datetime, close_time: datetime) -> bool:
        return self.is_open(open_time) and self.is_open(close_time - _EPS)

    def session_at(self, t: datetime) -> MarketSession:
        ref = session_at(t)
        if ref is not MarketSession.OPEN or self.broker is None or self.broker.is_open(t):
            return ref
        # Broker đóng trong lúc lịch tham chiếu mở: nếu sắp tới cuối tuần thì báo WEEKEND
        # (ví dụ thứ Sáu broker đóng sớm 1 giờ), ngược lại là nghỉ giữa ngày.
        for k in range(1, 13):  # nhìn tới 3 giờ
            if session_at(t + timedelta(minutes=15 * k)) is MarketSession.WEEKEND:
                return MarketSession.WEEKEND
        return MarketSession.DAILY_BREAK


REFERENCE = MarketCalendar()
