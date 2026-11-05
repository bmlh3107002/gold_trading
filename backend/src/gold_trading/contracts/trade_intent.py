"""TradeIntent — ý tưởng giao dịch từ Strategy, chưa phải lệnh (docs/06)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from gold_trading.common.enums import Side
from gold_trading.common.time import UtcDatetime
from gold_trading.contracts.base import Contract


class TradeIntent(Contract):
    intent_id: str
    strategy_id: str
    symbol: str
    side: Side
    entry_type: Literal["MARKET", "LIMIT", "STOP"]
    entry_reference: float = Field(gt=0)
    stop_loss: float = Field(gt=0, description="Bắt buộc — không có SL thì không có intent")
    take_profit: float | None = Field(default=None, gt=0)
    time_in_force: Literal["GTC", "DAY", "IOC", "FOK"] = "GTC"
    expiry: UtcDatetime
    risk_budget_requested: float = Field(
        gt=0, description="Mức rủi ro mong muốn theo tỷ lệ equity, ví dụ 0.005 = 0.5%"
    )
    market_view_id: str
    policy_version: str
    created_at: UtcDatetime
    reason: str
    idempotency_key: str
    correlation_id: str

    @model_validator(mode="after")
    def _check(self) -> TradeIntent:
        if self.expiry <= self.created_at:
            raise ValueError("expiry phải sau created_at")
        if self.side is Side.BUY:
            if self.stop_loss >= self.entry_reference:
                raise ValueError("BUY: stop_loss phải thấp hơn entry_reference")
            if self.take_profit is not None and self.take_profit <= self.entry_reference:
                raise ValueError("BUY: take_profit phải cao hơn entry_reference")
        else:
            if self.stop_loss <= self.entry_reference:
                raise ValueError("SELL: stop_loss phải cao hơn entry_reference")
            if self.take_profit is not None and self.take_profit >= self.entry_reference:
                raise ValueError("SELL: take_profit phải thấp hơn entry_reference")
        return self

    @property
    def stop_distance(self) -> float:
        return abs(self.entry_reference - self.stop_loss)
