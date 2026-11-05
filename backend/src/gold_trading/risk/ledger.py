"""Risk Ledger append-only (docs/07). Bản trong bộ nhớ; bản thật dùng DB có transaction."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from gold_trading.common.ids import new_id
from gold_trading.common.time import utcnow


class LedgerEventType(StrEnum):
    RESERVE = "RESERVE"
    RELEASE = "RELEASE"


@dataclass(frozen=True)
class LedgerEvent:
    event_id: str
    type: LedgerEventType
    reservation_id: str
    symbol: str
    amount: float
    at: datetime
    reason: str


class RiskLedger:
    def __init__(self) -> None:
        self._events: list[LedgerEvent] = []
        self._open: dict[str, LedgerEvent] = {}
        self.lock = threading.RLock()

    @property
    def events(self) -> tuple[LedgerEvent, ...]:
        return tuple(self._events)

    def reserved_total(self, symbol: str | None = None) -> float:
        with self.lock:
            return sum(
                e.amount for e in self._open.values() if symbol is None or e.symbol == symbol
            )

    def reserve(self, symbol: str, amount: float, reason: str) -> str:
        with self.lock:
            rid = new_id("res")
            ev = LedgerEvent(
                new_id("le"), LedgerEventType.RESERVE, rid, symbol, amount, utcnow(), reason
            )
            self._events.append(ev)
            self._open[rid] = ev
            return rid

    def release(self, reservation_id: str, reason: str) -> bool:
        """Nhả reservation bằng event bù trừ. Idempotent."""
        with self.lock:
            ev = self._open.pop(reservation_id, None)
            if ev is None:
                return False
            self._events.append(
                LedgerEvent(
                    new_id("le"),
                    LedgerEventType.RELEASE,
                    reservation_id,
                    ev.symbol,
                    -ev.amount,
                    utcnow(),
                    reason,
                )
            )
            return True
