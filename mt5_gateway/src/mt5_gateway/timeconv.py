"""Quy đổi thời gian MT5 → UTC.

MT5 trả ``time`` là số giây theo GIỜ SERVER của broker nhưng viết như thể UTC. Phải gắn múi giờ
server (IANA, có DST) rồi mới đổi sang UTC. Giờ mơ hồ/không tồn tại do đổi DST → None (không đoán).
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

OFFSET_TOLERANCE_S = 300  # tick "sống" phải lệch độ lệch giờ chẵn không quá 5 phút


def load_tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(
            f"Múi giờ không hợp lệ: {name!r} (cần tên IANA, ví dụ Europe/Athens)"
        ) from e


def server_epoch_to_utc(t: int | float, tz: ZoneInfo) -> datetime | None:
    naive = datetime.fromtimestamp(int(t), UTC).replace(tzinfo=None)
    a = naive.replace(tzinfo=tz, fold=0)
    b = naive.replace(tzinfo=tz, fold=1)
    if a.utcoffset() != b.utcoffset():
        return None
    utc = a.astimezone(UTC)
    if utc.astimezone(tz).replace(tzinfo=None) != naive:
        return None
    return utc


def tz_offset_hours(tz: ZoneInfo, at: datetime) -> float:
    off = at.astimezone(tz).utcoffset()
    return off.total_seconds() / 3600 if off is not None else 0.0


def detect_offset_hours(tick_server_epoch: float, now_utc_epoch: float) -> int | None:
    """Độ lệch giờ server so với UTC từ một tick VỪA MỚI xảy ra. None nếu không khớp giờ chẵn."""
    diff = tick_server_epoch - now_utc_epoch
    h = round(diff / 3600)
    if -12 <= h <= 14 and abs(diff - h * 3600) <= OFFSET_TOLERANCE_S:
        return h
    return None
