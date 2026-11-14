"""Chỉ báo kỹ thuật thuần (không phụ thuộc I/O). Dùng chung cho biểu đồ và analyst.

Quy ước: kết quả cùng độ dài với input; vị trí chưa đủ dữ liệu (warm-up) là ``None``.
"""

from __future__ import annotations

from collections.abc import Sequence


def ema(values: Sequence[float], period: int) -> list[float | None]:
    """EMA chuẩn: khởi tạo bằng SMA của ``period`` giá trị đầu, alpha = 2 / (period + 1)."""
    if period < 1:
        raise ValueError("period phải >= 1")
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    alpha = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def rsi(values: Sequence[float], period: int = 14) -> list[float | None]:
    """RSI Wilder: lãi/lỗ trung bình đầu = SMA của ``period`` thay đổi, rồi làm mượt Wilder."""
    if period < 1:
        raise ValueError("period phải >= 1")
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = values[i] - values[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_g, avg_l = gains / period, losses / period

    def value(g: float, lo: float) -> float:
        if lo == 0:
            return 100.0 if g > 0 else 50.0
        return 100 - 100 / (1 + g / lo)

    out[period] = value(avg_g, avg_l)
    for i in range(period + 1, len(values)):
        d = values[i] - values[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0.0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0.0)) / period
        out[i] = value(avg_g, avg_l)
    return out


def true_range(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]
) -> list[float]:
    """TR[0] = H−L; TR[i] = max(H−L, |H−C₋₁|, |L−C₋₁|)."""
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("highs, lows, closes phải cùng độ dài")
    out: list[float] = []
    for i, (h, lo) in enumerate(zip(highs, lows, strict=True)):
        if i == 0:
            out.append(h - lo)
        else:
            pc = closes[i - 1]
            out.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    return out


def atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> list[float | None]:
    """ATR Wilder: ATR đầu = SMA của ``period`` TR (từ TR[1]), sau đó (ATR₋₁·(n−1) + TR) / n.

    TR[0] không có close trước nên bỏ qua khi khởi tạo; giá trị đầu tiên nằm ở chỉ số ``period``.
    """
    if period < 1:
        raise ValueError("period phải >= 1")
    tr = true_range(highs, lows, closes)
    out: list[float | None] = [None] * len(tr)
    if len(tr) <= period:
        return out
    prev = sum(tr[1 : period + 1]) / period
    out[period] = prev
    for i in range(period + 1, len(tr)):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def adx(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """ADX Wilder (1978) → ``(adx, +DI, −DI)``, cùng độ dài input.

    - +DM = H − H₋₁ nếu > (L₋₁ − L) và > 0, ngược lại 0; −DM đối xứng. TR như ``true_range``.
    - TR / +DM / −DM làm mượt Wilder: tổng ``period`` giá trị đầu (từ chỉ số 1), sau đó
      S = S₋₁ − S₋₁/n + x. +DI = 100·(+DM)/TR, −DI = 100·(−DM)/TR (giá trị đầu ở chỉ số ``period``).
    - DX = 100·|+DI − −DI| / (+DI + −DI) (tổng 0 → 0). ADX đầu = trung bình ``period`` DX đầu
      (ở chỉ số ``2·period − 1``), sau đó (ADX₋₁·(n−1) + DX) / n.
    """
    if period < 1:
        raise ValueError("period phải >= 1")
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("highs, lows, closes phải cùng độ dài")
    n = len(highs)
    adx_out: list[float | None] = [None] * n
    pdi_out: list[float | None] = [None] * n
    mdi_out: list[float | None] = [None] * n
    if n <= period:
        return adx_out, pdi_out, mdi_out
    tr = true_range(highs, lows, closes)
    pdm = [0.0] * n
    mdm = [0.0] * n
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        pdm[i] = up if up > down and up > 0 else 0.0
        mdm[i] = down if down > up and down > 0 else 0.0
    s_tr = sum(tr[1 : period + 1])
    s_p = sum(pdm[1 : period + 1])
    s_m = sum(mdm[1 : period + 1])
    dx: list[float | None] = [None] * n
    for i in range(period, n):
        if i > period:
            s_tr = s_tr - s_tr / period + tr[i]
            s_p = s_p - s_p / period + pdm[i]
            s_m = s_m - s_m / period + mdm[i]
        pdi = 100 * s_p / s_tr if s_tr > 0 else 0.0
        mdi = 100 * s_m / s_tr if s_tr > 0 else 0.0
        pdi_out[i], mdi_out[i] = pdi, mdi
        tot = pdi + mdi
        dx[i] = 100 * abs(pdi - mdi) / tot if tot > 0 else 0.0
    first = 2 * period - 1
    if n <= first:
        return adx_out, pdi_out, mdi_out
    prev = sum(dx[period : first + 1]) / period  # type: ignore[arg-type]
    adx_out[first] = prev
    for i in range(first + 1, n):
        prev = (prev * (period - 1) + dx[i]) / period  # type: ignore[operator]
        adx_out[i] = prev
    return adx_out, pdi_out, mdi_out
