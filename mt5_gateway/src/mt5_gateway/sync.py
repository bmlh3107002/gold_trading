"""Vòng đồng bộ: nạp bù lịch sử một lần, sau đó gửi nến vừa đóng + nhịp tim. Chỉ đọc MT5."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from mt5_gateway import __version__
from mt5_gateway.backend_client import BackendClient, BackendError
from mt5_gateway.checks import CheckReport
from mt5_gateway.config import Config
from mt5_gateway.reader import Bar, Mt5Error, Mt5Reader

log = logging.getLogger("mt5_gateway")
BATCH = 1000
LIVE_BARS = 20
MAX_BACKOFF_S = 30.0


def chunks(xs: list[Bar], n: int) -> list[list[Bar]]:
    return [xs[i : i + n] for i in range(0, len(xs), n)]


class Syncer:
    def __init__(
        self,
        cfg: Config,
        reader: Mt5Reader,
        client: BackendClient,
        report: CheckReport,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg, self.reader, self.client, self.report = cfg, reader, client, report
        self.sleep, self.clock = sleep, clock
        self.last_sent: Bar | None = None
        self.terminal_ok = True

    def backfill(self) -> dict[str, int]:
        bars = self.reader.closed_bars(self.cfg.history_bars)
        totals = {"accepted": 0, "duplicates": 0, "quarantined": 0}
        for part in chunks(bars, BATCH):
            r = self.client.post_candles(
                symbol=self.cfg.symbol,
                bars=[b.to_json() for b in part],
                backfill=True,
                gateway_id=self.cfg.gateway_id,
            )
            for k in totals:
                totals[k] += r[k]
        if bars:
            self.last_sent = bars[-1]
        log.info("Nạp bù lịch sử: %s", totals)
        return totals

    def heartbeat_payload(self) -> dict[str, Any]:
        info = self.report.symbol_info
        acc = self.report.account
        last_tick = None
        try:
            t = self.reader.last_tick_utc()
            last_tick = t.isoformat() if t else None
        except Exception:
            pass
        return {
            "gateway_id": self.cfg.gateway_id,
            "gateway_version": __version__,
            "read_only": True,
            "terminal_connected": self.terminal_ok,
            "account_type": self.report.account_type,
            "server": getattr(acc, "server", None),
            "company": getattr(acc, "company", None),
            "server_tz": self.cfg.server_tz,
            "server_offset_hours_now": self.report.offset_now,
            "last_tick_time": last_tick,
            "symbol": None
            if info is None
            else {
                "broker_symbol": self.cfg.broker_symbol,
                "digits": int(info.digits),
                "point": float(info.point),
                "contract_size": float(info.trade_contract_size),
                "volume_min": float(info.volume_min),
                "volume_max": float(info.volume_max),
                "volume_step": float(info.volume_step),
                "currency_profit": getattr(info, "currency_profit", None),
            },
            "last_sent_bar": self.last_sent.open_time_utc.isoformat() if self.last_sent else None,
        }

    def push_recent(self) -> dict[str, Any] | None:
        bars = self.reader.closed_bars(LIVE_BARS)
        if not bars:
            return None
        r = self.client.post_candles(
            symbol=self.cfg.symbol,
            bars=[b.to_json() for b in bars],
            backfill=False,
            gateway_id=self.cfg.gateway_id,
        )
        if r["accepted"] or r["quarantined"]:
            log.info("Nến mới: +%d, cách ly %d %s", r["accepted"], r["quarantined"], r["reasons"])
        self.last_sent = bars[-1]
        return r

    def run_forever(self, stop: Callable[[], bool] = lambda: False) -> None:
        backoff = 1.0
        next_hb = 0.0
        while not stop():
            try:
                self.push_recent()
                self.terminal_ok = True
                backoff = 1.0
            except Mt5Error as e:
                self.terminal_ok = False
                log.warning("MT5 lỗi: %s. Thử kết nối lại sau %.0fs", e, backoff)
                try:
                    self.reader.connect()
                except Mt5Error:
                    pass
                self.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_S)
                continue
            except BackendError as e:
                log.warning("Backend lỗi: %s. Thử lại sau %.0fs", e, backoff)
                self.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_S)
                continue
            if self.clock() >= next_hb:
                try:
                    self.client.heartbeat(self.heartbeat_payload())
                except BackendError as e:
                    log.warning("Gửi nhịp tim lỗi: %s", e)
                next_hb = self.clock() + self.cfg.heartbeat_seconds
            self.sleep(self.cfg.poll_seconds)
