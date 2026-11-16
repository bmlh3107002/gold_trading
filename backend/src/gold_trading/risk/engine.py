"""Risk Engine (docs/07): cổng phê duyệt vốn — cổng cuối trước khi có lệnh.

RSK-10 (KN-01): Risk **tự đọc** cổng thật lúc quyết (``RiskGates``): Safety + khóa người dùng +
lệnh cấm làn nhanh (DEC-20) qua ``AccountRegistry``, chế độ của tài khoản, MarketView **hiện hành**
của đúng nguồn giá (thấy MarketView bị vô hiệu), sức khỏe nguồn lịch (Q1). Bên gọi chỉ đưa intent +
tài khoản. Đọc lỗi → ``REJECTED`` (``GATE_READ_ERROR:<cổng>``), không ném lên người gọi.
Thiết kế: docs/thiet-ke/35-risk-engine.md.

Chưa có lệnh thật nào: Risk chỉ ra quyết định + giữ chỗ ngân sách trong sổ paper.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from gold_trading.common.enums import RiskOutcome, TradingMode
from gold_trading.common.ids import new_id
from gold_trading.common.time import utcnow
from gold_trading.contracts.market_view import SAMPLE_DATA, UNVALIDATED_RULES, MarketView
from gold_trading.contracts.risk import RiskDecision
from gold_trading.contracts.trade_intent import TradeIntent
from gold_trading.risk.gates import RiskGates
from gold_trading.risk.ledger import RiskLedger

log = logging.getLogger("gold_trading.risk")


@dataclass(frozen=True)
class RiskPolicy:
    """Số rủi ro **không có mặc định** (DEC-09, KN-12): bước 3 thay bằng hồ sơ rủi ro người dùng
    chọn. Test dùng số giả có nhãn "chỉ để test"."""

    version: str
    max_risk_per_trade: float      # tỷ lệ equity / lệnh
    max_total_reserved: float      # tỷ lệ equity cho mọi reservation đang mở
    max_spread: float              # TẠM (tới RSK-11 2d): đơn vị giá
    decision_ttl: timedelta = timedelta(seconds=30)
    blocking_flags: frozenset[str] = frozenset({"NEWS_SHOCK", "EVENT_WINDOW"})
    # GĐ4 bước 5c (DEC-25, 4-C06): cờ chất lượng MarketView chặn theo chế độ. Dữ liệu mẫu và luật
    # chưa kiểm chứng (backtest GĐ6 + người dùng duyệt) KHÔNG được dẫn tới lệnh SHADOW / LIVE.
    # Gỡ UNVALIDATED_RULES = quyết định mới của người dùng (ghi file giai đoạn + đổi version).
    blocking_quality_flags: Mapping[TradingMode, frozenset[str]] = field(default_factory=lambda: {
        TradingMode.SHADOW: frozenset({SAMPLE_DATA, UNVALIDATED_RULES}),
        TradingMode.LIVE: frozenset({SAMPLE_DATA, UNVALIDATED_RULES}),
    })


@dataclass(frozen=True)
class SymbolSpec:
    """TẠM (tới RSK-11 2a): thông số hằng số — sẽ thay bằng ``spec_at`` của broker thật."""

    contract_size: float = 100.0
    volume_min: float = 0.01
    volume_max: float = 50.0
    volume_step: float = 0.01


@dataclass(frozen=True)
class SizingInputs:
    """TẠM (tới RSK-11 2b–2d): equity + spread do bên gọi đưa — sẽ thay bằng đọc thật."""

    equity: float
    spread: float


class RiskEngine:
    def __init__(
        self,
        policy: RiskPolicy,
        ledger: RiskLedger,
        gates: RiskGates,
        *,
        spec: SymbolSpec | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.policy = policy
        self.ledger = ledger
        self.gates = gates
        self.spec = spec or SymbolSpec()
        self.clock = clock

    # ------------------------------------------------------------------ pha A: cổng

    def _read(self, name: str, reasons: list[str], fn: Callable[[], object]) -> object | None:
        try:
            return fn()
        except Exception:
            log.exception("Risk: đọc cổng %s lỗi → từ chối", name)
            reasons.append(f"GATE_READ_ERROR:{name}")
            return None

    def _gate_checks(self, intent: TradeIntent, account_id: str, now: datetime,
                     reasons: list[str]) -> MarketView | None:
        g, p = self.gates, self.policy
        denials = self._read("accounts", reasons, lambda: g.accounts.entry_denials(account_id, now))
        if denials:
            reasons.extend(denials)  # type: ignore[arg-type]
        mode = self._read("mode", reasons, lambda: g.accounts.mode(account_id))
        if now >= intent.expiry:
            reasons.append("INTENT_EXPIRED")

        view: MarketView | None = None
        scope = self._read("price_feed", reasons, lambda: g.scope_for(account_id))
        if scope is None:
            if not any(r == "GATE_READ_ERROR:price_feed" for r in reasons):
                reasons.append("NO_PRICE_FEED")
        else:
            view = self._read("market_view", reasons,
                              lambda: g.market_views.current(scope, now))  # type: ignore[arg-type]
            if view is None:
                if "GATE_READ_ERROR:market_view" not in reasons:
                    reasons.append("NO_MARKET_VIEW")
            elif view.market_view_id != intent.market_view_id:
                reasons.append("MARKET_VIEW_MISMATCH")
            elif view.symbol != intent.symbol:
                reasons.append("SYMBOL_MISMATCH")
        if view is not None:
            if blocked := sorted(view.risk_flags & p.blocking_flags):
                reasons.append("RISK_FLAGS:" + ",".join(blocked))
        if not isinstance(mode, TradingMode):
            if "GATE_READ_ERROR:mode" not in reasons:
                reasons.append("MODE_UNKNOWN")
        elif view is not None and (
                q := sorted(view.quality_flags & p.blocking_quality_flags.get(mode, frozenset()))):
            reasons.append(f"QUALITY_FLAGS_{mode.value}:" + ",".join(q))
        cal = self._read("calendar_health", reasons, lambda: g.calendar_health(now))
        if cal:
            reasons.extend(cal)  # type: ignore[arg-type]
        return view

    # ------------------------------------------------------------------ quyết định

    def evaluate(self, intent: TradeIntent, account_id: str,
                 inputs: SizingInputs) -> RiskDecision:
        p = self.policy
        now = self.clock()
        reasons: list[str] = []
        self._gate_checks(intent, account_id, now, reasons)
        if inputs.spread > p.max_spread:
            reasons.append("SPREAD_TOO_WIDE")
        if inputs.equity <= 0:
            reasons.append("NO_EQUITY")
        if reasons:
            return self._reject(intent, now, reasons)

        # Khóa ledger để hai intent đồng thời không cùng vượt hạn mức.
        with self.ledger.lock:
            requested = min(intent.risk_budget_requested, p.max_risk_per_trade)
            headroom = p.max_total_reserved * inputs.equity - self.ledger.reserved_total()
            risk_amount = min(requested * inputs.equity, headroom)

            loss_per_lot = intent.stop_distance * self.spec.contract_size
            volume = self._floor_step(risk_amount / loss_per_lot) if risk_amount > 0 else 0.0
            volume = min(volume, self.spec.volume_max)
            if volume < self.spec.volume_min:
                return self._reject(intent, now, ["INSUFFICIENT_RISK_BUDGET"])

            actual_risk = volume * loss_per_lot
            reduced = requested < intent.risk_budget_requested or actual_risk < (
                intent.risk_budget_requested * inputs.equity - 1e-9
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
            decided_at=now,
            expires_at=now + p.decision_ttl,
            policy_version=p.version,
        )

    def _floor_step(self, volume: float) -> float:
        step = self.spec.volume_step
        return round(math.floor(volume / step + 1e-9) * step, 8)

    def _reject(self, intent: TradeIntent, now: datetime, reasons: list[str]) -> RiskDecision:
        return RiskDecision(
            risk_decision_id=new_id("rd"),
            intent_id=intent.intent_id,
            outcome=RiskOutcome.REJECTED,
            reason_codes=tuple(reasons),
            decided_at=now,
            expires_at=now + self.policy.decision_ttl,
            policy_version=self.policy.version,
        )
