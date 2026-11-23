"""Mốc so sánh của protocol-1 mục 6 (GĐ6 bước 6; thiết kế 39 mục 11).

1. **Mốc ngẫu nhiên** (bắt buộc, T4): vào lệnh tại các thời điểm **ngẫu nhiên** trong cùng giờ
   phiên (P3), cùng số lệnh (hiệu chỉnh, xem dưới), cùng tỷ lệ mua / bán, cùng SL / TP / hòa vốn /
   đóng 16:45 — đi qua **đúng** tầng 2 (Risk, hạn mức, chặn tin, lịch… như chiến lược). Bỏ các bộ
   lọc của chiến lược (V3 điểm, V4 cờ, V6 khoảng cách EMA20) — hướng do bốc thăm. Lặp ``runs`` lần
   (protocol: 1.000), mỗi lần một hạt giống suy ra từ hạt giống gốc → chạy lại ra đúng kết quả.
   Thời điểm được bốc = mốc đóng nến trong giờ phiên có MarketView của tầng 1 (tức có dữ liệu đủ
   chất lượng, có ATR) **và** có nến bắt đầu ngay lúc đó (có giá để khớp). Nhiều lần bốc rơi vào
   lúc đang có lệnh / nghỉ 30 phút / đủ 4 lệnh ngày → số lệnh **thực khớp** ít hơn số bốc. Để
   "cùng số lệnh" (protocol-1), **hiệu chỉnh trước** số lần bốc ``k``: chạy thử ``CALIB_RUNS`` hạt
   giống riêng, k ← ⌈n × k / trung vị số lệnh khớp⌉, tối đa ``CALIB_ROUNDS`` vòng (lỗi tìm được
   khi soát 23/11: bốc 248 → khớp ~137). Các lần bốc vẫn rải đều cả kỳ (không cắt sớm). Báo cáo
   in k, n, trung vị.
2. **Mốc không lọc**: chiến lược bỏ V3–V6 (vào mỗi khi có hướng, mọi giờ thị trường mở).
3. **Tham chiếu** (chỉ để đọc): không giao dịch = 0; mua – giữ = % thay đổi giá cả kỳ.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, time
from decimal import Decimal

from gold_trading.backtest import stats as S
from gold_trading.backtest.metrics import trades_of
from gold_trading.backtest.simulate import (
    Bars,
    HistoricalView,
    HistoricalViews,
    SimConfig,
    simulate,
)
from gold_trading.common.enums import Bias
from gold_trading.strategy.trend_m15 import Params, in_session

BIG = Decimal(10) ** 9
CALIB_RUNS = 5
CALIB_ROUNDS = 8
CALIB_OFFSET = 10**6          # chỉ số lần chạy dùng để hiệu chỉnh (không trùng lần chạy thật)


def no_filter_params(p: Params) -> Params:
    """Bỏ V3 (điểm), V4 (cờ của chiến lược), V5 (giờ — còn lại: thị trường mở + Risk), V6 (EMA20).
    Giữ SL / TP / hòa vốn / đóng 16:45 / một lệnh một lúc / nghỉ sau khi đóng."""
    return replace(p, min_confidence=0.0, blocked_flags=frozenset(),
                   session_start=time(0, 0), session_end=time.max, friday_end=time.max,
                   max_ema_gap_atr=BIG)


def random_entry_params(p: Params) -> Params:
    """Mốc ngẫu nhiên: giữ giờ phiên P3 + mọi luật quản lý lệnh; bỏ V3, V4, V6."""
    return replace(p, min_confidence=0.0, blocked_flags=frozenset(), max_ema_gap_atr=BIG)


def run_seed(seed: int, i: int) -> int:
    """Hạt giống của lần ``i`` — cố định theo (gốc, i), không phụ thuộc thứ tự chạy song song."""
    return int.from_bytes(hashlib.sha256(f"{seed}:{i}".encode()).digest()[:8], "big")


def eligible_times(bars: Bars, chain: Sequence[HistoricalView], p: Params,
                   start: datetime, end: datetime) -> list[HistoricalView]:
    """MarketView tầng 1 tại mốc đóng nến trong giờ phiên, có ATR, có nến bắt đầu lúc đó."""
    out = []
    for v in chain:
        t = v.computed_at
        if not (start < t <= end) or not in_session(t, p):
            continue
        atr = v.technical.get("atr14")
        if atr is None or float(atr) <= 0 or bars.starting_at(t) is None:
            continue
        out.append(v)
    return out


def random_views(pool: Sequence[HistoricalView], n: int, long_share: float,
                 rng: random.Random) -> list[HistoricalView]:
    """Bốc ``n`` thời điểm (không lặp) + gán đúng ``round(n × long_share)`` lệnh mua, xáo trộn.
    MarketView giữ nguyên (cờ, hạn, chất lượng) — chỉ đổi hướng và điểm (để chiến lược không
    lọc theo điểm); Technical giữ ATR thật, EMA20 không còn tác dụng (V6 đã bỏ)."""
    if n <= 0 or not pool:
        return []
    n = min(n, len(pool))
    picks = sorted(rng.sample(range(len(pool)), n))
    k = round(n * long_share)
    sides = [Bias.LONG] * k + [Bias.SHORT] * (n - k)
    rng.shuffle(sides)
    out = []
    for idx, side in zip(picks, sides, strict=True):
        v = pool[idx]
        nv = v.view.model_copy(update={"bias": side, "confidence": 1.0,
                                       "market_view_id": f"rnd:{v.view.market_view_id}"})
        out.append(HistoricalView(nv, v.computed_at, v.technical, v.invalidated_at))
    return out


@dataclass(frozen=True)
class RandomRun:
    seed: int
    drawn: int
    trades: int
    expectancy_r: float | None


@dataclass(frozen=True)
class RandomBaseline:
    runs: tuple[RandomRun, ...]
    root_seed: int
    p95_expectancy_r: float | None             # T4: chiến lược phải vượt số này
    target_trades: int = 0                     # số lệnh của chiến lược (n)
    draws: int = 0                             # số lần bốc sau hiệu chỉnh (k)

    @property
    def median_trades(self) -> float | None:
        return S.percentile([r.trades for r in self.runs], 0.5)


def _one(bars: Bars, pool, cfg: SimConfig, start, end, n, long_share, root, i) -> RandomRun:
    s = run_seed(root, i)
    views = random_views(pool, n, long_share, random.Random(s))
    res = simulate(bars, HistoricalViews(views, _scope_of(pool)), cfg, start, end)
    tr = trades_of(res)
    return RandomRun(s, len(views), len(tr), S.mean([t.r for t in tr]))


def _scope_of(pool: Sequence[HistoricalView]):
    from gold_trading.analysts.framework import Scope
    v = pool[0].view
    return Scope.of_feed(v.symbol, v.timeframe, v.source, v.feed_id)


def random_baseline(bars: Bars, chain: Sequence[HistoricalView], cfg: SimConfig,
                    start: datetime, end: datetime, *, n_trades: int, long_share: float,
                    runs: int = 1000, root_seed: int, workers: int = 1) -> RandomBaseline:
    """Chạy mốc ngẫu nhiên ``runs`` lần. ``cfg.params`` = tổ hợp đang so (SL / TP của nó); bộ lọc
    V3 / V4 / V6 tự bỏ. ``workers`` > 1 → chạy song song (fork), kết quả **giống hệt** chạy tuần tự.
    Lần chạy không có lệnh nào → kỳ vọng ``None``, không tính vào phân vị (báo cáo đếm riêng)."""
    rcfg = replace(cfg, params=random_entry_params(cfg.params))
    pool = eligible_times(bars, chain, rcfg.params, start, end)
    if not pool or n_trades <= 0:
        return RandomBaseline((), root_seed, None)
    _ = bars.spreads                                   # dựng trước khi fork (dùng chung)
    k = calibrate_draws(bars, pool, rcfg, start, end, n_trades, long_share, root_seed)
    if workers <= 1:
        out = [_one(bars, pool, rcfg, start, end, k, long_share, root_seed, i)
               for i in range(runs)]
    else:
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor

        global _CTX
        _CTX = (bars, pool, rcfg, start, end, k, long_share, root_seed)
        with ProcessPoolExecutor(workers, mp_context=mp.get_context("fork")) as ex:
            out = list(ex.map(_worker, range(runs), chunksize=max(1, runs // (workers * 4))))
        _CTX = None
    vals = [r.expectancy_r for r in out if r.expectancy_r is not None]
    return RandomBaseline(tuple(out), root_seed, S.percentile(vals, 0.95), n_trades, k)


def calibrate_draws(bars: Bars, pool, cfg: SimConfig, start, end, n: int, long_share: float,
                    root: int) -> int:
    """Số lần bốc ``k`` để trung vị số lệnh thực khớp ≈ ``n`` (xem đầu file). Không vượt kích
    thước kho thời điểm; số lệnh khớp = 0 ở mọi lần thử → giữ k hiện tại (không chia cho 0)."""
    k = min(n, len(pool))
    for rnd in range(CALIB_ROUNDS):
        got = [_one(bars, pool, cfg, start, end, k, long_share, root,
                    CALIB_OFFSET + rnd * CALIB_RUNS + j).trades for j in range(CALIB_RUNS)]
        med = S.percentile(got, 0.5)
        if not med or abs(med - n) <= max(1, 0.05 * n) or k >= len(pool):
            break
        k = min(len(pool), max(1, -(-n * k // int(med)) if med >= 1 else k * 2))
    return k


_CTX = None


def _worker(i: int) -> RandomRun:
    assert _CTX is not None
    bars, pool, cfg, start, end, n, ls, root = _CTX
    return _one(bars, pool, cfg, start, end, n, ls, root, i)


def buy_and_hold_pct(bars: Bars, start: datetime, end: datetime) -> float | None:
    """% thay đổi giá bid từ giá mở nến đầu tới giá đóng nến cuối trong (start, end] — chỉ đọc."""
    bs = bars.closed_between(start, end)
    if not bs or bs[0].open <= 0:
        return None
    return float((bs[-1].close - bs[0].open) / bs[0].open)
