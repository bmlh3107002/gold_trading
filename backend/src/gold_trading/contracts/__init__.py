"""Data contract giữa các lớp. Đây là nguồn sự thật cho OpenAPI và type frontend."""

from gold_trading.contracts.analyst import AnalystOutput
from gold_trading.contracts.execution import OrderRecord
from gold_trading.contracts.market_view import MarketView
from gold_trading.contracts.records import NormalizedRecord
from gold_trading.contracts.risk import RiskDecision
from gold_trading.contracts.safety import SafetyTransition
from gold_trading.contracts.snapshot import QualityReport, Snapshot
from gold_trading.contracts.trade_intent import TradeIntent

__all__ = [
    "AnalystOutput",
    "MarketView",
    "NormalizedRecord",
    "OrderRecord",
    "QualityReport",
    "RiskDecision",
    "SafetyTransition",
    "Snapshot",
    "TradeIntent",
]
