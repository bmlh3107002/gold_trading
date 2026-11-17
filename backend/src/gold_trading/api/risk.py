"""API trang Rủi ro (GĐ5 bước 8b — RPF-05, DSH-05; thiết kế 37 mục 3).

Mọi đường qua ``Guard.check`` (chỉ **chủ tài khoản** USER đang hoạt động; ADMIN không vào — DEC-16,
Q6). Mọi lệnh ghi có ``reason`` và ghi audit. Số tiền / tỷ lệ trả dạng ``Decimal`` (JSON chuỗi).

Không có lệnh thật: chỉ nhập những thứ Risk đang chờ (hồ sơ rủi ro, phí / lot, bắt đầu sổ paper,
nạp / rút, xác nhận sau khi dừng H6) + xem trạng thái + báo cáo khả thi.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from gold_trading.auth.web import CurrentUser
from gold_trading.common.enums import Side
from gold_trading.common.time import utcnow
from gold_trading.risk.book import position_of, unrealized
from gold_trading.risk.engine import BASELINE_WINDOW, EQUITY_MAX_AGE_S
from gold_trading.risk.feasibility import FeasibilityReport, compute, gather
from gold_trading.risk.ledger import EventType, LedgerConflict
from gold_trading.risk.paper import fresh_quote
from gold_trading.risk.periods import Periods
from gold_trading.storage.commissions import Commission
from gold_trading.storage.risk_profiles import (
    ProfileError,
    ProfilePermissionError,
    RiskProfileValues,
    create_profile,
)

Reason = Field(min_length=1, max_length=256, description="Lý do (bắt buộc, ghi audit)")


class ProfileValuesIO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    risk_per_trade: Decimal
    min_reward_risk: Decimal
    max_open_risk: Decimal
    max_daily_loss: Decimal
    max_weekly_loss: Decimal
    max_monthly_loss: Decimal
    max_consecutive_losses: int
    day_reset_tz: str
    day_reset_time: str
    max_trades_per_day: int
    max_drawdown_halt: Decimal
    news_hold_policy: str
    weekend_policy: str
    weekend_close_before_min: int
    max_effective_leverage: Decimal
    cash_flow_policy: str
    pyramiding_policy: str
    notes: str = ""


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: ProfileValuesIO
    reason: str = Reason


class ProfileOut(BaseModel):
    version: int
    created_at: datetime
    created_by: str
    reason: str
    values: ProfileValuesIO


class CommissionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    per_lot: Decimal = Field(description="Phí khứ hồi / lot, USD (≥ 0; nhập 0 nếu sàn không thu)")
    reason: str = Reason


class CommissionOut(BaseModel):
    per_lot: Decimal
    currency: str
    created_at: datetime
    created_by: str
    reason: str


class PaperStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Reason


class CashIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["CASH_IN", "CASH_OUT"]
    amount: Decimal = Field(gt=0)
    reason: str = Reason


class DrawdownResetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: Literal[True] = Field(description="Phải là true: xác nhận rõ đã xem lại (H6)")
    reason: str = Reason


class PositionOut(BaseModel):
    position_id: str
    side: Side
    volume: Decimal
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal | None
    opened_at: datetime
    strategy_id: str | None


class ReservationOut(BaseModel):
    reservation_id: str
    amount: Decimal
    at: datetime
    expires_at: datetime | None


class PaperOut(BaseModel):
    started: bool
    capital: Decimal | None = None
    realized_equity: Decimal | None = Field(default=None,
                                            description="vốn + nạp − rút + PnL đã đóng")
    unrealized: Decimal | None = Field(default=None,
                                       description="PnL đang chạy (null: không có giá mới)")
    peak: Decimal | None = None
    drawdown: Decimal | None = Field(default=None, description="Mức sụt từ đỉnh (0,05 = 5 %)")
    halted: bool = Field(default=False, description="Sụt ≥ ngưỡng H6 → cần xác nhận rõ")
    positions: list[PositionOut] = []
    reservations: list[ReservationOut] = []


class UsageOut(BaseModel):
    day_start: datetime
    trades_today: int
    max_trades_per_day: int
    daily_loss: Decimal | None = Field(description="Lỗ đã chốt trong ngày / equity paper")
    weekly_loss: Decimal | None
    monthly_loss: Decimal | None
    max_daily_loss: Decimal
    max_weekly_loss: Decimal
    max_monthly_loss: Decimal
    loss_streak: int
    max_consecutive_losses: int


class DecisionOut(BaseModel):
    risk_decision_id: str
    decided_at: datetime
    outcome: str
    reason_codes: list[str]
    volume: Decimal
    risk_amount: Decimal


class EvaluationOut(BaseModel):
    evaluated_at: datetime
    market_view_id: str
    outcome: str
    reasons: list[str]
    risk_outcome: str | None
    fill_code: str | None


class Readiness(BaseModel):
    profile: bool
    commission: bool
    paper_started: bool


class RiskOverview(BaseModel):
    account_id: str
    is_sample: bool
    strategy_enabled: bool
    readiness: Readiness
    profile: ProfileOut | None
    profile_history: list[ProfileOut]
    commission: CommissionOut | None
    commission_history: list[CommissionOut]
    paper: PaperOut
    usage: UsageOut | None
    decisions: list[DecisionOut]
    evaluations: list[EvaluationOut]


def _profile_out(p) -> ProfileOut:
    return ProfileOut(version=p.version, created_at=p.created_at, created_by=p.created_by,
                      reason=p.reason, values=ProfileValuesIO(**p.values.__dict__))


def _commission_out(c) -> CommissionOut:
    return CommissionOut(per_lot=c.per_lot, currency=c.currency, created_at=c.created_at,
                         created_by=c.created_by, reason=c.reason)


def risk_router(*, guard, repo, profiles, commissions, ledger, gates, evaluations,
                technical_latest: Callable[[str, datetime], object | None],
                strategy_enabled: Callable[[], bool],
                clock: Callable[[], datetime] = utcnow) -> APIRouter:
    r = APIRouter(prefix="/api/accounts/{account_id}/risk", tags=["risk"])

    def scope(acc: str):
        return gates.scope_for(acc)

    def is_sample(acc: str) -> bool:
        sc = scope(acc)
        return sc is not None and sc.source == "SAMPLE"

    def live_quote(acc: str, now: datetime):
        sc = scope(acc)
        if sc is None or not sc.feed:
            return None
        q = gates.latest_quote(sc.feed, now)
        return q if q is not None and fresh_quote(q, now) is None else None

    def unrealized_now(acc: str, now: datetime) -> Decimal | None:
        """PnL đang chạy của lệnh paper; không có lệnh → 0; có lệnh mà không có giá mới → None."""
        opened = ledger.open_position_events(acc)
        if not opened:
            return Decimal(0)
        q = live_quote(acc, now)
        if q is None:
            return None
        bid, ask = Decimal(str(q.bid)), Decimal(str(q.ask))
        return sum((unrealized(position_of(e, ledger.current_stop(acc, e)), bid, ask,
                               Decimal(e.data["contract_size"])) for e in opened), Decimal(0))

    def paper_out(acc: str, now: datetime, prof) -> PaperOut:
        st = ledger.equity_state(acc, now)
        opened = ledger.open_position_events(acc)
        pos = [PositionOut(position_id=e.ref_id, side=Side(e.data["side"]),
                           volume=Decimal(e.data["volume"]),
                           entry_price=Decimal(e.data["entry_price"]),
                           stop_loss=ledger.current_stop(acc, e),
                           take_profit=Decimal(e.data["take_profit"]) if e.data.get(
                               "take_profit") else None,
                           opened_at=e.at, strategy_id=e.data.get("strategy_id"))
               for e in opened]
        res = [ReservationOut(reservation_id=e.ref_id, amount=e.amount, at=e.at,
                              expires_at=datetime.fromisoformat(e.data["expires_at"])
                              if e.data.get("expires_at") else None)
               for e in ledger.open_reservations(acc)]
        if st is None:
            return PaperOut(started=False, positions=pos, reservations=res)
        start = next(e for e in ledger.events(acc, (EventType.START,)))
        un = unrealized_now(acc, now)
        eq = st.realized + (un or Decimal(0))
        peak = max(st.peak, eq)
        dd = ((peak - eq) / peak).quantize(Decimal("0.000001")) if peak > 0 else None
        halt = prof is not None and dd is not None and dd >= prof.values.max_drawdown_halt
        return PaperOut(started=True, capital=start.amount, realized_equity=st.realized,
                        unrealized=un, peak=peak, drawdown=dd, halted=halt, positions=pos,
                        reservations=res)

    def usage_out(acc: str, now: datetime, prof) -> UsageOut | None:
        if prof is None:
            return None
        pv = prof.values
        per = Periods.of(pv.day_reset_tz, pv.day_reset_time)
        day, week, month = per.day_start(now), per.week_start(now), per.month_start(now)
        st = ledger.equity_state(acc, now)
        closed = ledger.closed_trades(acc, min(day, week, month), now)

        def loss(start: datetime) -> Decimal | None:
            if st is None or st.realized <= 0:
                return None
            pnl = sum((t.net_pnl for t in closed if t.closed_at >= start), Decimal(0))
            return (-pnl / st.realized).quantize(Decimal("0.000001"))
        since = gates.accounts.active_since(acc)
        streak = 0
        for t in ledger.last_closed(acc, now, 500):           # cùng luật Risk 4c
            if since is not None and t.closed_at <= since:
                break
            if t.net_pnl > 0:
                break
            if t.net_pnl < 0:
                streak += 1
        return UsageOut(
            day_start=day, trades_today=ledger.opened_count(acc, day, now)
            + ledger.open_since(acc, day), max_trades_per_day=pv.max_trades_per_day,
            daily_loss=loss(day), weekly_loss=loss(week), monthly_loss=loss(month),
            max_daily_loss=pv.max_daily_loss, max_weekly_loss=pv.max_weekly_loss,
            max_monthly_loss=pv.max_monthly_loss, loss_streak=streak,
            max_consecutive_losses=pv.max_consecutive_losses)

    @r.get("/overview", response_model=RiskOverview)
    def overview(account_id: str, p: CurrentUser) -> RiskOverview:
        guard.check(account_id, p, "risk.overview")
        now = clock()
        prof = profiles.at(account_id, now)
        comm = commissions.at(account_id, now)
        paper = paper_out(account_id, now, prof)
        return RiskOverview(
            account_id=account_id, is_sample=is_sample(account_id),
            strategy_enabled=strategy_enabled(),
            readiness=Readiness(profile=prof is not None, commission=comm is not None,
                                paper_started=paper.started),
            profile=_profile_out(prof) if prof is not None else None,
            profile_history=[_profile_out(x) for x in reversed(profiles.history(account_id))],
            commission=_commission_out(comm) if comm is not None else None,
            commission_history=[_commission_out(x)
                                for x in reversed(commissions.history(account_id))],
            paper=paper, usage=usage_out(account_id, now, prof),
            decisions=[DecisionOut(risk_decision_id=d.risk_decision_id, decided_at=d.decided_at,
                                   outcome=d.outcome.value, reason_codes=list(d.reason_codes),
                                   volume=d.volume, risk_amount=d.risk_amount)
                       for d in ledger.recent_decisions(account_id, 20)],
            evaluations=[EvaluationOut(evaluated_at=e.evaluated_at,
                                       market_view_id=e.market_view_id, outcome=e.outcome,
                                       reasons=list(e.reasons), risk_outcome=e.risk_outcome,
                                       fill_code=e.fill_code)
                         for e in evaluations.recent(account_id, 20)])

    @r.get("/feasibility", response_model=FeasibilityReport)
    def feasibility(account_id: str, p: CurrentUser) -> FeasibilityReport:
        guard.check(account_id, p, "risk.feasibility")
        now = clock()
        b = gates.broker(account_id, now)
        fresh = (b.connected and b.heartbeat_age_s is not None
                 and 0 <= b.heartbeat_age_s <= EQUITY_MAX_AGE_S and b.equity is not None)
        sc = scope(account_id)
        feed = sc.feed if sc is not None else ""
        inp = gather(
            now=now, is_sample=is_sample(account_id),
            equity=Decimal(str(b.equity)) if fresh else None,
            equity_note="nhịp tim MT5" if fresh else "",
            spec=dict(b.spec.spec) if b.spec is not None else None,
            technical=technical_latest(account_id, now),
            quote=gates.latest_quote(feed, now) if feed else None,
            minute_rows=gates.spread_minutes(feed, now - BASELINE_WINDOW, now, now) if feed
            else [],
            commission=commissions.at(account_id, now), profile=profiles.at(account_id, now),
            paper_state=ledger.equity_state(account_id, now))
        return compute(inp)

    @r.post("/profile", response_model=ProfileOut, status_code=201)
    def new_profile(account_id: str, body: ProfileIn, p: CurrentUser) -> ProfileOut:
        guard.check(account_id, p, "risk.profile")
        payload = body.model_dump(mode="json")
        try:
            prof = create_profile(profiles, repo, account_id, p.sub,
                                  RiskProfileValues(**body.values.model_dump()),
                                  reason=body.reason, at=clock(), actor_is_admin=p.is_admin)
        except ProfilePermissionError as e:
            guard.audit(p, "risk.profile", "REJECTED", payload, str(e), account_id)
            raise HTTPException(403, str(e)) from e
        except ProfileError as e:
            guard.audit(p, "risk.profile", "REJECTED", payload, str(e), account_id)
            raise HTTPException(422, str(e)) from e
        guard.audit(p, "risk.profile", "ACCEPTED", payload | {"version": prof.version}, None,
                    account_id)
        return _profile_out(prof)

    @r.post("/commission", response_model=CommissionOut, status_code=201)
    def new_commission(account_id: str, body: CommissionIn, p: CurrentUser) -> CommissionOut:
        guard.check(account_id, p, "risk.commission")
        payload = body.model_dump(mode="json")
        c = Commission(account_id, body.per_lot, "USD", clock(), p.sub, body.reason)
        try:
            commissions.record(c)
        except ValueError as e:
            guard.audit(p, "risk.commission", "REJECTED", payload, str(e), account_id)
            raise HTTPException(422, str(e)) from e
        guard.audit(p, "risk.commission", "ACCEPTED", payload, None, account_id)
        return _commission_out(commissions.at(account_id, clock()) or c)

    def _write(p, account_id: str, action: str, payload: dict, fn) -> RiskOverview:
        try:
            fn()
        except LedgerConflict as e:
            guard.audit(p, action, "REJECTED", payload, "đã làm rồi", account_id)
            raise HTTPException(409, "Đã thực hiện trước đó") from e
        except ValueError as e:
            guard.audit(p, action, "REJECTED", payload, str(e), account_id)
            raise HTTPException(409, str(e)) from e
        guard.audit(p, action, "ACCEPTED", payload, None, account_id)
        return overview(account_id, p)

    @r.post("/paper/start", response_model=RiskOverview)
    def paper_start(account_id: str, body: PaperStartIn, p: CurrentUser) -> RiskOverview:
        guard.check(account_id, p, "risk.paper.start")
        now = clock()
        b = gates.broker(account_id, now)
        if not (b.connected and b.heartbeat_age_s is not None
                and 0 <= b.heartbeat_age_s <= EQUITY_MAX_AGE_S and b.equity):
            guard.audit(p, "risk.paper.start", "REJECTED", {}, "không có equity MT5 mới",
                        account_id)
            raise HTTPException(409, "Chưa có equity MT5 mới (Gateway chưa kết nối)")
        capital = Decimal(str(b.equity))
        return _write(p, account_id, "risk.paper.start",
                      {"capital": str(capital), "reason": body.reason},
                      lambda: ledger.start(account_id, capital, actor=p.username,
                                           reason=body.reason, at=now))

    def _need_unrealized(account_id: str, now: datetime) -> Decimal:
        un = unrealized_now(account_id, now)
        if un is None:
            raise HTTPException(409, "Có lệnh paper đang mở nhưng không có giá mới — thử lại sau")
        return un

    @r.post("/paper/cash", response_model=RiskOverview)
    def paper_cash(account_id: str, body: CashIn, p: CurrentUser) -> RiskOverview:
        guard.check(account_id, p, "risk.paper.cash")
        now = clock()
        un = _need_unrealized(account_id, now)
        return _write(p, account_id, "risk.paper.cash", body.model_dump(mode="json"),
                      lambda: ledger.cash_flow(account_id, EventType(body.kind), body.amount,
                                               unrealized=un, actor=p.username,
                                               reason=body.reason, at=now))

    @r.post("/paper/drawdown-reset", response_model=RiskOverview)
    def drawdown_reset(account_id: str, body: DrawdownResetIn, p: CurrentUser) -> RiskOverview:
        guard.check(account_id, p, "risk.paper.drawdown_reset")
        now = clock()
        st = ledger.equity_state(account_id, now)
        if st is None:
            raise HTTPException(409, "Sổ paper chưa bắt đầu")
        eq = st.realized + _need_unrealized(account_id, now)
        return _write(p, account_id, "risk.paper.drawdown_reset",
                      body.model_dump(mode="json") | {"equity": str(eq)},
                      lambda: ledger.drawdown_reset(account_id, eq.quantize(
                          Decimal("1e-8")), actor=p.username, reason=body.reason, at=now))

    return r
