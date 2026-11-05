"""Quyết định của Risk Engine (docs/07)."""

from __future__ import annotations

from pydantic import Field, model_validator

from gold_trading.common.enums import RiskOutcome
from gold_trading.common.time import UtcDatetime
from gold_trading.contracts.base import Contract


class RiskDecision(Contract):
    risk_decision_id: str
    intent_id: str
    outcome: RiskOutcome
    volume: float = Field(default=0.0, ge=0.0, description="Lot đã duyệt; 0 khi REJECTED")
    risk_amount: float = Field(default=0.0, ge=0.0, description="Số tiền rủi ro đã reserve")
    reservation_id: str | None = None
    reason_codes: tuple[str, ...] = ()
    decided_at: UtcDatetime
    expires_at: UtcDatetime
    policy_version: str

    @model_validator(mode="after")
    def _check(self) -> RiskDecision:
        if self.expires_at <= self.decided_at:
            raise ValueError("expires_at phải sau decided_at")
        if self.outcome is RiskOutcome.REJECTED:
            if self.volume != 0 or self.reservation_id is not None:
                raise ValueError("REJECTED không được có volume hay reservation")
            if not self.reason_codes:
                raise ValueError("REJECTED phải có reason_codes")
        elif self.volume <= 0 or self.reservation_id is None:
            raise ValueError("APPROVED/REDUCED phải có volume > 0 và reservation_id")
        return self
