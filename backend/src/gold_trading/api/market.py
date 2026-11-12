"""API dữ liệu thị trường cho Dashboard."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from gold_trading.auth.web import CurrentUser, Principal
from gold_trading.common.time import utcnow
from gold_trading.contracts.candle import CandleFlag, DataSource
from gold_trading.market.hours import MarketSession
from gold_trading.market.quotes import Calendar, QuoteStore
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


def summary_of(market: MarketDataService) -> MarketSummary:
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


def candles_of(market: MarketDataService, limit: int, end: datetime | None) -> CandlesResponse:
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


def quality_of(market: MarketDataService) -> DataQuality:
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
            QuarantineOut(received_at=q.received_at, source=q.source, reason=q.reason, raw=q.raw)
            for q in market.quarantine()
        ],
    )


Limit = Annotated[int, Query(ge=1, le=2000)]
End = Annotated[datetime | None, Query(description="open_time tối đa (UTC)")]


def market_router(market: MarketDataService) -> APIRouter:
    """Màn hình thị trường KHÔNG gắn tài khoản. MT-05: với nguồn MT5 không có "giá chung" — các
    endpoint này trả rỗng; giá broker đọc qua ``/api/accounts/{id}/market/*``."""
    r = APIRouter(prefix="/api/market", tags=["market"])

    @r.get("/summary", response_model=MarketSummary)
    def summary() -> MarketSummary:
        return summary_of(market)

    @r.get("/candles", response_model=CandlesResponse)
    def candles(limit: Limit = 300, end: End = None) -> CandlesResponse:
        return candles_of(market, limit, end)

    @r.get("/quality", response_model=DataQuality)
    def quality() -> DataQuality:
        return quality_of(market)

    return r


def account_market_router(
    market_for: Callable[[str], MarketDataService],
    check: Callable[[str, Principal, str], object],
) -> APIRouter:
    """MT-05: giá theo nguồn của chính tài khoản (DEC-14). ``check`` = ``Guard.check`` (chỉ chủ
    tài khoản đang ACTIVE); ``market_for(account_id)`` dựng dịch vụ đọc đúng nguồn của tài khoản."""
    r = APIRouter(prefix="/api/accounts/{account_id}/market", tags=["market"])

    @r.get("/summary", response_model=MarketSummary)
    def acc_summary(account_id: str, p: CurrentUser) -> MarketSummary:
        check(account_id, p, "market.summary")
        return summary_of(market_for(account_id))

    @r.get("/candles", response_model=CandlesResponse)
    def acc_candles(account_id: str, p: CurrentUser, limit: Limit = 300,
                    end: End = None) -> CandlesResponse:
        check(account_id, p, "market.candles")
        return candles_of(market_for(account_id), limit, end)

    @r.get("/quality", response_model=DataQuality)
    def acc_quality(account_id: str, p: CurrentUser) -> DataQuality:
        check(account_id, p, "market.quality")
        return quality_of(market_for(account_id))

    return r


def _r(v: float | None) -> float | None:
    return None if v is None else round(v, 4)


# --- DSH-07: giá sống bid/ask/spread (ING-08) ---

QUOTE_STALE_AFTER = timedelta(seconds=15)

QuoteState = Literal["NO_FEED", "NO_DATA", "LIVE", "STALE", "CLOSED"]


class LiveQuote(BaseModel):
    """Giây gần nhất đã nhận của nguồn giá của tài khoản (point-in-time: available_at ≤ now).

    ``state``: NO_FEED (chưa có nguồn giá: chưa liên kết MT5 / dữ liệu mẫu), NO_DATA (chưa có giá
    sống), LIVE (giây gần nhất cách ≤ 15 s), STALE (cũ hơn trong khi lịch nói thị trường mở —
    giá KHÔNG còn đúng), CLOSED (cũ hơn, lịch nói đóng cửa: giá cuối phiên)."""

    state: QuoteState
    market_open: bool
    as_of: datetime
    t: datetime | None = None
    age_seconds: float | None = None
    bid: float | None = None
    ask: float | None = None
    spread_points: int | None = None
    spread_max_points: int | None = None
    ticks: int | None = None
    flags: list[str] = Field(default_factory=list)


def live_quote(feed: str | None, store: QuoteStore, calendar: Calendar,
               now: datetime) -> LiveQuote:
    market_open = calendar.is_open(now)
    if not feed:
        return LiveQuote(state="NO_FEED", market_open=market_open, as_of=now)
    q = store.latest(feed, now)
    if q is None:
        return LiveQuote(state="NO_DATA", market_open=market_open, as_of=now)
    age = now - q.t
    if age <= QUOTE_STALE_AFTER:
        state: QuoteState = "LIVE"
    else:
        state = "STALE" if market_open else "CLOSED"
    return LiveQuote(
        state=state, market_open=market_open, as_of=now, t=q.t,
        age_seconds=round(age.total_seconds(), 1), bid=q.bid, ask=q.ask,
        spread_points=q.spread_points, spread_max_points=q.spread_max_points, ticks=q.ticks,
        flags=list(q.flags),
    )


def account_quote_router(
    feed_of: Callable[[str], str | None],
    store: QuoteStore,
    calendar: Calendar,
    check: Callable[[str, Principal, str], object],
) -> APIRouter:
    """DSH-07: giá sống của nguồn giá CHÍNH tài khoản (chỉ chủ tài khoản ACTIVE)."""
    r = APIRouter(prefix="/api/accounts/{account_id}/market", tags=["market"])

    @r.get("/quote", response_model=LiveQuote)
    def acc_quote(account_id: str, p: CurrentUser) -> LiveQuote:
        check(account_id, p, "market.quote")
        return live_quote(feed_of(account_id), store, calendar, utcnow())

    return r
