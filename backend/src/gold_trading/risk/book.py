"""Cổng **sổ lệnh** cho hạn mức theo thời gian + danh mục (GĐ5 bước 4c — RSK-04, RSK-05).

Risk chỉ ĐỌC sổ lệnh: lệnh đã đóng (PnL ròng đã gồm phí) và lệnh đang mở (giá vào, SL, lot,
chiều). Sổ lệnh thật = sổ cái paper (bước 6, LED-02/04) — tới lúc đó Risk từ chối
``TRADE_BOOK_UNAVAILABLE``. ``InMemoryTradeBook`` dùng cho test / tham chiếu.
Thiết kế: docs/thiet-ke/35-risk-engine.md mục 10.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from gold_trading.common.enums import Side


@dataclass(frozen=True)
class ClosedTrade:
    trade_id: str
    side: Side
    opened_at: datetime
    closed_at: datetime
    net_pnl: Decimal                 # tiền tài khoản, đã trừ spread / phí / swap


@dataclass(frozen=True)
class OpenPosition:
    position_id: str
    side: Side
    volume: Decimal
    entry_price: Decimal
    stop_loss: Decimal
    opened_at: datetime
    commission_per_lot: Decimal      # phí khứ hồi / lot áp cho lệnh này


class TradeBook(Protocol):
    def closed_trades(self, account_id: str, since: datetime, until: datetime
                      ) -> list[ClosedTrade]: ...          # since ≤ closed_at ≤ until
    def last_closed(self, account_id: str, until: datetime, limit: int
                    ) -> list[ClosedTrade]: ...            # mới nhất trước
    def open_positions(self, account_id: str, at: datetime) -> list[OpenPosition]: ...
    def opened_count(self, account_id: str, since: datetime, until: datetime) -> int: ...


class InMemoryTradeBook:
    def __init__(self) -> None:
        self.closed: dict[str, list[ClosedTrade]] = {}
        self.open: dict[str, list[OpenPosition]] = {}
        self._lock = threading.Lock()

    def add_closed(self, account_id: str, t: ClosedTrade) -> None:
        with self._lock:
            self.closed.setdefault(account_id, []).append(t)

    def add_open(self, account_id: str, p: OpenPosition) -> None:
        with self._lock:
            self.open.setdefault(account_id, []).append(p)

    def closed_trades(self, account_id, since, until):
        with self._lock:
            return [t for t in self.closed.get(account_id, []) if since <= t.closed_at <= until]

    def last_closed(self, account_id, until, limit):
        with self._lock:
            rows = [t for t in self.closed.get(account_id, []) if t.closed_at <= until]
        return sorted(rows, key=lambda t: (t.closed_at, t.trade_id), reverse=True)[:limit]

    def open_positions(self, account_id, at):
        with self._lock:
            return [p for p in self.open.get(account_id, []) if p.opened_at <= at]

    def opened_count(self, account_id, since, until):
        with self._lock:
            n = sum(since <= t.opened_at <= until for t in self.closed.get(account_id, []))
            return n + sum(since <= p.opened_at <= until for p in self.open.get(account_id, []))


def unrealized(p: OpenPosition, bid: Decimal, ask: Decimal, contract_size: Decimal) -> Decimal:
    """PnL đang chạy nếu đóng ngay (BUY đóng ở bid, SELL ở ask), trừ phí khứ hồi."""
    move = (bid - p.entry_price) if p.side is Side.BUY else (p.entry_price - ask)
    return move * contract_size * p.volume - p.commission_per_lot * p.volume


def remaining_risk(p: OpenPosition, slippage: Decimal, contract_size: Decimal) -> Decimal:
    """Rủi ro còn lại nếu chạm SL hiện tại (so với giá vào) + đệm trượt giá + phí; SL đã qua hòa
    vốn sau chi phí → 0."""
    gap = (p.entry_price - p.stop_loss) if p.side is Side.BUY else (p.stop_loss - p.entry_price)
    r = (gap + slippage) * contract_size * p.volume + p.commission_per_lot * p.volume
    return max(r, Decimal(0))
