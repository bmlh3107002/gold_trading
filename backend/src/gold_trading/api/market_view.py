"""API MarketView theo tài khoản (GĐ4 bước 6 — MKV-03). Thiết kế 33 mục 7.

Trả MarketView **còn hiệu lực** của nguồn giá tài khoản (MT-05), hoặc trạng thái + lý do khi không
có (chưa có / hết hạn / bị vô hiệu / Quality Gate từ chối). Không bịa: không có MarketView còn hạn
→ ``market_view = null`` (không có tín hiệu). ``bias`` là "nghiêng theo luật, chưa kiểm chứng"
(DEC-25); ``p_up`` / ``p_down`` luôn ``null`` (DEC-27).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from gold_trading.analysts.framework import Scope
from gold_trading.auth.web import CurrentUser, Principal
from gold_trading.common.enums import QualityVerdict
from gold_trading.common.time import utcnow
from gold_trading.contracts.market_view import MarketView
from gold_trading.market.service import MarketDataService

State = Literal["VALID", "NONE", "EXPIRED", "INVALIDATED", "NO_SOURCE"]


class GateSummary(BaseModel):
    verdict: QualityVerdict
    reasons: list[str]
    evaluated_at: datetime
    policy_version: str


class MarketViewLatest(BaseModel):
    market_view: MarketView | None = Field(
        description="MarketView còn hiệu lực lúc trả lời; null → không có tín hiệu")
    state: State = Field(description="VALID / NONE (chưa có) / EXPIRED / INVALIDATED / NO_SOURCE")
    last_as_of: datetime | None = None
    last_expires_at: datetime | None = None
    invalidated_at: datetime | None = None
    invalidation_reason: str | None = None
    gate: GateSummary | None = Field(
        default=None, description="Kết quả Quality Gate mới nhất của nguồn giá (vì sao có / không)")
    is_sample: bool
    rules_validated: bool = Field(
        default=False, description="GĐ4: luôn false — luật chưa kiểm chứng bằng backtest (DEC-25)")


def market_view_of(market: MarketDataService, views, reports,
                   now: datetime | None = None) -> MarketViewLatest:
    now = now or utcnow()
    feed = market.feed
    if market.source is None or feed is None:
        return MarketViewLatest(market_view=None, state="NO_SOURCE", is_sample=False)
    scope = Scope.of_feed(market.symbol, market.timeframe, market.source, feed)
    rep = reports.latest_for_scope(scope.key, now) if reports is not None else None
    gate = (GateSummary(verdict=rep.verdict, reasons=list(rep.reasons),
                        evaluated_at=rep.evaluated_at, policy_version=rep.policy_version)
            if rep is not None else None)
    sv = views.latest(scope, known_by=now)
    base = dict(gate=gate, is_sample=market.is_sample)
    if sv is None:
        return MarketViewLatest(market_view=None, state="NONE", **base)
    last = dict(last_as_of=sv.view.as_of, last_expires_at=sv.view.expires_at,
                invalidated_at=sv.invalidated_at, invalidation_reason=sv.reason)
    if sv.invalidated_at is not None:
        return MarketViewLatest(market_view=None, state="INVALIDATED", **last, **base)
    if not sv.view.is_valid_at(now):
        return MarketViewLatest(market_view=None, state="EXPIRED", **last, **base)
    return MarketViewLatest(market_view=sv.view, state="VALID", **last, **base)


def account_market_view_router(
    market_for: Callable[[str], MarketDataService],
    views, reports,
    check: Callable[[str, Principal, str], object],
) -> APIRouter:
    r = APIRouter(prefix="/api/accounts/{account_id}/market-view", tags=["market-view"])

    @r.get("/latest", response_model=MarketViewLatest)
    def latest(account_id: str, p: CurrentUser) -> MarketViewLatest:
        check(account_id, p, "market_view.latest")
        return market_view_of(market_for(account_id), views, reports)

    return r
