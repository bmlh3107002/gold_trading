"""Risk Engine (docs/07): cổng phê duyệt vốn — cổng cuối trước khi có lệnh.

RSK-10 (KN-01): Risk **tự đọc** cổng thật lúc quyết (``RiskGates``): Safety + khóa người dùng +
lệnh cấm làn nhanh (DEC-20) qua ``AccountRegistry``, chế độ của tài khoản, MarketView **hiện hành**
của đúng nguồn giá (thấy MarketView bị vô hiệu), sức khỏe nguồn lịch (Q1).

RSK-11 (KN-02): khối lượng + rủi ro theo thông số **thật** của broker tại lúc quyết (``spec_at``,
phải trùng nhịp tim hiện tại), equity từ nhịp tim, spread hiện tại + đệm trượt giá (p95 30 ngày
của chính sàn, Q4) + phí khứ hồi / lot do người dùng nhập (Q3); ngưỡng spread quá rộng = cùng mốc
p95 (Q5); SL quá gần stops / freeze level (RSK-08). Tiền / rủi ro bằng ``Decimal`` (CORE-05).

Bên gọi chỉ đưa intent + tài khoản. Thiếu / cũ / đọc lỗi → ``REJECTED`` có lý do, không ném lên
người gọi. Thiết kế: docs/thiet-ke/35-risk-engine.md. Chưa có lệnh thật nào.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from gold_trading.common.enums import RiskOutcome, TradingMode
from gold_trading.common.ids import new_id
from gold_trading.common.time import utcnow
from gold_trading.contracts.market_view import SAMPLE_DATA, UNVALIDATED_RULES, MarketView
from gold_trading.contracts.risk import RiskDecision
from gold_trading.contracts.trade_intent import TradeIntent
from gold_trading.market.quote_minutes import p_nearest_rank
from gold_trading.market.quotes import CALENDAR_CLOSED
from gold_trading.risk.gates import BrokerReading, RiskGates
from gold_trading.risk.ledger import RiskLedger
from gold_trading.risk.sizing import SizingSpec, dec, size

log = logging.getLogger("gold_trading.risk")

# Giá trị khởi đầu chưa hiệu chỉnh (thiết kế 35 mục 3; vào sổ tham số KN-08 ở bước 9).
EQUITY_MAX_AGE_S = 30.0                    # = HEARTBEAT_TIMEOUT của Gateway
QUOTE_MAX_AGE = timedelta(seconds=10)      # = ngân sách độ trễ làn nhanh (GĐ2 4d)
BASELINE_WINDOW = timedelta(days=30)       # Q4 / Q5
BASELINE_MIN_MINUTES = 6900                # ≈ 5 ngày giao dịch × 23 giờ × 60 phút
SUPPORTED_CURRENCY = "USD"                 # Q2
REQUIRED_SPEC = ("contract_size", "point", "volume_min", "volume_max", "volume_step",
                 "currency_profit", "account_currency", "stops_level", "freeze_level")


@dataclass(frozen=True)
class RiskPolicy:
    """Chính sách kỹ thuật (không có số rủi ro): số rủi ro / lệnh và trần tổng giữ chỗ lấy từ
    **hồ sơ rủi ro** người dùng chọn (bước 3, DEC-09 / KN-12). Chưa có hồ sơ → NO_RISK_PROFILE."""

    version: str
    decision_ttl: timedelta = timedelta(seconds=30)
    blocking_flags: frozenset[str] = frozenset({"NEWS_SHOCK", "EVENT_WINDOW"})
    # GĐ4 bước 5c (DEC-25, 4-C06): cờ chất lượng MarketView chặn theo chế độ. Dữ liệu mẫu và luật
    # chưa kiểm chứng (backtest GĐ6 + người dùng duyệt) KHÔNG được dẫn tới lệnh SHADOW / LIVE.
    # Gỡ UNVALIDATED_RULES = quyết định mới của người dùng (ghi file giai đoạn + đổi version).
    blocking_quality_flags: Mapping[TradingMode, frozenset[str]] = field(default_factory=lambda: {
        TradingMode.SHADOW: frozenset({SAMPLE_DATA, UNVALIDATED_RULES}),
        TradingMode.LIVE: frozenset({SAMPLE_DATA, UNVALIDATED_RULES}),
    })


@dataclass
class _Market:
    """Số đọc được ở pha A, dùng cho pha B (khối lượng)."""

    equity: Decimal | None = None
    spec: SizingSpec | None = None
    point: Decimal | None = None
    spread_points: int | None = None
    baseline_points: int | None = None
    commission: Decimal | None = None
    details: dict[str, str] = field(default_factory=dict)


class RiskEngine:
    def __init__(
        self,
        policy: RiskPolicy,
        ledger: RiskLedger,
        gates: RiskGates,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.policy = policy
        self.ledger = ledger
        self.gates = gates
        self.clock = clock

    # ------------------------------------------------------------------ đọc cổng an toàn

    @staticmethod
    def _read(name: str, reasons: list[str], fn: Callable[[], object]) -> tuple[bool, object]:
        try:
            return True, fn()
        except Exception:
            log.exception("Risk: đọc cổng %s lỗi → từ chối", name)
            reasons.append(f"GATE_READ_ERROR:{name}")
            return False, None

    # ------------------------------------------------------------------ pha A1–A6 (RSK-10)

    def _gate_checks(self, intent: TradeIntent, account_id: str, now: datetime,
                     reasons: list[str]) -> str | None:
        """Trả nguồn giá (feed) của tài khoản nếu đọc được."""
        g, p = self.gates, self.policy
        ok, denials = self._read("accounts", reasons,
                                 lambda: g.accounts.entry_denials(account_id, now))
        if ok and denials:
            reasons.extend(denials)  # type: ignore[arg-type]
        ok_mode, mode = self._read("mode", reasons, lambda: g.accounts.mode(account_id))
        if now >= intent.expiry:
            reasons.append("INTENT_EXPIRED")

        view: MarketView | None = None
        ok, scope = self._read("price_feed", reasons, lambda: g.scope_for(account_id))
        if ok and scope is None:
            reasons.append("NO_PRICE_FEED")
        elif scope is not None:
            ok, view = self._read("market_view", reasons,
                                  lambda: g.market_views.current(scope, now))  # type: ignore
            if ok and view is None:
                reasons.append("NO_MARKET_VIEW")
            elif view is not None:
                if view.market_view_id != intent.market_view_id:
                    reasons.append("MARKET_VIEW_MISMATCH")
                elif view.symbol != intent.symbol:
                    reasons.append("SYMBOL_MISMATCH")
                if blocked := sorted(view.risk_flags & p.blocking_flags):
                    reasons.append("RISK_FLAGS:" + ",".join(blocked))
        if ok_mode and not isinstance(mode, TradingMode):
            reasons.append("MODE_UNKNOWN")
        elif isinstance(mode, TradingMode) and view is not None and (
                q := sorted(view.quality_flags & p.blocking_quality_flags.get(mode, frozenset()))):
            reasons.append(f"QUALITY_FLAGS_{mode.value}:" + ",".join(q))
        ok, cal = self._read("calendar_health", reasons, lambda: g.calendar_health(now))
        if ok and cal:
            reasons.extend(cal)  # type: ignore[arg-type]
        return scope.feed if scope is not None else None  # type: ignore[union-attr]

    # ------------------------------------------------------------------ pha A7–A8 (RSK-11 2a–2b)

    @staticmethod
    def _broker_checks(b: BrokerReading, m: _Market, reasons: list[str]) -> None:
        fresh = (b.connected and b.heartbeat_age_s is not None
                 and 0 <= b.heartbeat_age_s <= EQUITY_MAX_AGE_S)
        if not fresh or b.equity is None:
            reasons.append("EQUITY_STALE")
        else:
            m.equity = dec(b.equity)
            m.details["equity"] = str(m.equity)
            if m.equity <= 0:
                reasons.append("NO_EQUITY")
        spec = b.spec
        if b.locked_symbol is None or spec is None:
            reasons.append("BROKER_SPEC_MISSING")
            return
        # Thông số trong DB phải là đúng thông số nhịp tim hiện tại báo (cùng MT5, cùng mã, cùng
        # giá trị) — khác = DB chưa kịp ghi bản mới / Gateway đổi MT5 / mất kết nối.
        if (not fresh or b.heartbeat_symbol != b.locked_symbol
                or b.identity != (spec.key.mt5_login, spec.key.mt5_server)
                or b.live_spec_hash != spec.spec_hash):
            reasons.append("BROKER_SPEC_STALE")
        s = spec.spec
        missing = [k for k in REQUIRED_SPEC if s.get(k) is None]
        if missing:
            reasons.extend(f"BROKER_SPEC_MISSING:{k}" for k in missing)
            return
        if (s["account_currency"] != SUPPORTED_CURRENCY
                or s["currency_profit"] != SUPPORTED_CURRENCY
                or (b.account_currency is not None
                    and b.account_currency != SUPPORTED_CURRENCY)):
            reasons.append("CURRENCY_UNSUPPORTED")
        m.spec = SizingSpec(dec(s["contract_size"]), dec(s["volume_min"]), dec(s["volume_max"]),
                            dec(s["volume_step"]))
        m.point = dec(s["point"])
        m.details |= {"broker_symbol": spec.key.broker_symbol,
                      "spec_observed_at": spec.observed_at.isoformat(),
                      "contract_size": str(m.spec.contract_size), "point": str(m.point),
                      "stops_level": str(s["stops_level"]),
                      "freeze_level": str(s["freeze_level"])}
        m.details["_stops"] = str(max(int(s["stops_level"]), int(s["freeze_level"])))

    # ------------------------------------------------------------------ pha A9–A11 (2c–2d)

    def _market_checks(self, account_id: str, feed: str, now: datetime, m: _Market,
                       reasons: list[str]) -> None:
        g = self.gates
        ok, q = self._read("quote", reasons, lambda: g.latest_quote(feed, now))
        if ok:
            if q is None or now - q.t > QUOTE_MAX_AGE or q.t > now:  # type: ignore[union-attr]
                reasons.append("QUOTE_STALE")
            elif CALENDAR_CLOSED in q.flags:  # type: ignore[union-attr]
                reasons.append("MARKET_CLOSED")
            else:
                m.spread_points = max(q.spread_points, q.spread_max_points)  # type: ignore
                m.details["spread_points"] = str(m.spread_points)
        ok, rows = self._read("spread_minutes", reasons,
                              lambda: g.spread_minutes(feed, now - BASELINE_WINDOW, now, now))
        if ok:
            vals = [r.spread_p95 for r in rows  # type: ignore[union-attr]
                    if r.seconds_closed == 0 and r.t < now]
            m.details["baseline_minutes"] = str(len(vals))
            if len(vals) < BASELINE_MIN_MINUTES:
                reasons.append("SPREAD_BASELINE_MISSING")
            else:
                m.baseline_points = p_nearest_rank(vals, 0.95)
                m.details["spread_p95_30d_points"] = str(m.baseline_points)
        if m.spread_points is not None and m.baseline_points is not None \
                and m.spread_points > m.baseline_points:
            reasons.append("SPREAD_TOO_WIDE")
        ok, c = self._read("commission", reasons, lambda: g.commission(account_id, now))
        if ok:
            if c is None:
                reasons.append("COMMISSION_UNKNOWN")
            elif c.currency != SUPPORTED_CURRENCY:  # type: ignore[union-attr]
                reasons.append("CURRENCY_UNSUPPORTED")
            else:
                m.commission = c.per_lot  # type: ignore[union-attr]
                m.details["commission_per_lot"] = str(m.commission)

    # ------------------------------------------------------------------ quyết định

    def evaluate(self, intent: TradeIntent, account_id: str) -> RiskDecision:
        now = self.clock()
        reasons: list[str] = []
        m = _Market()
        feed = self._gate_checks(intent, account_id, now, reasons)
        ok, b = self._read("broker", reasons, lambda: self.gates.broker(account_id, now))
        if ok:
            self._broker_checks(b, m, reasons)  # type: ignore[arg-type]
        ok, prof = self._read("risk_profile", reasons,
                              lambda: self.gates.risk_profile(account_id, now))
        if ok and prof is None:
            reasons.append("NO_RISK_PROFILE")
        if feed:
            self._market_checks(account_id, feed, now, m, reasons)
        elif feed == "":
            reasons.append("NO_PRICE_FEED")          # nguồn không gắn broker (SAMPLE / CSV)

        stop = dec(intent.entry_reference) - dec(intent.stop_loss)
        stop = abs(stop)
        if m.point is not None and m.spread_points is not None:
            spread = m.spread_points * m.point
            min_stop = max(int(m.details["_stops"]) * m.point, spread)
            if stop < min_stop:                                           # RSK-08, 5-C02
                reasons.append("SL_TOO_CLOSE")
                m.details["min_stop_distance"] = str(min_stop)
        m.details.pop("_stops", None)
        if intent.take_profit is None:                    # 4b: không có TP → không tính được R:R
            reasons.append("NO_TAKE_PROFIT")
        if reasons:
            return self._reject(intent, account_id, now, reasons, m.details)

        assert m.equity is not None and m.spec is not None and m.point is not None
        assert m.spread_points is not None and m.baseline_points is not None
        assert m.commission is not None
        p = self.policy
        spread = m.spread_points * m.point
        slippage = m.baseline_points * m.point
        requested = dec(intent.risk_budget_requested)
        with self.ledger.lock:            # hai intent đồng thời không cùng vượt hạn mức
            # 5-C13: đọc lại hồ sơ dưới khóa — đổi giữa lúc kiểm và lúc tính → dùng bản mới.
            ok, prof2 = self._read("risk_profile", reasons,
                                   lambda: self.gates.risk_profile(account_id, now))
            if not ok or prof2 is None:
                return self._reject(intent, account_id, now, reasons or ["NO_RISK_PROFILE"],
                                    m.details)
            if prof2.version != prof.version:  # type: ignore[union-attr]
                m.details["profile_reread"] = f"{prof.version}->{prof2.version}"  # type: ignore
            pv = prof2.values
            m.details["risk_profile_version"] = str(prof2.version)
            frac = min(requested, pv.risk_per_trade)
            headroom = pv.max_open_risk * m.equity - self.ledger.reserved_total()
            money = min(frac * m.equity, headroom)
            res = size(money, stop, spread, slippage, m.commission, m.spec)
            details = m.details | {
                "stop_distance": str(stop), "spread": str(spread), "slippage": str(slippage),
                "effective_distance": str(res.effective_distance),
                "risk_per_lot": str(res.risk_per_lot), "risk_money_allowed": str(money)}
            # 4b (H2): R:R sau chi phí = (|TP − vào| − spread) × cỡ HĐ − phí, chia rủi ro / lot.
            assert intent.take_profit is not None
            reward = ((abs(dec(intent.take_profit) - dec(intent.entry_reference)) - spread)
                      * m.spec.contract_size - m.commission)
            rr = reward / res.risk_per_lot
            details["reward_per_lot"] = str(reward)
            details["reward_risk"] = str(rr.quantize(Decimal("0.0001")))
            details["min_reward_risk"] = str(pv.min_reward_risk)
            if rr < pv.min_reward_risk:
                return self._reject(intent, account_id, now, ["REWARD_RISK_TOO_LOW"], details)
            if res.volume <= 0:                                           # 5-C01
                details["shortfall"] = str(res.shortfall)
                if frac > 0:
                    details["min_equity_for_min_lot"] = str(
                        m.spec.volume_min * res.risk_per_lot / frac)
                return self._reject(intent, account_id, now, ["BELOW_MIN_VOLUME"], details)
            reduced = (frac < requested or money < frac * m.equity or res.capped_at_max)
            rid = self.ledger.reserve(intent.symbol, res.risk_amount, f"intent:{intent.intent_id}")

        return RiskDecision(
            risk_decision_id=new_id("rd"),
            intent_id=intent.intent_id,
            account_id=account_id,
            outcome=RiskOutcome.REDUCED if reduced else RiskOutcome.APPROVED,
            volume=res.volume,
            risk_amount=res.risk_amount,
            reservation_id=rid,
            reason_codes=("REDUCED_TO_LIMIT",) if reduced else (),
            details=details,
            decided_at=now,
            expires_at=now + p.decision_ttl,
            policy_version=p.version,
            risk_profile_version=prof2.version,
        )

    def _reject(self, intent: TradeIntent, account_id: str, now: datetime, reasons: list[str],
                details: dict[str, str]) -> RiskDecision:
        return RiskDecision(
            risk_decision_id=new_id("rd"),
            intent_id=intent.intent_id,
            account_id=account_id,
            outcome=RiskOutcome.REJECTED,
            reason_codes=tuple(dict.fromkeys(reasons)),
            details=details,
            decided_at=now,
            expires_at=now + self.policy.decision_ttl,
            policy_version=self.policy.version,
        )
