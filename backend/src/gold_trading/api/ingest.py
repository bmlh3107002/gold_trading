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
from gold_trading.accounts.mt5_link import (
    CandleLinkError,
    Observed,
    check_candle_identity,
    held_link,
    link_status_for,
    lock_feed,
    observe_identity,
)
from gold_trading.common.time import UtcDatetime, utcnow
from gold_trading.contracts.candle import DataSource
from gold_trading.ingestion.candles import CandleIngestor, RawBar, TailStatus, tail_status
from gold_trading.ingestion.sources.csv_file import SESSION_MISMATCH_MAX, check_sessions
from gold_trading.market.feeds import USD_INDEX_PAIRS, feed_id_for
from gold_trading.market.quotes import QuoteIn, QuoteIngestor
from gold_trading.market.service import MarketDataService
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.candles import InMemoryCandleStore
from gold_trading.storage.repository import PriceFeed, Repository
from gold_trading.storage.schema import DEFAULT_ACCOUNT_ID

log = logging.getLogger("gold_trading.ingest")

MIN_TOKEN_LEN = 24
MAX_BARS = 2000
MAX_QUOTE_SECONDS = 600
HEARTBEAT_TIMEOUT = timedelta(seconds=30)
# ING-16 / 1A-C20: lệch đồng hồ máy Gateway so với backend (đồng hồ backend kiểm NTP, OPS-12)
GATEWAY_CLOCK_WARN_S = 2.0
GATEWAY_CLOCK_BAD_S = 30.0
# Lệch đồng hồ server MT5 (phần lẻ ngoài độ lệch giờ chẵn). Tick tới trễ ≤ chu kỳ Gateway (~5 s)
# nên chỉ cảnh báo từ 30 s.
MT5_CLOCK_BAD_S = 30.0
ClockState = Literal["OK", "WARN", "BAD", "UNKNOWN"]


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
    # MT-14 (Gateway ≥ 0.4): danh tính MT5 Gateway đọc ngay trước VÀ sau khi lấy nến (khác nhau
    # thì Gateway bỏ lô). Ghi thật chỉ khi khớp liên kết ACTIVE; thiếu → 409 (dry_run vẫn chạy).
    mt5_login: int | None = Field(default=None, gt=0, le=2**63 - 1)
    mt5_server: str | None = Field(default=None, min_length=1, max_length=256)
    mt5_account_type: Literal["DEMO", "CONTEST", "REAL", "UNKNOWN"] | None = None
    # MT-05 (Gateway ≥ 0.5): tên symbol trong MT5 của broker (vd. XAUUSD.r). Cùng với server xác
    # định nguồn giá. Bắt buộc khi ghi thật.
    broker_symbol: str | None = Field(default=None, min_length=1, max_length=64,
                                      pattern=r"^[\x21-\x7e]+$")

    @model_validator(mode="after")
    def _identity_all_or_none(self) -> CandleBatch:
        given = [self.mt5_login, self.mt5_server, self.mt5_account_type]
        if any(v is not None for v in given) and any(v is None for v in given):
            raise ValueError("mt5_login, mt5_server, mt5_account_type phải gửi đủ cả ba")
        return self


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
    # MT-14: trạng thái liên kết MT5 nhìn từ lô này (NONE / PENDING_CONFIRM / ACTIVE / MISMATCH /
    # DISCONNECTED). Lô ghi thật chỉ tới được đây khi ACTIVE.
    link_status: str | None = None


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
    # ING-16 (Gateway ≥ 0.9): giờ đồng hồ máy Gateway lúc gửi (CHƯA hiệu chỉnh) → backend tự đo
    # lệch; lệch của đồng hồ server MT5 (giây, phần lẻ ngoài độ lệch giờ chẵn) do Gateway đo trên
    # tick vừa tới. None = Gateway cũ / chưa đo được.
    gateway_time: UtcDatetime | None = None
    mt5_clock_residual_s: float | None = Field(default=None, ge=-3600, le=3600,
                                               allow_inf_nan=False)

    def gateway_version_tuple(self) -> tuple[int, ...]:
        """"0.9.0" → (0, 9, 0); không đọc được → () (coi như cũ nhất)."""
        try:
            return tuple(int(x) for x in self.gateway_version.split(".")[:3])
        except ValueError:
            return ()

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


FxPair = Literal["EURUSD", "USDJPY", "GBPUSD", "USDCAD", "USDSEK", "USDCHF"]
assert set(FxPair.__args__) == set(USD_INDEX_PAIRS)  # type: ignore[attr-defined]


class FxCandleBatch(BaseModel):
    """5d (chuẩn bị ING-24): nến M15 ĐÃ ĐÓNG của một cặp tiền trong chỉ số USD."""

    account_id: str | None = Field(default=None, max_length=64)
    pair: FxPair  # tên chuẩn
    broker_symbol: str = Field(min_length=1, max_length=64, pattern=r"^[\x21-\x7e]+$")
    timeframe: Literal["M15"]
    server_tz: str | None = Field(default=None, max_length=64)
    backfill: bool
    gateway_id: str = Field(min_length=1, max_length=64)
    bars: list[BarIn] = Field(max_length=MAX_BARS)
    mt5_login: int = Field(gt=0, le=2**63 - 1)
    mt5_server: str = Field(min_length=1, max_length=256)
    mt5_account_type: Literal["DEMO", "CONTEST", "REAL", "UNKNOWN"]


class QuoteSecondIn(BaseModel):
    """ING-08 / GW-08: một giây ĐÃ TRỌN do Gateway gom từ tick (giá cuối giây + cực trị)."""

    model_config = _FINITE
    t: UtcDatetime  # đầu giây (UTC, tròn giây)
    bid: float
    ask: float
    bid_low: float  # bid thấp nhất trong giây
    ask_high: float  # ask cao nhất trong giây
    spread_max_points: int  # spread lớn nhất trong giây (point)
    ticks: int


class QuoteBatch(BaseModel):
    model_config = _FINITE
    account_id: str | None = Field(default=None, max_length=64)
    symbol: str
    gateway_id: str = Field(min_length=1, max_length=64)
    # Danh tính MT5 + symbol broker: bắt buộc (cùng kiểm như lô nến, MT-14 / MT-05).
    mt5_login: int = Field(gt=0, le=2**63 - 1)
    mt5_server: str = Field(min_length=1, max_length=256)
    mt5_account_type: Literal["DEMO", "CONTEST", "REAL", "UNKNOWN"]
    broker_symbol: str = Field(min_length=1, max_length=64, pattern=r"^[\x21-\x7e]+$")
    point: float = Field(gt=0)  # symbol_info().point, để tính spread theo point
    seconds: list[QuoteSecondIn] = Field(max_length=MAX_QUOTE_SECONDS)
    # Số tick Gateway đã bỏ khi gom (1A-C13 phía Gateway), theo lý do. Chỉ để đếm + log.
    gateway_dropped: dict[str, int] = Field(default_factory=dict, max_length=16)


class QuoteReport(BaseModel):
    received: int
    accepted: int
    duplicates: int
    conflicts: int
    dropped: dict[str, int]
    wide_spread: int
    calendar_closed: int
    calendar_mismatch: bool


DisconnectReason = Literal["NO_HEARTBEAT", "TERMINAL_OFFLINE", "NOT_LOGGED_IN"]


class GatewayStatus(BaseModel):
    state: Literal["NEVER", "CONNECTED", "DISCONNECTED"]
    # 1A-C10: vì sao DISCONNECTED — Gateway không gửi nhịp tim > 30 s / MT5 mất kết nối tới
    # broker hoặc lỗi đọc / MT5 chưa đăng nhập tài khoản (Gateway ≥ 0.3 gửi danh tính).
    reason: DisconnectReason | None = None
    last_seen_at: datetime | None
    age_seconds: float | None
    heartbeat: Heartbeat | None
    # ING-16 / 1A-C20: dương = đồng hồ máy Gateway NHANH hơn backend. Backend luôn dùng đồng hồ
    # của mình cho dữ liệu; đây chỉ để cảnh báo.
    gateway_clock_skew_s: float | None = None
    gateway_clock: ClockState = "UNKNOWN"
    mt5_clock_residual_s: float | None = None
    mt5_clock: ClockState = "UNKNOWN"


def clock_state(skew: float | None, warn: float | None, bad: float) -> ClockState:
    if skew is None:
        return "UNKNOWN"
    if abs(skew) > bad:
        return "BAD"
    if warn is not None and abs(skew) > warn:
        return "WARN"
    return "OK"


@dataclass
class GatewayMonitor:
    last: Heartbeat | None = None
    last_seen_at: datetime | None = None

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._clock_states: tuple[ClockState, ClockState] = ("UNKNOWN", "UNKNOWN")

    def record(self, hb: Heartbeat, at: datetime) -> None:
        with self._lock:
            self.last, self.last_seen_at = hb, at
        st = self.status(at)
        now_states = (st.gateway_clock, st.mt5_clock)
        if now_states != self._clock_states:
            self._clock_states = now_states
            if "BAD" in now_states:
                log.warning("Đồng hồ lệch: máy Gateway %s s (%s), server MT5 %s s (%s)",
                            st.gateway_clock_skew_s, st.gateway_clock, st.mt5_clock_residual_s,
                            st.mt5_clock)

    def status(self, now: datetime) -> GatewayStatus:
        with self._lock:
            if self.last_seen_at is None:
                return GatewayStatus(
                    state="NEVER", last_seen_at=None, age_seconds=None, heartbeat=None
                )
            age = now - self.last_seen_at
            hb = self.last
            reason: DisconnectReason | None = None
            if age > HEARTBEAT_TIMEOUT or hb is None:
                reason = "NO_HEARTBEAT"
            elif not hb.terminal_connected:
                reason = "TERMINAL_OFFLINE"
            elif hb.identity is None and hb.gateway_version_tuple() >= (0, 3):
                reason = "NOT_LOGGED_IN"  # Gateway cũ < 0.3 không gửi danh tính: không kết luận
            state = "CONNECTED" if reason is None else "DISCONNECTED"
            skew = (round((hb.gateway_time - self.last_seen_at).total_seconds(), 1)
                    if hb is not None and hb.gateway_time is not None else None)
            mt5 = hb.mt5_clock_residual_s if hb is not None else None
            return GatewayStatus(
                state=state,
                reason=reason,
                last_seen_at=self.last_seen_at,
                age_seconds=round(age.total_seconds(), 1),
                heartbeat=hb,
                gateway_clock_skew_s=skew,
                gateway_clock=clock_state(skew, GATEWAY_CLOCK_WARN_S, GATEWAY_CLOCK_BAD_S),
                mt5_clock_residual_s=None if mt5 is None else round(mt5, 1),
                mt5_clock=clock_state(mt5, None, MT5_CLOCK_BAD_S),
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
    quotes: QuoteIngestor | None = None,
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
        if repo.account(account_id) is None:
            raise HTTPException(403, "Không có tài khoản giao dịch này")
        # MT-05: mọi tài khoản có liên kết ACTIVE đều ghi được, nhưng CHỈ vào nguồn giá của
        # (server, symbol broker) đã liên kết — không còn "kho nến dùng chung" duy nhất.
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
        now = utcnow()
        seen = (Observed(batch.mt5_login, batch.mt5_server, batch.mt5_account_type)
                if batch.mt5_login is not None else None)  # type: ignore[arg-type]
        feed = ""
        if dry_run:
            held = held_link(repo, account_id)
            pending = any(x.status == "PENDING_CONFIRM" for x in repo.mt5_links(account_id))
            link_status = link_status_for(held, seen, pending)
            if seen is not None and batch.broker_symbol:
                try:
                    feed = feed_id_for(seen.server, batch.broker_symbol)
                except ValueError:
                    feed = ""  # tên lạ: chạy thử vẫn kiểm nến, không so với nguồn nào
        else:
            try:
                link = check_candle_identity(repo, account_id, seen, now)
                feed = lock_feed(repo, link, batch.broker_symbol, now)
            except CandleLinkError as e:
                raise HTTPException(409, str(e)) from None
            except SQLAlchemyError as e:
                # Không kiểm được liên kết = không ghi (an toàn). Gateway sẽ gửi lại.
                log.error("Không đọc được liên kết MT5: %s", type(e).__name__)
                raise HTTPException(
                    503, "Lưu trữ đang lỗi (có thể ổ đĩa đầy): chưa ghi lô nến này"
                ) from e
            link_status = "ACTIVE"
        bars = [_bar(b) for b in batch.bars]
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
                feed=feed,
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
            link_status=link_status,
            **extra,
        )

    @r.post("/api/ingest/mt5/fx-candles", response_model=IngestReport)
    def ingest_fx_candles(
        batch: FxCandleBatch, authorization: Annotated[str | None, Header()] = None
    ) -> IngestReport:
        """5d: nến M15 của 6 cặp tiền chỉ số USD. Cùng kiểm token + danh tính MT5 như nến vàng;
        nguồn = (server đã liên kết, symbol broker của cặp). Không kiểm R1 (giờ FX khác giờ
        vàng; múi giờ đã kiểm trên nến vàng của cùng Gateway)."""
        account_id, _ = authorize(authorization, batch.account_id)
        if repo.account(account_id) is None:
            raise HTTPException(403, "Không có tài khoản giao dịch này")
        if ingest_guard and (reason := ingest_guard()):
            raise HTTPException(503, reason)
        if batch.pair not in batch.broker_symbol.upper():
            # Chặn cấu hình nhầm (vd. gửi GBPUSD dưới tên EURUSD): symbol broker phải chứa tên cặp
            raise HTTPException(422, f"Symbol broker {batch.broker_symbol!r} không phải cặp "
                                     f"{batch.pair}")
        server_tz = None
        if batch.server_tz is not None:
            try:
                server_tz = ZoneInfo(batch.server_tz)
            except (ZoneInfoNotFoundError, ValueError):
                raise HTTPException(422, "server_tz không hợp lệ") from None
        now = utcnow()
        seen = Observed(batch.mt5_login, batch.mt5_server, batch.mt5_account_type)
        try:
            link = check_candle_identity(repo, account_id, seen, now)
            feed = feed_id_for(link.mt5_server, batch.broker_symbol)
            repo.ensure_price_feed(PriceFeed(feed, link.mt5_server, batch.broker_symbol, now))
            res = ingestor.ingest(
                [_bar(b) for b in batch.bars], symbol=batch.pair, timeframe=Timeframe.M15,
                source=DataSource.MT5, ingested_at=now, backfill=batch.backfill,
                server_tz=server_tz, feed=feed,
            )
        except CandleLinkError as e:
            raise HTTPException(409, str(e)) from None
        except ValueError:
            raise HTTPException(422, "Symbol broker không hợp lệ") from None
        except SQLAlchemyError as e:
            log.error("Không ghi được nến cặp tiền: %s", type(e).__name__)
            raise HTTPException(
                503, "Lưu trữ đang lỗi (có thể ổ đĩa đầy): chưa ghi lô nến này"
            ) from e
        return IngestReport(
            dry_run=False, received=len(batch.bars), accepted=res.accepted,
            duplicates=res.duplicates, revised=res.revised, quarantined=res.quarantined,
            reasons=res.reasons, link_status="ACTIVE",
        )

    @r.post("/api/ingest/mt5/quotes", response_model=QuoteReport)
    def ingest_quotes(
        batch: QuoteBatch, authorization: Annotated[str | None, Header()] = None
    ) -> QuoteReport:
        """ING-08: giá sống theo giây. Chỉ ghi khi MT5 khớp liên kết ACTIVE, vào đúng nguồn giá
        (server + symbol broker) của liên kết — như lô nến."""
        account_id, _ = authorize(authorization, batch.account_id)
        if quotes is None:
            raise HTTPException(503, "Backend chưa bật nhận giá sống")
        if repo.account(account_id) is None:
            raise HTTPException(403, "Không có tài khoản giao dịch này")
        if ingest_guard and (reason := ingest_guard()):
            raise HTTPException(503, reason)
        if batch.symbol != market.symbol:
            raise HTTPException(422, f"Symbol phải là {market.symbol}")
        now = utcnow()
        seen = Observed(batch.mt5_login, batch.mt5_server, batch.mt5_account_type)
        try:
            link = check_candle_identity(repo, account_id, seen, now)
            feed = lock_feed(repo, link, batch.broker_symbol, now)
            res = quotes.ingest(
                (QuoteIn(q.t, q.bid, q.ask, q.bid_low, q.ask_high, q.spread_max_points, q.ticks)
                 for q in batch.seconds),
                feed=feed, point=batch.point, now=now,
            )
        except CandleLinkError as e:
            raise HTTPException(409, str(e)) from None
        except SQLAlchemyError as e:
            log.error("Không ghi được giá sống: %s", type(e).__name__)
            raise HTTPException(
                503, "Lưu trữ đang lỗi (có thể ổ đĩa đầy): chưa ghi lô giá này"
            ) from e
        if res.dropped or batch.gateway_dropped:
            log.warning("Giá sống %s: bỏ %s (Gateway bỏ thêm %s)", account_id, res.dropped,
                        batch.gateway_dropped)
        if res.calendar_mismatch:
            log.warning("CALENDAR_MISMATCH: nguồn %s vẫn có giá khi lịch nói đóng cửa", feed)
        return QuoteReport(**res.__dict__)

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

    def latest_by_open_time(self, symbol, tf, source, lo, hi, *, feed=""):
        return self._real.latest_by_open_time(symbol, tf, source, lo, hi, feed=feed)

    def last_before(self, symbol, tf, source, t, *, feed=""):
        return self._real.last_before(symbol, tf, source, t, feed=feed)
