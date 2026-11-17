"""Sổ cái paper chỉ-thêm (docs/07; GĐ5 bước 6 — DB-06, LED-02, LED-05, CORE-05).

Mọi thay đổi trạng thái paper của **một tài khoản** là một sự kiện (giữ chỗ, nhả, khớp, đóng, nạp,
rút…). Hai bản cùng giao diện và **cùng một logic** (lớp ``PaperLedger``): ``RiskLedger`` (bộ nhớ —
test / tham chiếu) và ``SqlLedger`` (bảng ``paper_ledger_events`` + ``risk_decisions``, migration
0026). Thiết kế: docs/thiet-ke/35-risk-engine.md mục 12.

- **Theo tài khoản:** giữ chỗ, heat, số lệnh ngày của tài khoản này không tính chung với tài khoản
  khác (lỗi cũ: sổ không có ``account_id`` → mọi người dùng tiêu chung một trần).
- **Khóa theo tài khoản** (``locked``): Postgres = giao dịch + ``pg_advisory_xact_lock``; SQLite =
  một khóa chung (SQLite chỉ một người ghi); bộ nhớ = khóa luồng. Trong khóa, mọi ghi nằm trong
  **một giao dịch** — lỗi giữa chừng → không ghi gì (crash trước commit = như chưa từng có).
- ``account_seq`` duy nhất trong tài khoản (lớp bảo vệ thứ hai), ``once_key`` duy nhất (giữ chỗ chỉ
  kết thúc một lần: nhả **hoặc** khớp; vị thế đóng một lần).
- Quyết định Risk lưu theo ``(tài khoản, idempotency_key)`` — gọi lại cùng khóa nhận lại đúng quyết
  định cũ (LED-05: khôi phục sau crash giữa giữ chỗ và khớp).
- Tiền ``Decimal`` (CORE-05); tối đa 8 chữ số thập phân (đúng ``NUMERIC(20,8)`` — không để DB làm
  tròn âm thầm).
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import StrEnum

from sqlalchemy import and_, exists, func, insert, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from gold_trading.common.ids import new_id
from gold_trading.common.time import utcnow
from gold_trading.contracts.risk import RiskDecision
from gold_trading.contracts.trade_intent import TradeIntent
from gold_trading.storage.schema import paper_ledger_events as ple
from gold_trading.storage.schema import risk_decisions as rdt

AMOUNT_MAX_EXP = -8                 # NUMERIC(20, 8)


class EventType(StrEnum):
    START = "START"
    RESERVE = "RESERVE"
    RELEASE = "RELEASE"
    OPEN = "OPEN"
    MODIFY_SL = "MODIFY_SL"
    CLOSE = "CLOSE"
    CASH_IN = "CASH_IN"
    CASH_OUT = "CASH_OUT"
    PEAK = "PEAK"
    DRAWDOWN_RESET = "DRAWDOWN_RESET"


# Tên cũ (LED-01) — giữ để mã / test cũ đọc được.
LedgerEventType = EventType


class LedgerConflict(Exception):
    """``once_key`` đã có (giữ chỗ đã kết thúc / vị thế đã đóng / đã bắt đầu)."""


@dataclass(frozen=True)
class LedgerEvent:
    event_id: str
    account_id: str
    account_seq: int
    type: EventType
    ref_id: str
    once_key: str | None
    amount: Decimal
    at: datetime
    actor: str
    reason: str
    links: str | None = None
    data: Mapping[str, str] = field(default_factory=dict)

    @property
    def reservation_id(self) -> str:          # tên cũ
        return self.ref_id

    @property
    def symbol(self) -> str:
        return self.data.get("symbol", "")


@dataclass(frozen=True)
class StoredDecision:
    decision: RiskDecision
    intent_hash: str


def intent_hash(intent: TradeIntent) -> str:
    """Băm **nội dung kinh tế** của intent (không gồm ``intent_id`` / ``created_at`` / ``expiry``):
    chiến lược gửi lại cùng yêu cầu sau crash với mã mới vẫn là cùng một yêu cầu."""
    body = {k: str(getattr(intent, k)) for k in (
        "strategy_id", "symbol", "side", "entry_type", "entry_reference", "stop_loss",
        "take_profit", "risk_budget_requested", "market_view_id", "time_in_force")}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def _utc(t: datetime) -> datetime:
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("thời điểm phải có múi giờ (UTC)")
    return t.astimezone(UTC)


def _db(t: datetime) -> datetime:
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


def check_amount(amount: Decimal) -> Decimal:
    if not isinstance(amount, Decimal) or not amount.is_finite():
        raise ValueError("số tiền phải là Decimal hữu hạn (CORE-05)")
    if amount.as_tuple().exponent < AMOUNT_MAX_EXP:  # type: ignore[operator]
        raise ValueError(f"số tiền tối đa 8 chữ số thập phân: {amount}")
    return amount


def end_key(reservation_id: str) -> str:
    return f"END:{reservation_id}"


def close_key(position_id: str) -> str:
    return f"CLOSE:{position_id}"


@dataclass(frozen=True)
class EquityState:
    realized: Decimal          # vốn + nạp − rút + PnL ròng đã đóng
    peak: Decimal              # đỉnh equity (H6), đã điều chỉnh theo nạp / rút (H10)


EQUITY_TYPES = (EventType.START, EventType.CASH_IN, EventType.CASH_OUT, EventType.CLOSE,
                EventType.PEAK, EventType.DRAWDOWN_RESET)


def money_floor(x: Decimal) -> Decimal:
    return x.quantize(Decimal("1e-8"), rounding=ROUND_FLOOR)


def replay_equity(events) -> EquityState | None:
    """Phát lại sự kiện theo thứ tự (thiết kế 35 mục 12.5). Không có ``START`` → None."""
    realized: Decimal | None = None
    peak = Decimal(0)
    for e in events:
        if e.type is EventType.START:
            realized = peak = e.amount
            continue
        if realized is None:
            continue
        if e.type is EventType.CASH_IN:
            realized += e.amount
            peak += e.amount
        elif e.type is EventType.CASH_OUT:
            before = Decimal(e.data["equity_before"])
            realized -= e.amount
            # đỉnh giảm theo tỷ lệ rút; làm tròn LÊN (đỉnh không nhỏ hơn thật → không lờ sụt)
            peak = (peak * (1 - e.amount / before)).quantize(Decimal("1e-8"),
                                                              rounding=ROUND_CEILING)
        elif e.type is EventType.CLOSE:
            realized += e.amount
            peak = max(peak, realized)
        elif e.type is EventType.PEAK:
            peak = max(peak, e.amount)
        elif e.type is EventType.DRAWDOWN_RESET:
            peak = e.amount
    return None if realized is None else EquityState(realized, peak)


class PaperLedger:
    """Logic chung; lớp con cài đặt phần lưu trữ (các hàm ``_x``)."""

    def __init__(self, *, clock: Callable[[], datetime] = utcnow) -> None:
        self.clock = clock
        self._guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}
        self._tl = threading.local()
        # Điểm "crash" giả lập cho test (LED-05): hàm được gọi ở các mốc trong giao dịch.
        self.fault: Callable[[str], None] | None = None

    # ------------------------------------------------------------------ khóa + giao dịch

    def _lock_name(self, account_id: str) -> str:
        return account_id

    def _thread_lock(self, account_id: str) -> threading.RLock:
        name = self._lock_name(account_id)
        with self._guard:
            return self._locks.setdefault(name, threading.RLock())

    def _handles(self) -> dict[str, object]:
        h = getattr(self._tl, "h", None)
        if h is None:
            h = self._tl.h = {}
        return h

    def _handle(self, account_id: str) -> object | None:
        return self._handles().get(account_id)

    @contextmanager
    def locked(self, account_id: str) -> Iterator[None]:
        """Khóa tài khoản + một giao dịch. Lồng nhau cùng luồng → dùng lại giao dịch ngoài."""
        if self._handle(account_id) is not None:
            yield
            return
        with self._thread_lock(account_id), self._begin(account_id) as h:
            self._handles()[account_id] = h
            try:
                yield
                self._hit("before_commit")
            finally:
                self._handles().pop(account_id, None)

    def _hit(self, point: str) -> None:
        if self.fault is not None:
            self.fault(point)

    # ------------------------------------------------------------------ ghi

    def append(self, account_id: str, type: EventType, ref_id: str, amount: Decimal, *,
               at: datetime | None = None, actor: str, reason: str,
               once_key: str | None = None, links: str | None = None,
               data: Mapping[str, str] | None = None) -> LedgerEvent:
        """Ghi một sự kiện (trong khóa của tài khoản; chưa có khóa → tự mở giao dịch riêng)."""
        check_amount(amount)
        if not actor or not reason or len(reason) > 256:
            raise ValueError("sự kiện cần người làm và lý do (≤ 256 ký tự)")
        d = dict(data or {})
        if any(not isinstance(v, str) for v in d.values()):
            raise ValueError("data chỉ chứa chuỗi (giữ đúng Decimal)")
        with self.locked(account_id):
            ev = LedgerEvent(new_id("le"), account_id, 0, EventType(type), ref_id, once_key,
                             amount, _utc(at or self.clock()), actor, reason, links, d)
            return self._append(self._handle(account_id), ev)

    def reserve(self, account_id: str, symbol: str, amount: Decimal, reason: str,
                at: datetime | None = None, *, data: Mapping[str, str] | None = None) -> str:
        if not isinstance(amount, Decimal) or not amount.is_finite() or amount <= 0:
            raise ValueError("số tiền giữ chỗ phải là Decimal > 0 (CORE-05)")
        rid = new_id("res")
        self.append(account_id, EventType.RESERVE, rid, amount, at=at, actor="risk",
                    reason=reason, data={"symbol": symbol, **(data or {})})
        self._hit("after_reserve")
        return rid

    def release(self, account_id: str, reservation_id: str, reason: str, *,
                actor: str = "risk", at: datetime | None = None) -> bool:
        """Nhả giữ chỗ bằng sự kiện bù trừ (trỏ về ``RESERVE``). Đã kết thúc → False."""
        with self.locked(account_id):
            res = self._find(account_id, EventType.RESERVE, reservation_id)
            if res is None or self._once_exists(account_id, end_key(reservation_id)):
                return False
            self.append(account_id, EventType.RELEASE, reservation_id, -res.amount, at=at,
                        actor=actor, reason=reason, once_key=end_key(reservation_id),
                        links=res.event_id, data={"symbol": res.symbol})
            return True

    # ------------------------------------------------------------------ đọc giữ chỗ

    def open_reservations(self, account_id: str | None) -> list[LedgerEvent]:
        """Giữ chỗ chưa kết thúc (chưa nhả, chưa khớp). Hết hạn mà chưa nhả vẫn tính (an toàn)."""
        return self._open_starts(account_id, EventType.RESERVE, "END:")

    def reserved_total(self, account_id: str | None = None, symbol: str | None = None
                       ) -> Decimal:
        return sum((e.amount for e in self.open_reservations(account_id)
                    if symbol is None or e.symbol == symbol), Decimal(0))

    def open_since(self, account_id: str, since: datetime) -> int:
        """Số giữ chỗ còn mở tạo từ ``since`` (đếm lệnh / ngày, bước 4c)."""
        return sum(e.at >= since for e in self.open_reservations(account_id))

    def events(self, account_id: str, types: tuple[EventType, ...] | None = None
               ) -> list[LedgerEvent]:
        return self._events(account_id, types)

    # ------------------------------------------------------------------ sổ lệnh (TradeBook, 6b)
    # Sổ cái hiện thực giao diện ``TradeBook`` (risk/book.py) cho Risk bước 4c. ``at`` = lúc quyết
    # (hiện tại): vị thế mở = có ``OPEN`` (at ≤ lúc đó), chưa có ``CLOSE``.

    def open_position_events(self, account_id: str) -> list[LedgerEvent]:
        return self._open_starts(account_id, EventType.OPEN, "CLOSE:")

    def current_stop(self, account_id: str, opened: LedgerEvent) -> Decimal:
        mods = [e for e in self._events(account_id, (EventType.MODIFY_SL,))
                if e.ref_id == opened.ref_id]
        return Decimal(mods[-1].data["stop_loss"] if mods else opened.data["stop_loss"])

    def open_positions(self, account_id: str, at: datetime):
        from gold_trading.risk.book import position_of
        return [position_of(e, self.current_stop(account_id, e))
                for e in self.open_position_events(account_id) if e.at <= at]

    def closed_trades(self, account_id: str, since: datetime, until: datetime):
        from gold_trading.risk.book import closed_of
        return [closed_of(e) for e in self._events(account_id, (EventType.CLOSE,), since)
                if e.at <= until]

    def last_closed(self, account_id: str, until: datetime, limit: int):
        from gold_trading.risk.book import closed_of
        rows = [closed_of(e) for e in self._events(account_id, (EventType.CLOSE,))
                if e.at <= until]
        return sorted(rows, key=lambda t: (t.closed_at, t.trade_id), reverse=True)[:limit]

    def opened_count(self, account_id: str, since: datetime, until: datetime) -> int:
        return sum(e.at <= until for e in self._events(account_id, (EventType.OPEN,), since))

    def position_closed(self, account_id: str, position_id: str) -> bool:
        return self._once_exists(account_id, close_key(position_id))

    def reservation_ended(self, account_id: str, reservation_id: str) -> LedgerEvent | None:
        """Sự kiện kết thúc giữ chỗ (``RELEASE`` hoặc ``OPEN``) nếu có."""
        return next((e for e in self._events(account_id, (EventType.RELEASE, EventType.OPEN))
                     if e.once_key == end_key(reservation_id)), None)

    # ------------------------------------------------------------------ equity paper (6c: H6, H10)

    def start(self, account_id: str, capital: Decimal, *, actor: str, reason: str,
              at: datetime | None = None) -> LedgerEvent:
        """Bắt đầu sổ cái paper với vốn đầu (= equity MT5 lúc bắt đầu). Một lần / tài khoản."""
        if not isinstance(capital, Decimal) or not capital.is_finite() or capital <= 0:
            raise ValueError("vốn đầu phải là Decimal > 0")
        return self.append(account_id, EventType.START, account_id, capital, at=at, actor=actor,
                           reason=reason, once_key=f"START:{account_id}")

    def equity_state(self, account_id: str, at: datetime) -> EquityState | None:
        """Equity đã chốt (vốn + nạp − rút + PnL đã đóng) và đỉnh. Chưa ``START`` → None."""
        evs = [e for e in self._events(account_id, EQUITY_TYPES) if e.at <= at]
        return replay_equity(evs)

    def cash_flow(self, account_id: str, kind: EventType, amount: Decimal, *,
                  unrealized: Decimal, actor: str, reason: str,
                  at: datetime | None = None) -> LedgerEvent:
        """H10: nạp / rút tách khỏi lãi lỗ. Nạp → đỉnh + số nạp; rút → đỉnh × (1 − rút / equity
        trước rút). ``unrealized`` = PnL đang chạy lúc đó (người gọi tính theo giá hiện tại)."""
        if kind not in (EventType.CASH_IN, EventType.CASH_OUT):
            raise ValueError("chỉ CASH_IN / CASH_OUT")
        if not isinstance(amount, Decimal) or not amount.is_finite() or amount <= 0:
            raise ValueError("số nạp / rút phải là Decimal > 0")
        with self.locked(account_id):
            st = self.equity_state(account_id, at or self.clock())
            if st is None:
                raise ValueError("sổ cái paper chưa bắt đầu")
            before = st.realized + unrealized
            if kind is EventType.CASH_OUT and amount >= before:
                raise ValueError("số rút phải nhỏ hơn equity paper")
            return self.append(account_id, kind, new_id("cash"), amount, at=at, actor=actor,
                               reason=reason, data={"equity_before": str(before)})

    def drawdown_reset(self, account_id: str, equity_now: Decimal, *, actor: str, reason: str,
                       at: datetime | None = None) -> LedgerEvent:
        """H6: người xác nhận rõ (có lý do) sau khi dừng vì sụt → đỉnh = equity lúc đó."""
        if not reason or not actor:
            raise ValueError("cần người xác nhận và lý do")
        return self.append(account_id, EventType.DRAWDOWN_RESET, new_id("ddr"), equity_now,
                           at=at, actor=actor, reason=reason)

    def mark_peak(self, account_id: str, equity_now: Decimal, *,
                  at: datetime | None = None) -> LedgerEvent | None:
        """Ghi đỉnh mới (gồm lãi đang chạy) nếu vượt đỉnh đã lưu."""
        with self.locked(account_id):
            st = self.equity_state(account_id, at or self.clock())
            if st is None or equity_now <= st.peak:
                return None
            return self.append(account_id, EventType.PEAK, new_id("peak"), money_floor(equity_now),
                               at=at, actor="paper", reason="NEW_PEAK")

    # ------------------------------------------------------------------ quyết định (idempotency)

    def decision_for(self, account_id: str, idempotency_key: str) -> StoredDecision | None:
        return self._decision_get(account_id, idempotency_key)

    def recent_decisions(self, account_id: str, limit: int = 20) -> list[RiskDecision]:
        """Quyết định Risk gần nhất (mới trước) — trang Rủi ro (bước 8)."""
        return self._decisions_recent(account_id, limit)

    def record_decision(self, decision: RiskDecision, intent: TradeIntent) -> StoredDecision:
        """Lưu quyết định (trong khóa tài khoản). Cùng (tài khoản, khóa) đã có → trả bản đã lưu,
        không ghi bản mới (người gọi so ``intent_hash`` để biết có phải cùng yêu cầu)."""
        with self.locked(decision.account_id):
            prior = self._decision_get(decision.account_id, intent.idempotency_key)
            if prior is not None:
                return prior
            ih = intent_hash(intent)
            self._decision_put(self._handle(decision.account_id), decision, intent, ih)
            self._hit("after_decision")
            return StoredDecision(decision, ih)

    # ------------------------------------------------------------------ phần lưu trữ (lớp con)

    def _begin(self, account_id: str):  # pragma: no cover - lớp con
        raise NotImplementedError

    def _append(self, h, ev: LedgerEvent) -> LedgerEvent:  # pragma: no cover
        raise NotImplementedError

    def _events(self, account_id, types, since=None):  # pragma: no cover
        raise NotImplementedError

    def _find(self, account_id, type, ref_id) -> LedgerEvent | None:  # pragma: no cover
        raise NotImplementedError

    def _once_exists(self, account_id, key) -> bool:  # pragma: no cover
        raise NotImplementedError

    def _open_starts(self, account_id, type, end_prefix) -> list[LedgerEvent]:  # pragma: no cover
        raise NotImplementedError

    def _decision_get(self, account_id, key) -> StoredDecision | None:  # pragma: no cover
        raise NotImplementedError

    def _decision_put(self, h, decision, intent, ihash) -> None:  # pragma: no cover
        raise NotImplementedError

    def _decisions_recent(self, account_id, limit) -> list[RiskDecision]:  # pragma: no cover
        raise NotImplementedError


# ====================================================================== bộ nhớ

@dataclass
class _MemTxn:
    events: list[LedgerEvent] = field(default_factory=list)
    decisions: dict[tuple[str, str], StoredDecision] = field(default_factory=dict)


class RiskLedger(PaperLedger):
    """Bản trong bộ nhớ (test / tham chiếu). Ghi trong khóa vào bộ đệm giao dịch; commit khi ra
    khỏi khóa không lỗi, lỗi → bỏ bộ đệm (giống DB)."""

    def __init__(self, *, clock: Callable[[], datetime] = utcnow) -> None:
        super().__init__(clock=clock)
        self._ev: dict[str, list[LedgerEvent]] = {}
        self._once: set[str] = set()
        self._dec: dict[tuple[str, str], StoredDecision] = {}
        self._mem = threading.Lock()

    @contextmanager
    def _begin(self, account_id):
        tx = _MemTxn()
        yield tx
        with self._mem:                       # commit
            for e in tx.events:
                if e.once_key is not None:
                    self._once.add(e.once_key)
            self._ev.setdefault(account_id, []).extend(tx.events)
            self._dec.update(tx.decisions)

    def _visible(self, account_id: str) -> list[LedgerEvent]:
        with self._mem:
            rows = list(self._ev.get(account_id, []))
        h = self._handle(account_id)
        return rows + (list(h.events) if isinstance(h, _MemTxn) else [])

    def _append(self, h, ev):
        assert isinstance(h, _MemTxn)
        rows = self._visible(ev.account_id)
        with self._mem:
            if ev.once_key is not None and (ev.once_key in self._once
                                            or any(e.once_key == ev.once_key for e in h.events)):
                raise LedgerConflict(ev.once_key)
        seq = (rows[-1].account_seq if rows else 0) + 1
        ev = LedgerEvent(**{**ev.__dict__, "account_seq": seq})
        h.events.append(ev)
        return ev

    def _all_accounts(self) -> list[str]:
        with self._mem:
            return list(self._ev)

    def _events(self, account_id, types, since=None):
        return [e for e in self._visible(account_id)
                if (types is None or e.type in types) and (since is None or e.at >= since)]

    def _find(self, account_id, type, ref_id):
        return next((e for e in self._visible(account_id)
                     if e.type is type and e.ref_id == ref_id), None)

    def _once_exists(self, account_id, key):
        return any(e.once_key == key for e in self._visible(account_id))

    def _open_starts(self, account_id, type, end_prefix):
        accs = [account_id] if account_id is not None else self._all_accounts()
        out = []
        for a in accs:
            rows = self._visible(a)
            ended = {e.once_key for e in rows if e.once_key}
            out += [e for e in rows if e.type is type and f"{end_prefix}{e.ref_id}" not in ended]
        return out

    def _decision_get(self, account_id, key):
        h = self._handle(account_id)
        if isinstance(h, _MemTxn) and (account_id, key) in h.decisions:
            return h.decisions[(account_id, key)]
        with self._mem:
            return self._dec.get((account_id, key))

    def _decisions_recent(self, account_id, limit):
        with self._mem:
            rows = [d.decision for (a, _), d in self._dec.items() if a == account_id]
        return sorted(rows, key=lambda d: d.decided_at, reverse=True)[:limit]

    def _decision_put(self, h, decision, intent, ihash):
        assert isinstance(h, _MemTxn)
        h.decisions[(decision.account_id, intent.idempotency_key)] = StoredDecision(decision,
                                                                                    ihash)


# ====================================================================== SQL

def _advisory_key(account_id: str) -> int:
    return int.from_bytes(hashlib.sha256(b"ledger:" + account_id.encode()).digest()[:8],
                          "big", signed=True)


class SqlLedger(PaperLedger):
    """Bảng ``paper_ledger_events`` + ``risk_decisions`` (migration 0026)."""

    def __init__(self, engine: Engine, *, clock: Callable[[], datetime] = utcnow) -> None:
        super().__init__(clock=clock)
        self.engine = engine
        self._pg = engine.dialect.name == "postgresql"

    def _lock_name(self, account_id: str) -> str:
        # SQLite: một người ghi cho cả tệp → một khóa chung (tránh "database is locked").
        return account_id if self._pg else "*"

    @contextmanager
    def _begin(self, account_id):
        with self.engine.connect() as conn, conn.begin():
            if self._pg:
                conn.execute(select(func.pg_advisory_xact_lock(_advisory_key(account_id))))
            yield conn

    @contextmanager
    def _savepoint(self, conn: Connection) -> Iterator[None]:
        """Postgres: lỗi trùng khóa làm hỏng cả giao dịch → bọc lệnh ghi trong savepoint.
        SQLite (pysqlite): savepoint ngoài cùng tự COMMIT phần đã ghi (đã gặp ở test crash) →
        không dùng; lỗi trùng khóa trên SQLite không làm hỏng giao dịch."""
        if self._pg:
            with conn.begin_nested():
                yield
        else:
            yield

    @contextmanager
    def _conn(self, account_id: str | None) -> Iterator[Connection]:
        h = self._handle(account_id) if account_id is not None else None
        if isinstance(h, Connection):
            yield h
        else:
            with self.engine.connect() as conn:
                yield conn

    @staticmethod
    def _row(m) -> LedgerEvent:
        return LedgerEvent(m.event_id, m.account_id, m.account_seq, EventType(m.type), m.ref_id,
                           m.once_key, Decimal(str(m.amount)), _db(m.at), m.actor, m.reason,
                           m.links,
                           dict(m.data or {}))

    def _append(self, h, ev):
        assert isinstance(h, Connection)
        c = ple.c
        seq = h.execute(select(func.coalesce(func.max(c.account_seq), 0))
                        .where(c.account_id == ev.account_id)).scalar_one() + 1
        ev = LedgerEvent(**{**ev.__dict__, "account_seq": seq})
        try:
            with self._savepoint(h):
                h.execute(insert(ple).values(
                    event_id=ev.event_id, account_id=ev.account_id, account_seq=seq,
                    type=ev.type.value, ref_id=ev.ref_id, once_key=ev.once_key,
                    amount=ev.amount, at=ev.at, actor=ev.actor, reason=ev.reason,
                    links=ev.links, data=dict(ev.data), recorded_at=utcnow()))
        except IntegrityError as e:
            if ev.once_key is not None and self._once_exists_conn(h, ev.once_key):
                raise LedgerConflict(ev.once_key) from e
            raise
        return ev

    def _events(self, account_id, types, since=None):
        c = ple.c
        q = select(ple).where(c.account_id == account_id)
        if types is not None:
            q = q.where(c.type.in_([t.value for t in types]))
        if since is not None:
            q = q.where(c.at >= since)
        with self._conn(account_id) as conn:
            return [self._row(m) for m in conn.execute(q.order_by(c.account_seq)).all()]

    def _find(self, account_id, type, ref_id):
        c = ple.c
        with self._conn(account_id) as conn:
            m = conn.execute(select(ple).where(c.account_id == account_id,
                                               c.type == type.value, c.ref_id == ref_id)
                             .order_by(c.account_seq).limit(1)).first()
        return self._row(m) if m is not None else None

    @staticmethod
    def _once_exists_conn(conn: Connection, key: str) -> bool:
        return conn.execute(select(ple.c.seq).where(ple.c.once_key == key)).first() is not None

    def _once_exists(self, account_id, key):
        with self._conn(account_id) as conn:
            return self._once_exists_conn(conn, key)

    def _open_starts(self, account_id, type, end_prefix):
        s, e = ple.alias("s"), ple.alias("e")
        q = select(s).where(s.c.type == type.value, ~exists().where(
            and_(e.c.once_key == end_prefix + s.c.ref_id)))
        if account_id is not None:
            q = q.where(s.c.account_id == account_id)
        with self._conn(account_id) as conn:
            return [self._row(m) for m in conn.execute(q.order_by(s.c.seq)).all()]

    def _decision_get(self, account_id, key):
        c = rdt.c
        with self._conn(account_id) as conn:
            m = conn.execute(select(rdt.c.decision, rdt.c.intent_hash).where(
                c.account_id == account_id, c.idempotency_key == key)).first()
        if m is None:
            return None
        return StoredDecision(RiskDecision.model_validate(m.decision), m.intent_hash)

    def _decisions_recent(self, account_id, limit):
        c = rdt.c
        with self.engine.connect() as conn:
            rows = conn.execute(select(rdt.c.decision).where(c.account_id == account_id)
                                .order_by(c.decided_at.desc()).limit(limit)).all()
        return [RiskDecision.model_validate(m.decision) for m in rows]

    def _decision_put(self, h, decision, intent, ihash):
        assert isinstance(h, Connection)
        with self._savepoint(h):
            h.execute(insert(rdt).values(
                risk_decision_id=decision.risk_decision_id, account_id=decision.account_id,
                idempotency_key=intent.idempotency_key, intent_id=intent.intent_id,
                intent_hash=ihash, outcome=decision.outcome.value,
                decided_at=decision.decided_at, expires_at=decision.expires_at,
                decision=decision.model_dump(mode="json"),
                intent=intent.model_dump(mode="json")))
