"""Đọc dữ liệu từ MT5. CHỈ dùng các hàm đọc (xem READ_ONLY_FUNCTIONS).

Module ``MetaTrader5`` được truyền vào (``mt5``) để test bằng bản giả lập.
"""

from __future__ import annotations

import ntpath
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


class TerminalMismatch(Mt5Error):
    """MT-15: đang nối terminal khác terminal đã cấu hình (``GT_MT5_PATH``)."""


def norm_terminal_dir(path: str) -> str:
    """Thư mục cài terminal, chuẩn hóa kiểu Windows (MT-15).

    ``GT_MT5_PATH`` trỏ tới ``terminal64.exe``; ``terminal_info().path`` trả THƯ MỤC chứa nó.
    Windows không phân biệt hoa/thường và nhận cả ``/`` lẫn ``\\`` → so sau khi chuẩn hóa.
    """
    p = path.strip().strip('"').strip()
    if p.lower().endswith(".exe"):
        p = ntpath.dirname(p)
    return ntpath.normcase(ntpath.normpath(p)) if p else ""


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
        try:
            self.ensure_terminal()
        except Mt5Error:
            self.shutdown()  # nối nhầm terminal: buông ra, không đọc gì của terminal đó
            raise

    def terminal_dir(self) -> str | None:
        """Thư mục terminal đang nối (``None`` nếu không đọc được)."""
        try:
            info = self.mt5.terminal_info()
        except Exception:
            return None
        path = getattr(info, "path", None) if info is not None else None
        return path if isinstance(path, str) and path.strip() else None

    def ensure_terminal(self) -> None:
        """MT-15: đã đặt ``GT_MT5_PATH`` thì terminal đang nối PHẢI đúng thư mục đó.

        Máy chạy nhiều MT5: nối nhầm terminal = gửi nến của MT5 người khác dưới token của mình.
        Không đọc được đường dẫn cũng coi là sai (mặc định an toàn). Không đặt ``GT_MT5_PATH``
        (máy một MT5) → không kiểm.
        """
        if not self.path:
            return
        want = norm_terminal_dir(self.path)
        got = self.terminal_dir()
        if got is None:
            raise TerminalMismatch("TERMINAL_MISMATCH: không đọc được đường dẫn terminal đang nối")
        if norm_terminal_dir(got) != want:
            raise TerminalMismatch(
                f"TERMINAL_MISMATCH: đang nối terminal ở {got}, "
                f"không phải terminal đã cấu hình ({self.path})"
            )

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

    def _to_bar(self, r: Any) -> Bar | None:
        t = server_epoch_to_utc(int(r["time"]), self.tz)
        if t is None:
            self.skipped_ambiguous += 1
            return None
        return Bar(
            t,
            float(r["open"]),
            float(r["high"]),
            float(r["low"]),
            float(r["close"]),
            int(r["tick_volume"]),
            int(r["spread"]),
        )

    def bars_with_tail(self, count: int, timeframe: str = "M15") -> tuple[list[Bar], Bar | None]:
        """(nến đã đóng ở vị trí 1..count, nến ở vị trí 0) đọc trong MỘT lần gọi MT5.

        Nến vị trí 0 có thể còn đang chạy, cũng có thể là nến cuối phiên đã hết giờ nhưng chưa có
        nến kế (cuối tuần, ngày lễ, giờ nghỉ — 1A-C21). Gateway KHÔNG tự quyết: gửi riêng trong
        ``tail_bar`` để backend xét theo đồng hồ + lịch broker. Đọc một lần để không lệch nhau
        khi nến mới hình thành giữa hai lần đọc.
        """
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"Khung không hỗ trợ: {timeframe}")
        tf_const = getattr(self.mt5, f"TIMEFRAME_{timeframe}")
        rates = self.mt5.copy_rates_from_pos(self.symbol, tf_const, 0, count + 1)
        if rates is None:
            raise self._err(f"Đọc nến {timeframe} (copy_rates_from_pos)")
        rows = list(rates)
        if not rows:
            return [], None
        # MT5 trả theo thứ tự cũ → mới: phần tử cuối là vị trí 0.
        tail = self._to_bar(rows[-1])
        closed = [b for b in (self._to_bar(r) for r in rows[:-1]) if b is not None]
        closed.sort(key=lambda b: b.open_time_utc)
        if tail is not None and closed and tail.open_time_utc <= closed[-1].open_time_utc:
            tail = None  # dữ liệu lạ: không gửi
        return closed, tail

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
        out = [b for b in (self._to_bar(r) for r in rates) if b is not None]
        return sorted(out, key=lambda b: b.open_time_utc)

    def terminal_connected(self) -> bool:
        """Terminal đang nối với server broker không (lỗi đọc → False, an toàn)."""
        try:
            info = self.mt5.terminal_info()
        except Exception:
            return False
        return bool(getattr(info, "connected", False)) if info is not None else False
