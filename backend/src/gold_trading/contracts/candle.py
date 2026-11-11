"""Nến OHLC đã chuẩn hóa (docs/02).

Hai mốc thời gian:
- ``ingested_at``: lúc hệ thống THỰC SỰ nhận bản ghi (đồng hồ thật, phục vụ audit).
- ``available_at``: lúc thông tin này được coi là đã biết, dùng cho truy vấn point-in-time.
  Dữ liệu realtime: = ingested_at. Dữ liệu nạp bù lịch sử: = close_time + cờ BACKFILL.
  Revision mới luôn có available_at = ingested_at (không được "biết trước" bản sửa).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from gold_trading.common.time import UtcDatetime
from gold_trading.contracts.base import Contract
from gold_trading.market.timeframes import Timeframe


class DataSource(StrEnum):
    SAMPLE = "SAMPLE"  # dữ liệu mẫu tự sinh — không bao giờ dùng cho quyết định thật
    CSV = "CSV"  # nạp từ file (thường xuất từ MT5)
    MT5 = "MT5"  # MT5 Gateway (sau này)

    @property
    def is_sample(self) -> bool:
        return self is DataSource.SAMPLE


class CandleFlag(StrEnum):
    BACKFILL = "BACKFILL"
    REVISED = "REVISED"
    GAP_BEFORE = "GAP_BEFORE"
    PRICE_JUMP = "PRICE_JUMP"
    ZERO_RANGE = "ZERO_RANGE"


class Candle(Contract):
    symbol: str = Field(min_length=1, max_length=32)
    timeframe: Timeframe
    source: DataSource
    # MT-05: nguồn giá (feed) = một (server broker, symbol broker). "" = nguồn không gắn broker
    # (SAMPLE, CSV). Nến của hai feed khác nhau KHÔNG BAO GIỜ trộn (DEC-14).
    feed_id: str = Field(default="", max_length=64)
    open_time: UtcDatetime
    close_time: UtcDatetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    tick_volume: int = Field(default=0, ge=0)
    spread_points: int | None = Field(default=None, ge=0)
    revision: int = Field(default=0, ge=0)
    ingested_at: UtcDatetime
    available_at: UtcDatetime
    flags: frozenset[CandleFlag] = frozenset()

    @model_validator(mode="after")
    def _invariants(self) -> Candle:
        if not self.timeframe.is_aligned(self.open_time):
            raise ValueError("open_time không khớp khung thời gian")
        if not self.timeframe.plausible_close(self.open_time, self.close_time):
            # M1–H1: đúng bằng open_time + khung. H4/D1 căn theo giờ server broker: độ dài thật
            # lệch tối đa 1 giờ ở ngày đổi DST (close_time do cửa nạp tính theo múi giờ server).
            raise ValueError("close_time không khớp open_time + timeframe")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("OHLC không hợp lệ: high/low không bao open/close")
        if self.available_at < self.close_time:
            raise ValueError("Nến chưa đóng không được coi là đã biết (available_at < close_time)")
        if self.available_at > self.ingested_at:
            raise ValueError("available_at không được muộn hơn ingested_at")
        if self.available_at < self.ingested_at and CandleFlag.BACKFILL not in self.flags:
            raise ValueError("available_at chỉ được sớm hơn ingested_at khi là BACKFILL")
        return self

    @property
    def ohlcv(self) -> tuple[float, float, float, float, int]:
        return (self.open, self.high, self.low, self.close, self.tick_volume)
