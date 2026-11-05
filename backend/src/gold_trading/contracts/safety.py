"""Event chuyển trạng thái Safety (docs/08)."""

from __future__ import annotations

from gold_trading.common.enums import SafetyState
from gold_trading.common.time import UtcDatetime
from gold_trading.contracts.base import Contract


class SafetyTransition(Contract):
    transition_id: str
    from_state: SafetyState
    to_state: SafetyState
    reason_code: str
    trigger_source: str
    actor: str
    at: UtcDatetime
    policy_version: str
