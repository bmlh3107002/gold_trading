"""Vòng làn nhanh 2 giây + ngân sách độ trễ (GĐ2 bước 4d — FAST-02; 2-C09; DEC-20 câu 4).

Thiết kế: ``docs/thiet-ke/26-lam-nhanh.md`` mục 5. Tóm tắt:

- Hai "làn" báo nhịp cho ``FastLaneMonitor``: ``spread`` (vòng 2 giây ở đây, xét spread từng nguồn
  giá — bước 4c) và ``events`` (Event Orchestrator chạy 2 giây / nhịp, job ``FAST_LANE``).
- **Ngân sách 10 giây.** Safety thêm lệnh cấm ``LATENCY`` (tính khi đọc, không lưu) khi:
  một làn chưa chạy xong lần nào kể từ khi bật, hoặc lần chạy xong gần nhất cũ hơn 10 giây
  (``FAST_LANE_STALLED``); hoặc có sự kiện làn nhanh đã biết quá 10 giây mà job chưa xong
  (``FAST_LANE_BACKLOG``). Hết tình trạng → tự hết chặn. Lệnh cấm ghi với ``latency_ms`` > 10 giây
  → log cảnh báo (``budget_breaches``).
- Chạy chậm / lỗi không bao giờ làm **mở** lệnh: chỉ có thể thêm chặn.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from gold_trading.common.time import utcnow
from gold_trading.risk import spread_lane
from gold_trading.risk.blocks import ALL, Block, BlockKind

log = logging.getLogger("gold_trading.fast_lane")

BUDGET = timedelta(seconds=10)
TICK = timedelta(seconds=2)
POLICY_VERSION = "fast-lane-loop-2026.11.14"
# Cửa sổ giá đọc mỗi vòng: mốc 60 phút trước giây đầu đợt giãn (lùi tối đa MAX_RUN_LOOKBACK).
QUOTE_WINDOW = timedelta(hours=1) + spread_lane.MAX_RUN_LOOKBACK + timedelta(minutes=1)


class FastLaneMonitor:
    """Nhịp của các làn + sự kiện tồn đọng → lệnh cấm ``LATENCY`` cho Safety. An toàn luồng."""

    def __init__(self, budget: timedelta = BUDGET) -> None:
        self.budget = budget
        self._lock = threading.Lock()
        self._started: dict[str, datetime] = {}
        self._ok: dict[str, datetime] = {}
        self._backlog: dict[str, datetime] = {}      # làn → known_at sớm nhất còn chờ
        self.budget_breaches = 0
        self.last_latency_ms: int | None = None

    def start(self, lane: str, now: datetime) -> None:
        with self._lock:
            self._started.setdefault(lane, now)

    def ok(self, lane: str, now: datetime) -> None:
        with self._lock:
            self._ok[lane] = now

    def backlog(self, lane: str, oldest_known_at: datetime | None) -> None:
        with self._lock:
            if oldest_known_at is None:
                self._backlog.pop(lane, None)
            else:
                self._backlog[lane] = oldest_known_at

    def latency(self, ms: int) -> None:
        with self._lock:
            self.last_latency_ms = ms
            if ms > self.budget.total_seconds() * 1000:
                self.budget_breaches += 1
                log.warning("Làn nhanh vượt ngân sách độ trễ: %d ms (> %d ms)", ms,
                            int(self.budget.total_seconds() * 1000))

    def snapshot(self, now: datetime) -> list[dict]:
        """Trạng thái từng làn (trang pipeline): bật lúc, chạy xong lần cuối, tồn đọng từ, đạt?"""
        with self._lock:
            lanes = sorted(set(self._started) | set(self._ok) | set(self._backlog))
            out = []
            for lane in lanes:
                last = self._ok.get(lane)
                oldest = self._backlog.get(lane)
                ok = (lane in self._started and last is not None and now - last <= self.budget
                      and (oldest is None or now - oldest <= self.budget))
                out.append({"lane": lane, "started_at": self._started.get(lane),
                            "last_ok_at": last, "backlog_since": oldest, "ok": ok})
            return out

    def blocks(self, now: datetime) -> list[Block]:
        out = []
        with self._lock:
            for lane, started in sorted(self._started.items()):
                last = self._ok.get(lane)
                if last is None:
                    out.append(self._block("FAST_LANE_STARTING", lane, started, now))
                elif now - last > self.budget:
                    out.append(self._block("FAST_LANE_STALLED", lane, last + self.budget, now))
            for lane, oldest in sorted(self._backlog.items()):
                if now - oldest > self.budget:
                    out.append(self._block("FAST_LANE_BACKLOG", lane, oldest + self.budget, now))
        return out

    @staticmethod
    def _block(reason: str, lane: str, start: datetime, now: datetime) -> Block:
        start = min(start, now)
        return Block(BlockKind.LATENCY, ALL, reason, start, None, f"latency:{lane}", now,
                     POLICY_VERSION)


class SpreadLoop:
    """Vòng 2 giây: xét spread từng nguồn giá đang dùng (4c), ghi / gỡ lệnh cấm, báo nhịp."""

    def __init__(self, *, quote_store, block_store, feeds: Callable[[], list[str]],
                 monitor: FastLaneMonitor, now: Callable[[], datetime] = utcnow,
                 tick: timedelta = TICK, clock: Callable[[], float] = time.monotonic) -> None:
        self.quote_store = quote_store
        self.block_store = block_store
        self.feeds = feeds
        self.monitor = monitor
        self._now = now
        self._tick = tick
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self, now: datetime | None = None) -> dict[str, str]:
        now = now or self._now()
        self.monitor.start("spread", now)
        t0 = self._clock()
        status = {}
        for feed in self.feeds():
            if not feed:
                continue                       # dữ liệu mẫu / CSV: không có giá theo giây
            rows = self.quote_store.window(feed, now - QUOTE_WINDOW, now + timedelta(seconds=1))
            c = spread_lane.check_feed(feed, rows, self.block_store.open_spread(now), now)
            spread_lane.apply(c, self.block_store)
            if c.block is not None:
                log.warning("Chặn mở lệnh mới: spread %s nguồn %s (mốc %s)", c.block.reason_code,
                            feed, c.baseline)
                self.monitor.latency(c.block.latency_ms or 0)
            for x in c.lifts:
                log.info("Gỡ chặn spread nguồn %s (%s)", feed, x.reason_code)
            status[feed] = c.status
        took = timedelta(seconds=self._clock() - t0)
        if took > self.monitor.budget:
            # Xong nhưng quá ngân sách: không báo nhịp (Safety tiếp tục chặn nếu kéo dài).
            log.warning("Vòng spread chạy %.1f giây (> ngân sách)", took.total_seconds())
            return status
        self.monitor.ok("spread", now)
        return status

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("Vòng làn nhanh (spread) lỗi, thử lại nhịp sau")
            if self._stop.wait(self._tick.total_seconds()):
                return

    def start(self) -> None:
        if self._thread is None:
            self.monitor.start("spread", self._now())
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="fast-lane-spread",
                                            daemon=True)
            self._thread.start()
            log.info("Bật vòng làn nhanh (spread, 2 giây)")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None
