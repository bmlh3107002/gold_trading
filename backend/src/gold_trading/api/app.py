"""FastAPI cho Dashboard: trạng thái hệ thống, Safety (kill switch), Mode.

TODO: xác thực + audit cho mọi endpoint ghi (docs/08 yêu cầu kill switch có xác thực).
Cho tới khi có xác thực, chỉ chạy API ở localhost.
"""

from __future__ import annotations

import os
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from gold_trading import __version__
from gold_trading.common.enums import SafetyState, TradingMode
from gold_trading.contracts.market_view import MarketView
from gold_trading.contracts.safety import SafetyTransition
from gold_trading.modes.manager import LIVE_CHECKLIST, ModeChangeError, ModeManager
from gold_trading.safety.supervisor import SafetySupervisor, SafetyTransitionError

POLICY_VERSION = "policy-0.1.0"


class SystemStatus(BaseModel):
    version: str
    mode: TradingMode
    live_unlocked: bool
    live_checklist: list[str]
    safety_state: SafetyState
    allows_new_orders: bool
    safety_history: list[SafetyTransition]
    market_view: MarketView | None


class SafetyCommand(BaseModel):
    action: Literal["pause", "halt", "resume"]
    reason_code: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    operator_approved: bool = False


class ModeCommand(BaseModel):
    mode: TradingMode
    actor: str = Field(min_length=1)
    approver: str | None = None
    checklist: dict[str, bool] = Field(default_factory=dict)


def create_app(safety: SafetySupervisor | None = None, modes: ModeManager | None = None) -> FastAPI:
    safety = safety or SafetySupervisor(policy_version=POLICY_VERSION)
    modes = modes or ModeManager(
        TradingMode(os.environ.get("GT_MODE", "PAPER")),
        live_unlocked=False,
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
            mode=modes.mode,
            live_unlocked=modes.live_unlocked,
            live_checklist=list(LIVE_CHECKLIST),
            safety_state=safety.state,
            allows_new_orders=safety.allows_new_orders(),
            safety_history=list(safety.history),
            market_view=market_view,
        )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/status", response_model=SystemStatus)
    def get_status() -> SystemStatus:
        return status()

    @app.post("/api/safety", response_model=SystemStatus)
    def safety_command(cmd: SafetyCommand) -> SystemStatus:
        kwargs = {"trigger_source": "dashboard", "actor": cmd.actor}
        try:
            if cmd.action == "pause":
                safety.pause(cmd.reason_code, **kwargs)
            elif cmd.action == "halt":
                safety.halt(cmd.reason_code, **kwargs)
            else:
                safety.resume(cmd.reason_code, operator_approved=cmd.operator_approved, **kwargs)
        except SafetyTransitionError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        return status()

    @app.post("/api/mode", response_model=SystemStatus)
    def mode_command(cmd: ModeCommand) -> SystemStatus:
        try:
            modes.set_mode(
                cmd.mode, actor=cmd.actor, approver=cmd.approver, checklist=cmd.checklist
            )
        except ModeChangeError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        return status()

    return app


app = create_app()
