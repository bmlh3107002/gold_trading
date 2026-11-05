"""FastAPI cho Dashboard: trạng thái hệ thống, Safety (kill switch), Mode, audit.

TODO: xác thực cho mọi endpoint ghi (docs/08 yêu cầu kill switch có xác thực).
Cho tới khi có xác thực, chỉ chạy API ở localhost.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gold_trading import __version__
from gold_trading.analysts.runner import TechnicalRunner
from gold_trading.api.analysts import analysts_router
from gold_trading.api.ingest import GatewayMonitor, ingest_router
from gold_trading.api.market import market_router
from gold_trading.common.enums import SafetyState, TradingMode
from gold_trading.common.time import utcnow
from gold_trading.contracts.candle import DataSource
from gold_trading.contracts.market_view import MarketView
from gold_trading.contracts.safety import SafetyTransition
from gold_trading.ingestion.candles import CandleIngestor
from gold_trading.ingestion.sample_feed import SampleFeed
from gold_trading.market.hours import REFERENCE, BrokerSessions, MarketCalendar
from gold_trading.market.service import MarketDataService
from gold_trading.modes.manager import LIVE_CHECKLIST, ModeChangeError, ModeManager
from gold_trading.safety.supervisor import SafetySupervisor, SafetyTransitionError
from gold_trading.storage.analyst_outputs import (
    AnalystOutputStore,
    InMemoryAnalystOutputStore,
    SqlAnalystOutputStore,
)
from gold_trading.storage.candles import CandleStore, InMemoryCandleStore, SqlCandleStore
from gold_trading.storage.repository import (
    AuditEntry,
    InMemoryRepository,
    Repository,
    SqlRepository,
    restore_mode,
    restore_safety_state,
)

POLICY_VERSION = "policy-0.1.0"
log = logging.getLogger("gold_trading.api")


class SystemStatus(BaseModel):
    version: str
    storage: str = Field(description="memory | postgres — nơi lưu trạng thái vận hành")
    data_source: DataSource | None = Field(description="Nguồn nến đang dùng; None = chưa cấu hình")
    data_is_sample: bool = Field(description="True: đang dùng dữ liệu mẫu, không phải giá thật")
    mode: TradingMode
    live_unlocked: bool
    live_checklist: list[str]
    safety_state: SafetyState
    allows_new_orders: bool
    safety_history: list[SafetyTransition]
    market_view: MarketView | None


class SafetyCommand(BaseModel):
    action: Literal["pause", "halt", "resume"]
    reason_code: str = Field(min_length=1, max_length=128)
    actor: str = Field(min_length=1, max_length=128)
    operator_approved: bool = False


class ModeCommand(BaseModel):
    mode: TradingMode
    actor: str = Field(min_length=1, max_length=128)
    approver: str | None = Field(default=None, max_length=128)
    checklist: dict[str, bool] = Field(default_factory=dict)


class AuditRecord(BaseModel):
    at: datetime
    actor: str
    action: str
    outcome: Literal["ACCEPTED", "REJECTED", "NOOP"]
    payload: dict[str, Any]
    detail: str | None = None


def repository_from_env() -> Repository:
    url = os.environ.get("DATABASE_URL")
    if not url:
        log.warning("DATABASE_URL chưa đặt: dùng bộ nhớ, restart sẽ mất trạng thái")
        return InMemoryRepository()
    return SqlRepository.from_url(url)


def data_source_from_env() -> DataSource | None:
    raw = os.environ.get("GT_DATA_SOURCE", "").strip().upper()
    if not raw or raw == "NONE":
        return None
    return DataSource(raw)


def calendar_from_env(source: DataSource | None) -> MarketCalendar:
    """Lịch broker từ ``GT_BROKER_SESSIONS`` + ``GT_BROKER_SERVER_TZ`` (giờ server, IANA).

    Chỉ áp dụng cho dữ liệu thật (MT5/CSV). Cấu hình sai → lỗi khi khởi động, không đoán.
    Dữ liệu mẫu được sinh theo lịch tham chiếu nên luôn dùng lịch tham chiếu.
    """
    spec = os.environ.get("GT_BROKER_SESSIONS", "").strip()
    tz = os.environ.get("GT_BROKER_SERVER_TZ", "").strip()
    if not spec:
        return REFERENCE
    if not tz:
        raise ValueError("Đã đặt GT_BROKER_SESSIONS nhưng thiếu GT_BROKER_SERVER_TZ (IANA)")
    broker = BrokerSessions.parse(spec, tz)
    if source is None or source.is_sample:
        log.warning("Bỏ qua GT_BROKER_SESSIONS vì nguồn dữ liệu là %s", source)
        return REFERENCE
    cal = MarketCalendar(broker)
    log.info("Lịch thị trường: %s", cal.description)
    return cal


SAMPLE_BLOCKED_MODES = (TradingMode.SHADOW, TradingMode.LIVE)


def create_app(
    repo: Repository | None = None,
    *,
    candle_store: CandleStore | None = None,
    data_source: DataSource | None | str = "env",
    run_sample_feed: bool | None = None,
    run_analysts: bool | None = None,
    analyst_store: AnalystOutputStore | None = None,
    ingest_token: str | None | Literal["env"] = "env",
    live_unlocked: bool = False,
    calendar: MarketCalendar | Literal["env"] = "env",
) -> FastAPI:
    repo = repo or repository_from_env()
    if candle_store is None:
        engine = getattr(repo, "engine", None)
        candle_store = SqlCandleStore(engine) if engine is not None else InMemoryCandleStore()
    if analyst_store is None:
        engine = getattr(repo, "engine", None)
        analyst_store = (
            SqlAnalystOutputStore(engine) if engine is not None else InMemoryAnalystOutputStore()
        )
    source = data_source_from_env() if data_source == "env" else data_source
    market = MarketDataService(
        candle_store,
        source=source,  # type: ignore[arg-type]
        calendar=calendar_from_env(source) if calendar == "env" else calendar,  # type: ignore[arg-type]
    )

    def mode_guard(mode: TradingMode) -> str | None:
        if market.is_sample and mode in SAMPLE_BLOCKED_MODES:
            return f"Đang dùng dữ liệu mẫu: không được chuyển sang {mode}"
        return None

    # --- Dựng lại trạng thái từ lịch sử append-only ---
    history = repo.safety_history()
    start_state, downgrade_reason = restore_safety_state(history)
    safety = SafetySupervisor(
        POLICY_VERSION, initial_state=start_state, history=history, persist=repo.append_safety
    )
    if downgrade_reason:
        safety.pause(downgrade_reason, trigger_source="startup", actor="system")

    default_mode = TradingMode(os.environ.get("GT_MODE", "PAPER"))
    if default_mode is TradingMode.LIVE or mode_guard(default_mode):
        default_mode = TradingMode.PAPER
    start_mode, relocked = restore_mode(repo.last_mode(), default_mode)
    if relocked:
        repo.append_audit(
            AuditEntry(
                utcnow(),
                "system",
                "mode.startup",
                "ACCEPTED",
                {"from": "LIVE", "to": "PAPER"},
                "LIVE không được khôi phục tự động sau restart",
            )
        )
    if (reason := mode_guard(start_mode)) is not None:
        repo.append_audit(
            AuditEntry(
                utcnow(),
                "system",
                "mode.startup",
                "ACCEPTED",
                {"from": start_mode.value, "to": "PAPER"},
                reason,
            )
        )
        start_mode = TradingMode.PAPER
    modes = ModeManager(
        start_mode, live_unlocked=live_unlocked, on_change=repo.append_mode, guard=mode_guard
    )

    feed: SampleFeed | None = None
    if run_sample_feed is None:
        run_sample_feed = source is DataSource.SAMPLE
    if run_sample_feed and source is DataSource.SAMPLE:
        feed = SampleFeed(
            candle_store,
            history_days=int(os.environ.get("GT_SAMPLE_HISTORY_DAYS", "90")),
            start_price=float(os.environ.get("GT_SAMPLE_START_PRICE", "2400")),
        )

    runner: TechnicalRunner | None = None
    if run_analysts is None:
        run_analysts = source is not None and os.environ.get("GT_RUN_ANALYSTS", "1") != "0"
    if run_analysts and source is not None:
        runner = TechnicalRunner(market, analyst_store)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if feed:
            feed.start()
        if runner:
            runner.start()
        yield
        if runner:
            runner.stop()
        if feed:
            feed.stop()

    market_view: MarketView | None = None  # TODO: lấy từ Market Intelligence

    app = FastAPI(title="Gold Trading AI", version=__version__, lifespan=lifespan)
    app.include_router(market_router(market))
    app.include_router(analysts_router(market, analyst_store))
    token = os.environ.get("GT_INGEST_TOKEN") if ingest_token == "env" else ingest_token
    app.include_router(
        ingest_router(market, CandleIngestor(candle_store), GatewayMonitor(), token or None)
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    def status() -> SystemStatus:
        return SystemStatus(
            version=__version__,
            storage=repo.kind,
            data_source=market.source,
            data_is_sample=market.is_sample,
            mode=modes.mode,
            live_unlocked=modes.live_unlocked,
            live_checklist=list(LIVE_CHECKLIST),
            safety_state=safety.state,
            allows_new_orders=safety.allows_new_orders(),
            safety_history=list(safety.history)[-200:],
            market_view=market_view,
        )

    def audit(
        actor: str, action: str, outcome: str, payload: dict[str, Any], detail: str | None = None
    ):
        repo.append_audit(AuditEntry(utcnow(), actor, action, outcome, payload, detail))

    @app.get("/api/health")
    def health():
        ok = repo.healthy()
        body = {"status": "ok" if ok else "degraded", "storage": repo.kind}
        return body if ok else JSONResponse(body, status_code=503)

    @app.get("/api/status", response_model=SystemStatus)
    def get_status() -> SystemStatus:
        return status()

    @app.get("/api/audit", response_model=list[AuditRecord])
    def get_audit(limit: int = 100) -> list[AuditRecord]:
        return [AuditRecord(**e.__dict__) for e in repo.audit(min(max(limit, 1), 500))]

    @app.post("/api/safety", response_model=SystemStatus)
    def safety_command(cmd: SafetyCommand) -> SystemStatus:
        kwargs = {"trigger_source": "dashboard", "actor": cmd.actor}
        payload = cmd.model_dump()
        try:
            if cmd.action == "pause":
                event = safety.pause(cmd.reason_code, **kwargs)
            elif cmd.action == "halt":
                event = safety.halt(cmd.reason_code, **kwargs)
            else:
                event = safety.resume(
                    cmd.reason_code, operator_approved=cmd.operator_approved, **kwargs
                )
        except SafetyTransitionError as e:
            audit(cmd.actor, f"safety.{cmd.action}", "REJECTED", payload, str(e))
            raise HTTPException(status_code=409, detail=str(e)) from e
        audit(cmd.actor, f"safety.{cmd.action}", "ACCEPTED" if event else "NOOP", payload)
        return status()

    @app.post("/api/mode", response_model=SystemStatus)
    def mode_command(cmd: ModeCommand) -> SystemStatus:
        payload = cmd.model_dump(mode="json")
        try:
            change = modes.set_mode(
                cmd.mode, actor=cmd.actor, approver=cmd.approver, checklist=cmd.checklist
            )
        except ModeChangeError as e:
            audit(cmd.actor, "mode.set", "REJECTED", payload, str(e))
            raise HTTPException(status_code=409, detail=str(e)) from e
        audit(cmd.actor, "mode.set", "ACCEPTED" if change else "NOOP", payload)
        return status()

    return app
