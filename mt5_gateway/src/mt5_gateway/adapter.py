"""Interface adapter broker. Bản MT5 thật sẽ hiện thực Protocol này trên Windows.

Yêu cầu (docs/09): timeout rõ ràng, reconnect có backoff, heartbeat, hàng đợi bền vững,
đồng bộ số dư/vị thế sau reconnect, giữ map request–ticket/deal, xác thực mTLS/token.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from mt5_gateway.reason_codes import ReasonCode


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: float
    ask: float
    time: datetime


@dataclass(frozen=True)
class AccountInfo:
    balance: float
    equity: float
    margin: float
    margin_free: float


@dataclass(frozen=True)
class OrderRequest:
    idempotency_key: str  # gửi lên MT5 trong trường comment để đối soát khi mất ACK
    symbol: str
    side: Literal["BUY", "SELL"]
    volume: float
    price: float | None
    stop_loss: float
    take_profit: float | None
    magic: int


@dataclass(frozen=True)
class OrderResult:
    reason: ReasonCode
    ticket: int | None
    deal: int | None
    filled_volume: float
    raw_retcode: int | None


class BrokerAdapter(Protocol):
    def quote(self, symbol: str) -> Quote: ...
    def account(self) -> AccountInfo: ...
    def send(self, req: OrderRequest) -> OrderResult: ...
    def find_by_idempotency_key(self, key: str) -> OrderResult | None:
        """Dùng khi kết quả mơ hồ: kiểm tra lệnh đã tồn tại ở MT5 chưa."""
        ...
