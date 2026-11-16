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


class AccountGate(Protocol):
    """``AccountRegistry`` thật: Safety + khóa người dùng + lệnh cấm làn nhanh + chế độ."""

    def entry_denials(self, account_id: str, now: datetime | None = None) -> list[str]: ...
    def mode(self, account_id: str) -> TradingMode | None: ...


class MarketViewGate(Protocol):
    def current(self, scope: Scope, at: datetime) -> MarketView | None: ...


@dataclass(frozen=True)
class RiskGates:
    accounts: AccountGate
    # tài khoản → phạm vi MarketView (nguồn giá của tài khoản); None = chưa có nguồn giá
    scope_for: Callable[[str], Scope | None]
    market_views: MarketViewGate
    # lúc quyết → các mã "nguồn lịch không khỏe" (rỗng = mọi nguồn lịch khỏe). Đọc lỗi → ném.
    calendar_health: Callable[[datetime], list[str]]


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
