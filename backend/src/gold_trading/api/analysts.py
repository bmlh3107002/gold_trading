"""API kết quả analyst."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from gold_trading.analysts import technical
from gold_trading.common.time import utcnow
from gold_trading.contracts.analyst import AnalystOutput
from gold_trading.market.service import MarketDataService
from gold_trading.storage.analyst_outputs import AnalystOutputStore


class AnalystLatest(BaseModel):
    output: AnalystOutput | None
    computed_at: datetime | None
    valid_now: bool = Field(description="Còn hiệu lực tại thời điểm trả lời (chưa quá expires_at)")
    is_sample: bool
    confidence_meaning: str = Field(
        default="DATA_QUALITY_ONLY",
        description="confidence của technical v1 chỉ đo chất lượng dữ liệu, không đo khả năng "
        "dự báo",
    )


def analysts_router(market: MarketDataService, store: AnalystOutputStore) -> APIRouter:
    r = APIRouter(prefix="/api/analysts", tags=["analysts"])

    @r.get("/technical/latest", response_model=AnalystLatest)
    def technical_latest() -> AnalystLatest:
        now = utcnow()
        feed = market.feed
        if market.source is None or feed is None:
            return AnalystLatest(output=None, computed_at=None, valid_now=False, is_sample=False)
        got = store.latest(
            technical.ANALYST_ID, symbol=market.symbol, tf=market.timeframe, source=market.source,
            feed=feed,
        )
        if got is None:
            return AnalystLatest(
                output=None, computed_at=None, valid_now=False, is_sample=market.is_sample
            )
        return AnalystLatest(
            output=got.output,
            computed_at=got.computed_at,
            valid_now=got.output.is_valid_at(now),
            is_sample=market.is_sample,
        )

    return r
