"""Khối lượng + rủi ro theo thông số thật của broker (RSK-11, KN-02) — hàm thuần, ``Decimal``.

Công thức (tài liệu Quản lý vốn mục 5.2 + 3.5; thiết kế docs/thiet-ke/35-risk-engine.md mục 4)::

    Dt = |vào − SL| + spread hiện tại + đệm trượt giá          (đơn vị giá)
    R1 = Dt × cỡ hợp đồng + phí khứ hồi / lot                  (tiền tài khoản, USD — Q2)
    lot = floor(M / R1 theo bước lot) × bước lot, cắt về max; < min → từ chối

Bất biến: ``lot × R1 ≤ M`` (rủi ro thật gồm chi phí không vượt mức được duyệt). Không bao giờ làm
tròn lên. Mọi đầu vào là ``Decimal``; số thực từ broker đổi bằng ``dec()`` (qua ``str``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

ZERO = Decimal(0)


def dec(x: float | int | str | Decimal) -> Decimal:
    """Số từ broker / Gateway → ``Decimal`` đúng số thập phân đã báo (``0.01`` →
    ``Decimal('0.01')``, không phải khai triển nhị phân). NaN / vô cực → lỗi."""
    if isinstance(x, bool):
        raise TypeError("bool không phải số")
    d = x if isinstance(x, Decimal) else Decimal(str(x))
    if not d.is_finite():
        raise ValueError("số không hữu hạn")
    return d


def floor_to_step(x: Decimal, step: Decimal) -> Decimal:
    """Bội lớn nhất của ``step`` không vượt ``x`` (x ≥ 0). Chính xác — không có sai số nhị phân."""
    if step <= 0:
        raise ValueError("bước lot phải > 0")
    if x <= 0:
        return ZERO
    return (x / step).to_integral_value(rounding=ROUND_FLOOR) * step


@dataclass(frozen=True)
class SizingSpec:
    contract_size: Decimal      # đơn vị / lot (oz); giá trị 1 đơn vị giá / lot = cỡ HĐ (USD, Q2)
    volume_min: Decimal
    volume_max: Decimal
    volume_step: Decimal


@dataclass(frozen=True)
class SizingResult:
    risk_per_lot: Decimal       # R1
    effective_distance: Decimal  # Dt
    volume: Decimal             # 0 khi không đủ lot tối thiểu
    risk_amount: Decimal        # volume × R1
    capped_at_max: bool
    shortfall: Decimal | None   # khi < lot tối thiểu: min × R1 − M (tiền còn thiếu)


def risk_per_lot(stop_distance: Decimal, spread: Decimal, slippage: Decimal,
                 contract_size: Decimal, commission_per_lot: Decimal) -> tuple[Decimal, Decimal]:
    """(R1, Dt). Mọi chi phí ≥ 0; khoảng SL > 0."""
    if stop_distance <= 0:
        raise ValueError("khoảng SL phải > 0")
    if min(spread, slippage, commission_per_lot) < 0 or contract_size <= 0:
        raise ValueError("chi phí âm / cỡ hợp đồng ≤ 0")
    dt = stop_distance + spread + slippage
    return dt * contract_size + commission_per_lot, dt


def size(money: Decimal, stop_distance: Decimal, spread: Decimal, slippage: Decimal,
         commission_per_lot: Decimal, spec: SizingSpec) -> SizingResult:
    r1, dt = risk_per_lot(stop_distance, spread, slippage, spec.contract_size, commission_per_lot)
    raw = floor_to_step(money / r1, spec.volume_step) if money > 0 else ZERO
    capped = raw > spec.volume_max
    vol = floor_to_step(spec.volume_max, spec.volume_step) if capped else raw
    if vol < spec.volume_min or vol <= 0:
        return SizingResult(r1, dt, ZERO, ZERO, False, spec.volume_min * r1 - money)
    return SizingResult(r1, dt, vol, vol * r1, capped, None)
