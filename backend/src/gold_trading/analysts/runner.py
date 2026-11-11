"""Chạy Technical analyst mỗi khi có nến M15 mới đóng (bản tối thiểu của Event Orchestrator)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime

from gold_trading.analysts import technical
from gold_trading.common.time import utcnow
from gold_trading.market.service import INDICATOR_WARMUP, MarketDataService
from gold_trading.storage.analyst_outputs import AnalystOutputStore

log = logging.getLogger("gold_trading.analysts")


class TechnicalRunner:
    """MT-05: ``feeds()`` trả các nguồn giá cần phân tích (mỗi nguồn một chuỗi kết quả riêng).
    Không truyền = chỉ nguồn của ``market``."""

    def __init__(
        self,
        market: MarketDataService,
        store: AnalystOutputStore,
        *,
        interval_s: float = 15.0,
        feeds: Callable[[], list[str]] | None = None,
    ) -> None:
        self.market = market
        self.store = store
        self.feeds = feeds
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self, now: datetime | None = None) -> bool:
        """Trả True nếu vừa lưu ít nhất một kết quả mới."""
        now = now or utcnow()
        if self.feeds is None:
            return self._tick_one(self.market, now)
        stored = False
        for f in self.feeds():
            try:
                stored |= self._tick_one(self.market.with_feed(lambda f=f: f), now)
            except Exception:
                # Lỗi ở một nguồn không được chặn các nguồn khác.
                log.exception("technical analyst lỗi ở nguồn %s", f)
        return stored

    def _tick_one(self, market: MarketDataService, now: datetime) -> bool:
        feed = market.feed
        if market.source is None or feed is None:
            return False  # MT-05: chưa có nguồn giá (vd. chưa liên kết MT5) → không phân tích
        rows = market.candles(as_of=now, limit=technical.WINDOW + INDICATOR_WARMUP)
        out = technical.analyze(
            rows,
            symbol=market.symbol,
            timeframe=market.timeframe,
            source=market.source,
            expected_last_close=market.expected_last_close(now),
            correlation_id=f"bar-close:{rows[-1].close_time.isoformat()}" if rows else "none",
            calendar=market.calendar,
        )
        if out is None:
            return False
        return self.store.append(
            out,
            symbol=market.symbol,
            tf=market.timeframe,
            source=market.source,
            computed_at=now,
            feed=feed,
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
