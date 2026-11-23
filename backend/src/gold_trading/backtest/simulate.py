"""Tầng 2 của backtest: mô phỏng giao dịch theo nến M15 (GĐ6 bước 5 — BT-02, MOD-03).

Thiết kế ``docs/thiet-ke/39-backtest.md`` mục 2, 5, 6, 9. **Chạy đúng mã đang dùng**:
``StrategyRunner`` (chiến lược v1 ``decide`` + ``Manager``), ``RiskEngine`` thật, ``RiskLedger``
(sổ paper trong bộ nhớ), ``PaperBroker.fill`` / ``close`` / ``net_pnl``, ``PaperMonitor.tick``.
Chỉ thay:

- **cổng đọc** của Risk bằng cổng lịch sử (dữ liệu truyền vào, đồng hồ mô phỏng);
- **dò SL / TP** theo giây bằng dò theo nến (``BarBroker.check_exits``), luôn chọn phía bất lợi.

Mỗi lần ``simulate`` có sổ riêng, không ghi gì ra ngoài bộ nhớ, **không có đường tới Gateway /
MT5** (test khẳng định). Thiếu giá tại một thời điểm → không quyết, không khớp (an toàn).
"""

from __future__ import annotations

import bisect
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from gold_trading.analysts.framework import Scope
from gold_trading.backtest.fastledger import FastLedger
from gold_trading.common.enums import Side, TradingMode
from gold_trading.contracts.market_view import MarketView
from gold_trading.market.quotes import QuoteSecond
from gold_trading.risk.book import position_of, unrealized
from gold_trading.risk.engine import RISK_POLICY_VERSION, RiskEngine, RiskPolicy
from gold_trading.risk.gates import BrokerReading, RiskGates
from gold_trading.risk.ledger import EventType, LedgerEvent, RiskLedger
from gold_trading.risk.paper import PaperBroker, PaperMonitor
from gold_trading.risk.periods import Periods
from gold_trading.storage.broker_history import SpecKey, SpecRow, spec_hash
from gold_trading.storage.commissions import Commission
from gold_trading.storage.market_views import StoredView, usable
from gold_trading.storage.risk_profiles import InMemoryRiskProfileStore, RiskProfileValues
from gold_trading.strategy.runner import InMemoryEvaluationStore, StrategyRunner
from gold_trading.strategy.trend_m15 import V1, Manager, Params

ACCOUNT = "backtest"
ACTOR = "backtest"
BAR = timedelta(minutes=15)
MINUTES_PER_BAR = 15
LOGIN, SERVER = 0, "BACKTEST"


# ====================================================================== dữ liệu vào


@dataclass(frozen=True)
class SimBar:
    """Nến M15 **giá bid** (như MT5) + spread nến (point). ``open_time`` UTC."""

    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    spread_points: int

    @property
    def close_time(self) -> datetime:
        return self.open_time + BAR


@dataclass(frozen=True)
class HistoricalView:
    """Một MarketView của tầng 1 + đặc trưng Technical ``decide`` cần (``atr14``, ``ema20``).
    ``computed_at`` = lúc MarketView có (point-in-time)."""

    view: MarketView
    computed_at: datetime
    technical: Mapping[str, Any]
    invalidated_at: datetime | None = None


class Bars:
    """Chuỗi nến đã sắp xếp, tra theo thời điểm (bisect)."""

    def __init__(self, bars: Iterable[SimBar]) -> None:
        self.bars = sorted(bars, key=lambda b: b.open_time)
        self.opens = [b.open_time for b in self.bars]
        if len(set(self.opens)) != len(self.opens):
            raise ValueError("nến trùng thời điểm")
        self._spreads: _SpreadMinutes | None = None

    @property
    def spreads(self) -> _SpreadMinutes:
        """Bảng "phút" spread dựng một lần, dùng lại cho mọi lần chạy trên cùng chuỗi nến."""
        if self._spreads is None:
            self._spreads = _SpreadMinutes(self)
        return self._spreads

    def starting_at(self, t: datetime) -> SimBar | None:
        i = bisect.bisect_left(self.opens, t)
        return self.bars[i] if i < len(self.bars) and self.opens[i] == t else None

    def closed_between(self, lo: datetime, hi: datetime) -> list[SimBar]:
        """Nến bắt đầu từ ``lo`` (gồm) và đã đóng tới ``hi`` (gồm)."""
        i = bisect.bisect_left(self.opens, lo)
        j = bisect.bisect_right(self.opens, hi - BAR)
        return self.bars[i:j]

    def before(self, t: datetime, lo: datetime) -> list[SimBar]:
        """Nến đã **đóng** trong [lo, t]."""
        i = bisect.bisect_left(self.opens, lo)
        j = bisect.bisect_right(self.opens, t - BAR)
        return self.bars[i:j]


class HistoricalViews:
    """``MarketViewGate`` từ chuỗi tầng 1: bản mới nhất đã biết tại ``at`` (cùng quy tắc
    ``storage.market_views``: hết hạn / bị vô hiệu → không có)."""

    def __init__(self, views: Iterable[HistoricalView], scope: Scope) -> None:
        self.rows = sorted(views, key=lambda v: (v.computed_at, v.view.as_of))
        self.times = [r.computed_at for r in self.rows]
        for a, b in zip(self.rows, self.rows[1:], strict=False):
            if b.view.as_of < a.view.as_of:
                raise ValueError("as_of của chuỗi MarketView phải không giảm theo computed_at")
        self.scope = scope
        self._tech = {r.view.market_view_id: r.technical for r in self.rows}

    def current(self, scope: Scope, at: datetime) -> MarketView | None:
        if scope != self.scope:
            return None
        i = bisect.bisect_right(self.times, at) - 1
        if i < 0:
            return None
        r = self.rows[i]
        inv = r.invalidated_at if r.invalidated_at is not None and r.invalidated_at <= at \
            else None
        return usable(StoredView(r.view, "backtest", r.computed_at, inv,
                                 "BACKTEST" if inv else None), at)

    def technical(self, view: MarketView) -> Mapping[str, Any] | None:
        return self._tech.get(view.market_view_id)


# ====================================================================== cấu hình một lần chạy


@dataclass(frozen=True)
class SimConfig:
    """Mọi số của một lần chạy — ghi nguyên vào báo cáo. ``spec`` = thông số broker (dạng
    ``spec_at`` của KN-05, mọi khóa ``REQUIRED_SPEC``)."""

    feed_id: str
    symbol: str
    spec: Mapping[str, Any]
    commission_per_lot: Decimal
    profile: RiskProfileValues
    capital: Decimal
    market_calendar: object
    params: Params = V1
    # thời điểm → mã "nguồn lịch không khỏe" (rỗng = khỏe) — lịch lịch sử (Q1)
    calendar_health: Callable[[datetime], list[str]] = field(default=lambda t: [])
    # thời điểm → lệnh cấm vào lệnh (``risk.blocks.Block``): tin HIGH dựng lại, spread giãn …
    entry_blocks: Callable[[datetime], list] = field(default=lambda t: [])


@dataclass
class PauseEvent:
    code: str
    at: datetime
    resumed_at: datetime | None = None


class BacktestAccounts:
    """``AccountGate`` của tài khoản mô phỏng. Chế độ = ``BACKTEST``. Risk đề nghị PAUSED (H4 / H6)
    → chặn vào lệnh; **người dùng mô phỏng mở lại ở mốc ngày giao dịch kế tiếp** (17:00 NY theo hồ
    sơ) — luật ghi trước (thiết kế 39 mục 5); H6 kèm đặt lại đỉnh equity. Mọi lần dừng được đếm."""

    def __init__(self, cfg: SimConfig, start: datetime, clock: Callable[[], datetime]) -> None:
        self.cfg = cfg
        self.clock = clock
        self.periods = Periods.of(cfg.profile.day_reset_tz, cfg.profile.day_reset_time)
        self.pauses: list[PauseEvent] = []
        self._active_since = start

    @property
    def paused(self) -> PauseEvent | None:
        return self.pauses[-1] if self.pauses and self.pauses[-1].resumed_at is None else None

    def entry_denials(self, account_id: str, now: datetime | None = None) -> list[str]:
        assert now is not None
        out = [f"SAFETY_PAUSED:{p.code}"] if (p := self.paused) else []
        out += [f"ENTRY_BLOCK:{b.reason_code}" for b in self.cfg.entry_blocks(now)]
        return out

    def mode(self, account_id: str) -> TradingMode:
        return TradingMode.BACKTEST

    def active_since(self, account_id: str) -> datetime:
        return self._active_since

    def request_pause(self, account_id: str, reason_code: str) -> bool:
        if self.paused is not None:
            return False
        self.pauses.append(PauseEvent(reason_code, self.clock()))
        return True

    def maybe_resume(self, now: datetime, ledger: RiskLedger, equity_now: Decimal | None) -> None:
        p = self.paused
        if p is None or now < self.periods.next_day_start(p.at):
            return
        if p.code == "DRAWDOWN_HALT" and equity_now is not None:
            ledger.drawdown_reset(ACCOUNT, equity_now, actor=ACTOR,
                                  reason="BACKTEST_RESUME_NEXT_DAY", at=now)
        p.resumed_at = now
        self._active_since = now


# ====================================================================== khớp / đóng theo nến


class BarBroker(PaperBroker):
    """``PaperBroker`` chỉ thay cách dò SL / TP: theo nến M15 đã đóng (thiết kế 39 mục 6).

    BUY (đóng ở bid): SL chạm khi ``low ≤ SL`` → giá = ``min(SL, open) − đệm``; TP chạm khi
    ``high ≥ TP`` → giá = TP. SELL (đóng ở ask = bid + spread nến): SL chạm khi
    ``high + spread ≥ SL`` → ``max(SL, open + spread) + đệm``; TP chạm khi ``low + spread ≤ TP``
    → TP. **Cùng một nến chạm cả hai → SL.** Đệm = đệm trượt giá đã ghi lúc khớp."""

    def __init__(self, ledger: RiskLedger, bars: Bars, point: Decimal, *,
                 latest_quote: Callable[[str, datetime], QuoteSecond | None],
                 clock: Callable[[], datetime]) -> None:
        super().__init__(ledger, latest_quote=latest_quote,
                         quote_window=lambda feed, lo, hi: [], clock=clock)
        self.bars = bars
        self.point = point
        self._checked: dict[str, datetime] = {}      # vị thế → nến đã xét tới (giờ đóng nến)

    @staticmethod
    def bar_hit(side: str, sl: Decimal, tp: Decimal | None, b: SimBar, point: Decimal,
                slip: Decimal) -> tuple[str, Decimal] | None:
        spread = b.spread_points * point
        if side == Side.BUY.value:
            if b.low <= sl:
                return "STOP_LOSS", min(sl, b.open) - slip
            if tp is not None and b.high >= tp:
                return "TAKE_PROFIT", tp
        else:
            if b.high + spread >= sl:
                return "STOP_LOSS", max(sl, b.open + spread) + slip
            if tp is not None and b.low + spread <= tp:
                return "TAKE_PROFIT", tp
        return None

    def check_exits(self, account_id: str) -> list[LedgerEvent]:
        now = self.clock()
        out: list[LedgerEvent] = []
        for opened in self.ledger.open_position_events(account_id):
            d = opened.data
            sl = self.ledger.current_stop(account_id, opened)
            tp = Decimal(d["take_profit"]) if d.get("take_profit") else None
            lo = self._checked.get(opened.ref_id, opened.at)
            for b in self.bars.closed_between(lo, now):
                if (h := self.bar_hit(d["side"], sl, tp, b, self.point,
                                      Decimal(d["slippage"]))) is not None:
                    why, price = h
                    ev = self.close(account_id, opened, price, why, trigger_t=b.open_time)
                    if ev is not None:
                        out.append(ev)
                    break
            else:
                self._checked[opened.ref_id] = now
        return out


# ====================================================================== cổng lịch sử


class _SpreadRow:
    """Dòng "phút" giả cho ``spread_baseline`` (chỉ đọc ``t``, ``spread_p95``,
    ``seconds_closed``). Mỗi nến M15 = 15 phút cùng spread nến (proxy — bias 1–2, thiết kế 39)."""

    __slots__ = ("bar_close", "seconds_closed", "spread_p95", "t")

    def __init__(self, t: datetime, spread: int, bar_close: datetime) -> None:
        self.t, self.spread_p95, self.seconds_closed = t, spread, 0
        self.bar_close = bar_close


class _SpreadMinutes:
    def __init__(self, bars: Bars) -> None:
        self.rows: list[_SpreadRow] = []
        for b in bars.bars:
            self.rows += [_SpreadRow(b.open_time + timedelta(minutes=k), b.spread_points,
                                     b.close_time) for k in range(MINUTES_PER_BAR)]
        self.times = [r.t for r in self.rows]

    def query(self, lo: datetime, hi: datetime, as_of: datetime) -> list[_SpreadRow]:
        """Phút trong [lo, hi) của các nến **đã đóng** tại ``as_of`` (point-in-time)."""
        i = bisect.bisect_left(self.times, lo)
        j = bisect.bisect_left(self.times, hi)
        return [r for r in self.rows[i:j] if r.bar_close <= as_of]


def _quote_from_bar(feed: str, b: SimBar, point: Decimal) -> QuoteSecond:
    """"Giây giá" tại giờ mở nến: bid = giá mở, ask = bid + spread nến (thiết kế 39 mục 6)."""
    ask = b.open + b.spread_points * point
    return QuoteSecond(feed, b.open_time, float(b.open), float(ask), float(b.open), float(ask),
                       b.spread_points, b.spread_points, 1, (), b.open_time, b.open_time)


class _IndexedEvaluations(InMemoryEvaluationStore):
    """Kho "lần xét" trong bộ nhớ có chỉ mục (lớp gốc quét toàn bộ mỗi lần — chậm theo bình
    phương khi mô phỏng nhiều năm). Cùng ngữ nghĩa: một dòng / (tài khoản, chiến lược,
    MarketView)."""

    def __init__(self) -> None:
        super().__init__()
        self._keys: set[tuple[str, str, str]] = set()

    def exists(self, account_id, strategy_ref, market_view_id):
        return (account_id, strategy_ref, market_view_id) in self._keys

    def record(self, e):
        k = (e.account_id, e.strategy_ref, e.market_view_id)
        if k in self._keys:
            return False
        self._keys.add(k)
        self.rows.append(e)
        return True


# ====================================================================== chạy


@dataclass
class SimResult:
    trades: list[LedgerEvent]                 # sự kiện CLOSE theo thời gian
    opens: list[LedgerEvent]                  # sự kiện OPEN (rủi ro lúc khớp, intent)
    evaluations: list                         # mọi lần xét của chiến lược (cả bỏ qua)
    decisions: list                           # mọi quyết định Risk
    pauses: list[PauseEvent]
    equity_by_day: list[tuple[datetime, Decimal]]   # equity đã chốt tại mỗi mốc ngày
    capital: Decimal
    ticks: int
    no_quote_ticks: int


def simulate(bars: Sequence[SimBar] | Bars, views: HistoricalViews, cfg: SimConfig,
             start: datetime, end: datetime) -> SimResult:
    """Đi từng mốc đóng nến ``t`` trong ``(start, end]``: quản lý lệnh → xét chiến lược → Risk →
    khớp ở giá mở nến bắt đầu lúc ``t``. Sổ mới với vốn ``cfg.capital`` lúc ``start``."""
    bs = bars if isinstance(bars, Bars) else Bars(bars)
    point = Decimal(str(cfg.spec["point"]))
    clock_now = [start]

    def clock() -> datetime:
        return clock_now[0]

    def latest_quote(feed: str, at: datetime) -> QuoteSecond | None:
        if feed != cfg.feed_id:
            return None
        b = bs.starting_at(at)
        return _quote_from_bar(feed, b, point) if b is not None else None

    ledger = FastLedger(clock=clock)
    ledger.start(ACCOUNT, cfg.capital, actor=ACTOR, reason="BACKTEST_START", at=start)
    accounts = BacktestAccounts(cfg, start, clock)
    profiles = InMemoryRiskProfileStore()
    profiles.append(ACCOUNT, cfg.profile, created_by=ACTOR, reason="BACKTEST",
                    at=start - timedelta(days=1))
    commission = Commission(ACCOUNT, cfg.commission_per_lot, "USD", start - timedelta(days=1),
                            ACTOR, "BACKTEST")
    spec_row = SpecRow(SpecKey(ACCOUNT, LOGIN, SERVER, cfg.symbol), start - timedelta(days=1),
                       dict(cfg.spec), spec_hash(dict(cfg.spec)), "backtest")
    spreads = bs.spreads
    broker = BarBroker(ledger, bs, point, latest_quote=latest_quote, clock=clock)
    cs = Decimal(str(cfg.spec["contract_size"]))
    lev = Decimal(str(cfg.spec["leverage"]))

    def equity_margin(at: datetime) -> tuple[Decimal | None, Decimal | None]:
        st = ledger.equity_state(ACCOUNT, at)
        if st is None:
            return None, None
        q = latest_quote(cfg.feed_id, at)
        opened = ledger.open_position_events(ACCOUNT)
        if opened and q is None:
            return None, None
        unreal = used = Decimal(0)
        for e in opened:
            p = position_of(e, ledger.current_stop(ACCOUNT, e))
            assert q is not None
            unreal += unrealized(p, Decimal(str(q.bid)), Decimal(str(q.ask)), cs)
            used += p.volume * cs * p.entry_price / lev
        eq = st.realized + unreal
        return eq, eq - used

    def broker_reading(acc: str, at: datetime) -> BrokerReading:
        eq, free = equity_margin(at)
        return BrokerReading(
            connected=True, heartbeat_age_s=0.0, equity=float(eq) if eq is not None else None,
            margin_free=float(free) if free is not None else None, account_currency="USD",
            identity=(LOGIN, SERVER), heartbeat_symbol=cfg.symbol,
            live_spec_hash=spec_row.spec_hash, locked_symbol=cfg.symbol, spec=spec_row)

    scope = views.scope
    gates = RiskGates(
        accounts=accounts, scope_for=lambda acc: scope, market_views=views,
        calendar_health=cfg.calendar_health, broker=broker_reading, latest_quote=latest_quote,
        spread_minutes=lambda feed, lo, hi, as_of: spreads.query(lo, hi, as_of),
        commission=lambda acc, at: commission, risk_profile=profiles.at,
        trade_book=ledger, market_calendar=cfg.market_calendar)
    engine = RiskEngine(RiskPolicy(version=RISK_POLICY_VERSION), ledger, gates, clock=clock)
    monitor = PaperMonitor(broker, feed_for=lambda acc: cfg.feed_id, risk_profile=profiles.at,
                           entry_blocks=lambda acc, at: cfg.entry_blocks(at),
                           market_calendar=cfg.market_calendar, managers=(Manager(cfg.params),))
    store = _IndexedEvaluations()
    runner = StrategyRunner(
        accounts=lambda: [ACCOUNT], mode=accounts.mode, feed_for=lambda acc: cfg.feed_id,
        view_for=lambda acc, at: views.current(scope, at), technical_for=views.technical,
        point_for=lambda acc, at: point, risk_profile=profiles.at, engine=engine, broker=broker,
        monitor=monitor, store=store, params=cfg.params, clock=clock)

    periods = accounts.periods
    equity_days: list[tuple[datetime, Decimal]] = []
    next_day = periods.next_day_start(start)
    ticks = no_quote = 0
    for b in bs.closed_between(start, end):
        t = b.close_time
        while next_day <= t:                         # chốt equity đã thực hiện ở mỗi mốc ngày
            st = ledger.equity_state(ACCOUNT, next_day)
            assert st is not None
            equity_days.append((next_day, st.realized))
            next_day = periods.next_day_start(next_day)
        clock_now[0] = t
        if accounts.paused is not None:              # equity chỉ cần khi mở lại sau H6
            accounts.maybe_resume(t, ledger, equity_margin(t)[0])
        if latest_quote(cfg.feed_id, t) is None:
            no_quote += 1
        runner.run_account(ACCOUNT)                 # monitor.tick + decide + Risk + fill
        ticks += 1
    clock_now[0] = end
    trades = sorted(ledger.events(ACCOUNT, (EventType.CLOSE,)), key=lambda e: e.at)
    opens = sorted(ledger.events(ACCOUNT, (EventType.OPEN,)), key=lambda e: e.at)
    return SimResult(trades, opens, list(reversed(store.recent(ACCOUNT, 10**9))),
                     list(reversed(ledger.recent_decisions(ACCOUNT, 10**9))),
                     accounts.pauses, equity_days, cfg.capital, ticks, no_quote)
