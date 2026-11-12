"""Bản ghi đã chuẩn hóa từ Ingestion (docs/02).

Dùng cho nguồn KHÔNG phải nến (lịch kinh tế, tin, vĩ mô, vị thế) — DB-08, ING-13. Quy tắc
point-in-time ở ``docs/thiet-ke/10-nguon-ngoai.md``:

- Định danh một dữ kiện: ``(source, logical_key)``; mỗi lần nguồn sửa số = một ``revision`` mới
  (không ghi đè). Định danh một bản ghi: ``(source, logical_key, revision)``.
- ``available_at``: lúc nguồn công bố công khai (thiếu → bằng ``ingested_at``).
- ``known_at = max(ingested_at, available_at)``: hệ thống chỉ được dùng bản ghi từ lúc này.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from gold_trading.common.enums import SourceStatus
from gold_trading.common.time import UtcDatetime
from gold_trading.contracts.base import Contract

EXTERNAL_KINDS = ("calendar", "news", "macro", "positioning")


class NormalizedRecord(Contract):
    record_id: str
    source: str
    kind: str = Field(description="price | news | calendar | macro | positioning")
    event_time: UtcDatetime = Field(description="Thời điểm sự kiện xảy ra ngoài đời")
    ingested_at: UtcDatetime = Field(description="Thời điểm hệ thống biết được")
    source_status: SourceStatus
    payload_version: str
    raw_ref: str
    revision: int = Field(default=0, ge=0)
    quality_flags: frozenset[str] = frozenset()
    payload: dict[str, Any] = Field(default_factory=dict)
    # Dữ kiện nào (vd. "CPIAUCSL:2026-09"); các revision của cùng dữ kiện chung logical_key.
    # Thiếu → payload["logical_key"] hoặc record_id (tương thích cũ).
    logical_key: str = ""
    # Lúc nguồn công bố công khai (vd. FRED công bố số ngày D vào D+1). Thiếu → ingested_at.
    available_at: UtcDatetime | None = None

    @model_validator(mode="before")
    @classmethod
    def _defaults(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("logical_key"):
            payload = data.get("payload") or {}
            data = dict(data)
            data["logical_key"] = str(payload.get("logical_key") or data.get("record_id") or "")
        return data

    @model_validator(mode="after")
    def _ingested_not_before_event(self) -> NormalizedRecord:
        # Dữ liệu có thể đến muộn, nhưng hệ thống không thể biết trước khi nó xảy ra.
        # Riêng lịch kinh tế được công bố trước, nên kind=calendar được miễn.
        if self.kind != "calendar" and self.ingested_at < self.event_time:
            raise ValueError("ingested_at không được sớm hơn event_time")
        if self.kind != "calendar" and self.available_at is not None \
                and self.available_at < self.event_time:
            raise ValueError("available_at không được sớm hơn event_time")
        if not self.logical_key:
            raise ValueError("thiếu logical_key")
        return self

    @property
    def known_at(self):
        """Lúc hệ thống được phép dùng bản ghi: đã nạp VÀ nguồn đã công bố."""
        if self.available_at is None:
            return self.ingested_at
        return max(self.ingested_at, self.available_at)
