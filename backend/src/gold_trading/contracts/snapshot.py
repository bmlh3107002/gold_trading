"""Snapshot và kết quả Data Quality Gate (docs/05, thiết kế 33 mục 3–4)."""

from __future__ import annotations

from pydantic import Field, model_validator

from gold_trading.common.enums import QualityVerdict
from gold_trading.common.time import UtcDatetime
from gold_trading.contracts.analyst import AnalystOutput
from gold_trading.contracts.base import Contract


class Snapshot(Contract):
    """Ảnh chụp bất biến các output analyst **còn hiệu lực** tại ``available_at`` cho một nguồn giá.

    ``input_manifest``: analyst → ``output_id`` đã dùng (tái dựng được, kho chỉ-thêm).
    ``excluded_inputs``: analyst → ``output_id`` mới nhất đã biết nhưng **hết hạn** tại
    ``available_at`` (không dùng, chỉ để audit / Quality Gate phân biệt "hết hạn" với "vắng").
    """

    snapshot_id: str
    builder_version: str
    symbol: str
    timeframe: str
    source: str
    feed_id: str
    event_time: UtcDatetime = Field(description="as_of mới nhất trong các output đã dùng")
    available_at: UtcDatetime = Field(description="Lúc mọi input đã sẵn sàng cho hệ thống")
    expires_at: UtcDatetime = Field(
        description="Sớm nhất trong hạn các output bắt buộc đã dùng; = available_at nếu không có")
    analyst_outputs: tuple[AnalystOutput, ...]
    quality_flags: frozenset[str] = frozenset()
    input_manifest: dict[str, str] = Field(
        default_factory=dict, description="analyst_id -> output_id, để tái dựng"
    )
    excluded_inputs: dict[str, str] = Field(
        default_factory=dict,
        description="analyst_id -> output_id đã biết nhưng hết hạn (không dùng)",
    )

    @model_validator(mode="after")
    def _check(self) -> Snapshot:
        if self.expires_at < self.available_at:
            raise ValueError("expires_at không được trước available_at")
        if self.event_time > self.available_at:
            raise ValueError("event_time sau available_at — nhìn trước tương lai")
        ids = {o.analyst_id: o.output_id for o in self.analyst_outputs}
        if len(ids) != len(self.analyst_outputs) or ids != self.input_manifest:
            raise ValueError("input_manifest phải khớp đúng một output cho mỗi analyst đã dùng")
        if set(self.excluded_inputs) & set(self.input_manifest):
            raise ValueError("một analyst không thể vừa được dùng vừa bị loại")
        return self


class QualityReport(Contract):
    snapshot_id: str
    verdict: QualityVerdict
    reasons: tuple[str, ...] = ()
    confidence_multiplier: float = Field(default=1.0, ge=0.0, le=1.0)
    policy_version: str
