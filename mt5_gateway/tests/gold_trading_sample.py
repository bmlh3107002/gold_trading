"""Sinh nến UTC đơn giản trong giờ mở cửa XAUUSD (giờ New York) cho MT5 giả lập."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
M15 = timedelta(minutes=15)


def _open(t: datetime) -> bool:
    ny = t.astimezone(NY)
    wd, tod = ny.weekday(), ny.time()
    if wd == 5 or (wd == 4 and tod >= time(17)) or (wd == 6 and tod < time(18)):
        return False
    return not (time(17) <= tod < time(18))


def bars_until(now: datetime, days: int = 70) -> list[dict]:
    ts = int(now.timestamp())
    t = datetime.fromtimestamp(ts - ts % 900, UTC) - timedelta(days=days)
    out, p = [], 2400.0
    while t <= now:
        if _open(t) and _open(t + M15 - timedelta(microseconds=1)):
            o = p
            c = round(p + (((int(t.timestamp()) // 900) * 7919) % 11 - 5) * 0.1, 2)
            out.append(
                {
                    "open_time": t,
                    "open": o,
                    "high": max(o, c) + 0.3,
                    "low": min(o, c) - 0.3,
                    "close": c,
                }
            )
            p = c
        t += M15
    return out
