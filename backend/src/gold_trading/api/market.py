"""API dữ liệu thị trường cho Dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from gold_trading.common.time import utcnow
from gold_trading.contracts.candle import CandleFlag, DataSource
from gold_trading.market.hours import MarketSession
from gold_trading.market.service import Freshness, MarketDataService
from gold_trading.market.timeframes import Timeframe


class CandleOut(BaseModel):
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int
    spread_points: int | None
    revision: int
    flags: list[CandleFlag]


class CandlesResponse(BaseModel):
    symbol: str
    timeframe: Timeframe
    source: DataSource | None
    is_sample: bool = Field(description="True: dữ liệu mẫu, KHÔNG phải giá thật")
    as_of: datetime
    candles: list[CandleOut]
    ema20: list[float | None]
    ema50: list[float | None]
    rsi14: list[float | None]


class MarketSummary(BaseModel):
    symbol: str
    timeframe: Timeframe
    source: DataSource | None
    is_sample: bool
    session: MarketSession
    freshness: Freshness
    as_of: datetime
    last_price: float | None
    last_close_time: datetime | None
    change: float | None
    change_pct: float | None


class QuarantineOut(BaseModel):
    received_at: datetime
    source: DataSource
    reason: str
    raw: dict[str, Any]


class DataQuality(BaseModel):
    source: DataSource | None
    is_sample: bool
    candle_count: int
    first_open_time: datetime | None
    last_open_time: datetime | None
    last_ingested_at: datetime | None
    quarantined: int
    recent_quarantine: list[QuarantineOut]


def market_router(market: MarketDataService) -> APIRouter:
    r = APIRouter(prefix="/api/market", tags=["market"])

    @r.get("/summary", response_model=MarketSummary)
    def summary() -> MarketSummary:
        s = market.summary(utcnow())
        return MarketSummary(
            symbol=s.symbol,
            timeframe=s.timeframe,
            source=s.source,
            is_sample=market.is_sample,
            session=s.session,
            freshness=s.freshness,
            as_of=s.as_of,
            last_price=s.last.close if s.last else None,
            last_close_time=s.last.close_time if s.last else None,
            change=s.change,
            change_pct=s.change_pct,
        )

    @r.get("/candles", response_model=CandlesResponse)
    def candles(
        limit: Annotated[int, Query(ge=1, le=2000)] = 300,
        end: Annotated[datetime | None, Query(description="open_time tối đa (UTC)")] = None,
    ) -> CandlesResponse:
        now = utcnow()
        rows, ind = market.candles_with_indicators(as_of=now, limit=limit, end=end)
        return CandlesResponse(
            symbol=market.symbol,
            timeframe=market.timeframe,
            source=market.source,
            is_sample=market.is_sample,
            as_of=now,
            candles=[
                CandleOut(
                    open_time=c.open_time,
                    close_time=c.close_time,
                    open=c.open,
                    high=c.high,
                    low=c.low,
                    close=c.close,
                    tick_volume=c.tick_volume,
                    spread_points=c.spread_points,
                    revision=c.revision,
                    flags=sorted(c.flags),
                )
                for c in rows
            ],
            ema20=[_r(v) for v in ind.ema20],
            ema50=[_r(v) for v in ind.ema50],
            rsi14=[_r(v) for v in ind.rsi14],
        )

    @r.get("/quality", response_model=DataQuality)
    def quality() -> DataQuality:
        st = market.stats()
        return DataQuality(
            source=market.source,
            is_sample=market.is_sample,
            candle_count=st.count if st else 0,
            first_open_time=st.first_open_time if st else None,
            last_open_time=st.last_open_time if st else None,
            last_ingested_at=st.last_ingested_at if st else None,
            quarantined=st.quarantined if st else 0,
            recent_quarantine=[
                QuarantineOut(
                    received_at=q.received_at, source=q.source, reason=q.reason, raw=q.raw
                )
                for q in market.quarantine()
            ],
        )

    return r


def _r(v: float | None) -> float | None:
    return None if v is None else round(v, 4)
