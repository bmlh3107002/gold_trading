"""Chạy Technical analyst mỗi khi có nến M15 mới đóng (bản tối thiểu của Event Orchestrator)."""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from gold_trading.analysts import technical
from gold_trading.common.time import utcnow
from gold_trading.market.service import INDICATOR_WARMUP, MarketDataService
from gold_trading.storage.analyst_outputs import AnalystOutputStore

log = logging.getLogger("gold_trading.analysts")


class TechnicalRunner:
    def __init__(
        self, market: MarketDataService, store: AnalystOutputStore, *, interval_s: float = 15.0
    ) -> None:
        self.market = market
        self.store = store
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self, now: datetime | None = None) -> bool:
        """Trả True nếu vừa lưu một kết quả mới."""
        now = now or utcnow()
        if self.market.source is None:
            return False
        rows = self.market.candles(as_of=now, limit=technical.WINDOW + INDICATOR_WARMUP)
        out = technical.analyze(
            rows,
            symbol=self.market.symbol,
            timeframe=self.market.timeframe,
            source=self.market.source,
            expected_last_close=self.market.expected_last_close(now),
            correlation_id=f"bar-close:{rows[-1].close_time.isoformat()}" if rows else "none",
        )
        if out is None:
            return False
        return self.store.append(
            out,
            symbol=self.market.symbol,
            tf=self.market.timeframe,
            source=self.market.source,
            computed_at=now,
        )

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if self.tick():
                    log.info("technical: đã lưu kết quả mới")
            except Exception:
                log.exception("technical analyst lỗi, thử lại lần sau")
            self._stop.wait(self.interval_s)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="technical", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
