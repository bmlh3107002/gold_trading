"""ING-16 / 1A-C20: ước lượng lệch đồng hồ máy Gateway so với backend (đồng hồ backend được kiểm
NTP — OPS-12). Mỗi nhịp tim: backend trả giờ nó nhận (``last_seen_at``); lệch = giờ backend −
điểm giữa (gửi, nhận) theo đồng hồ máy. Chỉ lấy mẫu khi khứ hồi ≤ 2 s; dùng trung vị 5 mẫu.

Dùng để HIỆU CHỈNH các phép so sánh với "bây giờ" của Gateway (phát hiện broker đổi giờ, chốt giây
giá sống) — đồng hồ máy Windows sai không bị hiểu nhầm thành broker đổi giờ. Thời gian của dữ
liệu luôn lấy từ MT5, không từ đồng hồ máy."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median

MAX_RTT_S = 2.0
MAX_ABS_OFFSET = timedelta(days=1)
SAMPLES = 5


@dataclass
class ClockSync:
    _samples: deque[float] = field(default_factory=lambda: deque(maxlen=SAMPLES))

    def sample(self, sent: datetime, received: datetime, backend_time: datetime) -> bool:
        rtt = (received - sent).total_seconds()
        if rtt < 0 or rtt > MAX_RTT_S:
            return False  # khứ hồi lâu / đồng hồ nhảy giữa chừng: mẫu không tin được
        off = backend_time - (sent + timedelta(seconds=rtt / 2))
        if abs(off) > MAX_ABS_OFFSET:
            return False
        self._samples.append(off.total_seconds())
        return True

    @property
    def known(self) -> bool:
        return bool(self._samples)

    @property
    def offset(self) -> timedelta:
        """Cộng vào đồng hồ máy để ra giờ backend. Chưa có mẫu → 0 (dùng đồng hồ máy)."""
        return timedelta(seconds=median(self._samples)) if self._samples else timedelta(0)
