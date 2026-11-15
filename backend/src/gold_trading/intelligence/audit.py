"""Kiểm Gate GĐ4 trên dữ liệu thật — CHỈ ĐỌC (bước 7; lệnh ``cli kiem-mv``).

Với mỗi MarketView tính trong khoảng thời gian:
1. Dựng lại snapshot từ manifest (``rebuild``) — thiếu output / ghi sau / lệch nội dung → lỗi.
2. Tính lại Quality Gate tại đúng lúc đánh giá → phải ra **đúng** báo cáo đã lưu.
3. Tính lại Fusion từ snapshot dựng lại + báo cáo → phải ra **đúng** MarketView đã lưu
   (so mọi trường; ``as_of`` / ``expires_at`` kiểm theo luật hạn).
Thêm: độ phủ — trong giờ thị trường mở (theo lịch broker), bao nhiêu phút có MarketView còn hiệu
lực; khoảng trống ≥ 30 phút; lý do vô hiệu; phân bố nghiêng. Không ghi gì vào DB.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from gold_trading.intelligence.fusion import FUSION_VERSION, MAX_TTL, fuse
from gold_trading.intelligence.quality_gate import POLICY_V1, evaluate
from gold_trading.intelligence.snapshot_builder import SnapshotRebuildError, rebuild
from gold_trading.market.hours import REFERENCE

GAP_REPORT = timedelta(minutes=30)
LOOKBACK = timedelta(hours=1)       # MarketView tính trước ``since`` vẫn có thể đang hiệu lực
_IGNORED = {"as_of", "expires_at"}


@dataclass
class FeedCoverage:
    open_minutes: int = 0
    covered_minutes: int = 0
    gaps: list[tuple[datetime, datetime]] = field(default_factory=list)


@dataclass
class AuditResult:
    since: datetime
    now: datetime
    checked: int = 0
    skipped_version: int = 0
    errors: list[str] = field(default_factory=list)
    bias: Counter = field(default_factory=Counter)
    invalidations: Counter = field(default_factory=Counter)
    coverage: dict[str, FeedCoverage] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def _scope_key(v) -> str:
    return f"{v.source}:{v.feed_id}:{v.symbol}:{v.timeframe}"


def check_view(sv, snapshots, reports, outs) -> str | None:
    """Lỗi đầu tiên (chuỗi ngắn) hoặc None nếu tái dựng khớp hoàn toàn."""
    v = sv.view
    rec = snapshots.get(v.snapshot_id)
    if rec is None:
        return "thiếu snapshot"
    try:
        snap = rebuild(rec, outs)
    except SnapshotRebuildError as e:
        return f"không tái dựng được snapshot ({e})"
    rep = reports.get(sv.report_id)
    if rep is None:
        return "thiếu báo cáo Quality Gate"
    if rep.snapshot_id != snap.snapshot_id:
        return "báo cáo Gate không thuộc snapshot"
    if evaluate(snap, POLICY_V1, rep.evaluated_at) != rep:
        return "tính lại Quality Gate ra kết quả khác"
    again = fuse(snap, rep)
    if again is None:
        return "Gate từ chối nhưng vẫn có MarketView"
    if again.model_dump(exclude=_IGNORED) != v.model_dump(exclude=_IGNORED):
        return "tính lại Fusion ra MarketView khác"
    if v.as_of < rep.evaluated_at or v.as_of > sv.computed_at:
        return "thời điểm MarketView sai"
    if v.expires_at != min(snap.expires_at, v.as_of + MAX_TTL):
        return "hạn MarketView sai"
    if any(o.as_of > v.as_of for o in snap.analyst_outputs):
        return "nhìn trước tương lai"
    return None


def _valid_at(rows, t: datetime) -> bool:
    """Như ``current``: bản mới nhất đã biết tại ``t``, còn hạn, chưa bị vô hiệu tới ``t``."""
    known = [r for r in rows if r.computed_at <= t]
    if not known:
        return False
    r = max(known, key=lambda x: (x.view.as_of, x.computed_at, x.view.market_view_id))
    if r.invalidated_at is not None and r.invalidated_at <= t:
        return False
    return r.view.as_of <= t < r.view.expires_at


def audit(views, snapshots, reports, outs, *, since: datetime, now: datetime,
          calendar=REFERENCE, step: timedelta = timedelta(minutes=1)) -> AuditResult:
    res = AuditResult(since=since, now=now)
    rows = views.computed_between(since - LOOKBACK, now)
    for sv in rows:
        if sv.invalidated_at is not None:
            res.invalidations[sv.reason or "?"] += 1
        if sv.computed_at <= since:
            continue
        v = sv.view
        if v.model_version != FUSION_VERSION or v.quality_policy_version != POLICY_V1.version:
            res.skipped_version += 1
            continue
        res.checked += 1
        res.bias[v.bias.value] += 1
        err = check_view(sv, snapshots, reports, outs)
        if err is not None:
            res.errors.append(f"{v.market_view_id}: {err}")

    by_feed: dict[str, list] = {}
    for sv in rows:
        by_feed.setdefault(_scope_key(sv.view), []).append(sv)
    for key, feed_rows in sorted(by_feed.items()):
        cov = FeedCoverage()
        gap_start: datetime | None = None
        t = since
        while t < now:
            if calendar.is_open(t):
                cov.open_minutes += 1
                if _valid_at(feed_rows, t):
                    cov.covered_minutes += 1
                    if gap_start is not None and t - gap_start >= GAP_REPORT:
                        cov.gaps.append((gap_start, t))
                    gap_start = None
                elif gap_start is None:
                    gap_start = t
            t += step
        if gap_start is not None and now - gap_start >= GAP_REPORT:
            cov.gaps.append((gap_start, now))
        res.coverage[key] = cov
    return res


def render(res: AuditResult) -> list[str]:
    out = [f"Kiểm MarketView từ {res.since:%Y-%m-%d %H:%M} đến {res.now:%Y-%m-%d %H:%M} UTC "
           "(chỉ đọc)."]
    if not res.coverage and not res.checked:
        out.append("Chưa có MarketView nào trong khoảng này.")
    out.append(f"Đã kiểm {res.checked} MarketView (dựng lại snapshot + tính lại Gate + Fusion); "
               f"bỏ qua {res.skipped_version} bản phiên bản cũ.")
    if res.errors:
        out.append(f"LỖI: {len(res.errors)} MarketView không tái dựng khớp:")
        out += [f"  - {e}" for e in res.errors[:20]]
    else:
        out.append("Tái dựng: khớp 100 %.")
    if res.bias:
        out.append("Nghiêng: " + ", ".join(f"{k} {n}" for k, n in sorted(res.bias.items())))
    if res.invalidations:
        out.append("Vô hiệu: " + ", ".join(f"{k} {n}" for k, n in
                                           sorted(res.invalidations.items())))
    for key, cov in res.coverage.items():
        pct = 100.0 * cov.covered_minutes / cov.open_minutes if cov.open_minutes else 0.0
        out.append(f"Nguồn {key}: thị trường mở {cov.open_minutes} phút, có MarketView "
                   f"{cov.covered_minutes} phút ({pct:.1f} %).")
        for a, b in cov.gaps[:10]:
            out.append(f"  khoảng trống {a:%m-%d %H:%M} → {b:%m-%d %H:%M} UTC "
                       f"({int((b - a).total_seconds() // 60)} phút)")
    out.append("Gửi toàn bộ nội dung này cho người phát triển.")
    return out
