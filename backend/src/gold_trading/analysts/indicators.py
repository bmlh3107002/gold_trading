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
