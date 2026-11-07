"""Cổng nhận dữ liệu từ MT5 Gateway (chỉ đọc). Xem docs/thiet-ke/09a-mt5-gateway-chi-doc.md.

Xác thực bằng token Gateway RIÊNG TỪNG TÀI KHOẢN (MT-04, lưu dạng băm trong DB, xoay trên giao
diện). Token cũ ``GT_INGEST_TOKEN`` vẫn được nhận cho tài khoản mặc định tới khi tài khoản đó
có token đầu tiên trong DB. Không có token nào → cổng TẮT (503).
"""

from __future__ import annotations

import hmac
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import SQLAlchemyError

from gold_trading.accounts.access import account_locked
from gold_trading.accounts.mt5_link import observe_identity
from gold_trading.common.time import UtcDatetime, utcnow
from gold_trading.contracts.candle import DataSource
from gold_trading.ingestion.candles import CandleIngestor, RawBar, TailStatus, tail_status
from gold_trading.ingestion.sources.csv_file import SESSION_MISMATCH_MAX, check_sessions
from gold_trading.market.service import MarketDataService
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.candles import InMemoryCandleStore
from gold_trading.storage.repository import Repository
from gold_trading.storage.schema import DEFAULT_ACCOUNT_ID

log = logging.getLogger("gold_trading.ingest")

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
    # Không bắt buộc. Nếu gửi thì phải đúng tài khoản của token (MT-C02).
    account_id: str | None = Field(default=None, max_length=64)
    symbol: str
    # ING-14: khung Gateway được gửi. H4/D1 căn theo giờ server broker → bắt buộc kèm server_tz.
    timeframe: Literal["M15", "H1", "H4", "D1"]
    # Múi giờ server broker (IANA), cùng giá trị Gateway dùng để đổi giờ. Bắt buộc với H4/D1.
    server_tz: str | None = Field(default=None, max_length=64)
    backfill: bool
    gateway_id: str = Field(min_length=1, max_length=64)
    bars: list[BarIn] = Field(max_length=MAX_BARS)
    # 1A-C21: nến ở VỊ TRÍ 0 của MT5 (có thể còn đang chạy). Backend tự quyết theo đồng hồ của
    # mình + lịch broker có coi là đã đóng không (xem ``tail_status``); không thì bỏ qua, không lưu.
    # Chỉ dùng với lô realtime (backfill=false).
    tail_bar: BarIn | None = None


def _bar(b: BarIn) -> RawBar:
    return RawBar(
        open_time=b.open_time,
        open=b.open,
        high=b.high,
        low=b.low,
        close=b.close,
        tick_volume=b.tick_volume,
        spread_points=b.spread_points,
    )


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
    # 1A-C21: số phận của ``tail_bar`` (NONE nếu không gửi)
    tail: TailStatus = TailStatus.NONE


_FINITE = ConfigDict(allow_inf_nan=False)
AccountType = Literal["DEMO", "CONTEST", "REAL", "UNKNOWN"]


class SymbolSpec(BaseModel):
    model_config = _FINITE
    broker_symbol: str = Field(max_length=64)
    digits: int = Field(ge=0, le=12)
    point: float = Field(gt=0)
    contract_size: float = Field(gt=0)
    volume_min: float = Field(gt=0)
    volume_max: float = Field(gt=0)
    volume_step: float = Field(gt=0)
    currency_profit: str | None = Field(default=None, max_length=16)
    # GW-09 (Gateway ≥ 0.3): None = Gateway cũ hoặc MT5 không trả được, KHÔNG phải 0.
    # Phí commission: MT5 không cung cấp qua symbol_info → không có trường này (không đoán).
    stops_level: int | None = Field(default=None, ge=0)
    freeze_level: int | None = Field(default=None, ge=0)
    swap_mode: int | None = Field(default=None, ge=0)
    swap_long: float | None = None
    swap_short: float | None = None
    swap_rollover3days: int | None = Field(default=None, ge=0, le=6)


class Mt5Identity(BaseModel):
    """MT-12: danh tính MT5 = ``(login, server)`` do terminal báo (không phải người dùng gõ)."""

    login: int = Field(gt=0, le=2**63 - 1)
    server: str = Field(min_length=1, max_length=256)
    company: str | None = Field(default=None, max_length=256)
    account_type: AccountType
    terminal_name: str | None = Field(default=None, max_length=256)
    terminal_path: str | None = Field(default=None, max_length=256)


class AccountSnapshot(BaseModel):
    """GW-09: số liệu tài khoản MT5 lúc gửi nhịp tim (chỉ đọc). Trường None = không đọc được."""

    model_config = _FINITE
    currency: str | None = Field(default=None, max_length=16)
    balance: float | None = None
    equity: float | None = None
    margin: float | None = Field(default=None, ge=0)
    margin_free: float | None = None
    # None khi margin = 0 (không có vị thế): mức ký quỹ không xác định
    margin_level: float | None = Field(default=None, ge=0)
    leverage: int | None = Field(default=None, gt=0)
    trade_allowed: bool | None = None


class Heartbeat(BaseModel):
    account_id: str | None = Field(default=None, max_length=64)
    gateway_id: str = Field(min_length=1, max_length=64)
    gateway_version: str = Field(max_length=32)
    read_only: Literal[True]
    terminal_connected: bool
    account_type: AccountType
    server: str | None = Field(default=None, max_length=256)
    company: str | None = Field(default=None, max_length=256)
    # MT-12 / GW-09 (Gateway ≥ 0.3). None = Gateway cũ, hoặc terminal chưa đăng nhập / đọc lỗi.
    identity: Mt5Identity | None = None
    account: AccountSnapshot | None = None
    server_tz: str = Field(max_length=64)
    server_offset_hours_now: int | None = None
    last_tick_time: UtcDatetime | None = None
    symbol: SymbolSpec | None = None
    last_sent_bar: UtcDatetime | None = None
    timeframes: list[Literal["M15", "H1", "H4", "D1"]] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def _identity_consistent(self) -> Heartbeat:
        """Trường cũ (server/account_type) và ``identity`` phải cùng một lần đọc. Lệch → dữ liệu
        hỏng/giả mạo: từ chối cả nhịp tim (an toàn hơn chọn một bên)."""
        i = self.identity
        if i is not None and (i.server != self.server or i.account_type != self.account_type):
            raise ValueError("identity mâu thuẫn với server/account_type")
        if i is None and self.account is not None:
            raise ValueError("có số liệu tài khoản nhưng không có danh tính MT5")
        return self


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


class GatewayMonitors:
    """Trạng thái Gateway theo từng tài khoản."""

    def __init__(self) -> None:
        self._m: dict[str, GatewayMonitor] = {}
        self._lock = threading.Lock()

    def get(self, account_id: str) -> GatewayMonitor:
        with self._lock:
            return self._m.setdefault(account_id, GatewayMonitor())


def ingest_router(
    market: MarketDataService,
    ingestor: CandleIngestor,
    monitors: GatewayMonitors,
    token: str | None,
    repo: Repository,
    ingest_guard: Callable[[], str | None] | None = None,
) -> APIRouter:
    """``ingest_guard()`` trả lý do nếu phải ngừng nhận nến (ví dụ đồng hồ lệch, OPS-12)."""
    r = APIRouter(tags=["ingest"])
    legacy = token if token and len(token) >= MIN_TOKEN_LEN else None

    def authorize(authorization: str | None, claimed: str | None) -> tuple[str, str | None]:
        """Trả ``(account_id, token_id)`` của token (token_id None = token cũ GT_INGEST_TOKEN).
        Không bao giờ tin account_id do Gateway tự khai."""
        prefix = "Bearer "
        given = (
            authorization[len(prefix) :]
            if authorization and authorization.startswith(prefix)
            else ""
        )
        found = repo.gateway_token(given) if given else None
        account_id, token_id = found if found else (None, None)
        if account_id is None and legacy and not repo.has_gateway_tokens(DEFAULT_ACCOUNT_ID):
            if hmac.compare_digest(given.encode(), legacy.encode()):
                account_id = DEFAULT_ACCOUNT_ID
        if account_id is None:
            if legacy is None and not any(
                repo.has_gateway_tokens(a.account_id) for a in repo.accounts()
            ):
                raise HTTPException(
                    503, "Cổng nhận dữ liệu đang tắt: chưa có token Gateway nào "
                    "(tạo trên giao diện, hoặc đặt GT_INGEST_TOKEN >= 24 ký tự)"
                )
            raise HTTPException(401, "Token không hợp lệ")
        if claimed is not None and claimed != account_id:
            raise HTTPException(403, "Token không thuộc tài khoản này")
        if account_locked(repo, account_id):
            # DEC-16: USER bị khóa → Gateway của họ bị từ chối hoàn toàn (cả nhịp tim).
            raise HTTPException(403, "Người dùng của tài khoản này đang bị khóa")
        return account_id, token_id

    @r.post("/api/ingest/mt5/candles", response_model=IngestReport)
    def ingest_candles(
        batch: CandleBatch,
        authorization: Annotated[str | None, Header()] = None,
        dry_run: Annotated[bool, Query()] = False,
    ) -> IngestReport:
        account_id, _ = authorize(authorization, batch.account_id)
        acc = repo.account(account_id)
        if acc is None or not acc.price_feed:
            # Tới MT-05 (GĐ1) chỉ tài khoản nguồn giá được ghi vào kho nến dùng chung.
            raise HTTPException(403, "Tài khoản này chưa được phép ghi nến dùng chung")
        if ingest_guard and (reason := ingest_guard()):
            raise HTTPException(503, reason)
        if batch.symbol != market.symbol:
            raise HTTPException(422, f"Symbol phải là {market.symbol}")
        tf = Timeframe(batch.timeframe)
        server_tz: ZoneInfo | None = None
        if batch.server_tz is not None:
            try:
                server_tz = ZoneInfo(batch.server_tz)
            except (ZoneInfoNotFoundError, ValueError):
                raise HTTPException(
                    422, f"server_tz không hợp lệ: {batch.server_tz!r} (cần tên IANA)"
                ) from None
        if tf.server_aligned and server_tz is None:
            # 1A-C19: không đoán ranh giới nến H4/D1 theo UTC.
            raise HTTPException(422, f"Khung {tf} cần server_tz (múi giờ server broker)")
        broker = market.calendar.broker
        if tf.server_aligned and broker is not None and broker.tz.key != server_tz.key:
            # Hai cấu hình múi giờ server khác nhau → không biết ranh giới nào đúng: từ chối.
            raise HTTPException(
                422,
                f"server_tz của Gateway ({server_tz.key}) khác GT_BROKER_SERVER_TZ của backend "
                f"({broker.tz.key}): sửa cho giống nhau",
            )
        bars = [_bar(b) for b in batch.bars]
        now = utcnow()
        tail = TailStatus.NONE
        if batch.tail_bar is not None:
            if batch.backfill:
                raise HTTPException(422, "tail_bar chỉ dùng với lô realtime (backfill=false)")
            latest = max((b.open_time for b in bars), default=None)
            tail = tail_status(
                batch.tail_bar.open_time, latest, tf, now, market.calendar, server_tz
            )
            if tail is TailStatus.INCLUDED:
                # Đi qua đúng các bước kiểm tra như nến thường (OHLC, căn khung, khử trùng…)
                bars.append(_bar(batch.tail_bar))
        extra: dict[str, Any] = {}
        # R1 (kiểm tra múi giờ) chỉ có nghĩa với nến ngắn nằm trọn trong phiên (M15, H1). Nến
        # H4/D1 vắt qua giờ nghỉ; múi giờ đã được R1 kiểm trên M15/H1 của cùng Gateway.
        chk = None if tf.server_aligned else check_sessions(bars, tf.minutes, market.calendar)
        if chk is not None:
            extra = {
                "session_outside_fraction": round(chk.outside_fraction, 4),
                "session_best_shift_hours": chk.best_shift_hours,
            }
        if chk is not None and batch.backfill and not chk.ok:
            raise HTTPException(
                422,
                f"Từ chối: {chk.outside_fraction:.1%} số nến rơi vào giờ đóng cửa (tối đa "
                f"{SESSION_MISMATCH_MAX:.0%}). Múi giờ server khai báo cho Gateway có thể sai; "
                f"dữ liệu khớp lịch nhất khi lệch thêm {chk.best_shift_hours:+d} giờ.",
            )
        target = ingestor
        if dry_run:
            # Chạy toàn bộ kiểm tra trên một kho tạm, có sẵn nến hiện có để khử trùng giống thật
            target = CandleIngestor(_DryRunStore(ingestor.store), ingestor.calendar)
        try:
            res = target.ingest(
                bars,
                symbol=batch.symbol,
                timeframe=tf,
                source=DataSource.MT5,
                ingested_at=now,
                backfill=batch.backfill,
                server_tz=server_tz,
            )
        except SQLAlchemyError as e:
            # 0-C05: ổ đầy / DB lỗi. Cả lô nằm trong một transaction nên không ghi dở;
            # nến đã ghi trước đó không mất. Gateway sẽ gửi lại.
            log.error("Không ghi được nến vào DB: %s", type(e).__name__)
            raise HTTPException(
                503, "Lưu trữ đang lỗi (có thể ổ đĩa đầy): chưa ghi lô nến này, Gateway sẽ gửi lại"
            ) from e
        return IngestReport(
            dry_run=dry_run,
            received=len(bars),
            accepted=res.accepted,
            duplicates=res.duplicates,
            revised=res.revised,
            quarantined=res.quarantined,
            reasons=res.reasons,
            tail=tail,
            **extra,
        )

    @r.post("/api/ingest/mt5/heartbeat", response_model=GatewayStatus)
    def heartbeat(
        hb: Heartbeat, authorization: Annotated[str | None, Header()] = None
    ) -> GatewayStatus:
        account_id, token_id = authorize(authorization, hb.account_id)
        now = utcnow()
        monitor = monitors.get(account_id)
        monitor.record(hb, now)
        try:
            # MT-13: danh tính MT5 mới → liên kết chờ chủ tài khoản xác nhận.
            observe_identity(repo, account_id, hb, token_id, now)
        except SQLAlchemyError as e:
            # Không tạo được liên kết chờ = không liên kết (an toàn). Nhịp tim vẫn ghi nhận.
            log.error("Không ghi được liên kết MT5 chờ xác nhận: %s", type(e).__name__)
        return monitor.status(now)

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
