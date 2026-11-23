"""Chấm tiêu chí T1–T8 của ``protocol-1`` (GĐ6 bước 8 — BT-04, 6-C05; thiết kế 38 mục 7,
thiết kế 39 mục 12).

Luật ghi **trước khi có kết quả** (23/11):

- Kỳ vọng / lệnh tính theo **R** (lãi ròng ÷ rủi ro đã duyệt lúc khớp), sau chi phí.
- **Thiếu bất kỳ số nào** để chấm một tiêu chí → tiêu chí đó **KHÔNG ĐẠT** (ghi "không đủ dữ liệu").
- Dữ liệu ``SAMPLE`` → mọi tiêu chí KHÔNG ĐẠT ("không có giá trị đánh giá").
- T2: khoảng tin cậy 95 % bằng bootstrap theo **khối ngày giao dịch** trên các ngày ngoài mẫu (gồm
  ngày không có lệnh).
- T4: mốc ngẫu nhiên chạy trên **đúng khoảng ngoài mẫu**, tổ hợp được chọn nhiều nhất, cùng số lệnh
  ngoài mẫu, cùng tỷ lệ mua / bán (``baselines.random_baseline``).
- T5: DSR với Sharpe **ngày** ngoài mẫu, số quan sát = số ngày ngoài mẫu, phương sai Sharpe = phương
  sai Sharpe ngày của các tổ hợp trên phần phát triển, số lần thử = lưới + lần thử thêm; PBO bằng
  CSCV 16 khối trên lợi nhuận ngày của các tổ hợp (phần phát triển).
- T6: sụt giảm trên đường equity ngoài mẫu **ghép theo ngày** (vốn đầu + lãi / lỗ ngày của tổ hợp
  được chọn ở từng đoạn kiểm; đoạn không chọn được tổ hợp = 0).
- T7: đoạn để dành chưa chạy → KHÔNG ĐẠT.
- T8: tổng lãi ròng ngoài mẫu ≤ 0 → KHÔNG ĐẠT; ngược lại lãi ròng của **mỗi** năm và **mỗi** regime
  ≤ 70 % tổng.

Kết luận ĐẠT chỉ khi **cả tám** đạt. Không đạt → chiến lược giữ "chưa kiểm chứng"; mã GĐ6 **không
có** đường nào đổi trạng thái kiểm chứng (6-C05, test khẳng định). Không số nào ở đây là "xác suất
thắng" hay "độ tin cậy dự báo".
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from gold_trading.backtest import stats as S
from gold_trading.backtest.metrics import Trade
from gold_trading.backtest.protocol import current_combo
from gold_trading.backtest.simulate import SimResult
from gold_trading.backtest.walkforward import DevResult

# Ngưỡng protocol-1 mục 7 (khóa 17/11 — đổi = phiên bản giao thức mới)
T1_MIN_OOS_TRADES = 200
T1_MIN_HOLDOUT_TRADES = 30
T3_MIN_PROFIT_FACTOR = 1.2
T5_MIN_DSR = 0.95
T5_MAX_PBO = 0.2
T6_MAX_DRAWDOWN = 0.05
T8_MAX_SHARE = 0.70
NO_DATA = "không đủ dữ liệu"


@dataclass(frozen=True)
class Criterion:
    code: str
    rule: str
    passed: bool
    value: str


@dataclass(frozen=True)
class Inputs:
    """Mọi số cần để chấm — tính sẵn bởi ``inputs_from``; ``None`` = không có."""

    sample: bool
    oos_trades: Sequence[Trade]
    oos_daily: Sequence[tuple[datetime, Decimal]]       # (mốc ngày, lãi / lỗ ròng ngày)
    capital: Decimal
    ci_low_r: float | None                               # T2
    random_p95_r: float | None                           # T4
    dsr: float | None                                    # T5
    pbo: float | None                                    # T5
    holdout_ran: bool
    holdout_trades: Sequence[Trade] = ()


@dataclass(frozen=True)
class Evaluation:
    criteria: tuple[Criterion, ...]
    sample: bool
    numbers: Mapping[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.sample and len(self.criteria) == 8 and all(c.passed for c in self.criteria)

    @property
    def conclusion(self) -> str:
        if self.passed:
            return "ĐẠT — chờ người dùng duyệt báo cáo (Gate GĐ6)"
        return "KHÔNG ĐẠT — quay lại GĐ5, không sang GĐ8; chiến lược giữ trạng thái chưa kiểm chứng"


def _f(x: float | None, nd: int = 3) -> str:
    return NO_DATA if x is None else f"{x:.{nd}f}"


def oos_curve(daily: Sequence[tuple[datetime, Decimal]], capital: Decimal) -> list[float]:
    eq = [float(capital)]
    for _, p in daily:
        eq.append(eq[-1] + float(p))
    return eq


def oos_daily_returns(daily: Sequence[tuple[datetime, Decimal]], capital: Decimal
                      ) -> list[float]:
    curve = oos_curve(daily, capital)
    return [(b - a) / a if a > 0 else 0.0 for a, b in zip(curve, curve[1:], strict=False)]


def share_max(trades: Sequence[Trade], key) -> tuple[float | None, str]:
    total = sum((t.pnl for t in trades), Decimal(0))
    if total <= 0:
        return None, "tổng lãi ròng ≤ 0"
    g: dict = defaultdict(Decimal)
    for t in trades:
        g[key(t)] += t.pnl
    k, v = max(g.items(), key=lambda kv: kv[1])
    return float(v / total), str(k)


def criteria(x: Inputs) -> Evaluation:
    """Chấm T1–T8 từ số đã tính. Hàm thuần."""
    oos = list(x.oos_trades)
    exp_r = S.mean([t.r for t in oos])
    pf = S.profit_factor([float(t.pnl) for t in oos])
    dd = S.max_drawdown(oos_curve(x.oos_daily, x.capital)) if x.oos_daily else None
    hold_r = S.mean([t.r for t in x.holdout_trades]) if x.holdout_ran else None
    out: list[Criterion] = []

    n_ok = len(oos) >= T1_MIN_OOS_TRADES and x.holdout_ran \
        and len(x.holdout_trades) >= T1_MIN_HOLDOUT_TRADES
    out.append(Criterion("T1", f"ngoài mẫu ≥ {T1_MIN_OOS_TRADES} lệnh; để dành ≥ "
                               f"{T1_MIN_HOLDOUT_TRADES} lệnh", n_ok,
                         f"ngoài mẫu {len(oos)}; để dành "
                         f"{len(x.holdout_trades) if x.holdout_ran else 'chưa chạy'}"))
    out.append(Criterion("T2", "kỳ vọng / lệnh > 0 và cận dưới KTC 95 % > 0 (ngoài mẫu, R)",
                         exp_r is not None and x.ci_low_r is not None and exp_r > 0
                         and x.ci_low_r > 0,
                         f"kỳ vọng {_f(exp_r)}R; cận dưới {_f(x.ci_low_r)}R"))
    out.append(Criterion("T3", f"hệ số lợi nhuận ngoài mẫu ≥ {T3_MIN_PROFIT_FACTOR}",
                         pf is not None and pf >= T3_MIN_PROFIT_FACTOR, _f(pf, 2)))
    out.append(Criterion("T4", "kỳ vọng / lệnh > phân vị 95 % của mốc ngẫu nhiên",
                         exp_r is not None and x.random_p95_r is not None
                         and exp_r > x.random_p95_r,
                         f"chiến lược {_f(exp_r)}R; mốc p95 {_f(x.random_p95_r)}R"))
    out.append(Criterion("T5", f"Deflated Sharpe ≥ {T5_MIN_DSR}; PBO ≤ {T5_MAX_PBO}",
                         x.dsr is not None and x.pbo is not None and x.dsr >= T5_MIN_DSR
                         and x.pbo <= T5_MAX_PBO,
                         f"DSR {_f(x.dsr)}; PBO {_f(x.pbo)}"))
    out.append(Criterion("T6", f"sụt giảm lớn nhất ngoài mẫu < {T6_MAX_DRAWDOWN:.0%}",
                         dd is not None and dd < T6_MAX_DRAWDOWN,
                         NO_DATA if dd is None else f"{dd:.2%}"))
    out.append(Criterion("T7", "để dành: kỳ vọng / lệnh > 0 và ≥ ½ kỳ vọng ngoài mẫu",
                         hold_r is not None and exp_r is not None and hold_r > 0
                         and hold_r >= exp_r / 2,
                         "chưa chạy" if not x.holdout_ran else
                         f"để dành {_f(hold_r)}R; ½ ngoài mẫu {_f(exp_r / 2 if exp_r else None)}R"))
    sy, ky = share_max(oos, lambda t: t.year)
    sr, kr = share_max(oos, lambda t: t.regime or "UNKNOWN")
    out.append(Criterion("T8", f"không năm / regime nào > {T8_MAX_SHARE:.0%} tổng lãi",
                         sy is not None and sr is not None and sy <= T8_MAX_SHARE
                         and sr <= T8_MAX_SHARE,
                         ky if sy is None else f"năm {ky}: {sy:.0%}; regime {kr}: {sr:.0%}"))
    if x.sample:
        out = [Criterion(c.code, c.rule, False, "dữ liệu mẫu — không có giá trị đánh giá")
               for c in out]
    nums = {"oos_trades": str(len(oos)), "oos_expectancy_r": _f(exp_r),
            "oos_profit_factor": _f(pf, 2), "oos_max_drawdown": _f(dd, 4),
            "oos_total_pnl": str(sum((t.pnl for t in oos), Decimal(0))),
            "holdout_expectancy_r": _f(hold_r)}
    return Evaluation(tuple(out), x.sample, nums)


# ---------------------------------------------------------------------- tính số từ walk-forward


def _equity_map(res: SimResult) -> dict[datetime, Decimal]:
    return dict(res.equity_by_day)


def oos_daily(dev: DevResult) -> list[tuple[datetime, Decimal]]:
    """Lãi / lỗ ngày ngoài mẫu: ở mỗi đoạn kiểm lấy chênh equity đã chốt mỗi mốc ngày của tổ hợp
    được chọn; không chọn được → 0 (lịch ngày lấy từ tổ hợp hiện tại)."""
    ref = current_combo()
    out: list[tuple[datetime, Decimal]] = []
    for rd in dev.rounds:
        w = rd.window
        src = dev.per_combo[rd.chosen] if rd.chosen is not None else dev.per_combo[ref]
        eq = _equity_map(src)
        days = sorted(d for d in eq if w.test_start < d <= w.test_end)
        prev = eq.get(w.test_start)
        for d in days:
            if rd.chosen is None or prev is None:
                out.append((d, Decimal(0)))
            else:
                out.append((d, eq[d] - prev))
            prev = eq[d]
    return out


def combo_daily_returns(dev: DevResult) -> dict[str, list[float]]:
    """Lợi nhuận ngày (theo equity đã chốt) của từng tổ hợp trên phần phát triển — PBO, DSR."""
    out = {}
    for c, res in dev.per_combo.items():
        prev = res.capital
        rets = []
        for _, e in res.equity_by_day:
            rets.append(float((e - prev) / prev) if prev > 0 else 0.0)
            prev = e
        out[c.key] = rets
    return out


def inputs_from(dev: DevResult, *, capital: Decimal, n_trials: int, random_p95_r: float | None,
                bootstrap_seed: int, bootstrap_resamples: int = 10_000, sample: bool = False,
                holdout_trades: Sequence[Trade] | None = None) -> Inputs:
    oos = dev.oos_trades
    daily = oos_daily(dev)
    # khối = ngày giao dịch (mỗi mốc ngày ngoài mẫu một khối, gồm ngày không lệnh)
    days = [d for d, _ in daily]
    blocks: list[list[float]] = [[] for _ in days]
    for t in oos:                     # ngày giao dịch của lệnh = mốc ngày đầu tiên ≥ lúc đóng
        i = bisect.bisect_left(days, t.closed_at)
        if i >= len(blocks):
            raise ValueError("lệnh ngoài mẫu đóng sau mốc ngày cuối của đoạn kiểm")
        blocks[i].append(t.r)
    ci = S.block_bootstrap_mean_per_trade(blocks, n_resamples=bootstrap_resamples,
                                          seed=bootstrap_seed)
    rets = oos_daily_returns(daily, capital)
    sr = S.sharpe(rets)
    sk, ku = S.skewness(rets), S.kurtosis(rets)
    combo_rets = combo_daily_returns(dev)
    sharpes = [s for s in (S.sharpe(v) for v in combo_rets.values()) if s is not None]
    sd = S.stdev(sharpes)
    dsr = None
    if sr is not None and sk is not None and ku is not None and sd is not None:
        dsr = S.deflated_sharpe(sr, len(rets), sk, ku, n_trials=n_trials, var_sharpe=sd * sd)
    pbo = S.pbo_cscv(combo_rets, 16)
    return Inputs(sample, oos, daily, capital, ci.low if ci else None, random_p95_r, dsr,
                  pbo.pbo if pbo else None, holdout_trades is not None,
                  list(holdout_trades or ()))
