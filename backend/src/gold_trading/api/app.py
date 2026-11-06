"""FastAPI cho Dashboard: trạng thái hệ thống, Safety (kill switch), Mode, audit.

Mọi route bắt buộc đăng nhập (BFF, Keycloak) trừ /api/health, /api/auth/* và cổng Gateway.
Người thực hiện (actor) luôn lấy từ phiên đã xác thực. Xem docs/thiet-ke/00-xac-thuc-phan-quyen.md.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from gold_trading import __version__
from gold_trading.accounts.runtime import AccountRegistry
from gold_trading.analysts.runner import TechnicalRunner
from gold_trading.api.accounts import accounts_router
from gold_trading.api.analysts import analysts_router
from gold_trading.api.ingest import GatewayMonitor, ingest_router
from gold_trading.api.market import market_router
from gold_trading.auth.config import AuthConfig
from gold_trading.auth.oidc import OidcClient
from gold_trading.auth.web import AuthService
from gold_trading.common.enums import TradingMode
from gold_trading.common.time import utcnow
from gold_trading.contracts.candle import DataSource
from gold_trading.contracts.market_view import MarketView
from gold_trading.ingestion.candles import CandleIngestor
from gold_trading.ingestion.sample_feed import SampleFeed
from gold_trading.market.hours import REFERENCE, BrokerSessions, MarketCalendar
from gold_trading.market.service import MarketDataService
from gold_trading.modes.manager import LIVE_CHECKLIST
from gold_trading.storage.analyst_outputs import (
    AnalystOutputStore,
    InMemoryAnalystOutputStore,
    SqlAnalystOutputStore,
)
from gold_trading.storage.candles import CandleStore, InMemoryCandleStore, SqlCandleStore
from gold_trading.storage.repository import (
    AuditEntry,
    InMemoryRepository,
    Member,
    Repository,
    SqlRepository,
)
from gold_trading.storage.schema import DEFAULT_ACCOUNT_ID

POLICY_VERSION = "policy-0.1.0"
log = logging.getLogger("gold_trading.api")


class SystemStatus(BaseModel):
    """Thông tin chung của hệ thống. Trạng thái Safety/Mode nằm ở /api/accounts/{id}/status."""

    version: str
    storage: str = Field(description="memory | postgres — nơi lưu trạng thái vận hành")
    data_source: DataSource | None = Field(description="Nguồn nến đang dùng; None = chưa cấu hình")
    data_is_sample: bool = Field(description="True: đang dùng dữ liệu mẫu, không phải giá thật")
    live_checklist: list[str]
    multi_user_enabled: bool = Field(
        description="False: chưa nhận người dùng thứ hai (chờ ý kiến pháp lý, DEC-12)"
    )


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
    auth: AuthConfig | Literal["env"] = "env",
    oidc: OidcClient | None = None,
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

    repo.ensure_default_account()
    default_mode = TradingMode(os.environ.get("GT_MODE", "PAPER"))
    # Dựng Safety/Mode cho MỌI tài khoản từ lịch sử append-only (quy tắc khôi phục ở runtime.py)
    registry = AccountRegistry(
        repo,
        policy_version=POLICY_VERSION,
        default_mode=default_mode,
        live_unlocked=live_unlocked,
        mode_guard=mode_guard,
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
        registry.start()
        if feed:
            feed.start()
        if runner:
            runner.start()
        yield
        if runner:
            runner.stop()
        if feed:
            feed.stop()
        registry.stop()

    market_view: MarketView | None = None  # TODO: lấy từ Market Intelligence

    def audit(
        actor: str,
        action: str,
        outcome: str,
        payload: dict[str, Any],
        detail: str | None = None,
        *,
        actor_sub: str | None = None,
        account_id: str | None = None,
    ):
        repo.append_audit(
            AuditEntry(utcnow(), actor, action, outcome, payload, detail, account_id, actor_sub)
        )

    def auth_audit(actor, actor_sub, action, outcome, payload, detail):
        audit(actor, action, outcome, payload, detail, actor_sub=actor_sub)

    def on_login(p) -> None:
        """MT-01: lưu hồ sơ người dùng; ADMIN đầu tiên thành OWNER của tài khoản mặc định."""
        now = utcnow()
        repo.upsert_user(p.sub, p.username, p.email, p.display_name, now)
        if p.is_admin and not any(m.role == "OWNER" for m in repo.members(DEFAULT_ACCOUNT_ID)):
            repo.set_member(Member(DEFAULT_ACCOUNT_ID, p.sub, "OWNER", now, "bootstrap"))
            audit(p.username, "account.bootstrap_owner", "ACCEPTED", {"role": "OWNER"},
                  "ADMIN đầu tiên đăng nhập được gán OWNER tài khoản mặc định",
                  actor_sub=p.sub, account_id=DEFAULT_ACCOUNT_ID)

    auth_cfg = AuthConfig.from_env() if auth == "env" else auth
    auth_service = AuthService(
        auth_cfg, oidc or OidcClient(auth_cfg), audit=auth_audit, on_login=on_login
    )

    app = FastAPI(
        title="Gold Trading AI",
        version=__version__,
        lifespan=lifespan,
        dependencies=[Depends(auth_service.dependency())],
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.auth = auth_service
    app.include_router(auth_service.router())
    app.include_router(market_router(market))
    app.include_router(analysts_router(market, analyst_store))
    token = os.environ.get("GT_INGEST_TOKEN") if ingest_token == "env" else ingest_token
    app.include_router(
        ingest_router(market, CandleIngestor(candle_store), GatewayMonitor(), token or None)
    )
    # Chống DNS rebinding: chỉ nhận Host của địa chỉ công khai, localhost và tên nội bộ.
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=sorted({auth_cfg.public_host, "localhost", "127.0.0.1", "backend"}),
    )

    app.include_router(accounts_router(repo, registry, market_view=lambda: market_view))
    app.state.registry = registry

    @app.get("/api/health")
    def health():
        ok = repo.healthy()
        body = {"status": "ok" if ok else "degraded", "storage": repo.kind}
        return body if ok else JSONResponse(body, status_code=503)

    @app.get("/api/status", response_model=SystemStatus)
    def get_status() -> SystemStatus:
        return SystemStatus(
            version=__version__,
            storage=repo.kind,
            data_source=market.source,
            data_is_sample=market.is_sample,
            live_checklist=list(LIVE_CHECKLIST),
            multi_user_enabled=auth_cfg.multi_user_enabled,
        )

    return app
