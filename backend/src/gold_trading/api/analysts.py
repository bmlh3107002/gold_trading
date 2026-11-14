"""API kết quả analyst."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from gold_trading.analysts import event, macro, regime, technical
from gold_trading.analysts.framework import GLOBAL_SCOPE, Scope
from gold_trading.auth.web import CurrentUser, Principal
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
        description="confidence của analyst (technical, regime) chỉ đo chất lượng dữ liệu (và độ "
        "rõ ràng của nhãn với regime), không đo khả năng dự báo",
    )


class EventLatest(BaseModel):
    """GĐ3 bước 2 (ANA-02): kết quả analyst Lịch sự kiện — chung cho mọi tài khoản."""

    output: AnalystOutput | None
    computed_at: datetime | None
    valid_now: bool = Field(description="Còn hiệu lực tại thời điểm trả lời (chưa quá expires_at)")
    confidence_meaning: str = Field(
        default="DATA_QUALITY_ONLY",
        description="confidence chỉ đo chất lượng dữ liệu lịch, không phải xác suất",
    )
    observer_only: bool = Field(
        default=True,
        description="Analyst chỉ mô tả; chặn mở lệnh do Safety / làn nhanh quyết",
    )


def event_of(store: AnalystOutputStore) -> EventLatest:
    now = utcnow()
    got = store.latest_scoped(event.ANALYST_ID, GLOBAL_SCOPE, known_by=now)
    if got is None or got.output.version != event.VERSION:
        return EventLatest(output=None, computed_at=None, valid_now=False)
    return EventLatest(output=got.output, computed_at=got.computed_at,
                       valid_now=got.output.is_valid_at(now))


def technical_of(market: MarketDataService, store: AnalystOutputStore) -> AnalystLatest:
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


def regime_of(market: MarketDataService, store: AnalystOutputStore) -> AnalystLatest:
    """GĐ3 bước 3: Regime trên nguồn giá của tài khoản (MT-05)."""
    return feed_scoped_of(regime, market, store)


def macro_of(market: MarketDataService, store: AnalystOutputStore) -> AnalystLatest:
    """GĐ3 bước 4: Macro trên nguồn giá của tài khoản (chỉ số USD theo broker — DEC-14)."""
    return feed_scoped_of(macro, market, store)


def feed_scoped_of(mod, market: MarketDataService, store: AnalystOutputStore) -> AnalystLatest:
    """Kết quả mới nhất (đúng phiên bản hiện hành) của analyst theo nguồn giá tài khoản."""
    now = utcnow()
    feed = market.feed
    if market.source is None or feed is None:
        return AnalystLatest(output=None, computed_at=None, valid_now=False, is_sample=False)
    got = store.latest_scoped(mod.ANALYST_ID,
                              Scope.of_feed(market.symbol, market.timeframe, market.source, feed),
                              known_by=now)
    if got is None or got.output.version != mod.VERSION:
        return AnalystLatest(output=None, computed_at=None, valid_now=False,
                             is_sample=market.is_sample)
    return AnalystLatest(output=got.output, computed_at=got.computed_at,
                         valid_now=got.output.is_valid_at(now), is_sample=market.is_sample)


def analysts_router(market: MarketDataService, store: AnalystOutputStore) -> APIRouter:
    r = APIRouter(prefix="/api/analysts", tags=["analysts"])

    @r.get("/technical/latest", response_model=AnalystLatest)
    def technical_latest() -> AnalystLatest:
        return technical_of(market, store)

    @r.get("/event/latest", response_model=EventLatest)
    def event_latest(p: CurrentUser) -> EventLatest:
        return event_of(store)

    return r


def account_analysts_router(
    market_for: Callable[[str], MarketDataService],
    store: AnalystOutputStore,
    check: Callable[[str, Principal, str], object],
) -> APIRouter:
    """MT-05: kết quả analyst trên nguồn giá của chính tài khoản."""
    r = APIRouter(prefix="/api/accounts/{account_id}/analysts", tags=["analysts"])

    @r.get("/technical/latest", response_model=AnalystLatest)
    def acc_technical_latest(account_id: str, p: CurrentUser) -> AnalystLatest:
        check(account_id, p, "analysts.technical")
        return technical_of(market_for(account_id), store)

    @r.get("/regime/latest", response_model=AnalystLatest)
    def acc_regime_latest(account_id: str, p: CurrentUser) -> AnalystLatest:
        check(account_id, p, "analysts.regime")
        return regime_of(market_for(account_id), store)

    @r.get("/macro/latest", response_model=AnalystLatest)
    def acc_macro_latest(account_id: str, p: CurrentUser) -> AnalystLatest:
        check(account_id, p, "analysts.macro")
        return macro_of(market_for(account_id), store)

    return r
