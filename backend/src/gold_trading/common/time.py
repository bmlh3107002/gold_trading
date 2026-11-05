"""Tiện ích thời gian. Mọi thời gian lưu trữ/API dùng UTC (docs README)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator


def utcnow() -> datetime:
    return datetime.now(UTC)


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime phải có timezone (UTC)")
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
"""Datetime bắt buộc có timezone, luôn chuẩn hóa về UTC."""
