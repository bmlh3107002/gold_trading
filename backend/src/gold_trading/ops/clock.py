"""Kiểm tra đồng hồ máy chủ (OPS-12, case 0-C09).

``ingested_at`` của nến lấy theo đồng hồ backend, nên đồng hồ sai = point-in-time sai.
Đo độ lệch bằng header ``Date`` của vài máy chủ HTTPS lớn, lấy TRUNG VỊ (cần >= 3 kết quả).

- ``Date`` chỉ chính xác tới giây và bị cắt xuống, nên cộng 0,5 s và chấp nhận sai số ~±1 s.
  Ngưỡng 2 s vì vậy chỉ dùng để CẢNH BÁO.
- |lệch| > 30 s → BLOCKED: ngừng nhận nến (cổng ingest trả 503) cho tới khi hết lệch.
- Không đo được → UNKNOWN: cảnh báo, không chặn (không biết thì không nói được là sai; chặn ingest
  không bảo vệ tiền mà chỉ làm mất dữ liệu). ``GT_CLOCK_UNKNOWN_BLOCKS=1`` để chặn cả khi UNKNOWN.
Chi tiết và lý do: docs/thiet-ke/00-xac-thuc-phan-quyen.md mục 9.
"""

from __future__ import annotations

import logging
import statistics
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Literal

import httpx

from gold_trading.common.time import utcnow

log = logging.getLogger("gold_trading.clock")

SOURCES = (
    "https://www.google.com/",
    "https://www.cloudflare.com/",
    "https://www.microsoft.com/",
    "https://www.apple.com/",
    "https://www.amazon.com/",
)
WARN_S = 2.0
BLOCK_S = 30.0
MIN_SOURCES = 3
INTERVAL_OK_S = 300.0
INTERVAL_BAD_S = 60.0

ClockState = Literal["OK", "WARN", "BLOCKED", "UNKNOWN"]


@dataclass(frozen=True)
class ClockStatus:
    state: ClockState
    offset_s: float | None
    """Đồng hồ backend nhanh hơn giờ chuẩn bao nhiêu giây (âm = chậm)."""
    sources_ok: int
    measured_at: datetime | None


def classify(offset: float | None, *, unknown_blocks: bool = False) -> ClockState:
    if offset is None:
        return "BLOCKED" if unknown_blocks else "UNKNOWN"
    a = abs(offset)
    if a > BLOCK_S:
        return "BLOCKED"
    if a > WARN_S:
        return "WARN"
    return "OK"


def measure_offset(
    client: httpx.Client,
    sources: tuple[str, ...] = SOURCES,
    now: Callable[[], float] = time.time,
) -> tuple[float | None, int]:
    """(độ lệch trung vị, số nguồn đo được). Độ lệch = đồng hồ local − giờ chuẩn."""
    offsets: list[float] = []
    for url in sources:
        try:
            t0 = now()
            resp = client.head(url, follow_redirects=False)
            t1 = now()
            raw = resp.headers.get("date")
            if not raw:
                continue
            server = parsedate_to_datetime(raw).timestamp() + 0.5
        except (httpx.HTTPError, ValueError, TypeError, OverflowError) as e:
            log.info("Không đo được đồng hồ từ %s: %s", url, type(e).__name__)
            continue
        if t1 - t0 > 5.0:
            continue  # phản hồi quá chậm: điểm giữa không đáng tin
        offsets.append((t0 + t1) / 2 - server)
    if len(offsets) < MIN_SOURCES:
        return None, len(offsets)
    return statistics.median(offsets), len(offsets)


class ClockMonitor:
    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        sources: tuple[str, ...] = SOURCES,
        unknown_blocks: bool = False,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._client = client or httpx.Client(timeout=5.0)
        self._sources = sources
        self._unknown_blocks = unknown_blocks
        self._now = now
        self._status = ClockStatus(
            classify(None, unknown_blocks=unknown_blocks), None, 0, None
        )
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def status(self) -> ClockStatus:
        with self._lock:
            return self._status

    def check(self) -> ClockStatus:
        offset, n = measure_offset(self._client, self._sources, self._now)
        st = ClockStatus(classify(offset, unknown_blocks=self._unknown_blocks),
                         None if offset is None else round(offset, 2), n, utcnow())
        with self._lock:
            prev = self._status.state
            self._status = st
        if st.state != "OK" and st.state != prev:
            log.warning("Đồng hồ máy chủ: %s (lệch %s s, %d nguồn)", st.state, st.offset_s, n)
        return st

    def ingest_block_reason(self) -> str | None:
        st = self.status
        if st.state != "BLOCKED":
            return None
        if st.offset_s is None:
            return ("Ngừng nhận nến: không kiểm tra được đồng hồ máy chủ "
                    "(GT_CLOCK_UNKNOWN_BLOCKS=1)")
        return (f"Ngừng nhận nến: đồng hồ máy chủ lệch {st.offset_s:+.1f} giây "
                f"(> {BLOCK_S:.0f} s). Khởi động lại Docker Desktop hoặc đồng bộ giờ Windows "
                "rồi đợi tối đa 1 phút.")

    def _loop(self) -> None:
        while True:
            try:
                st = self.check()
            except Exception:
                log.exception("Kiểm tra đồng hồ lỗi")
                st = self.status
            wait = INTERVAL_OK_S if st.state == "OK" else INTERVAL_BAD_S
            if self._stop.wait(wait):
                return

    def start(self) -> None:
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="clock-check", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
