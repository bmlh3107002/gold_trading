from datetime import datetime, timedelta

from gold_trading.common.enums import Bias, Regime, Side, SourceStatus
from gold_trading.contracts import AnalystOutput, MarketView, NormalizedRecord, TradeIntent


def record(rid: str, event_time: datetime, ingested_at: datetime, **kw) -> NormalizedRecord:
    defaults = dict(
        record_id=rid,
        source="mt5",
        kind="price",
        event_time=event_time,
        ingested_at=ingested_at,
        source_status=SourceStatus.HEALTHY,
        payload_version="1",
        raw_ref=f"raw/{rid}",
    )
    return NormalizedRecord(**(defaults | kw))


def analyst(aid: str, as_of: datetime, ttl_min: float = 15, **kw) -> AnalystOutput:
    defaults = dict(
        output_id=f"{aid}-{as_of.isoformat()}",
        analyst_id=aid,
        as_of=as_of,
        expires_at=as_of + timedelta(minutes=ttl_min),
        confidence=0.7,
        source_status=SourceStatus.HEALTHY,
        version="0",
        correlation_id="c1",
    )
    return AnalystOutput(**(defaults | kw))


def market_view(as_of: datetime, **kw) -> MarketView:
    defaults = dict(
        market_view_id="mv1",
        snapshot_id="s1",
        as_of=as_of,
        expires_at=as_of + timedelta(minutes=15),
        bias=Bias.LONG,
        p_up=0.6,
        p_down=0.3,
        confidence=0.7,
        regime=Regime.TREND,
        vol_forecast=12.0,
        model_version="0",
    )
    return MarketView(**(defaults | kw))


def intent(created_at: datetime, **kw) -> TradeIntent:
    defaults = dict(
        intent_id="i1",
        strategy_id="trend-m15",
        symbol="XAUUSD",
        side=Side.BUY,
        entry_type="MARKET",
        entry_reference=2400.0,
        stop_loss=2390.0,
        take_profit=2420.0,
        expiry=created_at + timedelta(minutes=2),
        risk_budget_requested=0.005,
        market_view_id="mv1",
        policy_version="p0",
        created_at=created_at,
        reason="test",
        idempotency_key="k1",
        correlation_id="c1",
    )
    return TradeIntent(**(defaults | kw))
