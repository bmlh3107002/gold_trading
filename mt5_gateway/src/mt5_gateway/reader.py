"""Đọc dữ liệu từ MT5. CHỈ dùng các hàm đọc (xem READ_ONLY_FUNCTIONS).

Module ``MetaTrader5`` được truyền vào (``mt5``) để test bằng bản giả lập.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from mt5_gateway.timeconv import detect_offset_hours, server_epoch_to_utc

READ_ONLY_FUNCTIONS = frozenset(
    {
        "initialize",
        "shutdown",
        "last_error",
        "terminal_info",
        "account_info",
        "symbol_info",
        "symbol_select",
        "symbol_info_tick",
        "copy_rates_from_pos",
        "symbols_get",
    }
)

ACCOUNT_TYPES = {0: "DEMO", 1: "CONTEST", 2: "REAL"}
TIMEFRAMES = ("M15", "H1", "H4", "D1")


class Mt5Error(RuntimeError):
    pass


@dataclass(frozen=True)
class Bar:
    open_time_utc: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int
    spread_points: int

    def to_json(self) -> dict[str, Any]:
        return {
            "open_time": self.open_time_utc.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "tick_volume": self.tick_volume,
            "spread_points": self.spread_points,
        }


class _ReadOnly:
    """Bọc module MT5: chỉ cho truy cập hàm đọc và hằng số TIMEFRAME_*."""

    def __init__(self, mt5: Any) -> None:
        self._mt5 = mt5

    def __getattr__(self, name: str) -> Any:
        if name in READ_ONLY_FUNCTIONS or name.startswith("TIMEFRAME_"):
            return getattr(self._mt5, name)
        raise AttributeError(f"Gateway chỉ đọc: không được dùng mt5.{name}")


class Mt5Reader:
    def __init__(
        self, mt5: Any, *, broker_symbol: str, server_tz: ZoneInfo, terminal_path: str | None = None
    ) -> None:
        self.mt5 = _ReadOnly(mt5)
        self.symbol = broker_symbol
        self.tz = server_tz
        self.path = terminal_path
        self.skipped_ambiguous = 0

    def _err(self, what: str) -> Mt5Error:
        try:
            code, msg = self.mt5.last_error()
        except Exception:
            code, msg = None, "không rõ"
        return Mt5Error(f"{what} thất bại (mã {code}: {msg})")

    def connect(self) -> None:
        ok = self.mt5.initialize(path=self.path) if self.path else self.mt5.initialize()
        if not ok:
            raise self._err("Kết nối MT5 (initialize)")

    def shutdown(self) -> None:
        try:
            self.mt5.shutdown()
        except Exception:
            pass

    def terminal(self) -> Any:
        info = self.mt5.terminal_info()
        if info is None:
            raise self._err("Đọc terminal_info")
        return info

    def account(self) -> tuple[str, Any]:
        acc = self.mt5.account_info()
        if acc is None:
            raise self._err("Đọc account_info (đã đăng nhập tài khoản trong MT5 chưa?)")
        return ACCOUNT_TYPES.get(getattr(acc, "trade_mode", -1), "UNKNOWN"), acc

    def symbol_info(self) -> Any:
        info = self.mt5.symbol_info(self.symbol)
        if info is None:
            return None
        if not getattr(info, "visible", True) and not self.mt5.symbol_select(self.symbol, True):
            raise self._err(f"Bật symbol {self.symbol} trong Market Watch")
        return info

    def similar_symbols(self) -> list[str]:
        try:
            found = self.mt5.symbols_get(group="*XAU*,*GOLD*") or ()
        except Exception:
            return []
        return sorted(s.name for s in found)[:20]

    def live_tick_offset(
        self, wait_s: float = 10.0, sleep=_time.sleep, now=_time.time
    ) -> int | None:
        """Chờ một tick MỚI (time_msc thay đổi) rồi suy ra độ lệch giờ.

        None nếu không có tick mới (thị trường đóng/yên): không đoán từ tick cũ.
        """
        first = self.mt5.symbol_info_tick(self.symbol)
        if first is None:
            return None
        waited = 0.0
        while waited < wait_s:
            sleep(0.5)
            waited += 0.5
            tick = self.mt5.symbol_info_tick(self.symbol)
            if tick is not None and tick.time_msc != first.time_msc:
                return detect_offset_hours(tick.time_msc / 1000, now())
        return None

    def last_tick_utc(self) -> datetime | None:
        tick = self.mt5.symbol_info_tick(self.symbol)
        return server_epoch_to_utc(tick.time, self.tz) if tick is not None else None

    def closed_bars(self, count: int, timeframe: str = "M15") -> list[Bar]:
        """Nến ĐÃ ĐÓNG gần nhất của ``timeframe`` (M15/H1/H4/D1), đọc thẳng từ MT5.

        Vị trí 0 là nến đang chạy nên bắt đầu từ vị trí 1. ``open_time`` của H4/D1 là ranh giới
        theo giờ server broker (ví dụ D1 = 00:00 giờ server), chỉ đổi sang UTC, không cắt lại.
        """
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"Khung không hỗ trợ: {timeframe}")
        tf_const = getattr(self.mt5, f"TIMEFRAME_{timeframe}")
        rates = self.mt5.copy_rates_from_pos(self.symbol, tf_const, 1, count)
        if rates is None:
            raise self._err(f"Đọc nến {timeframe} (copy_rates_from_pos)")
        out: list[Bar] = []
        for r in rates:
            t = server_epoch_to_utc(int(r["time"]), self.tz)
            if t is None:
                self.skipped_ambiguous += 1
                continue
            out.append(
                Bar(
                    t,
                    float(r["open"]),
                    float(r["high"]),
                    float(r["low"]),
                    float(r["close"]),
                    int(r["tick_volume"]),
                    int(r["spread"]),
                )
            )
        return sorted(out, key=lambda b: b.open_time_utc)
