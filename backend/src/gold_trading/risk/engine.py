"""Risk Engine (docs/07): cổng phê duyệt vốn.

Bản khung này kiểm tra các điều kiện cốt lõi và tính volume từ mức rủi ro.
Các kiểm tra margin, correlation, exposure ròng... sẽ bổ sung sau.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from gold_trading.common.enums import RiskOutcome
from gold_trading.common.ids import new_id
from gold_trading.contracts.market_view import MarketView
from gold_trading.contracts.risk import RiskDecision
from gold_trading.contracts.trade_intent import TradeIntent
from gold_trading.risk.ledger import RiskLedger
from gold_trading.safety.supervisor import SafetySupervisor


@dataclass(frozen=True)
class RiskPolicy:
    version: str
    max_risk_per_trade: float = 0.005  # 0.5% equity
    max_total_reserved: float = 0.02  # 2% equity cho mọi reservation đang mở
    max_spread: float = 0.5  # đơn vị giá
    decision_ttl: timedelta = timedelta(seconds=30)
    blocking_flags: frozenset[str] = frozenset({"NEWS_SHOCK", "EVENT_WINDOW"})


@dataclass(frozen=True)
class SymbolSpec:
    contract_size: float = 100.0  # XAUUSD: 1 lot = 100 oz
    volume_min: float = 0.01
    volume_max: float = 50.0
    volume_step: float = 0.01


@dataclass(frozen=True)
class MarketContext:
    equity: float
    spread: float
    now: datetime


class RiskEngine:
    def __init__(
        self,
        policy: RiskPolicy,
        ledger: RiskLedger,
        safety: SafetySupervisor,
        spec: SymbolSpec | None = None,
    ) -> None:
        self.policy = policy
        self.ledger = ledger
        self.safety = safety
        self.spec = spec or SymbolSpec()

    def evaluate(self, intent: TradeIntent, view: MarketView, ctx: MarketContext) -> RiskDecision:
        p = self.policy
        reasons: list[str] = []

        if not self.safety.allows_new_orders():
            reasons.append(f"SAFETY_{self.safety.state}")
        if ctx.now >= intent.expiry:
            reasons.append("INTENT_EXPIRED")
        if view.market_view_id != intent.market_view_id:
            reasons.append("MARKET_VIEW_MISMATCH")
        elif not view.is_valid_at(ctx.now):
            reasons.append("MARKET_VIEW_EXPIRED")
        if blocked := sorted(view.risk_flags & p.blocking_flags):
            reasons.append("RISK_FLAGS:" + ",".join(blocked))
        if ctx.spread > p.max_spread:
            reasons.append("SPREAD_TOO_WIDE")
        if ctx.equity <= 0:
            reasons.append("NO_EQUITY")
        if reasons:
            return self._reject(intent, ctx, reasons)

        # Khóa ledger để hai intent đồng thời không cùng vượt hạn mức.
        with self.ledger.lock:
            requested = min(intent.risk_budget_requested, p.max_risk_per_trade)
            headroom = p.max_total_reserved * ctx.equity - self.ledger.reserved_total()
            risk_amount = min(requested * ctx.equity, headroom)

            loss_per_lot = intent.stop_distance * self.spec.contract_size
            volume = self._floor_step(risk_amount / loss_per_lot) if risk_amount > 0 else 0.0
            volume = min(volume, self.spec.volume_max)
            if volume < self.spec.volume_min:
                return self._reject(intent, ctx, ["INSUFFICIENT_RISK_BUDGET"])

            actual_risk = volume * loss_per_lot
            reduced = requested < intent.risk_budget_requested or actual_risk < (
                intent.risk_budget_requested * ctx.equity - 1e-9
            )
            rid = self.ledger.reserve(intent.symbol, actual_risk, f"intent:{intent.intent_id}")

        return RiskDecision(
            risk_decision_id=new_id("rd"),
            intent_id=intent.intent_id,
            outcome=RiskOutcome.REDUCED if reduced else RiskOutcome.APPROVED,
            volume=volume,
            risk_amount=actual_risk,
            reservation_id=rid,
            reason_codes=("REDUCED_TO_LIMIT",) if reduced else (),
            decided_at=ctx.now,
            expires_at=ctx.now + p.decision_ttl,
            policy_version=p.version,
        )

    def _floor_step(self, volume: float) -> float:
        step = self.spec.volume_step
        return round(math.floor(volume / step + 1e-9) * step, 8)

    def _reject(self, intent: TradeIntent, ctx: MarketContext, reasons: list[str]) -> RiskDecision:
        return RiskDecision(
            risk_decision_id=new_id("rd"),
            intent_id=intent.intent_id,
            outcome=RiskOutcome.REJECTED,
            reason_codes=tuple(reasons),
            decided_at=ctx.now,
            expires_at=ctx.now + self.policy.decision_ttl,
            policy_version=self.policy.version,
        )
