"""Bản ghi lệnh trong Execution Orchestrator (docs/09)."""

from __future__ import annotations

from pydantic import Field

from gold_trading.common.enums import OrderState, Side
from gold_trading.common.time import UtcDatetime
from gold_trading.contracts.base import Contract


class OrderRecord(Contract):
    order_id: str
    intent_id: str
    risk_decision_id: str
    market_view_id: str
    policy_version: str
    correlation_id: str
    idempotency_key: str
    symbol: str
    side: Side
    volume: float = Field(gt=0)
    filled_volume: float = Field(default=0.0, ge=0)
    state: OrderState
    broker_ticket: int | None = None
    updated_at: UtcDatetime
