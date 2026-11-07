"""Khung thời gian nến.

Hai loại khung (ING-14, 1A-C19):

- **M1–H1**: ranh giới nến trùng với epoch UTC (mọi broker lệch giờ chẵn). Độ dài cố định.
- **H4, D1** (``server_aligned``): MT5 cắt nến theo **giờ đồng hồ của server broker** (D1 bắt đầu
  lúc 00:00 giờ server, H4 lúc 00/04/08/12/16/20 giờ server). Ranh giới phụ thuộc múi giờ server
  (IANA, có DST), nên ngày đổi giờ nến dài 23/25 giờ (D1) hoặc 3/5 giờ (H4). Muốn kiểm tra căn
  khung hay tính ``close_time`` phải biết múi giờ server; KHÔNG tự cắt lại theo UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

GRID = timedelta(minutes=15)  # mọi múi giờ thật đều lệch UTC bội số của 15 phút
MAX_DST_SHIFT = timedelta(hours=1)


class Timeframe(StrEnum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"

    @property
    def delta(self) -> timedelta:
        """Độ dài DANH NGHĨA. Với H4/D1 độ dài thật có thể khác ±1 giờ (xem ``close_time``)."""
        return timedelta(seconds=_SECONDS[self])

    @property
    def server_aligned(self) -> bool:
        """True: ranh giới nến theo giờ server broker, cần múi giờ server để tính."""
        return self in _SERVER_ALIGNED

    @property
    def minutes(self) -> int:
        return _SECONDS[self] // 60

    def floor(self, t: datetime) -> datetime:
        """Thời điểm mở của nến chứa ``t`` (căn theo epoch UTC). Chỉ cho M1–H1."""
        if self.server_aligned:
            raise ValueError(f"{self} căn theo giờ server broker: không floor theo UTC")
        s = _SECONDS[self]
        ts = int(t.astimezone(UTC).timestamp())
        return datetime.fromtimestamp(ts - ts % s, UTC)

    def is_aligned(self, t: datetime) -> bool:
        """Kiểm tra KHÔNG cần múi giờ (dùng trong contract).

        M1–H1: căn theo epoch UTC. H4/D1: chỉ kiểm tra lưới 15 phút (kiểm tra đầy đủ theo giờ
        server ở ``is_aligned_in``, chạy lúc nạp)."""
        if t.tzinfo is None or t.microsecond != 0:
            return False
        step = GRID.total_seconds() if self.server_aligned else _SECONDS[self]
        return int(t.astimezone(UTC).timestamp()) % int(step) == 0

    def is_aligned_in(self, t: datetime, tz: ZoneInfo | None) -> bool:
        """Căn khung đầy đủ. H4/D1 bắt buộc có ``tz`` (múi giờ server)."""
        if not self.server_aligned:
            return self.is_aligned(t)
        if tz is None or not self.is_aligned(t):
            return False
        local = t.astimezone(tz)
        if local.minute or local.second:
            return False
        return local.hour == 0 if self is Timeframe.D1 else local.hour % 4 == 0

    def close_time(self, open_time: datetime, tz: ZoneInfo | None = None) -> datetime:
        """Thời điểm đóng THẬT (UTC) của nến mở lúc ``open_time``.

        H4/D1: ranh giới kế tiếp theo đồng hồ server. Nếu giờ đó mơ hồ (lặp lại khi lùi giờ) lấy
        lần muộn hơn; nếu không tồn tại (nhảy giờ) lấy lúc đồng hồ vượt qua nó. Cả hai cách đều
        không bao giờ coi nến là đã đóng sớm hơn thực tế.
        """
        if not self.server_aligned:
            return open_time + self.delta
        if tz is None:
            raise ValueError(f"{self} cần múi giờ server để tính giờ đóng nến")
        wall = open_time.astimezone(tz).replace(tzinfo=None) + self.delta
        return _wall_to_utc_not_early(wall, tz)

    def plausible_close(self, open_time: datetime, close_time: datetime) -> bool:
        """Kiểm tra KHÔNG cần múi giờ (contract): M1–H1 đúng bằng ``delta``; H4/D1 lệch tối đa
        1 giờ do đổi DST ở giờ server."""
        length = close_time - open_time
        if not self.server_aligned:
            return length == self.delta
        return abs(length - self.delta) <= MAX_DST_SHIFT and length > timedelta(0)


def _wall_to_utc_not_early(wall: datetime, tz: ZoneInfo) -> datetime:
    cands = sorted({wall.replace(tzinfo=tz, fold=f).astimezone(UTC) for f in (0, 1)})
    valid = [c for c in cands if c.astimezone(tz).replace(tzinfo=None) == wall]
    if valid:
        return valid[-1]  # mơ hồ → lần muộn hơn
    # Giờ không tồn tại (nhảy giờ): tìm thời điểm đầu tiên đồng hồ server >= wall.
    lo, hi = cands[0], cands[-1]
    while hi - lo > timedelta(seconds=1):
        mid = lo + (hi - lo) / 2
        if mid.astimezone(tz).replace(tzinfo=None) >= wall:
            hi = mid
        else:
            lo = mid
    return hi.replace(microsecond=0)


_SECONDS = {
    Timeframe.M1: 60,
    Timeframe.M5: 300,
    Timeframe.M15: 900,
    Timeframe.M30: 1800,
    Timeframe.H1: 3600,
    Timeframe.H4: 14400,
    Timeframe.D1: 86400,
}
_SERVER_ALIGNED = frozenset({Timeframe.H4, Timeframe.D1})
