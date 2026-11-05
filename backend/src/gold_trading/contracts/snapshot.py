"""Snapshot và kết quả Data Quality Gate (docs/05)."""

from __future__ import annotations

from pydantic import Field

from gold_trading.common.enums import QualityVerdict
from gold_trading.common.time import UtcDatetime
from gold_trading.contracts.analyst import AnalystOutput
from gold_trading.contracts.base import Contract


class Snapshot(Contract):
    snapshot_id: str
    event_time: UtcDatetime
    available_at: UtcDatetime = Field(description="Lúc mọi input đã sẵn sàng cho hệ thống")
    expires_at: UtcDatetime
    analyst_outputs: tuple[AnalystOutput, ...]
    quality_flags: frozenset[str] = frozenset()
    input_manifest: dict[str, str] = Field(
        default_factory=dict, description="analyst_id -> output_id, để tái dựng"
    )


class QualityReport(Contract):
    snapshot_id: str
    verdict: QualityVerdict
    reasons: tuple[str, ...] = ()
    confidence_multiplier: float = Field(default=1.0, ge=0.0, le=1.0)
    policy_version: str
