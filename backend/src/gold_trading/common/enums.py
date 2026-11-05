"""Enum dùng chung. Không dùng chuỗi tự do cho trạng thái an toàn (docs README)."""

from __future__ import annotations

from enum import StrEnum


class SourceStatus(StrEnum):
    HEALTHY = "HEALTHY"
    STALE = "STALE"
    MISSING = "MISSING"
    INVALID = "INVALID"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class Bias(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class Regime(StrEnum):
    TREND = "TREND"
    RANGE = "RANGE"
    RISK_OFF = "RISK_OFF"
    HIGH_VOL = "HIGH_VOL"


class SafetyState(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    HALTED = "HALTED"


class TradingMode(StrEnum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    LIVE = "LIVE"


class RiskOutcome(StrEnum):
    APPROVED = "APPROVED"
    REDUCED = "REDUCED"
    REJECTED = "REJECTED"


class QualityVerdict(StrEnum):
    ACCEPTED = "ACCEPTED"
    DEGRADED = "DEGRADED"
    REJECTED = "REJECTED"


class OrderState(StrEnum):
    REQUESTED = "REQUESTED"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"
