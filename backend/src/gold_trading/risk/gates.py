"""Cổng đọc của Risk Engine (RSK-10, KN-01; thiết kế docs/thiet-ke/35-risk-engine.md mục 6).

Risk **tự đọc** trạng thái thật tại lúc quyết qua các cổng này — không tin giá trị do bên gọi
đưa. Mỗi cổng có thể ném lỗi khi đọc hỏng; ``RiskEngine`` bắt lỗi và từ chối
(``GATE_READ_ERROR:<cổng>``), không cho qua.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from gold_trading.analysts.framework import Scope
from gold_trading.common.enums import SourceStatus, TradingMode
from gold_trading.contracts.market_view import MarketView
from gold_trading.market.quote_minutes import QuoteMinute
from gold_trading.market.quotes import QuoteSecond
from gold_trading.storage.broker_history import SpecRow
from gold_trading.storage.commissions import Commission


class AccountGate(Protocol):
    """``AccountRegistry`` thật: Safety + khóa người dùng + lệnh cấm làn nhanh + chế độ."""

    def entry_denials(self, account_id: str, now: datetime | None = None) -> list[str]: ...
    def mode(self, account_id: str) -> TradingMode | None: ...


class MarketViewGate(Protocol):
    def current(self, scope: Scope, at: datetime) -> MarketView | None: ...


@dataclass(frozen=True)
class BrokerReading:
    """Đọc lúc quyết (RSK-11 2a–2b): nhịp tim Gateway hiện tại + thông số broker ``spec_at``.

    ``None`` ở trường nào = không đọc được / không có — Risk từ chối, không đoán."""

    connected: bool                         # GatewayStatus CONNECTED
    heartbeat_age_s: float | None
    equity: float | None
    account_currency: str | None            # trong nhịp tim (AccountSnapshot)
    identity: tuple[int, str] | None        # (login, server) MT5 do terminal báo
    heartbeat_symbol: str | None            # mã broker trong nhịp tim
    live_spec_hash: str | None              # mã băm thông số trong nhịp tim (cùng cách băm KN-05)
    locked_symbol: str | None               # mã broker đã khóa vào liên kết (nguồn giá, MT-05)
    spec: SpecRow | None                    # spec_at(tài khoản, mã đã khóa, lúc quyết)


@dataclass(frozen=True)
class RiskGates:
    accounts: AccountGate
    # tài khoản → phạm vi MarketView (nguồn giá của tài khoản); None = chưa có nguồn giá
    scope_for: Callable[[str], Scope | None]
    market_views: MarketViewGate
    # lúc quyết → các mã "nguồn lịch không khỏe" (rỗng = mọi nguồn lịch khỏe). Đọc lỗi → ném.
    calendar_health: Callable[[datetime], list[str]]
    # RSK-11: (tài khoản, lúc) → nhịp tim + thông số broker
    broker: Callable[[str, datetime], BrokerReading]
    # (nguồn giá, lúc) → giây giá mới nhất đã biết
    latest_quote: Callable[[str, datetime], QuoteSecond | None]
    # (nguồn giá, từ, tới, đã biết lúc) → spread theo phút (KN-03), point-in-time
    spread_minutes: Callable[[str, datetime, datetime, datetime], list[QuoteMinute]]
    # (tài khoản, lúc) → phí khứ hồi / lot hiện hành (Q3); None = chưa nhập
    commission: Callable[[str, datetime], Commission | None]


# Nguồn lịch Risk đòi phải khỏe (Q1). Cùng danh sách với lịch kinh tế hợp nhất.
def calendar_health_codes(details: dict, sources: Iterable[str]) -> list[str]:
    """``details``: nguồn → ``SourceHealth`` (ING-30). Không khỏe = khác HEALTHY **hoặc** lần nạp
    gần nhất lỗi (``failures_since_ok > 0``). Nguồn không có trong ``details`` = chưa biết →
    không khỏe."""
    out = []
    for src in sources:
        h = details.get(src)
        if h is None:
            out.append(f"CALENDAR_SOURCE_UNHEALTHY:{src}")
        elif h.status is not SourceStatus.HEALTHY or h.failures_since_ok:
            out.append(f"CALENDAR_SOURCE_UNHEALTHY:{src}")
    return out


def calendar_health_gate(check_log, record_store) -> Callable[[datetime], list[str]]:
    """Cổng sức khỏe nguồn lịch thật. Không có nhật ký kiểm nguồn → luôn báo chưa biết."""
    from gold_trading.ingestion.economic_calendar import CALENDAR_SOURCES, health_details

    def gate(now: datetime) -> list[str]:
        if check_log is None or record_store is None:
            return ["CALENDAR_HEALTH_UNKNOWN"]
        return calendar_health_codes(health_details(check_log, record_store, now),
                                     CALENDAR_SOURCES)

    return gate


def broker_gate(monitors, history, locked_symbol: Callable[[str], str | None]
                ) -> Callable[[str, datetime], BrokerReading]:
    """Cổng broker thật: ``GatewayMonitors`` (nhịp tim trong bộ nhớ) + ``BrokerHistoryStore``
    (``spec_at``, KN-05) + mã broker đã khóa của liên kết MT5."""
    from gold_trading.api.ingest import heartbeat_spec
    from gold_trading.storage.broker_history import spec_hash

    def gate(account_id: str, now: datetime) -> BrokerReading:
        st = monitors.get(account_id).status(now)
        hb = st.heartbeat
        acc = hb.account if hb is not None else None
        ident = hb.identity if hb is not None else None
        live = heartbeat_spec(hb) if hb is not None and hb.symbol is not None else None
        sym = locked_symbol(account_id)
        return BrokerReading(
            connected=st.state == "CONNECTED",
            heartbeat_age_s=st.age_seconds,
            equity=acc.equity if acc is not None else None,
            account_currency=acc.currency if acc is not None else None,
            identity=(ident.login, ident.server) if ident is not None else None,
            heartbeat_symbol=hb.symbol.broker_symbol if hb is not None and hb.symbol else None,
            live_spec_hash=spec_hash(live) if live is not None else None,
            locked_symbol=sym,
            spec=history.spec_at(account_id, sym, now) if sym else None,
        )

    return gate
