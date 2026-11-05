"""Bản ghi đã chuẩn hóa từ Ingestion (docs/02)."""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from gold_trading.common.enums import SourceStatus
from gold_trading.common.time import UtcDatetime
from gold_trading.contracts.base import Contract


class NormalizedRecord(Contract):
    record_id: str
    source: str
    kind: str = Field(description="price | news | calendar | macro | positioning")
    event_time: UtcDatetime = Field(description="Thời điểm sự kiện xảy ra ngoài đời")
    ingested_at: UtcDatetime = Field(description="Thời điểm hệ thống biết được")
    source_status: SourceStatus
    payload_version: str
    raw_ref: str
    revision: int = 0
    quality_flags: frozenset[str] = frozenset()
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _ingested_not_before_event(self) -> NormalizedRecord:
        # Dữ liệu có thể đến muộn, nhưng hệ thống không thể biết trước khi nó xảy ra.
        # Riêng lịch kinh tế được công bố trước, nên kind=calendar được miễn.
        if self.kind != "calendar" and self.ingested_at < self.event_time:
            raise ValueError("ingested_at không được sớm hơn event_time")
        return self
