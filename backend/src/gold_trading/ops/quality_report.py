"""Báo cáo ngưỡng R3 / R5 trên dữ liệu thật (GĐ3 bước 7c — TEC-05). Chỉ đọc, không đổi ngưỡng.

Thiết kế: ``docs/thiet-ke/03-technical-analyst.md`` §11. Với mỗi nến M15 vàng của một nguồn giá,
tính đúng như cổng chất lượng của Technical (``market/quality.py``) trên cửa sổ 300 nến **kết thúc ở
nến đó** (không nhìn trước):

- R3: ``biên độ / trung vị biên độ`` và ``|open − close trước| / trung vị biên độ`` (ngưỡng 8×).
- R5: ``spread / trung vị spread`` (ngưỡng 3×).

Ra phân bố (p50 / p90 / p99 / lớn nhất), số lần chạm ngưỡng mỗi ngày, và danh sách lần chạm R3 kèm
**có trùng cửa sổ công bố số liệu không** (lịch kinh tế GĐ1) — trùng → nhiều khả năng biến động
thật; không trùng → cần đối chiếu biểu đồ MT5 (có thể lỗi feed). Người dùng / người phát triển
quyết đổi ngưỡng; báo cáo không tự đổi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median

from gold_trading.contracts.candle import Candle
from gold_trading.market.quality import SPIKE_MULTIPLE, WIDE_SPREAD_MULTIPLE

WINDOW = 300


@dataclass
class Event:
    open_time: datetime
    kind: str            # RANGE / JUMP / SPREAD
    ratio: float
    in_release_window: bool | None = None


@dataclass
class Report:
    bars: int
    first: datetime | None
    last: datetime | None
    range_ratios: list[float] = field(default_factory=list)
    jump_ratios: list[float] = field(default_factory=list)
    spread_ratios: list[float] = field(default_factory=list)
    r3: list[Event] = field(default_factory=list)
    r5: list[Event] = field(default_factory=list)

    @property
    def days(self) -> float:
        if not self.first or not self.last:
            return 0.0
        return max((self.last - self.first).total_seconds() / 86400, 1 / 96)


def pct(xs: list[float], q: float) -> float | None:
    """Phân vị kiểu "gần nhất phía trên" (không nội suy)."""
    if not xs:
        return None
    s = sorted(xs)
    k = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[k]


def analyze(candles: list[Candle], windows: list[tuple[datetime, datetime]] | None = None,
            since: datetime | None = None) -> Report:
    """``candles``: M15 cũ → mới (gồm nến khởi động phía trước). Chỉ đếm nến có
    ``open_time ≥ since``; nến trước đó chỉ làm cửa sổ trung vị. ``windows``: cửa sổ công bố số
    liệu (đối chiếu R3)."""
    idx = [i for i, c in enumerate(candles) if since is None or c.open_time >= since]
    rep = Report(len(idx), candles[idx[0]].open_time if idx else None,
                 candles[idx[-1]].open_time if idx else None)
    for i in idx:
        lo = max(0, i - WINDOW + 1)
        win = candles[lo:i + 1]
        if len(win) < 50:                 # quá ít nến → trung vị chưa ổn định, bỏ
            continue
        med = median(c.high - c.low for c in win)
        c = candles[i]
        if med > 0:
            rr = (c.high - c.low) / med
            rep.range_ratios.append(rr)
            if i > 0:
                jr = abs(c.open - candles[i - 1].close) / med
                rep.jump_ratios.append(jr)
                if jr > SPIKE_MULTIPLE:
                    rep.r3.append(Event(c.open_time, "JUMP", round(jr, 2)))
            if rr > SPIKE_MULTIPLE:
                rep.r3.append(Event(c.open_time, "RANGE", round(rr, 2)))
        spreads = [x.spread_points for x in win if x.spread_points is not None]
        if c.spread_points is not None and spreads and median(spreads) > 0:
            sr = c.spread_points / median(spreads)
            rep.spread_ratios.append(sr)
            if sr > WIDE_SPREAD_MULTIPLE:
                rep.r5.append(Event(c.open_time, "SPREAD", round(sr, 2)))
    if windows is not None:
        for e in rep.r3:
            end = e.open_time + timedelta(minutes=15)
            e.in_release_window = any(s < end and e.open_time < w for s, w in windows)
    return rep


def render(rep: Report, label: str) -> list[str]:
    L = [f"Nguồn {label}: {rep.bars} nến M15"
         + (f" ({rep.first:%d/%m %H:%M} → {rep.last:%d/%m %H:%M} UTC, ~{rep.days:.1f} ngày)"
            if rep.first else "")]

    def row(name, xs, thr):
        if not xs:
            return f"  {name}: không đủ dữ liệu"
        n = sum(1 for x in xs if x > thr)
        return (f"  {name}: p50 {pct(xs, .5):.2f} · p90 {pct(xs, .9):.2f} · p99 {pct(xs, .99):.2f}"
                f" · lớn nhất {max(xs):.2f} — vượt {thr:g}×: {n} lần ({n / rep.days:.2f}/ngày)")

    L.append(row("R3 biên độ / trung vị", rep.range_ratios, SPIKE_MULTIPLE))
    L.append(row("R3 khoảng nhảy / trung vị", rep.jump_ratios, SPIKE_MULTIPLE))
    L.append(row("R5 spread / trung vị", rep.spread_ratios, WIDE_SPREAD_MULTIPLE))
    if rep.r3:
        L.append("  Các lần chạm R3 (đối chiếu biểu đồ MT5):")
        for e in sorted(rep.r3, key=lambda e: e.open_time)[-15:]:
            tag = ("trùng giờ công bố → nhiều khả năng biến động thật" if e.in_release_window
                   else "KHÔNG trùng giờ công bố → kiểm biểu đồ" if e.in_release_window is False
                   else "")
            L.append(f"    {e.open_time:%d/%m %H:%M} UTC  {e.kind}  {e.ratio}×  {tag}")
    return L
