"""Chiến lược v1 "Theo xu hướng M15" (``xu-huong-m15`` 1.0.0) — GĐ5 bước 7 (STR-02, STR-03, STR-04).

Văn bản người dùng duyệt 17/11: ``docs/thiet-ke/36-chien-luoc-v1.md``. **Chưa kiểm chứng** (DEC-25):
mọi tham số là giá trị khởi đầu chưa hiệu chỉnh; chỉ PAPER (Risk chặn SHADOW / LIVE qua cờ
``UNVALIDATED_RULES`` của MarketView).

Hàm **thuần**: nhận đủ đầu vào (bên gọi đọc point-in-time), trả ý định hoặc lý do bỏ qua. Không đọc
DB, không gửi gì đi. Chiến lược chỉ **đề nghị** mức rủi ro (hồ sơ) — không tự tính lot.
Thiếu dữ liệu → không vào lệnh (``MISSING_*``), không đoán.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from zoneinfo import ZoneInfo

from gold_trading.common.enums import Bias, Side
from gold_trading.common.ids import new_id
from gold_trading.contracts.market_view import SAMPLE_DATA, MarketView
from gold_trading.contracts.trade_intent import TradeIntent

STRATEGY_ID = "xu-huong-m15"
VERSION = "1.0.0"
STRATEGY_REF = f"{STRATEGY_ID}@{VERSION}"


@dataclass(frozen=True)
class Params:
    """Tham số v1 (thiết kế 36 mục 7, P1–P11) — giá trị khởi đầu chưa hiệu chỉnh."""

    min_confidence: float = 0.6                                       # P1
    blocked_flags: frozenset[str] = frozenset({                       # P2
        "EVENT_SOON", "EVENT_WINDOW", "NEWS_SHOCK", "HIGH_VOLATILITY", "HIGH_VOLATILITY_REGIME",
        "RISK_OFF_REGIME", "MACRO_STRESS", "CROWDING_RISK", "WIDE_SPREAD",
        "LOW_LIQUIDITY_HOLIDAY"})
    tz: str = "America/New_York"                                      # P3
    session_start: time = time(3, 0)
    session_end: time = time(12, 0)
    friday_end: time = time(10, 0)
    max_ema_gap_atr: Decimal = Decimal(1)                             # P4
    max_open: int = 1                                                 # P5
    cooldown: timedelta = timedelta(minutes=30)                       # P6
    sl_atr: Decimal = Decimal("1.5")                                  # P7
    tp_r: Decimal = Decimal(2)                                        # P8
    be_at_r: Decimal = Decimal(1)                                     # P9
    close_at: time = time(16, 45)                                     # P10
    intent_ttl: timedelta = timedelta(seconds=60)                     # P11


V1 = Params()


@dataclass(frozen=True)
class Inputs:
    """Mọi thứ chiến lược cần, đọc tại ``now`` (point-in-time) bởi bên gọi."""

    now: datetime
    feed_id: str
    view: MarketView | None               # MarketView hiện hành (còn hạn, chưa vô hiệu)
    technical: Mapping | None             # features của output Technical trong snapshot của view
    bid: Decimal | None                   # giây giá mới nhất (bên gọi đã kiểm còn mới)
    ask: Decimal | None
    point: Decimal | None                 # bước giá broker (làm tròn SL / TP)
    open_count: int                       # lệnh paper đang mở + giữ chỗ chưa kết thúc
    last_closed_at: datetime | None       # lần đóng lệnh gần nhất
    risk_per_trade: Decimal | None        # hồ sơ rủi ro (H1)


@dataclass(frozen=True)
class Outcome:
    intent: TradeIntent | None
    reasons: tuple[str, ...]              # lý do bỏ qua (rỗng khi có intent)
    details: dict[str, str] = field(default_factory=dict)


def in_session(now: datetime, p: Params = V1) -> bool:
    """V5: 03:00–12:00 New York thứ Hai–thứ Năm, thứ Sáu 03:00–10:00 (tự theo DST)."""
    loc = now.astimezone(ZoneInfo(p.tz))
    wd, t = loc.weekday(), loc.time()
    if wd > 4:
        return False
    end = p.friday_end if wd == 4 else p.session_end
    return p.session_start <= t < end


def idempotency_key(feed_id: str, market_view_id: str) -> str:
    """STR-04: một ý định / MarketView / nguồn giá / phiên bản chiến lược. Băm (độ dài cố định:
    mã MarketView có thể dài gần 256 ký tự — cột ``idempotency_key`` chỉ 256)."""
    h = hashlib.sha256(f"{feed_id}|{market_view_id}".encode()).hexdigest()[:40]
    return f"{STRATEGY_REF}:{h}"


def _dec(x) -> Decimal | None:
    if x is None:
        return None
    try:
        d = Decimal(str(x))
    except Exception:
        return None
    return d if d.is_finite() else None


def decide(inp: Inputs, p: Params = V1) -> Outcome:
    now, v = inp.now, inp.view
    why: list[str] = []
    det: dict[str, str] = {"strategy": STRATEGY_REF}
    # V1–V4: nhận định thị trường
    if v is None or not v.is_valid_at(now):
        return Outcome(None, ("NO_MARKET_VIEW",), det)
    if v.feed_id != inp.feed_id:
        return Outcome(None, ("MARKET_VIEW_FEED_MISMATCH",), det)
    det |= {"market_view_id": v.market_view_id, "bias": v.bias.value,
            "confidence": str(v.confidence)}
    if v.bias is Bias.NEUTRAL:
        why.append("BIAS_NEUTRAL")
    if v.confidence < p.min_confidence:
        why.append("CONFIDENCE_LOW")
    if bad := sorted(v.risk_flags & p.blocked_flags):
        why.append("RISK_FLAGS:" + ",".join(bad))
    # V5: giờ
    if not in_session(now, p):
        why.append("OUT_OF_SESSION")
    # V7, V8: một lệnh một lúc, nghỉ sau khi đóng
    if inp.open_count >= p.max_open:
        why.append("POSITION_OPEN")
    if inp.last_closed_at is not None and now - inp.last_closed_at < p.cooldown:
        why.append("COOLDOWN")
    # dữ liệu bắt buộc
    tech = inp.technical or {}
    atr, ema20 = _dec(tech.get("atr14")), _dec(tech.get("ema20"))
    bid, ask, point, risk = inp.bid, inp.ask, inp.point, inp.risk_per_trade
    for name, val in (("MISSING_ATR", atr), ("MISSING_EMA20", ema20), ("MISSING_QUOTE", bid),
                      ("MISSING_QUOTE", ask), ("MISSING_POINT", point),
                      ("MISSING_RISK_PROFILE", risk)):
        if val is None or val <= 0:
            why.append(name)
    if why:
        return Outcome(None, tuple(dict.fromkeys(why)), det)
    assert atr is not None and ema20 is not None and bid is not None and point is not None
    assert risk is not None
    # V6: không đuổi giá — dùng bid (giá trên biểu đồ MT5)
    gap = abs(bid - ema20) / atr
    det |= {"atr14": str(atr), "ema20": str(ema20), "bid": str(bid), "ask": str(ask),
            "ema_gap_atr": str(gap.quantize(Decimal("0.0001")))}
    if gap > p.max_ema_gap_atr:
        return Outcome(None, ("PRICE_EXTENDED",), det)
    # Đặt lệnh (mục 4): SL 1,5 ATR, TP 2 × SL. Làm tròn theo point: SL ra XA hơn (rủi ro không nhỏ
    # đi do làm tròn), TP vào GẦN hơn (R:R không đẹp hơn thật).
    dist = p.sl_atr * atr
    buy = v.bias is Bias.LONG
    if buy:
        sl = ((bid - dist) / point).to_integral_value(ROUND_FLOOR) * point
        tp = ((bid + p.tp_r * (bid - sl)) / point).to_integral_value(ROUND_FLOOR) * point
    else:
        sl = ((bid + dist) / point).to_integral_value(ROUND_CEILING) * point
        tp = ((bid - p.tp_r * (sl - bid)) / point).to_integral_value(ROUND_CEILING) * point
    det |= {"stop_loss": str(sl), "take_profit": str(tp), "sl_distance": str(abs(bid - sl))}
    sample = SAMPLE_DATA in v.quality_flags
    intent = TradeIntent(
        intent_id=new_id("it"),
        strategy_id=STRATEGY_REF,
        symbol=v.symbol,
        side=Side.BUY if buy else Side.SELL,
        entry_type="MARKET",
        entry_reference=float(bid),
        stop_loss=float(sl),
        take_profit=float(tp),
        time_in_force="IOC",
        expiry=now + p.intent_ttl,
        risk_budget_requested=float(risk),
        market_view_id=v.market_view_id,
        policy_version=VERSION,
        created_at=now,
        reason=(("[SAMPLE_DATA] " if sample else "")
                + f"{v.bias.value} conf={v.confidence} gap={det['ema_gap_atr']}ATR "
                  f"SL={p.sl_atr}ATR TP={p.tp_r}R"),
        idempotency_key=idempotency_key(inp.feed_id, v.market_view_id),
        correlation_id=v.market_view_id,
    )
    return Outcome(intent, (), det)


# ====================================================================== quản lý lệnh mở (mục 5)

def time_stop_at(opened_at: datetime, p: Params = V1) -> datetime:
    """P10: 16:45 New York đầu tiên sau lúc mở (không giữ qua đêm). Tự theo DST."""
    tz = ZoneInfo(p.tz)
    loc = opened_at.astimezone(tz)
    day = loc.date() if loc.time() < p.close_at else loc.date() + timedelta(days=1)
    return datetime.combine(day, p.close_at, tzinfo=tz).astimezone(opened_at.tzinfo)


class Manager:
    """Quản lý lệnh của chiến lược này (thiết kế 36 mục 5) cho ``PaperMonitor``:

    - Đóng theo giờ (P10) → ``("CLOSE", "TIME_STOP")``.
    - Dời hòa vốn (P9): giá đóng hiện tại (bid cho BUY, ask cho SELL) đi thuận ≥ 1 × khoảng SL ban
      đầu (từ giá khớp) → SL = giá khớp ± (đệm trượt giá + phí / cỡ HĐ), làm tròn theo point về
      phía an toàn → rủi ro còn lại = 0 (cùng định nghĩa "an toàn" của H7). Chỉ thắt lại.
    - Không trailing (v1). Tín hiệu ngược chiều: không làm gì (5-C03).
    Lệnh không phải của chiến lược này → bỏ qua."""

    def __init__(self, p: Params = V1) -> None:
        self.p = p

    def action(self, opened, current_sl: Decimal, q, now: datetime):
        d = opened.data
        if d.get("strategy_id") != STRATEGY_REF:
            return None
        if now >= time_stop_at(opened.at, self.p):
            return ("CLOSE", "TIME_STOP")
        entry, sl0 = Decimal(d["entry_price"]), Decimal(d["stop_loss"])
        cs, point = Decimal(d["contract_size"]), Decimal(d["point"])
        cost = Decimal(d["slippage"]) + Decimal(d["commission_per_lot"]) / cs
        r = abs(entry - sl0)
        bid, ask = Decimal(str(q.bid)), Decimal(str(q.ask))
        if d["side"] == Side.BUY.value:
            if bid - entry < self.p.be_at_r * r:
                return None
            be = ((entry + cost) / point).to_integral_value(ROUND_CEILING) * point
            ok = current_sl < be < bid
        else:
            if entry - ask < self.p.be_at_r * r:
                return None
            be = ((entry - cost) / point).to_integral_value(ROUND_FLOOR) * point
            ok = ask < be < current_sl
        return ("MOVE_SL", be) if ok else None
