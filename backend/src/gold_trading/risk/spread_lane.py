"""Làn nhanh — chặn mở lệnh mới khi spread giãn mạnh (GĐ2 bước 4c — FAST-01; DEC-20 câu 2).

Thiết kế + lý do: ``docs/thiet-ke/26-lam-nhanh.md`` mục 4. Tóm tắt:

- Dữ liệu: giá theo giây của **từng nguồn giá** (``quote_seconds``, ING-08), chỉ giây đã biết tại
  lúc xét (``available_at <= now``) — point-in-time.
- **Mốc** = trung vị spread cuối giây trong 60 phút **trước giây bắt đầu giãn** (giữ nguyên suốt
  đợt giãn), cùng nguồn, bỏ giây lịch đóng cửa, cần ≥ ``BASELINE_MIN`` giây.
- **Chặn:** spread lớn nhất trong giây > ``3 ×`` mốc, liên tục (không có giây bình thường xen
  giữa) **≥ 5 giây** → lệnh cấm ``SPREAD`` cho đúng nguồn đó, không có giờ hết.
- **Gỡ:** từ lúc bắt đầu chặn, spread < ``1,5 ×`` mốc **lúc bắt đầu chặn** liên tục ≥ 2 phút, và
  giá còn mới (≤ ``FRESH`` giây) → gỡ. Mốc giữ nguyên lúc chặn (trung vị trượt sẽ bị chính đợt giãn
  kéo lên). Thiếu giá / giá cũ → **không gỡ** (an toàn); giây giãn đến trễ vẫn gây chặn.
- **Chưa đủ mốc** (vừa mở cửa, nguồn mới) mà đang có giá → lệnh cấm ``SPREAD_UNRATED`` (không biết
  spread có bình thường không → chặn), gỡ theo cùng luật khi đã có mốc.
- Gỡ ghi ``lifted_at = now`` (lúc hệ thống biết) — không viết lại quá khứ.
"""

from __future__ import annotations

from bisect import bisect_left, insort
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from gold_trading.market.quotes import BASELINE_MIN, BASELINE_WINDOW, CALENDAR_CLOSED
from gold_trading.risk.blocks import Block, BlockKind, Lift

POLICY_VERSION = "spread-lane-2026.11.14"
WIDE_MULTIPLE = 3.0          # DEC-20 câu 2
WIDE_FOR = timedelta(seconds=5)
CALM_MULTIPLE = 1.5
CALM_FOR = timedelta(minutes=2)
FRESH = timedelta(seconds=10)    # giá mới nhất cũ hơn → không kết luận gì mới
SECOND = timedelta(seconds=1)


@dataclass(frozen=True)
class SpreadCheck:
    feed: str
    status: str                          # WIDE / NORMAL / UNRATED / STALE
    baseline: float | None
    block: Block | None = None           # lệnh cấm mới cần ghi
    lifts: tuple[Lift, ...] = ()         # lệnh cấm cần gỡ


def _visible(rows, now: datetime):
    return sorted((r for r in rows if r.available_at <= now and r.t <= now), key=lambda r: r.t)


def _base_values(rows, t: datetime) -> list[int]:
    return [r.spread_points for r in rows
            if t - BASELINE_WINDOW <= r.t < t and CALENDAR_CLOSED not in r.flags]


def _median_of(values) -> float | None:
    if len(values) < BASELINE_MIN:
        return None
    m = median(values)
    return float(m) if m > 0 else None


def baseline_at(rows, t: datetime) -> float | None:
    """Mốc tại ``t``: trung vị spread cuối giây trong ``[t - 60 phút, t)``, bỏ giây đóng cửa;
    thiếu mẫu / bằng 0 → None. Đợt giãn dùng mốc **tại giây bắt đầu giãn** (giữ nguyên suốt đợt),
    để chính các giây giãn không kéo mốc lên (lỗi tìm được khi soát lại 2026-11-14)."""
    return _median_of(_base_values(rows, t))


def cause_for(feed: str, start_t: datetime) -> str:
    return f"spread:{feed}@{start_t.isoformat()}"[:256]


def _block(feed: str, reason: str, start_t: datetime, start_at: datetime,
           now: datetime) -> Block:
    return Block(BlockKind.SPREAD, feed, reason, start_at, None, cause_for(feed, start_t),
                 now, POLICY_VERSION,
                 latency_ms=int(max((now - start_at).total_seconds(), 0) * 1000))


def _calm_since(rows, limit: float, since: datetime) -> datetime | None:
    """Đầu chuỗi giây cuối cùng (sau ``since``) có spread lớn nhất < ``limit`` liên tục."""
    start = None
    for r in rows:
        if r.t < since:
            continue
        if r.spread_max_points < limit:
            start = start or r.t
        else:
            start = None
    return start


MAX_RUN_LOOKBACK = timedelta(minutes=10)   # đợt giãn dài hơn đã bị chặn từ giây thứ 5
CLEARLY_NORMAL = 2.0


def _wide_run(rows) -> tuple[list, float | None]:
    """Chuỗi giây giãn liên tục tới giây mới nhất: giây đầu ``s`` sớm nhất sao cho **mọi** giây từ
    ``s`` tới giây mới nhất có spread lớn nhất > 3 × mốc tại ``s``. Lùi từng giây, dừng khi gặp
    giây rõ ràng bình thường (≤ ``CLEARLY_NORMAL`` × mốc của nó — chuỗi chứa nó cần mốc sớm hơn
    giảm hơn 1/3 trong vài giây, coi như không xảy ra) hoặc quá ``MAX_RUN_LOOKBACK``. Mốc tính trượt
    bằng danh sách đã sắp (không tính lại cả giờ cho mỗi giây). Trả (chuỗi, mốc tại đầu chuỗi)."""
    n = len(rows)
    if n == 0:
        return [], None
    last = rows[-1]
    # Cửa sổ của giây i: các hàng có t trong [t_i - 60 phút, t_i), không đóng cửa.
    i = n - 1
    lo = n - 1
    while lo > 0 and rows[lo - 1].t >= rows[i].t - BASELINE_WINDOW:
        lo -= 1
    win = sorted(r.spread_points for r in rows[lo:i] if CALENDAR_CLOSED not in r.flags)
    best: int | None = None
    best_base: float | None = None
    suffix_min = None
    while i >= 0 and last.t - rows[i].t <= MAX_RUN_LOOKBACK:
        r = rows[i]
        suffix_min = r.spread_max_points if suffix_min is None else min(suffix_min,
                                                                        r.spread_max_points)
        base = _median_of(win)
        if base is None or r.spread_max_points <= CLEARLY_NORMAL * base:
            break                     # giây rõ ràng bình thường: chuỗi không thể bắt đầu sớm hơn
        if suffix_min > WIDE_MULTIPLE * base:
            best, best_base = i, base
        # sang giây i-1: bỏ hàng i-1 khỏi cửa sổ, thêm các hàng có t >= t_{i-1} - 60 phút
        if i == 0:
            break
        prev = rows[i - 1]
        if CALENDAR_CLOSED not in prev.flags:
            del win[bisect_left(win, prev.spread_points)]
        while lo > 0 and rows[lo - 1].t >= prev.t - BASELINE_WINDOW:
            lo -= 1
            if CALENDAR_CLOSED not in rows[lo].flags:
                insort(win, rows[lo].spread_points)
        i -= 1
    if best is None:
        return [], None
    return rows[best:], best_base


def check_feed(feed: str, rows, open_blocks, now: datetime) -> SpreadCheck:
    """Một lần xét cho một nguồn giá.

    ``rows``: giây của nguồn trong ít nhất ``[now - 60 phút - vài phút, now]`` (đọc từ store).
    ``open_blocks``: lệnh cấm ``SPREAD`` chưa gỡ của nguồn (``BlockStore.open_spread``)."""
    rows = _visible(rows, now)
    mine = [b for b in open_blocks if b.scope == feed and b.kind is BlockKind.SPREAD]
    if not rows:
        return SpreadCheck(feed, "STALE", None)            # không có giá: không kết luận gì
    last = rows[-1]
    # Giá cũ (nguồn trễ / mất kết nối): không gỡ, không kết luận "chưa đủ mốc"; nhưng bằng
    # chứng giãn (dù đến trễ) vẫn chặn — hướng an toàn.
    stale = now - last.t > FRESH

    # ---- gỡ (xét trước): mốc lúc bắt đầu chặn, yên ≥ 2 phút sau lúc bắt đầu chặn
    lifts = []
    for b in ([] if stale else mine):
        base = (baseline_at(rows, b.start_at - WIDE_FOR) if b.reason_code == "SPREAD_WIDE"
                else None)
        if base is None:
            base = baseline_at(rows, now)                  # chặn vì chưa đủ mốc → mốc hiện tại
        if base is None:
            continue
        calm = _calm_since(rows, CALM_MULTIPLE * base, b.start_at)
        if calm is not None and last.t + SECOND - calm >= CALM_FOR:
            lifts.append(Lift(b.block_id, now, "SPREAD_NORMAL"))
    still_open = [b for b in mine if b.block_id not in {x.block_id for x in lifts}]

    # ---- chặn mới: chuỗi giây giãn liên tục ở cuối
    run, run_base = _wide_run(rows)
    status = "NORMAL"
    block = None
    if run:
        status = "WIDE"
        first = run[0]
        if last.t + SECOND - first.t >= WIDE_FOR and not still_open:
            block = _block(feed, "SPREAD_WIDE", first.t, first.t + WIDE_FOR, now)
        base_now = run_base
    else:
        base_now = baseline_at(rows, last.t + SECOND)
        if stale:
            status = "STALE"
        elif base_now is None:
            status = "UNRATED"
            if not still_open:
                block = _block(feed, "SPREAD_UNRATED", last.t, last.t, now)
    return SpreadCheck(feed, status, base_now, block, tuple(lifts))


def apply(check: SpreadCheck, block_store) -> None:
    """Ghi kết quả (idempotent: lệnh cấm theo nguyên nhân, gỡ một lần)."""
    for x in check.lifts:
        block_store.lift(x)
    if check.block is not None:
        block_store.add(check.block)
