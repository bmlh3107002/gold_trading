"""Hợp đồng chung cho output analyst (docs/04)."""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from gold_trading.common.enums import SourceStatus
from gold_trading.common.time import UtcDatetime
from gold_trading.contracts.base import Contract


class AnalystOutput(Contract):
    output_id: str
    analyst_id: str = Field(description="technical | news | event | macro | positioning | regime")
    as_of: UtcDatetime
    expires_at: UtcDatetime
    confidence: float = Field(ge=0.0, le=1.0)
    features: dict[str, Any] = Field(default_factory=dict)
    drivers: tuple[str, ...] = ()
    risk_flags: frozenset[str] = frozenset()
    source_status: SourceStatus
    quality_flags: frozenset[str] = frozenset()
    version: str
    correlation_id: str

    @model_validator(mode="after")
    def _expiry_after_as_of(self) -> AnalystOutput:
        if self.expires_at <= self.as_of:
            raise ValueError("expires_at phải sau as_of")
        return self

    def is_valid_at(self, at: UtcDatetime) -> bool:
        return self.as_of <= at < self.expires_at
