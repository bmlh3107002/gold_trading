from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum


class Timeframe(StrEnum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"

    @property
    def delta(self) -> timedelta:
        return timedelta(seconds=_SECONDS[self])

    def floor(self, t: datetime) -> datetime:
        """Thời điểm mở của nến chứa ``t`` (căn theo epoch UTC)."""
        s = _SECONDS[self]
        ts = int(t.astimezone(UTC).timestamp())
        return datetime.fromtimestamp(ts - ts % s, UTC)

    def is_aligned(self, t: datetime) -> bool:
        return int(t.astimezone(UTC).timestamp()) % _SECONDS[self] == 0 and t.microsecond == 0


_SECONDS = {
    Timeframe.M1: 60,
    Timeframe.M5: 300,
    Timeframe.M15: 900,
    Timeframe.M30: 1800,
    Timeframe.H1: 3600,
    Timeframe.H4: 14400,
}
