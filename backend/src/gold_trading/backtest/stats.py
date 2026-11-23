"""Thống kê cho báo cáo backtest (GĐ6 bước 6 — protocol-1 mục 5–6; thiết kế 39 mục 11).

Hàm **thuần**, chỉ thư viện chuẩn (không numpy). Tiền tính ở nơi khác bằng ``Decimal``; ở đây là
thống kê → ``float``. Đầu vào rỗng / không đủ → ``None`` ("không đủ dữ liệu"), không đoán.

Không con số nào ở đây là "xác suất thắng" hay "độ tin cậy dự báo". ``deflated_sharpe`` trả xác
suất **theo mô hình của Bailey & López de Prado** rằng Sharpe thật > 0 sau khi trừ hiệu ứng thử
nhiều lần — chỉ dùng cho tiêu chí T5.

Tham chiếu:
- Bailey, D. H. & López de Prado, M. (2014). *The Deflated Sharpe Ratio: Correcting for Selection
  Bias, Backtest Overfitting and Non-Normality.* Journal of Portfolio Management 40(5).
- Bailey, D. H., Borwein, J., López de Prado, M. & Zhu, Q. J. (2017). *The Probability of Backtest
  Overfitting.* Journal of Computational Finance 20(4). (CSCV)
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from statistics import NormalDist

EULER_GAMMA = 0.5772156649015329
_N = NormalDist()


# ---------------------------------------------------------------------- cơ bản


def mean(xs: Sequence[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def stdev(xs: Sequence[float]) -> float | None:
    """Độ lệch chuẩn mẫu (chia n − 1). < 2 phần tử → None."""
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def percentile(xs: Sequence[float], q: float) -> float | None:
    """Phân vị ``q`` ∈ [0, 1], nội suy tuyến tính giữa hai phần tử (như numpy 'linear')."""
    if not xs or not 0 <= q <= 1:
        return None
    s = sorted(xs)
    pos = q * (len(s) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def sharpe(returns: Sequence[float]) -> float | None:
    """Sharpe **theo kỳ** (không năm hóa, lãi suất phi rủi ro = 0): trung bình / độ lệch chuẩn.
    Độ lệch chuẩn 0 → None (không xác định — không trả vô cực)."""
    sd = stdev(returns)
    if sd is None or sd == 0:
        return None
    return sum(returns) / len(returns) / sd


def skewness(xs: Sequence[float]) -> float | None:
    """Độ lệch (moment chuẩn hóa bậc 3, kiểu tổng thể — như trong công thức DSR)."""
    n = len(xs)
    if n < 3:
        return None
    m = sum(xs) / n
    m2 = sum((x - m) ** 2 for x in xs) / n
    if m2 == 0:
        return None
    return sum((x - m) ** 3 for x in xs) / n / m2 ** 1.5


def kurtosis(xs: Sequence[float]) -> float | None:
    """Độ nhọn **không trừ 3** (phân phối chuẩn = 3) — đúng dạng γ4 trong DSR."""
    n = len(xs)
    if n < 4:
        return None
    m = sum(xs) / n
    m2 = sum((x - m) ** 2 for x in xs) / n
    if m2 == 0:
        return None
    return sum((x - m) ** 4 for x in xs) / n / m2 ** 2


# ---------------------------------------------------------------------- chỉ số giao dịch


def profit_factor(pnls: Sequence[float]) -> float | None:
    """Tổng lãi / |tổng lỗ|. Không có lệnh lỗ → None (không xác định, không trả vô cực)."""
    win = sum(p for p in pnls if p > 0)
    loss = -sum(p for p in pnls if p < 0)
    if not pnls or loss == 0:
        return None
    return win / loss


def win_rate(pnls: Sequence[float]) -> float | None:
    """Tỷ lệ lệnh có lãi ròng > 0 (quá khứ — không phải "xác suất thắng")."""
    return sum(1 for p in pnls if p > 0) / len(pnls) if pnls else None


def longest_losing_streak(pnls: Sequence[float]) -> int:
    """Chuỗi lệnh lỗ ròng (< 0) liên tiếp dài nhất. Lệnh hòa (= 0) cắt chuỗi."""
    best = cur = 0
    for p in pnls:
        cur = cur + 1 if p < 0 else 0
        best = max(best, cur)
    return best


def max_drawdown(equity: Sequence[float]) -> float | None:
    """Sụt giảm lớn nhất theo **tỷ lệ** từ đỉnh trước đó: max (đỉnh − đáy) / đỉnh. Đỉnh ≤ 0 →
    None (không định nghĩa được theo tỷ lệ)."""
    if not equity:
        return None
    peak = equity[0]
    worst = 0.0
    for e in equity:
        if e > peak:
            peak = e
        if peak <= 0:
            return None
        worst = max(worst, (peak - e) / peak)
    return worst


# ---------------------------------------------------------------------- bootstrap theo khối ngày


@dataclass(frozen=True)
class BootstrapCI:
    estimate: float
    low: float
    high: float
    n_resamples: int
    seed: int


def block_bootstrap_mean_per_trade(days: Sequence[Sequence[float]], *, n_resamples: int = 10_000,
                                   seed: int, level: float = 0.95) -> BootstrapCI | None:
    """Khoảng tin cậy của **kỳ vọng / lệnh** bằng bootstrap theo khối ngày giao dịch.

    ``days``: mỗi phần tử = các kết quả (R hoặc tiền) của những lệnh **đóng trong ngày đó** (ngày
    không có lệnh vẫn có thể có mặt, là danh sách rỗng). Mỗi lần lấy mẫu lại có hoàn lại đúng
    ``len(days)`` ngày, kỳ vọng / lệnh = tổng / số lệnh của mẫu. Mẫu không có lệnh nào bị bỏ (đếm
    vào ``n_resamples`` thực tế). Giữ tương quan giữa các lệnh cùng ngày."""
    total = sum(len(d) for d in days)
    if total < 2 or not 0 < level < 1:
        return None
    sums = [sum(d) for d in days]
    counts = [len(d) for d in days]
    rng = random.Random(seed)
    k = len(days)
    stats: list[float] = []
    for _ in range(n_resamples):
        s = c = 0
        for _ in range(k):
            i = rng.randrange(k)
            s += sums[i]
            c += counts[i]
        if c:
            stats.append(s / c)
    if not stats:
        return None
    a = (1 - level) / 2
    lo, hi = percentile(stats, a), percentile(stats, 1 - a)
    assert lo is not None and hi is not None
    return BootstrapCI(sum(sums) / total, lo, hi, len(stats), seed)


# ---------------------------------------------------------------------- Deflated Sharpe (2014)


def expected_max_sharpe(n_trials: int, var_sharpe: float) -> float | None:
    """SR0: Sharpe lớn nhất **kỳ vọng** khi thử ``n_trials`` lần mà Sharpe thật = 0 (phương sai
    Sharpe giữa các lần thử = ``var_sharpe``) — công thức (Bailey & López de Prado 2014)::

        SR0 = √V · [(1 − γ) Φ⁻¹(1 − 1/N) + γ Φ⁻¹(1 − 1/(N·e))]
    """
    if n_trials < 2 or var_sharpe < 0:
        return None
    a = _N.inv_cdf(1 - 1 / n_trials)
    b = _N.inv_cdf(1 - 1 / (n_trials * math.e))
    return math.sqrt(var_sharpe) * ((1 - EULER_GAMMA) * a + EULER_GAMMA * b)


def probabilistic_sharpe(sr: float, sr_benchmark: float, n_obs: int, skew: float,
                         kurt: float) -> float | None:
    """PSR: Φ[(SR − SR*)·√(T − 1) / √(1 − γ3·SR + (γ4 − 1)/4 · SR²)]. Sharpe theo kỳ,
    ``kurt`` không trừ 3."""
    if n_obs < 2:
        return None
    den = 1 - skew * sr + (kurt - 1) / 4 * sr * sr
    if den <= 0:
        return None
    return _N.cdf((sr - sr_benchmark) * math.sqrt(n_obs - 1) / math.sqrt(den))


def deflated_sharpe(sr: float, n_obs: int, skew: float, kurt: float, *, n_trials: int,
                    var_sharpe: float) -> float | None:
    """DSR = PSR với mốc SR0 (``expected_max_sharpe``). Mọi Sharpe **cùng kỳ** (ngày)."""
    sr0 = expected_max_sharpe(n_trials, var_sharpe)
    if sr0 is None:
        return None
    return probabilistic_sharpe(sr, sr0, n_obs, skew, kurt)


# ---------------------------------------------------------------------- PBO bằng CSCV (2017)


@dataclass(frozen=True)
class PboResult:
    pbo: float
    n_splits: int
    n_blocks: int
    n_strategies: int


def _block_sharpe(sums: Sequence[float], sqs: Sequence[float], n: int) -> float:
    """Sharpe từ tổng và tổng bình phương (một cấu hình trên tập khối). Độ lệch chuẩn 0 →
    ±∞ theo dấu trung bình (0 nếu trung bình 0) — chỉ dùng để **xếp hạng** trong CSCV."""
    s, q = sum(sums), sum(sqs)
    m = s / n
    var = (q - n * m * m) / (n - 1) if n > 1 else 0.0
    if var <= 1e-18:
        return 0.0 if m == 0 else math.copysign(math.inf, m)
    return m / math.sqrt(var)


def pbo_cscv(returns: Mapping[str, Sequence[float]], n_blocks: int = 16) -> PboResult | None:
    """Xác suất khớp quá mức (PBO) bằng CSCV.

    ``returns``: cấu hình → chuỗi lợi nhuận **cùng các kỳ** (ví dụ ngày), cùng độ dài. Chia T kỳ
    thành ``n_blocks`` khối liền nhau bằng nhau (bỏ phần dư ở **đầu** chuỗi để mọi khối bằng nhau —
    ghi trong báo cáo). Với mọi cách chọn một nửa số khối làm "trong mẫu" (IS) và phần còn lại làm
    "ngoài mẫu" (OOS): cấu hình có Sharpe IS cao nhất → hạng tương đối ω trong OOS (hạng 1..N tăng
    dần, hòa lấy hạng trung bình; ω = hạng / (N + 1)); λ = ln(ω / (1 − ω)). PBO = tỷ lệ λ ≤ 0.
    Hòa ở IS → chọn cấu hình xếp trước theo tên (cố định, không ngẫu nhiên)."""
    names = sorted(returns)
    if len(names) < 2 or n_blocks < 2 or n_blocks % 2:
        return None
    t = len(returns[names[0]])
    if any(len(returns[k]) != t for k in names):
        return None
    size = t // n_blocks
    if size < 2:
        return None
    start = t - size * n_blocks
    sums = {k: [] for k in names}
    sqs = {k: [] for k in names}
    for k in names:
        r = returns[k]
        for b in range(n_blocks):
            seg = r[start + b * size: start + (b + 1) * size]
            sums[k].append(sum(seg))
            sqs[k].append(sum(x * x for x in seg))
    n = len(names)
    below = total = 0
    all_blocks = range(n_blocks)
    for is_set in combinations(all_blocks, n_blocks // 2):
        oos_set = [b for b in all_blocks if b not in is_set]
        n_is, n_oos = size * len(is_set), size * len(oos_set)
        is_perf = [_block_sharpe([sums[k][b] for b in is_set], [sqs[k][b] for b in is_set], n_is)
                   for k in names]
        best = max(range(n), key=lambda i: (is_perf[i], -i))
        oos = [_block_sharpe([sums[k][b] for b in oos_set], [sqs[k][b] for b in oos_set], n_oos)
               for k in names]
        v = oos[best]
        less = sum(1 for x in oos if x < v)
        equal = sum(1 for x in oos if x == v)
        rank = less + (equal + 1) / 2                 # hạng trung bình khi hòa (1..N)
        w = rank / (n + 1)
        if math.log(w / (1 - w)) <= 0:
            below += 1
        total += 1
    return PboResult(below / total, total, n_blocks, n)
