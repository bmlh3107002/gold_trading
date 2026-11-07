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


class FakeMt5:
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
        self.now = now_utc
        self.tz = ZoneInfo(server_tz)
        self.trade_mode = trade_mode
        self.symbol = symbol
        self.connected = connected
        self.init_ok = init_ok
        self.live_ticks = live_ticks
        self._msc = 0
        self.calls: list[str] = []
        self.order_send_called = False

    # --- hàm đọc ---
    def initialize(self, path=None):
        self.calls.append("initialize")
        return self.init_ok

    def shutdown(self):
        return True

    def last_error(self):
        return (-10003, "IPC initialize failed") if not self.init_ok else (1, "Success")

    def terminal_info(self):
        return SimpleNamespace(
            connected=self.connected, company="Demo Broker Ltd", name="MetaTrader 5"
        )

    def account_info(self):
        return SimpleNamespace(
            trade_mode=self.trade_mode, server="DemoBroker-Demo", company="Demo Broker Ltd"
        )

    def symbol_info(self, name):
        if name != self.symbol:
            return None
        return SimpleNamespace(
            visible=True,
            digits=2,
            point=0.01,
            trade_contract_size=100.0,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            currency_profit="USD",
        )

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
        if name != self.symbol or tf in self.missing_tfs:
            return None
        if tf != TIMEFRAME_M15 and tf not in _TF_SECONDS:
            return None
        rows = self._rows(tf)
        end = len(rows) - start
        return rows[max(0, end - count) : end]

    # --- hàm GIAO DỊCH: không bao giờ được gọi ---
    def order_send(self, request):
        self.order_send_called = True
        raise AssertionError("Gateway chỉ đọc không được gọi order_send")
