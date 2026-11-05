"""Luồng dữ liệu MẪU chạy nền: nạp bù lịch sử một lần, sau đó thêm nến mỗi khi một nến đóng.

Giả lập hành vi của một nguồn realtime để kiểm thử toàn bộ pipeline. Chỉ chạy khi
GT_DATA_SOURCE=SAMPLE.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from gold_trading.common.time import utcnow
from gold_trading.contracts.candle import DataSource
from gold_trading.ingestion.candles import CandleIngestor, IngestResult
from gold_trading.ingestion.sources import sample
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.candles import CandleStore

log = logging.getLogger("gold_trading.sample_feed")


class SampleFeed:
    def __init__(
        self,
        store: CandleStore,
        *,
        symbol: str = "XAUUSD",
        timeframe: Timeframe = Timeframe.M15,
        history_days: int = 90,
        start_price: float = 2400.0,
        seed: int = 20260101,
        interval_s: float = 15.0,
    ) -> None:
        self.store = store
        self.ingestor = CandleIngestor(store)
        self.symbol = symbol
        self.tf = timeframe
        self.history_days = history_days
        self.start_price = start_price
        self.seed = seed
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self, now: datetime | None = None) -> IngestResult:
        now = now or utcnow()
        last = self.store.last_before(self.symbol, self.tf, DataSource.SAMPLE, now + self.tf.delta)
        if last is None:
            start = now - timedelta(days=self.history_days)
            prev_close, backfill = self.start_price, True
        else:
            start, prev_close, backfill = last.open_time + self.tf.delta, last.close, False
        bars = list(
            sample.generate(start=start, end=now, tf=self.tf, prev_close=prev_close, seed=self.seed)
        )
        return self.ingestor.ingest(
            bars,
            symbol=self.symbol,
            timeframe=self.tf,
            source=DataSource.SAMPLE,
            ingested_at=now,
            backfill=backfill,
        )

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                r = self.tick()
                if r.accepted or r.quarantined:
                    log.info("sample feed: +%d nến, %d cách ly", r.accepted, r.quarantined)
            except IntegrityError:
                log.warning("sample feed: trùng khóa (có tiến trình khác vừa ghi), thử lại lần sau")
            except Exception:
                log.exception("sample feed lỗi, thử lại lần sau")
            self._stop.wait(self.interval_s)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="sample-feed", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
