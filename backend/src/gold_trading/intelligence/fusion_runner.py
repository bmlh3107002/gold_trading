"""Chạy Snapshot → Quality Gate → Fusion → lưu MarketView trong orchestrator (GĐ4 bước 5b).

Thiết kế 33 mục 7. Vì sao **việc mỗi nhịp** (``periodic``) chứ không phải job trong bảng định tuyến:
bộ điều phối chạy các job của cùng một sự kiện theo thứ tự chữ cái của loại job → job ``FUSION``
sẽ chạy **trước** ``REGIME`` / ``TECHNICAL`` của chính cây nến đó (dùng kết quả cũ). Việc mỗi nhịp
chạy **sau** mọi job của nhịp → luôn thấy kết quả analyst mới nhất đã ghi.

Mỗi nguồn giá đang dùng, tại ``now``:
1. Snapshot point-in-time (``known_by = now``) → Quality Gate ``quality-policy-1``.
2. Lưu snapshot + báo cáo (chỉ thêm, idempotent).
3. ``REJECTED`` → không sinh MarketView **và vô hiệu MarketView hiện hành còn hạn**
   (``QUALITY_REJECTED``) — nếu không, MarketView tạo lúc nguồn còn khỏe vẫn dùng được tới hết hạn.
4. Ngược lại → Fusion → lưu MarketView (mới nhất = hiện hành).

Không đổi gì (cùng snapshot + cùng kết quả Gate với lần trước) → không ghi gì (bộ nhớ đệm theo
nguồn; khởi động lại → tính lại một lần, ghi idempotent).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from gold_trading.analysts.framework import Scope
from gold_trading.common.enums import QualityVerdict
from gold_trading.intelligence.fusion import fuse
from gold_trading.intelligence.quality_gate import POLICY_V1, QualityPolicy, evaluate
from gold_trading.intelligence.snapshot_builder import SnapshotRecord, snapshot_at

log = logging.getLogger("gold_trading.intelligence")

HANDLER_VERSION = "fusion-job-1"
QUALITY_REJECTED = "QUALITY_REJECTED"


class FusionRunner:
    def __init__(self, *, market, out_store, snapshot_store, report_store, view_store,
                 active_feeds: Callable[[], list[str]],
                 policy: QualityPolicy = POLICY_V1) -> None:
        self.market = market
        self.out_store = out_store
        self.snapshot_store = snapshot_store
        self.report_store = report_store
        self.view_store = view_store
        self.active_feeds = active_feeds
        self.policy = policy
        self._last: dict[str, tuple[str, str]] = {}    # feed -> (snapshot_id, report_id)

    def scope(self, feed: str) -> Scope | None:
        m = self.market
        if m.source is None:
            return None
        return Scope.of_feed(m.symbol, m.timeframe, m.source, feed)

    def run_feed(self, feed: str, now: datetime) -> str:
        scope = self.scope(feed)
        if scope is None:
            return "fusion:no_source"
        snap = snapshot_at(self.out_store, scope, now, required=self.policy.required)
        report = evaluate(snap, self.policy, now)
        key = (snap.snapshot_id, report.report_id)
        if self._last.get(feed) == key:
            return "fusion:unchanged"
        self.snapshot_store.append(SnapshotRecord.of(snap))
        self.report_store.append(report)
        if report.verdict is QualityVerdict.REJECTED:
            cur = self.view_store.current(scope, now)
            if cur is not None:
                self.view_store.invalidate(cur.market_view_id, at=now, reason=QUALITY_REJECTED,
                                           ref=report.report_id)
                log.info("MarketView %s bị vô hiệu: Quality Gate từ chối (%s)",
                         cur.market_view_id, ",".join(report.reasons))
            self._last[feed] = key
            return "fusion:rejected"
        mv = fuse(snap, report)
        if mv is None:                   # chỉ xảy ra khi REJECTED — đã xử lý ở trên
            raise RuntimeError("Fusion không trả MarketView cho báo cáo không bị từ chối")
        stored = self.view_store.append(mv, report_id=report.report_id, computed_at=now)
        self._last[feed] = key
        return "fusion:stored" if stored else "fusion:unchanged"

    def tick(self, now: datetime) -> dict[str, str]:
        """Việc mỗi nhịp của orchestrator: mọi nguồn giá đang dùng. Lỗi một nguồn không chặn nguồn
        khác (nguồn lỗi không có MarketView mới → MarketView cũ hết hạn → không tín hiệu)."""
        out: dict[str, str] = {}
        for feed in self.active_feeds():
            try:
                out[feed] = self.run_feed(feed, now)
            except Exception:
                log.exception("Fusion lỗi ở nguồn giá %r, thử lại nhịp sau", feed)
                self._last.pop(feed, None)
                out[feed] = "fusion:error"
        return out


def invalidate_handler(runner: FusionRunner):
    """Job ``INVALIDATE_MARKETVIEW`` (output analyst hết hạn mà chưa có kết quả mới — ORC-07):
    tính lại ngay cho nguồn giá bị ảnh hưởng (analyst toàn cục → mọi nguồn) → bắt buộc hết hạn thì
    Gate ``REJECTED`` → vô hiệu MarketView hiện hành nếu còn hạn."""
    from gold_trading.analysts.framework import GLOBAL_SOURCE
    from gold_trading.orchestrator.dispatcher import Handler
    from gold_trading.orchestrator.model import EventType
    from gold_trading.orchestrator.runner import feed_of

    def run(e, now: datetime) -> str | None:
        if e.event_type is not EventType.OUTPUT_EXPIRED:
            raise ValueError("INVALIDATE_MARKETVIEW chỉ nhận sự kiện OUTPUT_EXPIRED")
        parts = e.subject.split(":")
        # Analyst toàn cục (chủ thể "event:GLOBAL::*:*") → mọi nguồn giá; theo nguồn → đúng nguồn.
        feed = None if len(parts) == 5 and parts[1] == GLOBAL_SOURCE else feed_of(e)
        feeds = runner.active_feeds()
        targets = feeds if feed is None else [f for f in feeds if f == feed]
        if not targets:
            return "skipped:feed_inactive"
        res = {f: runner.run_feed(f, now) for f in targets}
        return ";".join(f"{f or '-'}={r}" for f, r in sorted(res.items()))

    return Handler(HANDLER_VERSION, run, deadline=timedelta(seconds=30), max_attempts=3,
                   fatal=(ValueError,))
