"""Mốc kỳ giao dịch cho hạn mức lỗ (GĐ5 bước 4a — RSK-05; H4). Thiết kế 35 mục 10.

Ngày giao dịch = [mốc hôm trước; mốc hôm nay) theo múi giờ + giờ của hồ sơ rủi ro (người dùng chốt
17:00 ``America/New_York``). Tuần bắt đầu ở mốc **Chủ nhật** (17:00 NY CN, trước giờ mở cửa 18:00).
Tháng bắt đầu ở mốc của **ngày trước ngày 1** (ngày giao dịch đầu tháng). Tính bằng giờ địa phương
của múi giờ → tự theo DST. Mọi giá trị trả về là UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Periods:
    tz: ZoneInfo
    at: time

    @classmethod
    def of(cls, tz_name: str, hm: str) -> Periods:
        h, m = hm.split(":")
        return cls(ZoneInfo(tz_name), time(int(h), int(m)))

    def _boundary(self, d: date) -> datetime:
        """Mốc của ngày lịch ``d`` (giờ địa phương) → UTC. Giờ không tồn tại / lặp do đổi giờ:
        theo quy ước ``zoneinfo`` (fold=0) rồi chuẩn hóa qua UTC."""
        return datetime.combine(d, self.at, tzinfo=self.tz).astimezone(UTC)

    @staticmethod
    def _utc(t: datetime) -> datetime:
        if t.tzinfo is None or t.utcoffset() is None:
            raise ValueError("thời điểm phải có múi giờ (UTC)")
        return t.astimezone(UTC)

    def day_start(self, t: datetime) -> datetime:
        t = self._utc(t)
        d = t.astimezone(self.tz).date()
        for k in range(0, 3):           # mốc gần nhất ≤ t (thường là hôm nay hoặc hôm qua)
            b = self._boundary(d - timedelta(days=k))
            if b <= t:
                return b
        raise AssertionError("không tìm được mốc ngày")  # pragma: no cover

    def next_day_start(self, t: datetime) -> datetime:
        start = self.day_start(t)
        d = start.astimezone(self.tz).date()
        for k in range(1, 4):
            b = self._boundary(d + timedelta(days=k))
            if b > start:
                return b
        raise AssertionError("không tìm được mốc kế tiếp")  # pragma: no cover

    def trade_date(self, t: datetime) -> date:
        """Ngày giao dịch chứa ``t`` = ngày lịch của mốc kết thúc của nó."""
        return self.next_day_start(t).astimezone(self.tz).date()

    def week_start(self, t: datetime) -> datetime:
        t = self._utc(t)
        d = t.astimezone(self.tz).date()
        back = (d.weekday() - 6) % 7          # số ngày về Chủ nhật gần nhất (CN = 6)
        b = self._boundary(d - timedelta(days=back))
        return b if b <= t else self._boundary(d - timedelta(days=back + 7))

    def next_week_start(self, t: datetime) -> datetime:
        s = self.week_start(t)
        return self._boundary(s.astimezone(self.tz).date() + timedelta(days=7))

    def month_start(self, t: datetime) -> datetime:
        td = self.trade_date(t)
        return self._boundary(date(td.year, td.month, 1) - timedelta(days=1))

    def next_month_start(self, t: datetime) -> datetime:
        td = self.trade_date(t)
        y, m = (td.year + 1, 1) if td.month == 12 else (td.year, td.month + 1)
        return self._boundary(date(y, m, 1) - timedelta(days=1))
