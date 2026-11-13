"""Chạy Event Orchestrator trong backend (GĐ2 bước 3 — ORC-01, ORC-07).

Mỗi nhịp (10 giây): quét sự kiện mới từ dữ liệu đã lưu → bộ điều phối tạo + chạy job. Thay
``TechnicalRunner`` chạy theo vòng 15 giây: Technical chạy khi có nến M15 vàng đóng (theo đúng
nguồn giá) hoặc khi kết quả cũ hết hạn mà chưa có kết quả mới (ORC-07). ``GT_ORCHESTRATOR=0`` →
quay về runner cũ (đường lui).

Đồng hồ máy chủ bị chặn (``ClockMonitor``) → **không chạy** (giờ sai làm sai thời điểm "đã biết").
Lỗi trong một nhịp → ghi log, nhịp sau chạy tiếp (job dở dang được khôi phục từ nhật ký).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta

from gold_trading.common.time import utcnow
from gold_trading.orchestrator import scanner
from gold_trading.orchestrator.dispatcher import Dispatcher, Handler
from gold_trading.orchestrator.model import Event, EventType

log = logging.getLogger("gold_trading.orchestrator")

TICK = timedelta(seconds=10)
TECHNICAL_VERSION = "technical-job-1"


def enabled(env: Mapping[str, str]) -> bool:
    return (env.get("GT_ORCHESTRATOR") or "1").strip().lower() not in {"0", "off", "false"}


def feed_of(e: Event) -> str | None:
    """Nguồn giá trong chủ thể sự kiện: nến ``SRC:feed:SYM:TF``; hết hạn
    ``analyst:SRC:feed:SYM:TF``."""
    parts = e.subject.split(":")
    if e.event_type is EventType.CANDLE_CLOSED and len(parts) == 4:
        return parts[1]
    if e.event_type is EventType.OUTPUT_EXPIRED and len(parts) == 5:
        return parts[2]
    return None


def technical_handler(technical_runner, active_feeds: Callable[[], list[str]]) -> Handler:
    """Job TECHNICAL: chạy Technical analyst cho đúng nguồn giá của sự kiện, tại thời điểm chạy
    (dùng nến đã đóng tới lúc đó — point-in-time). Nguồn không còn tài khoản nào dùng → bỏ qua."""

    def run(e: Event, now: datetime) -> str | None:
        feed = feed_of(e)
        if feed is None:
            raise ValueError("sự kiện không có nguồn giá")
        if feed not in active_feeds():
            return "skipped:feed_inactive"
        return "technical:stored" if technical_runner.run_feed(feed, now) else \
            "technical:unchanged"

    return Handler(TECHNICAL_VERSION, run, deadline=timedelta(seconds=30), max_attempts=3,
                   fatal=(ValueError,))


class OrchestratorRunner:
    def __init__(self, *, orch, candle_store, record_store, analyst_store,
                 handlers: dict[str, Handler],
                 blocked: Callable[[], str | None] = lambda: None,
                 now: Callable[[], datetime] = utcnow, tick: timedelta = TICK) -> None:
        self.orch = orch
        self.candle_store = candle_store
        self.record_store = record_store
        self.analyst_store = analyst_store
        self.dispatcher = Dispatcher(orch, handlers)
        self._blocked = blocked
        self._now = now
        self._tick = tick
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._blocked_logged = False

    def tick(self, now: datetime | None = None):
        reason = self._blocked()
        if reason:
            if not self._blocked_logged:
                log.warning("Tạm dừng Event Orchestrator: %s", reason)
                self._blocked_logged = True
            return None
        self._blocked_logged = False
        now = now or self._now()
        sres = scanner.scan(orch=self.orch, candle_store=self.candle_store,
                            record_store=self.record_store, analyst_store=self.analyst_store,
                            now=now)
        dres = self.dispatcher.tick(now)
        # Chỉ ghi log khi có việc thật (quét lại vùng chồng lấn không tạo dòng log mỗi 10 giây).
        if dres.created or dres.ran or dres.superseded:
            log.info("Orchestrator: sự kiện mới %s, job mới %d, bỏ qua (debounce) %d, chạy %s",
                     dict(sres.new), dres.created, dres.superseded + dres.skipped, dres.ran)
        return sres, dres

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("Event Orchestrator lỗi, thử lại nhịp sau")
            if self._stop.wait(self._tick.total_seconds()):
                return

    def start(self) -> None:
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="orchestrator", daemon=True)
            self._thread.start()
            log.info("Bật Event Orchestrator (thay vòng Technical 15 giây)")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None
