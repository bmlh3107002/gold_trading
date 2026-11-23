"""GĐ6 bước 6 — thống kê backtest (protocol-1 mục 5–6). Giá trị tham chiếu tính tay / từ bài báo."""

from __future__ import annotations

import math
import random

import pytest

from gold_trading.backtest import stats as S


def test_percentile_linear_matches_hand_values():
    assert S.percentile([1, 2, 3, 4], 0.5) == 2.5
    assert S.percentile(list(range(1, 101)), 0.95) == pytest.approx(95.05)
    assert S.percentile([7], 0.3) == 7
    assert S.percentile([], 0.5) is None
    assert S.percentile([1, 2], 1.5) is None


def test_basic_moments_hand_values():
    assert S.sharpe([1, 2, 3]) == pytest.approx(2.0)          # trung bình 2, độ lệch chuẩn 1
    assert S.sharpe([5, 5, 5]) is None                        # độ lệch chuẩn 0 → không xác định
    assert S.sharpe([1]) is None
    assert S.skewness([1, 2, 3]) == pytest.approx(0.0)
    assert S.kurtosis([1, 2, 3, 4]) == pytest.approx(2.5625 / 1.5625)   # = 1,64
    assert S.skewness([1, 1, 1]) is None


def test_trade_metrics_hand_values():
    pnl = [10, -5, -5, 20, -10, -1, -2, 0, 3]
    assert S.profit_factor(pnl) == pytest.approx(33 / 23)
    assert S.win_rate(pnl) == pytest.approx(3 / 9)
    assert S.longest_losing_streak(pnl) == 3                  # -10, -1, -2; số 0 cắt chuỗi
    assert S.profit_factor([1, 2]) is None                    # không có lệnh lỗ
    assert S.profit_factor([]) is None
    assert S.win_rate([]) is None
    assert S.longest_losing_streak([]) == 0


def test_max_drawdown_from_prior_peak():
    assert S.max_drawdown([100, 120, 90, 130, 65]) == pytest.approx(0.5)
    assert S.max_drawdown([100, 101, 102]) == 0
    assert S.max_drawdown([]) is None
    assert S.max_drawdown([0, -1]) is None                    # đỉnh ≤ 0: không định nghĩa


def test_deflated_sharpe_reference_example_bailey_lopez_de_prado_2014():
    # Ví dụ số trong bài báo: Sharpe năm hóa 2,5; T = 1.250 quan sát ngày; độ lệch −3;
    # độ nhọn 10; N = 100 lần thử; phương sai Sharpe năm hóa giữa các lần thử 0,5 → DSR ≈ 0,9004.
    sr = 2.5 / math.sqrt(250)
    var = 0.5 / 250
    # Tính tay từng bước, độc lập với mã:
    n = S._N
    sr0 = math.sqrt(var) * ((1 - 0.5772156649) * n.inv_cdf(0.99)
                            + 0.5772156649 * n.inv_cdf(1 - 1 / (100 * math.e)))
    z = (sr - sr0) * math.sqrt(1249) / math.sqrt(1 + 3 * sr + 9 / 4 * sr * sr)
    assert S.expected_max_sharpe(100, var) == pytest.approx(sr0, rel=1e-12)
    dsr = S.deflated_sharpe(sr, 1250, -3, 10, n_trials=100, var_sharpe=var)
    assert dsr == pytest.approx(n.cdf(z), rel=1e-12)
    assert dsr == pytest.approx(0.9004, abs=0.0001)          # số trong bài báo


def test_deflated_sharpe_more_trials_is_stricter_and_guards():
    a = S.deflated_sharpe(0.1, 500, 0, 3, n_trials=27, var_sharpe=0.001)
    b = S.deflated_sharpe(0.1, 500, 0, 3, n_trials=1000, var_sharpe=0.001)
    assert a > b
    assert S.deflated_sharpe(0.1, 500, 0, 3, n_trials=1, var_sharpe=0.001) is None
    assert S.probabilistic_sharpe(0.1, 0, 1, 0, 3) is None
    assert S.probabilistic_sharpe(0.0, 0.0, 100, 0, 3) == pytest.approx(0.5)


def test_pbo_random_strategies_near_half():
    rng = random.Random(7)
    rets = {f"s{i:02d}": [rng.gauss(0, 1) for _ in range(640)] for i in range(27)}
    r = S.pbo_cscv(rets, 16)
    assert r.n_splits == 12870 and r.n_blocks == 16 and r.n_strategies == 27
    assert 0.3 < r.pbo < 0.7                                  # không có lợi thế thật → ≈ 0,5


def test_pbo_dominant_strategy_near_zero():
    rng = random.Random(11)
    rets = {f"s{i:02d}": [rng.gauss(0, 1) for _ in range(640)] for i in range(10)}
    rets["best"] = [rng.gauss(1.0, 1) for _ in range(640)]   # lợi thế thật, ổn định
    assert S.pbo_cscv(rets, 16).pbo < 0.05


def test_pbo_overfit_strategy_high():
    # Cấu hình "tốt" chỉ ở nửa đầu, rất tệ ở nửa sau: chọn theo IS thường sai ở OOS.
    rng = random.Random(3)
    rets = {f"s{i:02d}": [rng.gauss(0, 1) for _ in range(640)] for i in range(10)}
    rets["lucky"] = [rng.gauss(2, 1) if t < 320 else rng.gauss(-2, 1) for t in range(640)]
    assert S.pbo_cscv(rets, 16).pbo > 0.4


def test_pbo_guards_and_remainder_dropped_at_start():
    assert S.pbo_cscv({"a": [1.0] * 64}, 16) is None          # < 2 cấu hình
    assert S.pbo_cscv({"a": [1.0] * 64, "b": [1.0] * 63}, 16) is None   # lệch độ dài
    assert S.pbo_cscv({"a": [1.0] * 64, "b": [1.0] * 64}, 15) is None   # số khối lẻ
    assert S.pbo_cscv({"a": [1.0] * 20, "b": [1.0] * 20}, 16) is None   # khối < 2 kỳ
    # Phần dư bỏ ở đầu: thêm 5 kỳ đầu khác hẳn không đổi kết quả.
    rng = random.Random(5)
    base = {f"s{i}": [rng.gauss(0, 1) for _ in range(64)] for i in range(4)}
    padded = {k: [99.0] * 5 + v for k, v in base.items()}
    assert S.pbo_cscv(base, 16).pbo == S.pbo_cscv(padded, 16).pbo


def test_block_bootstrap_hand_and_deterministic():
    days = [[1.0, 1.0], [], [1.0]]
    r = S.block_bootstrap_mean_per_trade(days, n_resamples=500, seed=1)
    assert (r.estimate, r.low, r.high) == (1.0, 1.0, 1.0)     # mọi lệnh = 1 → khoảng sụp về 1
    days = [[2.0, -1.0], [0.5], [-0.5, -0.5, 3.0], [1.0]]
    a = S.block_bootstrap_mean_per_trade(days, n_resamples=2000, seed=42)
    b = S.block_bootstrap_mean_per_trade(days, n_resamples=2000, seed=42)
    assert a == b                                             # cùng hạt giống → cùng kết quả
    assert a.estimate == pytest.approx(4.5 / 7)
    assert a.low < a.estimate < a.high
    assert S.block_bootstrap_mean_per_trade([[1.0]], seed=1) is None   # < 2 lệnh
    assert S.block_bootstrap_mean_per_trade([[1.0, 2.0]], seed=1, level=1.0) is None


def test_block_bootstrap_ci_covers_true_mean_on_known_series():
    rng = random.Random(9)
    days = [[rng.gauss(0.2, 1) for _ in range(rng.randrange(0, 4))] for _ in range(400)]
    r = S.block_bootstrap_mean_per_trade(days, n_resamples=3000, seed=9)
    assert r.low < 0.2 < r.high
    assert r.high - r.low < 0.25
