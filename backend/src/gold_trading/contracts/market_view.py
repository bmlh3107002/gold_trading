"""MarketView — đầu ra tiêu chuẩn của Market Intelligence (docs/05, thiết kế 33).

GĐ4 (DEC-25, DEC-27): MarketView là "nghiêng theo luật, chưa kiểm chứng" — chưa có xác suất đã hiệu
chỉnh nên ``p_up`` / ``p_down`` luôn ``None``, và mọi MarketView bắt buộc mang hai cờ chất lượng
``UNCALIBRATED`` + ``UNVALIDATED_RULES`` (Risk chặn ở SHADOW/LIVE). Gỡ cờ / cho phép số xác suất là
**quyết định mới của người dùng** (sau backtest GĐ6 / hiệu chỉnh GĐ7) → phải sửa hợp đồng này.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from gold_trading.common.enums import Bias, Regime
from gold_trading.common.time import UtcDatetime
from gold_trading.contracts.base import Contract

UNCALIBRATED = "UNCALIBRATED"
UNVALIDATED_RULES = "UNVALIDATED_RULES"
SAMPLE_DATA = "SAMPLE_DATA"
# Cờ bắt buộc trong GĐ4 (DEC-25, DEC-27).
REQUIRED_QUALITY_FLAGS = frozenset({UNCALIBRATED, UNVALIDATED_RULES})


class MarketView(Contract):
    market_view_id: str
    snapshot_id: str
    symbol: str = "XAUUSD"
    timeframe: str = "M15"
    source: str = Field(
        pattern=r"^[A-Z0-9_]+$",
        description="Nguồn giá (SAMPLE / CSV / MT5), chữ hoa — mỗi broker một chuỗi (MT-05)",
    )
    feed_id: str = Field(description="Id nguồn giá; chuỗi rỗng khi nguồn không có id")
    as_of: UtcDatetime
    expires_at: UtcDatetime
    bias: Bias = Field(
        description="Nghiêng theo luật, chưa kiểm chứng (DEC-25) — không phải tín hiệu",
    )
    p_up: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Luôn null trong GĐ4: chưa có xác suất đã hiệu chỉnh (DEC-27)",
    )
    p_down: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Luôn null trong GĐ4: chưa có xác suất đã hiệu chỉnh (DEC-27)",
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Chất lượng dữ liệu × mức đồng thuận — không phải xác suất đúng",
    )
    regime: Regime
    vol_forecast: float | None = Field(
        default=None, ge=0.0,
        description="σ một ngày giao dịch, % (EWMA TEC-07, luật cố định); null khi chưa đủ dữ liệu",
    )
    drivers: tuple[str, ...] = ()
    risk_flags: frozenset[str] = frozenset()
    quality_flags: frozenset[str] = frozenset()
    model_version: str = Field(description="Phiên bản Fusion")
    quality_policy_version: str = Field(description="Phiên bản chính sách Quality Gate")

    @model_validator(mode="after")
    def _check(self) -> MarketView:
        if self.expires_at <= self.as_of:
            raise ValueError("expires_at phải sau as_of")
        if self.p_up is not None or self.p_down is not None:
            raise ValueError(
                "GĐ4 chưa có xác suất đã hiệu chỉnh: p_up / p_down phải để trống (DEC-27)")
        if missing := sorted(REQUIRED_QUALITY_FLAGS - self.quality_flags):
            raise ValueError(f"thiếu cờ chất lượng bắt buộc: {', '.join(missing)} (DEC-25, DEC-27)")
        if self.source == "SAMPLE" and SAMPLE_DATA not in self.quality_flags:
            raise ValueError("nguồn SAMPLE phải mang cờ SAMPLE_DATA")
        return self

    def is_valid_at(self, at: UtcDatetime) -> bool:
        return self.as_of <= at < self.expires_at
