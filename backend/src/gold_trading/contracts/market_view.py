"""MarketView — đầu ra tiêu chuẩn của Market Intelligence (docs/05)."""

from __future__ import annotations

from pydantic import Field, model_validator

from gold_trading.common.enums import Bias, Regime
from gold_trading.common.time import UtcDatetime
from gold_trading.contracts.base import Contract


class MarketView(Contract):
    market_view_id: str
    snapshot_id: str
    symbol: str = "XAUUSD"
    as_of: UtcDatetime
    expires_at: UtcDatetime
    bias: Bias
    p_up: float = Field(ge=0.0, le=1.0)
    p_down: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    regime: Regime
    vol_forecast: float = Field(ge=0.0)
    drivers: tuple[str, ...] = ()
    risk_flags: frozenset[str] = frozenset()
    quality_flags: frozenset[str] = frozenset()
    model_version: str

    @model_validator(mode="after")
    def _check(self) -> MarketView:
        if self.expires_at <= self.as_of:
            raise ValueError("expires_at phải sau as_of")
        if self.p_up + self.p_down > 1.0 + 1e-9:
            raise ValueError("p_up + p_down không được vượt 1")
        return self

    def is_valid_at(self, at: UtcDatetime) -> bool:
        return self.as_of <= at < self.expires_at
