"""Chuyển mã trả về của MT5 (trade retcode) thành reason code chuẩn của hệ thống."""

from __future__ import annotations

from enum import StrEnum


class ReasonCode(StrEnum):
    OK = "OK"
    PLACED = "PLACED"
    PARTIAL = "PARTIAL"
    REQUOTE = "REQUOTE"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    INVALID_VOLUME = "INVALID_VOLUME"
    INVALID_PRICE = "INVALID_PRICE"
    INVALID_STOPS = "INVALID_STOPS"
    MARKET_CLOSED = "MARKET_CLOSED"
    NO_MONEY = "NO_MONEY"
    PRICE_CHANGED = "PRICE_CHANGED"
    NO_QUOTES = "NO_QUOTES"
    TIMEOUT = "TIMEOUT"
    CONNECTION = "CONNECTION"
    UNKNOWN = "UNKNOWN"


# https://www.mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes
_RETCODES: dict[int, ReasonCode] = {
    10004: ReasonCode.REQUOTE,
    10006: ReasonCode.REJECTED,
    10007: ReasonCode.CANCELLED,
    10008: ReasonCode.PLACED,
    10009: ReasonCode.OK,
    10010: ReasonCode.PARTIAL,
    10012: ReasonCode.TIMEOUT,
    10014: ReasonCode.INVALID_VOLUME,
    10015: ReasonCode.INVALID_PRICE,
    10016: ReasonCode.INVALID_STOPS,
    10018: ReasonCode.MARKET_CLOSED,
    10019: ReasonCode.NO_MONEY,
    10020: ReasonCode.PRICE_CHANGED,
    10021: ReasonCode.NO_QUOTES,
    10031: ReasonCode.CONNECTION,
}

# Với các mã này không biết chắc lệnh đã tới broker hay chưa:
# phải truy vấn MT5 trước, tuyệt đối không gửi lại mù (docs/09).
AMBIGUOUS: frozenset[ReasonCode] = frozenset(
    {ReasonCode.TIMEOUT, ReasonCode.CONNECTION, ReasonCode.UNKNOWN}
)


def from_retcode(retcode: int) -> ReasonCode:
    return _RETCODES.get(retcode, ReasonCode.UNKNOWN)
