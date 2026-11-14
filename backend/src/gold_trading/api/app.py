"""FastAPI cho Dashboard: trạng thái hệ thống, Safety (kill switch), Mode, audit.

Mọi route bắt buộc đăng nhập (BFF, Keycloak) trừ /api/health, /api/auth/* và cổng Gateway.
Người thực hiện (actor) luôn lấy từ phiên đã xác thực. Xem docs/thiet-ke/00-xac-thuc-phan-quyen.md.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import Depends, FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from gold_trading import __version__
from gold_trading.accounts.mt5_link import account_feed
from gold_trading.accounts.runtime import AccountRegistry
from gold_trading.analysts.runner import TechnicalRunner
from gold_trading.api.accounts import Guard, accounts_router
from gold_trading.api.analysts import account_analysts_router, analysts_router
from gold_trading.api.data_sources import data_sources_router
from gold_trading.api.ingest import GatewayMonitors, ingest_router
from gold_trading.api.market import account_market_router, account_quote_router, market_router
from gold_trading.api.users import users_router
from gold_trading.auth.config import AuthConfig
from gold_trading.auth.kc_admin import KeycloakAdmin
from gold_trading.auth.oidc import OidcClient
from gold_trading.auth.web import AuthService
from gold_trading.common.enums import TradingMode
from gold_trading.common.time import utcnow
from gold_trading.contracts.candle import DataSource
from gold_trading.contracts.market_view import MarketView
from gold_trading.ingestion.candles import CandleIngestor
from gold_trading.ingestion.external_runner import ExternalSourceRunner, runner_from_env
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.ingestion.sample_feed import SampleFeed
from gold_trading.market.hours import REFERENCE, BrokerSessions, BrokerSpecialHours, MarketCalendar
from gold_trading.market.quotes import QuoteIngestor, QuoteStore
from gold_trading.market.service import MarketDataService
from gold_trading.modes.manager import LIVE_CHECKLIST
from gold_trading.ops.clock import ClockMonitor
from gold_trading.ops.logging import CorrelationMiddleware, configure_logging
from gold_trading.ops.storage_health import backup_info, disk
from gold_trading.orchestrator.model import OrchestratorStore
from gold_trading.orchestrator.runner import OrchestratorRunner, technical_handler
from gold_trading.orchestrator.runner import enabled as orchestrator_enabled
from gold_trading.risk.blocks import BlockStore
from gold_trading.risk.fast_lane import CalendarBlocks, dedupe, fast_lane_handler
from gold_trading.storage.analyst_outputs import (
    AnalystOutputStore,
    InMemoryAnalystOutputStore,
    SqlAnalystOutputStore,
)
from gold_trading.storage.candles import CandleStore, InMemoryCandleStore, SqlCandleStore
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.orchestrator import SqlOrchestratorStore
from gold_trading.storage.quotes import InMemoryQuoteStore, SqlQuoteStore
from gold_trading.storage.repository import (
    AuditEntry,
    InMemoryRepository,
    Repository,
    SqlRepository,
)
from gold_trading.storage.risk_blocks import SqlBlockStore
from gold_trading.storage.source_checks import SqlSourceCheckLog

POLICY_VERSION = "policy-0.1.0"
log = logging.getLogger("gold_trading.api")


class ClockOut(BaseModel):
    state: Literal["OK", "WARN", "BLOCKED", "UNKNOWN"] = Field(
        description="OK ≤ 2 s; WARN 2–30 s; BLOCKED > 30 s (ngừng nhận nến); UNKNOWN chưa đo được"
    )
    offset_s: float | None = Field(description="Đồng hồ backend nhanh hơn giờ chuẩn (giây)")
    sources_ok: int
    measured_at: datetime | None


class DiskOut(BaseModel):
    name: Literal["docker", "backups"]
    used_pct: float | None
    free_gb: float | None
    warn: bool = Field(description="True khi đã dùng > 85%")


class BackupOut(BaseModel):
    state: Literal["OK", "STALE", "FAILED", "MISSING", "DISABLED"]
    last_finished_at: datetime | None
    last_result: str | None
    app_file: str | None
    keycloak_file: str | None
    app_count: int | None
    keycloak_count: int | None


class OpsHealth(BaseModel):
    """Tình trạng vận hành hiển thị trên Dashboard (đồng hồ, ổ đĩa, sao lưu)."""

    clock: ClockOut
    disks: list[DiskOut]
    backup: BackupOut


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
    special_spec = os.environ.get("GT_BROKER_SPECIAL_HOURS", "").strip()
    special_label = os.environ.get("GT_BROKER_SPECIAL_HOURS_VERSION", "").strip()
    if not spec:
        if special_spec:
            raise ValueError("Đã đặt GT_BROKER_SPECIAL_HOURS nhưng thiếu GT_BROKER_SESSIONS")
        _warn_holiday_coverage(REFERENCE)
        return REFERENCE
    if not tz:
        raise ValueError("Đã đặt GT_BROKER_SESSIONS nhưng thiếu GT_BROKER_SERVER_TZ (IANA)")
    broker = BrokerSessions.parse(spec, tz)
    # CAL-05: giờ đặc biệt broker thông báo (giờ server), sai cú pháp → không khởi động
    special = BrokerSpecialHours.parse(special_spec, special_label) if special_spec else None
    if source is None or source.is_sample:
        log.warning("Bỏ qua GT_BROKER_SESSIONS vì nguồn dữ liệu là %s", source)
        return REFERENCE
    cal = MarketCalendar(broker, special=special)
    log.info("Lịch thị trường: %s", cal.description)
    _warn_holiday_coverage(cal)
    return cal


HOLIDAY_COVERAGE_WARN_DAYS = 60


def _warn_holiday_coverage(cal: MarketCalendar, now: datetime | None = None) -> bool:
    """Cảnh báo khi bảng ngày lễ sắp hết năm (ngoài bảng = không biết ngày lễ). True = cảnh báo."""
    now = now or datetime.now(UTC)
    ahead = now + timedelta(days=HOLIDAY_COVERAGE_WARN_DAYS)
    if cal.covers(now) and cal.covers(ahead):
        return False
    log.warning(
        "Bảng ngày lễ (%s) không có dữ liệu cho %s: ngày lễ sẽ bị coi là thiếu nến (R2 có thể "
        "chặn). Cần cập nhật market/holidays.py",
        cal.holidays.version if cal.holidays else "không có",
        ahead.date() if cal.covers(now) else now.date(),
    )
    return True


SAMPLE_BLOCKED_MODES = (TradingMode.SHADOW, TradingMode.LIVE)


def quote_retention_days() -> int:
    """ING-08: số ngày giữ giá sống theo giây (mặc định 30, tối thiểu 1, tối đa 365)."""
    raw = os.environ.get("GT_QUOTE_RETENTION_DAYS", "").strip()
    days = int(raw) if raw else 30
    if not 1 <= days <= 365:
        raise ValueError("GT_QUOTE_RETENTION_DAYS phải từ 1 tới 365")
    return days


def create_app(
    repo: Repository | None = None,
    *,
    candle_store: CandleStore | None = None,
    data_source: DataSource | None | str = "env",
    run_sample_feed: bool | None = None,
    run_analysts: bool | None = None,
    analyst_store: AnalystOutputStore | None = None,
    quote_store: QuoteStore | None = None,
    ingest_token: str | None | Literal["env"] = "env",
    live_unlocked: bool = False,
    calendar: MarketCalendar | Literal["env"] = "env",
    auth: AuthConfig | Literal["env"] = "env",
    oidc: OidcClient | None = None,
    kc_admin: KeycloakAdmin | None = None,
    clock: ClockMonitor | None = None,
    run_clock: bool | None = None,
    external_runner: ExternalSourceRunner | None | Literal["env"] = "env",
) -> FastAPI:
    if os.environ.get("GT_LOG_FORMAT", "").lower() == "json":
        configure_logging(os.environ.get("GT_LOG_LEVEL", "INFO").upper())
    repo = repo or repository_from_env()
    if candle_store is None:
        engine = getattr(repo, "engine", None)
        candle_store = SqlCandleStore(engine) if engine is not None else InMemoryCandleStore()
    if analyst_store is None:
        engine = getattr(repo, "engine", None)
        analyst_store = (
            SqlAnalystOutputStore(engine) if engine is not None else InMemoryAnalystOutputStore()
        )
    if quote_store is None:
        engine = getattr(repo, "engine", None)
        quote_store = SqlQuoteStore(engine) if engine is not None else InMemoryQuoteStore()
    source = data_source_from_env() if data_source == "env" else data_source
    market = MarketDataService(
        candle_store,
        source=source,  # type: ignore[arg-type]
        calendar=calendar_from_env(source) if calendar == "env" else calendar,  # type: ignore[arg-type]
        # MT-05 / DEC-14: với MT5 KHÔNG có nguồn giá chung — màn hình không gắn tài khoản không có
        # dữ liệu; mỗi tài khoản đọc nguồn của mình qua ``market_for``.
        feed_resolver=(lambda: None) if source is DataSource.MT5 else None,
    )

    def market_for(account_id: str) -> MarketDataService:
        if source is DataSource.MT5:
            return market.with_feed(lambda: account_feed(repo, account_id))
        return market.with_feed(None)  # SAMPLE / CSV: một nguồn không gắn broker

    def active_feeds() -> list[str]:
        """Nguồn giá cần chạy analyst: mỗi nguồn đang được ít nhất một tài khoản dùng."""
        if source is not DataSource.MT5:
            return [""]
        return sorted({f for a in repo.accounts() if (f := account_feed(repo, a.account_id))})

    def mode_guard(mode: TradingMode) -> str | None:
        if market.is_sample and mode in SAMPLE_BLOCKED_MODES:
            return f"Đang dùng dữ liệu mẫu: không được chuyển sang {mode}"
        return None

    repo.ensure_default_account()
    default_mode = TradingMode(os.environ.get("GT_MODE", "PAPER"))
    # Dựng Safety/Mode cho MỌI tài khoản từ lịch sử append-only (quy tắc khôi phục ở runtime.py)
    # GĐ2 4a (DEC-20): lệnh cấm có hạn của làn nhanh — Safety đọc theo nguồn giá của tài khoản.
    engine_ = getattr(repo, "engine", None)
    block_store = SqlBlockStore(engine_) if engine_ is not None else BlockStore()
    # GĐ2 4b: cửa sổ lịch kinh tế + 15 phút sau khi nhận số HIGH (tính khi đọc, point-in-time,
    # có trạng thái nguồn). Chỉ khi có DB (bảng lịch nằm trong DB); bộ nhớ: nối ở dưới nếu có.
    calendar_blocks: CalendarBlocks | None = None
    if engine_ is not None:
        calendar_blocks = CalendarBlocks(SqlExternalRecordStore(engine_),
                                         SqlSourceCheckLog(engine_), market.calendar)

    def account_entry_blocks(account_id: str, now):
        feed_ = account_feed(repo, account_id) if source is DataSource.MT5 else ""
        stored = block_store.active(now, feed_)
        cal = calendar_blocks.active(now) if calendar_blocks is not None else []
        return dedupe([*stored, *cal])

    registry = AccountRegistry(
        repo,
        policy_version=POLICY_VERSION,
        default_mode=default_mode,
        live_unlocked=live_unlocked,
        mode_guard=mode_guard,
        entry_blocks=account_entry_blocks,
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
        runner = TechnicalRunner(market, analyst_store, feeds=active_feeds)

    if clock is None:
        srcs = tuple(
            u.strip() for u in os.environ.get("GT_CLOCK_SOURCES", "").split(",") if u.strip()
        )
        clock = ClockMonitor(
            unknown_blocks=os.environ.get("GT_CLOCK_UNKNOWN_BLOCKS", "0") == "1",
            **({"sources": srcs} if srcs else {}),
        )
    if run_clock is None:
        run_clock = os.environ.get("GT_CLOCK_CHECK", "1") != "0"
    if external_runner == "env":
        # Bước 8g: tự nạp lịch kinh tế FOMC / BEA / DOL (GT_EXTERNAL_SOURCES; 0 = tắt).
        # Đồng hồ máy chủ bị chặn → không nạp (giờ sai làm sai thời điểm "đã biết").
        external_runner = runner_from_env(getattr(repo, "engine", None), os.environ,
                                          blocked=clock.ingest_block_reason)
    if calendar_blocks is None and getattr(external_runner, "store", None) is not None:
        calendar_blocks = CalendarBlocks(external_runner.store,
                                         getattr(external_runner, "check_log", None),
                                         market.calendar)

    # GĐ2 bước 3 (ORC-01): Event Orchestrator thay vòng Technical 15 giây (GT_ORCHESTRATOR=0 →
    # quay về runner cũ). Sự kiện suy ra từ dữ liệu đã lưu; nhật ký sự kiện / job trong DB.
    orchestrator: OrchestratorRunner | None = None
    if runner is not None and orchestrator_enabled(os.environ):
        engine = getattr(repo, "engine", None)
        if engine is not None:
            orch_store, record_store = SqlOrchestratorStore(engine), SqlExternalRecordStore(engine)
        else:
            orch_store = OrchestratorStore()
            record_store = (getattr(external_runner, "store", None) if external_runner
                            else None) or PointInTimeStore()
        orchestrator = OrchestratorRunner(
            orch=orch_store, candle_store=candle_store, record_store=record_store,
            analyst_store=analyst_store,
            handlers={"TECHNICAL": technical_handler(runner, active_feeds),
                      # GĐ2 4b (FAST-01..03): số liệu vừa ra + thông cáo Fed → lệnh cấm có hạn
                      "FAST_LANE": fast_lane_handler(block_store, record_store,
                                                     market.calendar)},
            blocked=clock.ingest_block_reason)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        registry.start()
        if run_clock:
            clock.start()
        if feed:
            feed.start()
        if orchestrator:
            orchestrator.start()
        elif runner:
            runner.start()
        if external_runner:
            external_runner.start()
        yield
        if external_runner:
            external_runner.stop()
        if orchestrator:
            orchestrator.stop()
        if runner:
            runner.stop()
        if feed:
            feed.stop()
        clock.stop()
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
        """MT-01: lưu hồ sơ người dùng + vai trò lấy từ Keycloak (DEC-16: ADMIN | USER).

        ADMIN không được gán tài khoản giao dịch nào (khác trước DEC-16)."""
        repo.upsert_user(p.sub, p.username, p.email, p.display_name, utcnow(),
                         role="ADMIN" if p.is_admin else "USER")

    def is_locked(sub: str) -> bool:
        u = repo.user(sub)
        return u is not None and u.status != "ACTIVE"

    auth_cfg = AuthConfig.from_env() if auth == "env" else auth
    auth_service = AuthService(
        auth_cfg, oidc or OidcClient(auth_cfg), audit=auth_audit, on_login=on_login,
        is_locked=is_locked,
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

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, exc: RequestValidationError):
        # Không bao giờ trả lại giá trị đã gửi (mật khẩu, token...): chỉ vị trí + loại lỗi.
        errors = [{k: v for k, v in e.items() if k not in ("input", "ctx", "url")}
                  for e in exc.errors()]
        return JSONResponse({"detail": jsonable_encoder(errors)}, status_code=422)

    app.include_router(auth_service.router())
    app.include_router(market_router(market))
    app.include_router(analysts_router(market, analyst_store))
    app.include_router(data_sources_router(lambda: external_runner or None))
    account_guard = Guard(repo, registry)
    app.include_router(account_market_router(market_for, account_guard.check))
    app.include_router(account_quote_router(
        # Chỉ MT5 có giá sống; SAMPLE/CSV → không có nguồn (không bịa bid/ask từ nến).
        lambda a: account_feed(repo, a) if source is DataSource.MT5 else None,
        quote_store, market.calendar, account_guard.check,
    ))
    app.include_router(account_analysts_router(market_for, analyst_store, account_guard.check))
    token = os.environ.get("GT_INGEST_TOKEN") if ingest_token == "env" else ingest_token
    monitors = GatewayMonitors()
    app.include_router(
        ingest_router(
            market,
            CandleIngestor(candle_store, market.calendar),
            monitors,
            token or None,
            repo,
            ingest_guard=clock.ingest_block_reason,
            quotes=QuoteIngestor(quote_store, market.calendar,
                                 retention=timedelta(days=quote_retention_days())),
        )
    )
    # Chống DNS rebinding: chỉ nhận Host của địa chỉ công khai, localhost và tên nội bộ.
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=sorted({auth_cfg.public_host, "localhost", "127.0.0.1", "backend"}),
    )
    app.add_middleware(CorrelationMiddleware)  # ngoài cùng: mọi request đều có correlation id

    app.include_router(
        accounts_router(
            repo,
            registry,
            market_view=lambda: market_view,
            monitors=monitors,
            legacy_token_configured=bool(token and len(token) >= 24),
        )
    )
    app.include_router(
        users_router(
            repo,
            registry,
            kc_admin or KeycloakAdmin(auth_cfg),
            monitors=monitors,
            revoke_sessions=auth_service.store.delete_by_sub,
            multi_user_enabled=auth_cfg.multi_user_enabled,
        )
    )
    app.state.registry = registry
    app.state.runner = runner  # MT-05: để kiểm tra / chẩn đoán analyst theo từng nguồn
    app.state.orchestrator = orchestrator
    app.state.block_store = block_store

    @app.get("/api/health")
    def health():
        ok = repo.healthy()
        body = {"status": "ok" if ok else "degraded", "storage": repo.kind}
        return body if ok else JSONResponse(body, status_code=503)

    @app.get("/api/system/health", response_model=OpsHealth)
    def ops_health() -> OpsHealth:
        st = clock.status
        bdir = os.environ.get("GT_BACKUP_DIR") or None
        disks = [disk("docker", "/")]
        if bdir:
            disks.append(disk("backups", bdir))
        for d in disks:
            if d.warn:
                log.warning("Ổ đĩa %s đã dùng %.1f%% (> 85%%)", d.name, d.used_pct)
        return OpsHealth(
            clock=ClockOut(**st.__dict__),
            disks=[DiskOut(**d.__dict__) for d in disks],
            backup=BackupOut(**backup_info(bdir).__dict__),
        )

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
