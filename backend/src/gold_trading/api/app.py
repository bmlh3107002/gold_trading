"""FastAPI cho Dashboard: trạng thái hệ thống, Safety (kill switch), Mode, audit.

TODO: xác thực cho mọi endpoint ghi (docs/08 yêu cầu kill switch có xác thực).
Cho tới khi có xác thực, chỉ chạy API ở localhost.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gold_trading import __version__
from gold_trading.common.enums import SafetyState, TradingMode
from gold_trading.common.time import utcnow
from gold_trading.contracts.market_view import MarketView
from gold_trading.contracts.safety import SafetyTransition
from gold_trading.modes.manager import LIVE_CHECKLIST, ModeChangeError, ModeManager
from gold_trading.safety.supervisor import SafetySupervisor, SafetyTransitionError
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


def create_app(repo: Repository | None = None, *, live_unlocked: bool = False) -> FastAPI:
    repo = repo or repository_from_env()

    # --- Dựng lại trạng thái từ lịch sử append-only ---
    history = repo.safety_history()
    start_state, downgrade_reason = restore_safety_state(history)
    safety = SafetySupervisor(
        POLICY_VERSION, initial_state=start_state, history=history, persist=repo.append_safety
    )
    if downgrade_reason:
        safety.pause(downgrade_reason, trigger_source="startup", actor="system")

    default_mode = TradingMode(os.environ.get("GT_MODE", "PAPER"))
    if default_mode is TradingMode.LIVE:
        default_mode = TradingMode.PAPER
    start_mode, relocked = restore_mode(repo.last_mode(), default_mode)
    modes = ModeManager(start_mode, live_unlocked=live_unlocked, on_change=repo.append_mode)
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

    market_view: MarketView | None = None  # TODO: lấy từ Market Intelligence

    app = FastAPI(title="Gold Trading AI", version=__version__)
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
