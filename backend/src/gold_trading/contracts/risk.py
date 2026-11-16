"""Quyết định của Risk Engine (docs/07)."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, model_validator

from gold_trading.common.enums import RiskOutcome
from gold_trading.common.time import UtcDatetime
from gold_trading.contracts.base import Contract


class RiskDecision(Contract):
    risk_decision_id: str
    intent_id: str
    account_id: str
    outcome: RiskOutcome
    # CORE-05 (RSK-11): Decimal — không sai số nhị phân ở lot / tiền.
    volume: Decimal = Field(default=Decimal(0), ge=0, description="Lot đã duyệt; 0 khi REJECTED")
    risk_amount: Decimal = Field(default=Decimal(0), ge=0,
                                 description="Rủi ro thật gồm spread + trượt giá + phí (tiền TK)")
    reservation_id: str | None = None
    reason_codes: tuple[str, ...] = ()
    # Số đã dùng để quyết (equity, thông số broker, spread, đệm, phí, rủi ro / lot…) — để audit.
    details: dict[str, str] = Field(default_factory=dict)
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
