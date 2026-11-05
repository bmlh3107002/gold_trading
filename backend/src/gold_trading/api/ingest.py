"""Cổng nhận dữ liệu từ MT5 Gateway (chỉ đọc). Xem docs/thiet-ke/09a-mt5-gateway-chi-doc.md.

Bắt buộc token (GT_INGEST_TOKEN). Không đặt token thì cổng TẮT.
"""

from __future__ import annotations

import hmac
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from gold_trading.common.time import UtcDatetime, utcnow
from gold_trading.contracts.candle import DataSource
from gold_trading.ingestion.candles import CandleIngestor, RawBar
from gold_trading.ingestion.sources.csv_file import SESSION_MISMATCH_MAX, check_sessions
from gold_trading.market.service import MarketDataService
from gold_trading.storage.candles import InMemoryCandleStore

MIN_TOKEN_LEN = 24
MAX_BARS = 2000
HEARTBEAT_TIMEOUT = timedelta(seconds=30)


class BarIn(BaseModel):
    open_time: UtcDatetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int = 0
    spread_points: int | None = None


class CandleBatch(BaseModel):
    symbol: str
    timeframe: Literal["M15"]
    backfill: bool
    gateway_id: str = Field(min_length=1, max_length=64)
    bars: list[BarIn] = Field(max_length=MAX_BARS)


class IngestReport(BaseModel):
    dry_run: bool
    received: int
    accepted: int
    duplicates: int
    revised: int
    quarantined: int
    reasons: dict[str, int]
    session_outside_fraction: float | None = None
    session_best_shift_hours: int | None = None


class SymbolSpec(BaseModel):
    broker_symbol: str
    digits: int
    point: float
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    currency_profit: str | None = None


class Heartbeat(BaseModel):
    gateway_id: str = Field(min_length=1, max_length=64)
    gateway_version: str
    read_only: Literal[True]
    terminal_connected: bool
    account_type: Literal["DEMO", "CONTEST", "REAL", "UNKNOWN"]
    server: str | None = None
    company: str | None = None
    server_tz: str
    server_offset_hours_now: int | None = None
    last_tick_time: UtcDatetime | None = None
    symbol: SymbolSpec | None = None
    last_sent_bar: UtcDatetime | None = None


class GatewayStatus(BaseModel):
    state: Literal["NEVER", "CONNECTED", "DISCONNECTED"]
    last_seen_at: datetime | None
    age_seconds: float | None
    heartbeat: Heartbeat | None


@dataclass
class GatewayMonitor:
    last: Heartbeat | None = None
    last_seen_at: datetime | None = None

    def __post_init__(self) -> None:
        self._lock = threading.Lock()

    def record(self, hb: Heartbeat, at: datetime) -> None:
        with self._lock:
            self.last, self.last_seen_at = hb, at

    def status(self, now: datetime) -> GatewayStatus:
        with self._lock:
            if self.last_seen_at is None:
                return GatewayStatus(
                    state="NEVER", last_seen_at=None, age_seconds=None, heartbeat=None
                )
            age = now - self.last_seen_at
            state = (
                "CONNECTED"
                if age <= HEARTBEAT_TIMEOUT and self.last and self.last.terminal_connected
                else "DISCONNECTED"
            )
            return GatewayStatus(
                state=state,
                last_seen_at=self.last_seen_at,
                age_seconds=round(age.total_seconds(), 1),
                heartbeat=self.last,
            )


def ingest_router(
    market: MarketDataService,
    ingestor: CandleIngestor,
    monitor: GatewayMonitor,
    token: str | None,
) -> APIRouter:
    r = APIRouter(tags=["ingest"])

    def authorize(authorization: str | None) -> None:
        if not token or len(token) < MIN_TOKEN_LEN:
            raise HTTPException(
                503, "Cổng nhận dữ liệu đang tắt: chưa đặt GT_INGEST_TOKEN (>= 24 ký tự)"
            )
        prefix = "Bearer "
        given = (
            authorization[len(prefix) :]
            if authorization and authorization.startswith(prefix)
            else ""
        )
        if not hmac.compare_digest(given.encode(), token.encode()):
            raise HTTPException(401, "Token không hợp lệ")

    @r.post("/api/ingest/mt5/candles", response_model=IngestReport)
    def ingest_candles(
        batch: CandleBatch,
        authorization: Annotated[str | None, Header()] = None,
        dry_run: Annotated[bool, Query()] = False,
    ) -> IngestReport:
        authorize(authorization)
        if batch.symbol != market.symbol:
            raise HTTPException(422, f"Symbol phải là {market.symbol}")
        bars = [
            RawBar(
                open_time=b.open_time,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                tick_volume=b.tick_volume,
                spread_points=b.spread_points,
            )
            for b in batch.bars
        ]
        chk = check_sessions(bars, 15)
        extra: dict[str, Any] = {
            "session_outside_fraction": round(chk.outside_fraction, 4),
            "session_best_shift_hours": chk.best_shift_hours,
        }
        if batch.backfill and not chk.ok:
            raise HTTPException(
                422,
                f"Từ chối: {chk.outside_fraction:.1%} số nến rơi vào giờ đóng cửa (tối đa "
                f"{SESSION_MISMATCH_MAX:.0%}). Múi giờ server khai báo cho Gateway có thể sai; "
                f"dữ liệu khớp lịch nhất khi lệch thêm {chk.best_shift_hours:+d} giờ.",
            )
        target = ingestor
        if dry_run:
            # Chạy toàn bộ kiểm tra trên một kho tạm, có sẵn nến hiện có để khử trùng giống thật
            target = CandleIngestor(_DryRunStore(ingestor.store))
        res = target.ingest(
            bars,
            symbol=batch.symbol,
            timeframe=market.timeframe,
            source=DataSource.MT5,
            ingested_at=utcnow(),
            backfill=batch.backfill,
        )
        return IngestReport(
            dry_run=dry_run,
            received=len(bars),
            accepted=res.accepted,
            duplicates=res.duplicates,
            revised=res.revised,
            quarantined=res.quarantined,
            reasons=res.reasons,
            **extra,
        )

    @r.post("/api/ingest/mt5/heartbeat", response_model=GatewayStatus)
    def heartbeat(
        hb: Heartbeat, authorization: Annotated[str | None, Header()] = None
    ) -> GatewayStatus:
        authorize(authorization)
        now = utcnow()
        monitor.record(hb, now)
        return monitor.status(now)

    @r.get("/api/gateway/status", response_model=GatewayStatus)
    def gateway_status() -> GatewayStatus:
        return monitor.status(utcnow())

    return r


class _DryRunStore(InMemoryCandleStore):
    """Đọc từ kho thật, ghi vào bộ nhớ (bỏ đi sau khi trả lời)."""

    def __init__(self, real) -> None:
        super().__init__()
        self._real = real

    def latest_by_open_time(self, symbol, tf, source, lo, hi):
        return self._real.latest_by_open_time(symbol, tf, source, lo, hi)

    def last_before(self, symbol, tf, source, t):
        return self._real.last_before(symbol, tf, source, t)
