"""Nối chiến lược v1 vào luồng paper (GĐ5 bước 7 — STR-05). Thiết kế 36 mục 9.

Mỗi nhịp orchestrator (sau Fusion), với từng tài khoản:
1. ``PaperMonitor.tick`` — quản lý lệnh paper đang mở (SL / TP, hòa vốn, đóng 16:45 NY, cuối tuần,
   tin HIGH, nhả giữ chỗ hết hạn). Chạy ở mọi chế độ (lệnh paper đã mở vẫn phải được quản lý).
2. Chỉ ở chế độ **PAPER**: MarketView hiện hành mới (chưa xét) → ``decide`` → Risk (tự đọc cổng
   thật) → khớp paper. Ghi một dòng ``strategy_evaluations`` (cả khi bỏ qua, có lý do).

**Không có đường nào tới Gateway / MT5**: chỉ sổ cái paper (test khẳng định). Lỗi một tài khoản
không chặn tài khoản khác; lỗi bất kỳ → không vào lệnh (an toàn).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from gold_trading.common.enums import RiskOutcome, TradingMode
from gold_trading.common.time import utcnow
from gold_trading.risk.ledger import EventType
from gold_trading.risk.paper import fresh_quote
from gold_trading.storage.schema import strategy_evaluations as sev
from gold_trading.strategy.trend_m15 import STRATEGY_REF, V1, Inputs, Params, decide

log = logging.getLogger("gold_trading.strategy")


@dataclass(frozen=True)
class Evaluation:
    account_id: str
    strategy_ref: str
    market_view_id: str
    evaluated_at: datetime
    outcome: str                                  # SKIPPED / INTENT
    reasons: tuple[str, ...]
    details: Mapping[str, str] = field(default_factory=dict)
    intent_id: str | None = None
    risk_decision_id: str | None = None
    risk_outcome: str | None = None
    fill_code: str | None = None                  # FILLED / mã lỗi khớp
    position_id: str | None = None


class EvaluationStore(Protocol):
    def exists(self, account_id: str, strategy_ref: str, market_view_id: str) -> bool: ...
    def record(self, e: Evaluation) -> bool: ...
    def recent(self, account_id: str, limit: int = 50) -> list[Evaluation]: ...


class InMemoryEvaluationStore:
    def __init__(self) -> None:
        self.rows: list[Evaluation] = []
        self._lock = threading.Lock()

    def exists(self, account_id, strategy_ref, market_view_id):
        with self._lock:
            return any((r.account_id, r.strategy_ref, r.market_view_id)
                       == (account_id, strategy_ref, market_view_id) for r in self.rows)

    def record(self, e):
        with self._lock:
            if any((r.account_id, r.strategy_ref, r.market_view_id)
                   == (e.account_id, e.strategy_ref, e.market_view_id) for r in self.rows):
                return False
            self.rows.append(e)
            return True

    def recent(self, account_id, limit=50):
        with self._lock:
            rows = [r for r in self.rows if r.account_id == account_id]
        return rows[::-1][:limit]


class SqlEvaluationStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def exists(self, account_id, strategy_ref, market_view_id):
        c = sev.c
        with self.engine.connect() as conn:
            return conn.execute(select(c.seq).where(
                c.account_id == account_id, c.strategy_ref == strategy_ref,
                c.market_view_id == market_view_id)).first() is not None

    def record(self, e):
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(sev).values(
                    account_id=e.account_id, strategy_ref=e.strategy_ref,
                    market_view_id=e.market_view_id, evaluated_at=e.evaluated_at,
                    outcome=e.outcome, reasons=list(e.reasons), details=dict(e.details),
                    intent_id=e.intent_id, risk_decision_id=e.risk_decision_id,
                    risk_outcome=e.risk_outcome, fill_code=e.fill_code,
                    position_id=e.position_id))
            return True
        except IntegrityError:
            return False                          # đã có (chạy lại / hai tiến trình)

    def recent(self, account_id, limit=50):
        c = sev.c
        with self.engine.connect() as conn:
            rows = conn.execute(select(sev).where(c.account_id == account_id)
                                .order_by(c.seq.desc()).limit(limit)).all()
        return [Evaluation(m.account_id, m.strategy_ref, m.market_view_id,
                           m.evaluated_at.replace(tzinfo=UTC) if m.evaluated_at.tzinfo is None
                           else m.evaluated_at, m.outcome, tuple(m.reasons), dict(m.details),
                           m.intent_id, m.risk_decision_id, m.risk_outcome, m.fill_code,
                           m.position_id) for m in rows]


class StrategyRunner:
    def __init__(self, *, accounts: Callable[[], list[str]],
                 mode: Callable[[str], TradingMode | None],
                 feed_for: Callable[[str], str | None],
                 view_for: Callable[[str, datetime], object | None],
                 technical_for: Callable[[object], Mapping | None],
                 point_for: Callable[[str, datetime], Decimal | None],
                 risk_profile: Callable[[str, datetime], object | None],
                 engine, broker, monitor, store: EvaluationStore,
                 params: Params = V1, clock: Callable[[], datetime] = utcnow) -> None:
        self.accounts = accounts
        self.mode = mode
        self.feed_for = feed_for
        self.view_for = view_for
        self.technical_for = technical_for
        self.point_for = point_for
        self.risk_profile = risk_profile
        self.engine = engine
        self.broker = broker
        self.ledger = broker.ledger
        self.monitor = monitor
        self.store = store
        self.params = params
        self.clock = clock
        self._seen: dict[str, str] = {}           # tài khoản → MarketView đã xét (bộ nhớ đệm)

    def tick(self, now: datetime | None = None) -> dict[str, str]:
        out: dict[str, str] = {}
        for acc in self.accounts():
            try:
                out[acc] = self.run_account(acc)
            except Exception:
                log.exception("Chiến lược lỗi ở tài khoản %s — không vào lệnh, thử lại nhịp sau",
                              acc)
                out[acc] = "error"
        return out

    def _safe(self, name: str, fn, default=None):
        try:
            return fn()
        except Exception:
            log.exception("Chiến lược: đọc %s lỗi → coi như thiếu", name)
            return default

    def run_account(self, acc: str) -> str:
        self.monitor.tick(acc)                                    # 1. quản lý lệnh đang mở
        now = self.clock()
        if self.mode(acc) is not TradingMode.PAPER:               # v1 chưa kiểm chứng: chỉ PAPER
            return "skip:mode"
        feed = self.feed_for(acc)
        if feed is None:                       # chưa có nguồn giá ("" = nguồn mẫu / CSV: vẫn xét,
            return "skip:no_feed"              # Risk từ chối NO_PRICE_FEED)
        view = self.view_for(acc, now)
        if view is None:
            return "skip:no_view"
        mv = view.market_view_id                                  # type: ignore[attr-defined]
        if self._seen.get(acc) == mv or self.store.exists(acc, STRATEGY_REF, mv):
            self._seen[acc] = mv
            return "skip:seen"
        q = self._safe("quote", lambda: self.broker.latest_quote(feed, now))
        fresh = q is not None and fresh_quote(q, now) is None
        prof = self._safe("risk_profile", lambda: self.risk_profile(acc, now))
        closes = self.ledger.events(acc, (EventType.CLOSE,))
        inp = Inputs(
            now=now, feed_id=feed, view=view,                     # type: ignore[arg-type]
            technical=self._safe("technical", lambda: self.technical_for(view)),
            bid=Decimal(str(q.bid)) if fresh else None,           # type: ignore[union-attr]
            ask=Decimal(str(q.ask)) if fresh else None,           # type: ignore[union-attr]
            point=self._safe("point", lambda: self.point_for(acc, now)),
            open_count=(len(self.ledger.open_position_events(acc))
                        + len(self.ledger.open_reservations(acc))),
            last_closed_at=max((e.at for e in closes), default=None),
            risk_per_trade=getattr(getattr(prof, "values", None), "risk_per_trade", None))
        o = decide(inp, self.params)
        if o.intent is None:
            rec = Evaluation(acc, STRATEGY_REF, mv, now, "SKIPPED", o.reasons, o.details)
        else:
            d = self.engine.evaluate(o.intent, acc)               # Risk tự đọc cổng thật
            fill_code = position = None
            if d.outcome is not RiskOutcome.REJECTED:
                f = self.broker.fill(d, o.intent, feed)           # chỉ sổ cái paper
                fill_code = "FILLED" if f.ok else f.code
                position = f.position_id
            rec = Evaluation(acc, STRATEGY_REF, mv, now, "INTENT", d.reason_codes,
                             o.details | {"reason": o.intent.reason}, o.intent.intent_id,
                             d.risk_decision_id, d.outcome.value, fill_code, position)
        self.store.record(rec)
        self._seen[acc] = mv
        return f"{rec.outcome.lower()}:{rec.risk_outcome or ','.join(rec.reasons)}"
