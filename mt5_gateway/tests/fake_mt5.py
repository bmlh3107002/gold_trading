"""MT5 giả lập: mô phỏng đúng hành vi quan trọng của thư viện MetaTrader5.

- ``time`` của nến/tick = giờ SERVER viết như UTC (epoch của giờ địa phương server).
- copy_rates_from_pos: vị trí 0 là nến ĐANG CHẠY; mảng trả về theo thứ tự cũ → mới.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

# Hằng số giống thư viện MetaTrader5 thật
TIMEFRAME_M15 = 15
TIMEFRAME_H1 = 16385
TIMEFRAME_H4 = 16388
TIMEFRAME_D1 = 16408
_TF_SECONDS = {TIMEFRAME_H1: 3600, TIMEFRAME_H4: 14400, TIMEFRAME_D1: 86400}


COPY_TICKS_INFO = 1


class FakeMt5:
    COPY_TICKS_INFO = COPY_TICKS_INFO
    TIMEFRAME_M15 = TIMEFRAME_M15
    TIMEFRAME_H1 = TIMEFRAME_H1
    TIMEFRAME_H4 = TIMEFRAME_H4
    TIMEFRAME_D1 = TIMEFRAME_D1

    def __init__(
        self,
        *,
        now_utc: datetime,
        server_tz: str = "Europe/Athens",
        trade_mode=0,
        symbol="XAUUSD",
        connected=True,
        init_ok=True,
        live_ticks=True,
        missing_tfs=(),
    ):
        self.missing_tfs = set(missing_tfs)
        self.rate_requests: list[tuple[int, int]] = []
        self.now = now_utc
        self.tz = ZoneInfo(server_tz)
        self.trade_mode = trade_mode
        self.symbol = symbol
        self.connected = connected
        self.init_ok = init_ok
        self.live_ticks = live_ticks
        self._msc = 0
        self.calls: list[str] = []
        self.init_paths: list[str | None] = []
        self.shutdowns = 0
        # MT-15: thư mục terminal mà initialize() thực sự nối tới (test đổi được)
        self.terminal_dir: str | None = r"C:\Program Files\MetaTrader 5"
        self.order_send_called = False
        # GW-08: tick giả. None = tự sinh 2 tick/giây (bid 2400.0 / ask 2400.2) khi live_ticks;
        # list = trả đúng các dòng này (lọc theo mốc). tick_requests ghi lại các lần gọi.
        self.tick_rows: list[dict] | None = None
        self.tick_requests: list[tuple[int, int]] = []
        self.tick_shift_s = 0  # mô phỏng thư viện hiểu mốc lệch (giây)
        # 5d: symbol khác trong Market Watch (vd. EURUSD) → hệ số nhân giá so với vàng
        self.extra_symbols: dict[str, float] = {}
        self.no_history: set[str] = set()
        # MT-12/GW-09: danh tính + số liệu tài khoản (test đổi được giữa các nhịp tim)
        self.login = 51234567
        self.server = "DemoBroker-Demo"
        self.account_extra: dict = dict(
            currency="USD",
            balance=10000.0,
            equity=10012.5,
            margin=0.0,
            margin_free=10012.5,
            margin_level=0.0,
            leverage=100,
            trade_allowed=True,
        )
        self.account_none = False
        self.account_raises = False
        self.symbol_extra: dict = dict(
            trade_stops_level=10,
            trade_freeze_level=5,
            swap_mode=1,
            swap_long=-25.3,
            swap_short=8.1,
            swap_rollover3days=3,
        )

    # --- hàm đọc ---
    def initialize(self, path=None):
        self.calls.append("initialize")
        self.init_paths.append(path)
        return self.init_ok

    def shutdown(self):
        self.shutdowns += 1
        return True

    def last_error(self):
        return (-10003, "IPC initialize failed") if not self.init_ok else (1, "Success")

    def terminal_info(self):
        return SimpleNamespace(
            connected=self.connected,
            company="Demo Broker Ltd",
            name="MetaTrader 5",
            path=self.terminal_dir,
        )

    def account_info(self):
        if self.account_raises:
            raise RuntimeError("IPC lỗi")
        if self.account_none:
            return None
        return SimpleNamespace(
            login=self.login,
            trade_mode=self.trade_mode,
            server=self.server,
            company="Demo Broker Ltd",
            **self.account_extra,
        )

    def symbol_info(self, name):
        if name in self.extra_symbols:
            return SimpleNamespace(visible=True, digits=5, point=0.00001, trade_contract_size=1e5,
                                   volume_min=0.01, volume_max=100.0, volume_step=0.01,
                                   currency_profit="USD")
        if name != self.symbol:
            return None
        fields = dict(
            visible=True,
            digits=2,
            point=0.01,
            trade_contract_size=100.0,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            currency_profit="USD",
        )
        fields.update(self.symbol_extra)  # test ghi đè được cả trường cốt lõi
        return SimpleNamespace(**fields)

    def symbol_select(self, name, enable):
        return name == self.symbol

    def symbols_get(self, group=None):
        return [SimpleNamespace(name=n) for n in ("XAUUSD.r", "XAUEUR")]

    def _server_epoch(self, utc: datetime) -> int:
        local = utc.astimezone(self.tz).replace(tzinfo=None)
        return int(local.replace(tzinfo=UTC).timestamp())

    def symbol_info_tick(self, name):
        if name != self.symbol:
            return None
        if self.live_ticks:
            self._msc += 1
        t = self._server_epoch(self.now)
        if not self.live_ticks:
            t -= 300  # thị trường yên/đóng: tick cuối đã cũ
        return SimpleNamespace(time=t, time_msc=t * 1000 + self._msc, bid=2400.0, ask=2400.2)

    def _rows(self, tf):
        """Nến theo giờ server (``time`` = epoch giờ server). H1/H4/D1 gom từ M15 theo RANH GIỚI
        GIỜ SERVER (như MT5 thật: D1 bắt đầu 00:00 giờ server, H4 lúc 00/04/…/20)."""
        from tests.gold_trading_sample import bars_until

        m15 = [
            {
                "time": self._server_epoch(b["open_time"]),
                "open": b["open"],
                "high": b["high"],
                "low": b["low"],
                "close": b["close"],
                "tick_volume": 100,
                "spread": 20,
                "real_volume": 0,
            }
            for b in bars_until(self.now)  # gồm cả nến đang chạy ở cuối
        ]
        if tf == TIMEFRAME_M15:
            return m15
        width = _TF_SECONDS[tf]
        out: list[dict] = []
        for r in m15:
            start = r["time"] - r["time"] % width
            if out and out[-1]["time"] == start:
                g = out[-1]
                g["high"] = max(g["high"], r["high"])
                g["low"] = min(g["low"], r["low"])
                g["close"] = r["close"]
                g["tick_volume"] += r["tick_volume"]
            else:
                out.append(dict(r, time=start))
        return out

    def copy_rates_from_pos(self, name, tf, start, count):
        self.rate_requests.append((tf, count))
        if name in self.extra_symbols:
            if name in self.no_history:
                return []
            k = self.extra_symbols[name]
            rows = self._rows(tf)
            end = len(rows) - start
            return [dict(r, open=round(r["open"] * k, 5), high=round(r["high"] * k, 5),
                         low=round(r["low"] * k, 5), close=round(r["close"] * k, 5))
                    for r in rows[max(0, end - count) : end]]
        if name != self.symbol or tf in self.missing_tfs:
            return None
        if tf != TIMEFRAME_M15 and tf not in _TF_SECONDS:
            return None
        rows = self._rows(tf)
        end = len(rows) - start
        return rows[max(0, end - count) : end]

    def copy_ticks_from(self, name, date_from, count, flags):
        self.tick_requests.append((int(date_from), count))
        if name != self.symbol:
            return None
        start = (int(date_from) + self.tick_shift_s) * 1000
        if self.tick_rows is not None:
            rows = [r for r in self.tick_rows if r["time_msc"] >= start]
            return rows[:count]
        if not self.live_ticks:
            return []
        end = self._server_epoch(self.now)
        rows = []
        for s in range(start // 1000, end):
            for ms, bid in ((100, 2400.0), (600, 2400.1)):
                if s * 1000 + ms >= start:
                    rows.append({"time": s, "time_msc": s * 1000 + ms, "bid": bid,
                                 "ask": round(bid + 0.2, 2), "last": 0.0, "volume": 0,
                                 "flags": 6})
        return rows[:count]

    # --- hàm GIAO DỊCH: không bao giờ được gọi ---
    def order_send(self, request):
        self.order_send_called = True
        raise AssertionError("Gateway chỉ đọc không được gọi order_send")
