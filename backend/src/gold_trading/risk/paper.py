"""Khớp + đóng lệnh **paper** (GĐ5 bước 6b — LED-04). Thiết kế 35 mục 12.4.

**Không có lệnh thật**: không có đường nào tới Gateway / MT5. "Khớp" = ghi sự kiện ``OPEN`` vào sổ
cái paper theo giá ask / bid **thật** của nguồn giá lúc đó + đệm trượt giá Risk đã dùng; "đóng" =
sự kiện ``CLOSE`` khi giây giá **đã biết** (``available_at ≤ now``) chạm SL / TP. Tiền ``Decimal``.

Giá trị khởi đầu chưa hiệu chỉnh (sổ tham số KN-08): đệm trượt giá vào lệnh = p95 spread 30 ngày
(như Risk); SL đóng ở ``min(SL, bid)`` (BUY) — khoảng trống giá cho giá xấu hơn SL; TP đóng đúng TP
(không tính trượt giá có lợi); cùng giây chạm cả hai → SL.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal

from gold_trading.common.enums import RiskOutcome, Side
from gold_trading.common.ids import new_id
from gold_trading.common.time import utcnow
from gold_trading.contracts.risk import RiskDecision
from gold_trading.contracts.trade_intent import TradeIntent
from gold_trading.market.quotes import CALENDAR_CLOSED, QuoteSecond
from gold_trading.risk.ledger import (
    EventType,
    LedgerConflict,
    LedgerEvent,
    PaperLedger,
    close_key,
    end_key,
)
from gold_trading.risk.periods import Periods

log = logging.getLogger("gold_trading.paper")

QUOTE_MAX_AGE = timedelta(seconds=10)      # = Risk (thiết kế 35 mục 3)
LATE_LOOKBACK = timedelta(seconds=60)      # quét nhanh: lùi 60 giây cho giây giá đến muộn
FULL_RESCAN = timedelta(minutes=5)         # quét lại từ lúc mở: bắt giây đến muộn hơn nữa
SCAN_CHUNK = timedelta(hours=1)
CENT = Decimal("1e-8")


def money(x: Decimal) -> Decimal:
    """Làm tròn **xuống** 8 chữ số (đúng cột NUMERIC(20,8)): PnL không bao giờ đẹp hơn thật."""
    return x.quantize(CENT, rounding=ROUND_FLOOR)


def dec(x) -> Decimal:
    return Decimal(str(x))


@dataclass(frozen=True)
class FillResult:
    ok: bool
    position_id: str | None = None
    code: str | None = None
    details: dict[str, str] = field(default_factory=dict)


def fresh_quote(q: QuoteSecond | None, now: datetime) -> str | None:
    """Lý do không dùng được giây giá (None = dùng được)."""
    if q is None or q.t > now or q.available_at > now or now - q.t > QUOTE_MAX_AGE:
        return "QUOTE_STALE"
    if CALENDAR_CLOSED in q.flags:
        return "MARKET_CLOSED"
    return None


def swap_nights(opened_at: datetime, closed_at: datetime, tz: str, hm: str,
                rollover3days: int) -> int:
    """Số "đêm swap" giữa lúc mở và lúc đóng: mỗi mốc ngày (theo hồ sơ, tự theo DST) **thứ Hai –
    thứ Sáu** đã qua = 1 (mốc thứ Bảy / Chủ nhật không có phiên → không swap), mốc rơi vào ngày
    ``rollover3days`` (đánh số MT5: 0 = CN … 6 = T7) = 3 (gồm hai ngày cuối tuần)."""
    per = Periods.of(tz, hm)
    n = 0
    b = per.next_day_start(opened_at)
    while b <= closed_at:
        wd = b.astimezone(per.tz).weekday()             # Python: T2 = 0 … CN = 6
        if wd <= 4:
            n += 3 if (wd + 1) % 7 == rollover3days else 1
        b = per.next_day_start(b)
    return n


def net_pnl(opened: LedgerEvent, exit_price: Decimal, closed_at: datetime) -> tuple[Decimal, dict]:
    d = opened.data
    side = Side(d["side"])
    vol, cs = Decimal(d["volume"]), Decimal(d["contract_size"])
    entry = Decimal(d["entry_price"])
    move = (exit_price - entry) if side is Side.BUY else (entry - exit_price)
    nights = swap_nights(opened.at, closed_at, d["day_reset_tz"], d["day_reset_time"],
                         int(d["swap_rollover3days"]))
    swap = Decimal(d["swap_night_cost"]) * nights * vol
    comm = Decimal(d["commission_per_lot"]) * vol
    gross = move * cs * vol
    return money(gross - comm - swap), {"gross": str(gross), "commission": str(comm),
                                        "swap": str(swap), "swap_nights": str(nights)}


class PaperBroker:
    """Khớp / đóng paper trên ``PaperLedger``. ``latest_quote(nguồn giá, lúc)``,
    ``quote_window(nguồn giá, từ, tới)`` = kho giây giá thật (ING-08)."""

    def __init__(self, ledger: PaperLedger,
                 latest_quote: Callable[[str, datetime], QuoteSecond | None],
                 quote_window: Callable[[str, datetime, datetime], list[QuoteSecond]], *,
                 clock: Callable[[], datetime] = utcnow) -> None:
        self.ledger = ledger
        self.latest_quote = latest_quote
        self.quote_window = quote_window
        self.clock = clock
        self._mark: dict[str, datetime] = {}       # vị thế → giây giá đã xét tới (bộ nhớ)
        self._full: dict[str, datetime] = {}       # vị thế → lần quét lại toàn bộ gần nhất

    # ------------------------------------------------------------------ khớp (LED-04)

    def fill(self, decision: RiskDecision, intent: TradeIntent, feed: str) -> FillResult:
        """Khớp paper một quyết định đã duyệt. Idempotent: đã khớp → trả vị thế cũ."""
        now = self.clock()
        acc = decision.account_id
        if decision.outcome is RiskOutcome.REJECTED or decision.reservation_id is None:
            return FillResult(False, code="NOT_APPROVED")
        if decision.intent_id != intent.intent_id:
            return FillResult(False, code="INTENT_MISMATCH")
        rid = decision.reservation_id
        with self.ledger.locked(acc):
            ended = self.ledger.reservation_ended(acc, rid)
            if ended is not None:
                if ended.type is EventType.OPEN:
                    return FillResult(True, ended.ref_id, details={"already_filled": "1"})
                return FillResult(False, code="RESERVATION_RELEASED")
            if now >= decision.expires_at:
                return FillResult(False, code="DECISION_EXPIRED")   # tick sẽ nhả (6d)
            q = self.latest_quote(feed, now)
            if (why := fresh_quote(q, now)) is not None:
                return FillResult(False, code=why)
            assert q is not None
            det = decision.details
            slip, cs = Decimal(det["slippage"]), Decimal(det["contract_size"])
            vol = decision.volume
            sl = dec(intent.stop_loss)
            tp = dec(intent.take_profit) if intent.take_profit is not None else None
            bid, ask = dec(q.bid), dec(q.ask)
            if intent.side is Side.BUY:
                entry = ask + slip
                wrong = not (bid > sl and entry > sl and (tp is None or tp > entry))
            else:
                entry = bid - slip
                wrong = not (ask < sl and entry < sl and (tp is None or tp < entry))
            costs = Decimal(det["commission_per_lot"]) + Decimal(det["swap_per_lot"])
            risk = abs(entry - sl) * cs * vol + costs * vol
            info = {"entry_price": str(entry), "risk_at_fill": str(risk),
                    "risk_approved": str(decision.risk_amount), "bid": str(bid),
                    "ask": str(ask), "quote_t": q.t.isoformat()}
            # Rủi ro thật lúc khớp không bao giờ vượt số đã duyệt + giữ chỗ.
            if wrong or risk > decision.risk_amount:
                return FillResult(False, code="PRICE_MOVED", details=info)
            pid = new_id("pos")
            self.ledger.append(acc, EventType.OPEN, pid, Decimal(0), at=now, actor="paper",
                               reason=f"fill:{decision.risk_decision_id}", once_key=end_key(rid),
                               data={
                "reservation_id": rid, "risk_decision_id": decision.risk_decision_id,
                "intent_id": intent.intent_id, "symbol": intent.symbol, "feed": feed,
                "side": intent.side.value, "volume": str(vol), "entry_price": str(entry),
                "stop_loss": str(sl), "take_profit": str(tp) if tp is not None else "",
                "contract_size": str(cs), "point": det["point"], "slippage": str(slip),
                "commission_per_lot": det["commission_per_lot"],
                "swap_night_cost": det["swap_night_cost"],
                "swap_rollover3days": det["swap_rollover3days"],
                "day_reset_tz": det["day_reset_tz"], "day_reset_time": det["day_reset_time"],
                "risk_at_fill": str(risk), "quote_t": q.t.isoformat()})
            return FillResult(True, pid, details=info)

    # ------------------------------------------------------------------ dời SL (chỉ thắt lại)

    def modify_sl(self, account_id: str, position_id: str, new_sl: Decimal, *, actor: str,
                  reason: str) -> bool:
        """Dời SL **chỉ theo hướng giảm rủi ro** (BUY lên, SELL xuống). Trả False nếu không hợp lệ
        (vị thế không mở / nới SL)."""
        with self.ledger.locked(account_id):
            opened = next((e for e in self.ledger.open_position_events(account_id)
                           if e.ref_id == position_id), None)
            if opened is None:
                return False
            cur = self.ledger.current_stop(account_id, opened)
            buy = Side(opened.data["side"]) is Side.BUY
            if (new_sl <= cur) if buy else (new_sl >= cur):
                return False
            self.ledger.append(account_id, EventType.MODIFY_SL, position_id, Decimal(0),
                               actor=actor, reason=reason, links=opened.event_id,
                               data={"stop_loss": str(new_sl), "previous": str(cur)})
            return True

    # ------------------------------------------------------------------ đóng

    def close(self, account_id: str, opened: LedgerEvent, exit_price: Decimal, reason: str, *,
              actor: str = "paper", trigger_t: datetime | None = None) -> LedgerEvent | None:
        """Đóng một vị thế (một lần — trùng → None)."""
        now = self.clock()
        pnl, info = net_pnl(opened, exit_price, now)
        try:
            return self.ledger.append(
                account_id, EventType.CLOSE, opened.ref_id, pnl, at=now, actor=actor,
                reason=reason, once_key=close_key(opened.ref_id), links=opened.event_id,
                data={"side": opened.data["side"], "opened_at": opened.at.isoformat(),
                      "volume": opened.data["volume"], "entry_price": opened.data["entry_price"],
                      "exit_price": str(exit_price),
                      "trigger_t": (trigger_t or now).isoformat(), **info})
        except LedgerConflict:
            return None

    def exit_price_now(self, opened: LedgerEvent, q: QuoteSecond) -> Decimal:
        """Đóng chủ động (cuối tuần / tin): BUY ở bid − đệm, SELL ở ask + đệm."""
        slip = Decimal(opened.data["slippage"])
        return dec(q.bid) - slip if opened.data["side"] == Side.BUY.value else dec(q.ask) + slip

    @staticmethod
    def hit(opened_side: str, sl: Decimal, tp: Decimal | None, q: QuoteSecond
            ) -> tuple[str, Decimal] | None:
        """SL / TP trong một giây giá. SL xét trước (cùng giây chạm cả hai → SL)."""
        if opened_side == Side.BUY.value:
            if dec(q.bid_low) <= sl:
                return "STOP_LOSS", min(sl, dec(q.bid))
            if tp is not None and dec(q.bid) >= tp:
                return "TAKE_PROFIT", tp
        else:
            if dec(q.ask_high) >= sl:
                return "STOP_LOSS", max(sl, dec(q.ask))
            if tp is not None and dec(q.ask) <= tp:
                return "TAKE_PROFIT", tp
        return None

    def check_exits(self, account_id: str) -> list[LedgerEvent]:
        """Quét giây giá **đã biết** từ lần quét trước (lùi ``LATE_LOOKBACK``) tới ``now`` cho mọi
        vị thế mở; chạm SL / TP → ``CLOSE``. Khởi động lại → quét lại từ lúc mở (idempotent)."""
        now = self.clock()
        out: list[LedgerEvent] = []
        for opened in self.ledger.open_position_events(account_id):
            d = opened.data
            sl = self.ledger.current_stop(account_id, opened)
            tp = Decimal(d["take_profit"]) if d.get("take_profit") else None
            lo = max(opened.at, self._mark.get(opened.ref_id, opened.at) - LATE_LOOKBACK)
            last_full = self._full.get(opened.ref_id)
            if last_full is None or now - last_full >= FULL_RESCAN:
                lo = opened.at                         # giây đến muộn hơn 60 giây (mất kết nối)
                self._full[opened.ref_id] = now
            hit = None
            while lo < now and hit is None:
                hi = min(now, lo + SCAN_CHUNK)
                # kho giây giá trả [lo, hi) → đoạn cuối mở rộng 1 µs để lấy cả giây = now
                q_hi = hi + timedelta(microseconds=1) if hi == now else hi
                rows = sorted((q for q in self.quote_window(d["feed"], lo, q_hi)
                               if opened.at < q.t <= now and q.available_at <= now),
                              key=lambda q: q.t)
                for q in rows:
                    if CALENDAR_CLOSED in q.flags:
                        continue
                    if (h := self.hit(d["side"], sl, tp, q)) is not None:
                        hit = (h, q.t)
                        break
                lo = hi
            if hit is None:
                self._mark[opened.ref_id] = now
                continue
            (why, price), t = hit
            ev = self.close(account_id, opened, price, why, trigger_t=t)
            if ev is not None:
                out.append(ev)
            self._mark.pop(opened.ref_id, None)
            self._full.pop(opened.ref_id, None)
        return out


# ====================================================================== 6d: quản lý lệnh đang mở

# Lệnh cấm tin HIGH (DEC-20): cửa sổ lịch HIGH, số HIGH vừa nhận, thông cáo Fed ngoài lịch.
NEWS_HIGH_CODES = frozenset({"CALENDAR_HIGH", "RELEASE_HIGH_RECEIVED"})
# Hồ sơ không đọc được → chính sách an toàn nhất (thiết kế 35 mục 12.6).
SAFE_NEWS_POLICY = "CLOSE_ALL"
SAFE_WEEKEND_MIN = 30


def is_high_news(block) -> bool:
    return getattr(block, "reason_code", None) in NEWS_HIGH_CODES or \
        str(getattr(block, "kind", "")) == "NEWS"


@dataclass
class TickReport:
    closed: list[tuple[str, str]] = field(default_factory=list)     # (vị thế, lý do)
    released: list[str] = field(default_factory=list)               # giữ chỗ đã nhả
    status: list[str] = field(default_factory=list)                 # FEED_STALE, …
    peak: Decimal | None = None


class PaperMonitor:
    """Một nhịp quản lý lệnh paper đang mở của một tài khoản (thiết kế 35 mục 12.6):
    SL / TP → H8 đóng trước cuối tuần / lễ → H7 qua tin HIGH → nhả giữ chỗ hết hạn → ghi đỉnh.
    Chưa chạy theo nhịp nào (nối cùng Strategy ở bước 7). Mọi lỗi đọc → hướng an toàn."""

    def __init__(self, broker: PaperBroker, *, feed_for: Callable[[str], str | None],
                 risk_profile: Callable[[str, datetime], object | None],
                 entry_blocks: Callable[[str, datetime], list],
                 market_calendar: object | None) -> None:
        self.broker = broker
        self.ledger = broker.ledger
        self.feed_for = feed_for
        self.risk_profile = risk_profile
        self.entry_blocks = entry_blocks
        self.market_calendar = market_calendar

    def tick(self, account_id: str) -> TickReport:
        from gold_trading.risk.book import position_of, remaining_risk, unrealized
        from gold_trading.risk.engine import closing_soon

        now = self.broker.clock()
        rep = TickReport()
        for ev in self.broker.check_exits(account_id):                 # 1. SL / TP
            rep.closed.append((ev.ref_id, ev.reason))
        try:
            prof = self.risk_profile(account_id, now)
        except Exception:
            log.exception("Paper: không đọc được hồ sơ rủi ro %s → chính sách an toàn", account_id)
            prof = None
        if prof is None:
            rep.status.append("RISK_PROFILE_UNKNOWN")
        pv = getattr(prof, "values", None)
        news_policy = pv.news_hold_policy if pv is not None else SAFE_NEWS_POLICY
        wk_min = pv.weekend_close_before_min if pv is not None else SAFE_WEEKEND_MIN

        opened = self.ledger.open_position_events(account_id)
        feed = self.feed_for(account_id)
        q = self.broker.latest_quote(feed, now) if feed else None
        quote_ok = fresh_quote(q, now) is None
        if opened and not quote_ok:
            rep.status.append("FEED_STALE")         # không bịa giá: lệnh vẫn mở, báo lên

        # 2. H8: sắp đóng cửa cuối tuần / lễ dài (hoặc lịch không biết) → đóng hết
        try:
            wk, _ = closing_soon(self.market_calendar, now, wk_min)
        except Exception:
            log.exception("Paper: lịch thị trường lỗi → coi như sắp đóng cửa")
            wk = "MARKET_CALENDAR_UNKNOWN"
        to_close: dict[str, str] = {}
        if wk is not None:
            rep.status.append(wk)
            for e in opened:
                to_close[e.ref_id] = "WEEKEND_CLOSE"

        # 3. H7: lệnh cấm tin HIGH đang hiệu lực
        try:
            news = any(is_high_news(b) for b in self.entry_blocks(account_id, now))
        except Exception:
            log.exception("Paper: không đọc được lệnh cấm tin → coi như có tin HIGH")
            news = True
            rep.status.append("NEWS_UNKNOWN")
        if news:
            for e in opened:
                if e.ref_id in to_close:
                    continue
                if news_policy == "KEEP_SAFE_ONLY":
                    p = position_of(e, self.ledger.current_stop(account_id, e))
                    if remaining_risk(p, Decimal(e.data["slippage"]),
                                      Decimal(e.data["contract_size"])) <= 0:
                        continue                     # SL đã qua hòa vốn sau chi phí → giữ
                to_close[e.ref_id] = "NEWS_CLOSE"

        if to_close and quote_ok:
            assert q is not None
            for e in opened:
                if (why := to_close.get(e.ref_id)) is not None:
                    ev = self.broker.close(account_id, e, self.broker.exit_price_now(e, q), why,
                                           trigger_t=q.t)
                    if ev is not None:
                        rep.closed.append((e.ref_id, why))

        # 4. nhả giữ chỗ hết hạn (LED-05) — sự kiện bù trừ trỏ về RESERVE
        for r in self.ledger.open_reservations(account_id):
            exp = r.data.get("expires_at")
            # không có hạn (không do Risk tạo) → giữ nguyên, vẫn tính vào heat (an toàn)
            if exp is not None and datetime.fromisoformat(exp) <= now:
                if self.ledger.release(account_id, r.ref_id, "RESERVATION_EXPIRED",
                                       actor="system", at=now):
                    rep.released.append(r.ref_id)

        # 5. đỉnh equity gồm lãi đang chạy (H6)
        if quote_ok:
            assert q is not None
            bid, ask = dec(q.bid), dec(q.ask)
            still = self.ledger.open_position_events(account_id)
            unreal = sum((unrealized(position_of(e, self.ledger.current_stop(account_id, e)),
                                     bid, ask, Decimal(e.data["contract_size"]))
                          for e in still), Decimal(0))
            st = self.ledger.equity_state(account_id, now)
            if st is not None and self.ledger.mark_peak(account_id, st.realized + unreal,
                                                        at=now) is not None:
                rep.peak = st.realized + unreal
        return rep
