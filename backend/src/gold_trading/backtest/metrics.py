"""Chỉ số của một lần mô phỏng (GĐ6 bước 6 — protocol-1 mục 5; thiết kế 39 mục 11).

Mọi số **sau chi phí** (lãi / lỗ ròng từ sổ paper mô phỏng, ``Decimal``). R của một lệnh = lãi / lỗ
ròng ÷ rủi ro đã duyệt lúc khớp (``risk_at_fill``). Thống kê tổng hợp là ``float``.
Thiếu → ``None``.

Phiên (theo giờ New York lúc **mở** lệnh, ghi trước): Á 18:00–03:00, London 03:00–08:00,
Mỹ 08:00–17:00. Năm = năm (New York) lúc mở lệnh.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from gold_trading.backtest import stats as S
from gold_trading.backtest.simulate import SimResult
from gold_trading.risk.periods import Periods

NY = ZoneInfo("America/New_York")
DAY = Periods.of("America/New_York", "17:00")
H4_CODES = frozenset({"DAILY_LOSS_LIMIT", "WEEKLY_LOSS_LIMIT", "MONTHLY_LOSS_LIMIT",
                      "LOSS_STREAK_LIMIT"})
H6_CODE = "DRAWDOWN_HALT"


def session_of(t: datetime) -> str:
    x = t.astimezone(NY).time()
    if time(3, 0) <= x < time(8, 0):
        return "LONDON"
    if time(8, 0) <= x < time(17, 0):
        return "US"
    return "ASIA"


@dataclass(frozen=True)
class Trade:
    position_id: str
    side: str
    opened_at: datetime
    closed_at: datetime
    pnl: Decimal                       # ròng, tiền tài khoản
    risk: Decimal                      # rủi ro đã duyệt lúc khớp
    reason: str                        # STOP_LOSS / TAKE_PROFIT / TIME_STOP / …
    market_view_id: str | None
    regime: str | None

    @property
    def r(self) -> float:
        return float(self.pnl / self.risk) if self.risk > 0 else 0.0

    @property
    def session(self) -> str:
        return session_of(self.opened_at)

    @property
    def year(self) -> int:
        return self.opened_at.astimezone(NY).year

    @property
    def trade_day(self) -> date:
        """Ngày giao dịch (kết thúc ở mốc 17:00 NY) chứa lúc đóng — khối của bootstrap."""
        return DAY.trade_date(self.closed_at)


def trades_of(res: SimResult, regimes: Mapping[str, str] | None = None) -> list[Trade]:
    """Ghép CLOSE với OPEN (rủi ro lúc khớp, intent) và lần xét của chiến lược (MarketView)."""
    opens = {e.ref_id: e for e in res.opens}
    view_of_intent = {e.intent_id: e.market_view_id for e in res.evaluations if e.intent_id}
    out = []
    for c in res.trades:
        o = opens[c.ref_id]
        mv = view_of_intent.get(o.data.get("intent_id"))
        out.append(Trade(c.ref_id, c.data["side"], o.at, c.at, c.amount,
                         Decimal(o.data["risk_at_fill"]), c.reason, mv,
                         (regimes or {}).get(mv) if mv else None))
    return sorted(out, key=lambda t: t.closed_at)


@dataclass(frozen=True)
class Group:
    n: int
    expectancy_r: float | None
    pnl: Decimal


@dataclass(frozen=True)
class Summary:
    n: int
    win_rate: float | None
    expectancy_r: float | None
    expectancy_usd: float | None
    profit_factor: float | None
    max_drawdown: float | None                 # theo equity đã chốt mỗi ngày (17:00 NY)
    longest_losing_streak: int
    h6_count: int
    h4_count: int
    sharpe_daily: float | None
    avg_hold_minutes: float | None
    total_pnl: Decimal
    by_regime: Mapping[str, Group]
    by_session: Mapping[str, Group]
    by_year: Mapping[int, Group]
    by_side: Mapping[str, Group]


def _groups(trades: Iterable[Trade], key) -> dict:
    g: dict = defaultdict(list)
    for t in trades:
        g[key(t)].append(t)
    return {k: Group(len(v), S.mean([t.r for t in v]), sum((t.pnl for t in v), Decimal(0)))
            for k, v in sorted(g.items(), key=lambda kv: str(kv[0]))}


def daily_returns(equity_by_day: Sequence[tuple[datetime, Decimal]],
                  capital: Decimal) -> list[float]:
    prev = capital
    out = []
    for _, e in equity_by_day:
        out.append(float((e - prev) / prev) if prev > 0 else 0.0)
        prev = e
    return out


def summarize(res: SimResult, regimes: Mapping[str, str] | None = None) -> Summary:
    tr = trades_of(res, regimes)
    pnls = [float(t.pnl) for t in tr]
    curve = [float(res.capital)] + [float(e) for _, e in res.equity_by_day]
    holds = [(t.closed_at - t.opened_at).total_seconds() / 60 for t in tr]
    return Summary(
        n=len(tr),
        win_rate=S.win_rate(pnls),
        expectancy_r=S.mean([t.r for t in tr]),
        expectancy_usd=S.mean(pnls),
        profit_factor=S.profit_factor(pnls),
        max_drawdown=S.max_drawdown(curve),
        longest_losing_streak=S.longest_losing_streak(pnls),
        h6_count=sum(1 for p in res.pauses if p.code == H6_CODE),
        h4_count=sum(1 for p in res.pauses if p.code in H4_CODES),
        sharpe_daily=S.sharpe(daily_returns(res.equity_by_day, res.capital)),
        avg_hold_minutes=S.mean(holds),
        total_pnl=sum((t.pnl for t in tr), Decimal(0)),
        by_regime=_groups(tr, lambda t: t.regime or "UNKNOWN"),
        by_session=_groups(tr, lambda t: t.session),
        by_year=_groups(tr, lambda t: t.year),
        by_side=_groups(tr, lambda t: t.side),
    )
