"""Kiểm Gate GĐ4 trên dữ liệu thật — CHỈ ĐỌC (bước 7; lệnh ``cli kiem-mv``).

Với mỗi MarketView tính trong khoảng thời gian:
1. Dựng lại snapshot từ manifest (``rebuild``) — thiếu output / ghi sau / lệch nội dung → lỗi.
2. Tính lại Quality Gate tại đúng lúc đánh giá → phải ra **đúng** báo cáo đã lưu.
3. Tính lại Fusion từ snapshot dựng lại + báo cáo → phải ra **đúng** MarketView đã lưu
   (so mọi trường; ``as_of`` / ``expires_at`` kiểm theo luật hạn).
Thêm: độ phủ — trong giờ thị trường mở (theo lịch broker), bao nhiêu phút có MarketView còn hiệu
lực; khoảng trống ≥ 30 phút; lý do vô hiệu; phân bố nghiêng. Không ghi gì vào DB.
Thêm (24/11): mọi phút thiếu được chia thành **khoảng thiếu** (dừng ở giờ đóng cửa) có nguyên nhân —
mở lại phiên / hết hạn (kèm analyst giới hạn hạn + lúc có bản sau) / Gate từ chối / bị vô hiệu /
chưa có MarketView — tổng phút các khoảng = phút mở − phút có MarketView; liệt kê khoảng ≥ 5 phút.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from gold_trading.contracts.snapshot import QualityVerdict
from gold_trading.intelligence.fusion import FUSION_VERSION, MAX_TTL, fuse
from gold_trading.intelligence.quality_gate import POLICY_V1, evaluate
from gold_trading.intelligence.snapshot_builder import SnapshotRebuildError, rebuild
from gold_trading.market.hours import REFERENCE

GAP_REPORT = timedelta(minutes=30)
SHORT_GAP_REPORT = timedelta(minutes=5)   # khoảng thiếu từ ngần này trở lên được liệt kê
SHORT_GAP_LIST = 30
LOOKBACK = timedelta(hours=1)       # MarketView tính trước ``since`` vẫn có thể đang hiệu lực
_IGNORED = {"as_of", "expires_at"}

# Nguyên nhân khoảng thiếu (mã → chữ hiển thị)
REOPEN, EXPIRED, GATE_REJECTED, INVALIDATED, NONE_YET = (
    "MO_LAI_PHIEN", "HET_HAN", "GATE_TU_CHOI", "VO_HIEU", "CHUA_CO")
CAUSE_LABEL = {
    REOPEN: "mở lại phiên (chờ nến M15 đầu đóng)",
    EXPIRED: "bản trước hết hạn, bản sau chưa có",
    GATE_REJECTED: "Quality Gate từ chối",
    INVALIDATED: "MarketView bị vô hiệu",
    NONE_YET: "chưa có MarketView nào",
}


@dataclass(frozen=True)
class Hole:
    """Một khoảng liên tục các phút thị trường mở mà không có MarketView hiệu lực.
    ``end``: phút đầu tiên sau khoảng (có lại MarketView / đóng cửa / hết cửa sổ kiểm)."""

    start: datetime
    end: datetime
    minutes: int
    cause: str
    detail: str = ""


@dataclass
class FeedCoverage:
    open_minutes: int = 0
    covered_minutes: int = 0
    gaps: list[tuple[datetime, datetime]] = field(default_factory=list)
    holes: list[Hole] = field(default_factory=list)

    def by_cause(self) -> dict[str, tuple[int, int]]:
        """Nguyên nhân → (số khoảng, tổng phút)."""
        out: dict[str, tuple[int, int]] = {}
        for h in self.holes:
            n, m = out.get(h.cause, (0, 0))
            out[h.cause] = (n + 1, m + h.minutes)
        return out


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


def _latest_known(rows, t: datetime):
    known = [r for r in rows if r.computed_at <= t]
    if not known:
        return None
    return max(known, key=lambda x: (x.view.as_of, x.computed_at, x.view.market_view_id))


def _valid_at(rows, t: datetime) -> bool:
    """Như ``current``: bản mới nhất đã biết tại ``t``, còn hạn, chưa bị vô hiệu tới ``t``."""
    r = _latest_known(rows, t)
    if r is None:
        return False
    if r.invalidated_at is not None and r.invalidated_at <= t:
        return False
    return r.view.as_of <= t < r.view.expires_at


def _limiting(r, snapshots, outs) -> str:
    """Vì sao bản ``r`` hết hạn lúc đó: trần của Fusion hay (các) analyst có hạn sớm nhất."""
    v = r.view
    if v.expires_at == v.as_of + MAX_TTL:
        return "trần 30 phút của Fusion"
    rec = snapshots.get(v.snapshot_id)
    if rec is None:
        return "không rõ (thiếu snapshot)"
    try:
        snap = rebuild(rec, outs)
    except SnapshotRebuildError:
        return "không rõ (không tái dựng được snapshot)"
    names = sorted(o.analyst_id for o in snap.analyst_outputs if o.expires_at == v.expires_at)
    return "hạn của " + ", ".join(names) if names else "không rõ"


def _hole_cause(rows, key: str, start: datetime, end: datetime, reopened: bool,
                reports, snapshots, outs) -> tuple[str, str]:
    """Nguyên nhân của khoảng thiếu [start, end) — chỉ đọc, dùng dữ liệu đã biết tới lúc đó."""
    if reopened:
        return REOPEN, ""
    r = _latest_known(rows, start)
    if r is None:
        return NONE_YET, ""
    if r.invalidated_at is not None and r.invalidated_at <= start:
        return INVALIDATED, r.reason or "?"
    nxt = min((x for x in rows if x.computed_at > start), key=lambda x: x.computed_at,
              default=None)
    # Báo cáo Gate mới nhất trước khi có bản sau (bản sau kèm báo cáo ACCEPTED của chính nó)
    upto = min(end, nxt.computed_at) if nxt is not None else end
    latest = getattr(reports, "latest_for_scope", None)
    rep = latest(key, upto - timedelta(microseconds=1)) if latest else None
    if (rep is not None and rep.report_id != r.report_id and rep.evaluated_at > r.computed_at
            and rep.verdict is QualityVerdict.REJECTED):
        return GATE_REJECTED, ", ".join(rep.reasons[:3])
    after = (f"bản sau as_of {nxt.view.as_of:%H:%M} tính lúc {nxt.computed_at:%H:%M:%S}"
             if nxt is not None else "chưa có bản sau trong cửa sổ kiểm")
    return EXPIRED, (f"bản trước hết hạn {r.view.expires_at:%H:%M:%S} "
                     f"({_limiting(r, snapshots, outs)}); {after}")


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
        hole: list = []                      # [start, số phút mở, mở lại phiên?] hoặc rỗng

        def close_hole(end: datetime, cov=cov, hole=hole, feed_rows=feed_rows, key=key) -> None:
            if hole:
                start, n, reopened = hole
                cause, detail = _hole_cause(feed_rows, key, start, end, reopened,
                                            reports, snapshots, outs)
                cov.holes.append(Hole(start, end, n, cause, detail))
                hole.clear()

        prev_open = calendar.is_open(since - step)
        t = since
        while t < now:
            is_open = calendar.is_open(t)
            if is_open:
                cov.open_minutes += 1
                if _valid_at(feed_rows, t):
                    cov.covered_minutes += 1
                    if gap_start is not None and t - gap_start >= GAP_REPORT:
                        cov.gaps.append((gap_start, t))
                    gap_start = None
                    close_hole(t)
                else:
                    if gap_start is None:
                        gap_start = t
                    if hole:
                        hole[1] += 1
                    else:
                        hole.extend([t, 1, not prev_open])
            else:
                close_hole(t)                # khoảng thiếu dừng ở giờ đóng cửa
            prev_open = is_open
            t += step
        if gap_start is not None and now - gap_start >= GAP_REPORT:
            cov.gaps.append((gap_start, now))
        close_hole(now)
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
        causes = cov.by_cause()
        if causes:
            out.append("  Phút thiếu theo nguyên nhân: " + "; ".join(
                f"{CAUSE_LABEL.get(c, c)} {m} phút ({n} lần)"
                for c, (n, m) in sorted(causes.items(), key=lambda x: -x[1][1])))
        longer = [h for h in cov.holes if h.end - h.start >= SHORT_GAP_REPORT]
        if longer:
            out.append(f"  Khoảng thiếu ≥ {int(SHORT_GAP_REPORT.total_seconds() // 60)} phút "
                       f"({len(longer)}):")
            for h in longer[:SHORT_GAP_LIST]:
                tail = f": {h.detail}" if h.detail else ""
                out.append(f"    {h.start:%m-%d %H:%M} → {h.end:%H:%M} UTC ({h.minutes} phút) — "
                           f"{CAUSE_LABEL.get(h.cause, h.cause)}{tail}")
            if len(longer) > SHORT_GAP_LIST:
                out.append(f"    … và {len(longer) - SHORT_GAP_LIST} khoảng nữa")
    out.append("Gửi toàn bộ nội dung này cho người phát triển.")
    return out
