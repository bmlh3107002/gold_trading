"""Khớp + đóng lệnh paper — GĐ5 bước 6b (LED-04, CORE-05). Thiết kế 35 mục 12.4.

Số broker / hồ sơ là **số giả chỉ để test** (``tests/test_risk_engine.py``). Bảng tính tay:
equity 10.000, rủi ro 0,5 % = 50 $; vào tham chiếu 2400, SL 2390, TP 2420; bid 2400,00 /
ask 2400,20 (spread 20 point), đệm p95 = 30 point = 0,30; phí 0.
R1 = (10 + 0,20 + 0,30) × 100 = 1050 $/lot → 0,04 lot, rủi ro 42 $.
Khớp BUY = ask + đệm = 2400,50 → rủi ro lúc khớp = (2400,50 − 2390) × 100 × 0,04 = 42,00 ≤ 42.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from gold_trading.common.enums import RiskOutcome
from gold_trading.market.quotes import CALENDAR_CLOSED, QuoteSecond
from gold_trading.risk.ledger import EventType, RiskLedger, SqlLedger
from gold_trading.risk.paper import PaperBroker, swap_nights
from gold_trading.storage.repository import SqlRepository
from tests.conftest import minutes
from tests.factories import intent
from tests.test_paper_ledger import LEDGER_KINDS, make_ledger
from tests.test_risk_engine import ACC, FEED, World, reading, spec_row

D = Decimal
S = timedelta(seconds=1)


def q(t: datetime, bid, ask, *, bid_low=None, ask_high=None, avail=None, flags=()):
    bid, ask = float(bid), float(ask)
    return QuoteSecond(FEED, t, bid, ask, float(bid_low if bid_low is not None else bid),
                       float(ask_high if ask_high is not None else ask), 20, 20, 3,
                       tuple(flags), avail or t, avail or t)


class Paper:
    def __init__(self, t0, ledger=None):
        self.w = World(t0, ledger=ledger or RiskLedger())
        self.led = self.w.engine.ledger
        self.w.gates = replace(self.w.gates, trade_book=self.led)
        self.w.engine.gates = self.w.gates
        # vốn đầu paper GIẢ (chỉ để test) = equity MT5 giả
        self.led.start(ACC, D(10_000), actor="sub-u", reason="test", at=t0 - timedelta(days=2))
        self.quotes: list[QuoteSecond] = []
        self.broker = PaperBroker(
            self.led, latest_quote=lambda f, at: self.w.quote,
            quote_window=lambda f, lo, hi: [x for x in self.quotes if lo <= x.t < hi],
            clock=lambda: self.w.now)

    def open(self, i=None):
        i = i or intent(self.w.now - minutes(0.5))
        d = self.w.evaluate(i, keep_key=True)
        assert d.outcome is RiskOutcome.APPROVED, d.reason_codes
        return d, i, self.broker.fill(d, i, FEED)

    def at(self, t):
        self.w.now = t


@pytest.fixture(params=LEDGER_KINDS)
def paper(request, tmp_path, t0):
    if request.param == "memory":
        return Paper(t0)
    return Paper(t0, make_ledger(request.param, tmp_path, "p.db"))


def test_fill_hand_computed(paper):
    d, i, f = paper.open()
    assert f.ok, f
    assert f.details["entry_price"] == "2400.50" and D(f.details["risk_at_fill"]) == D("42")
    pos = paper.led.open_positions(ACC, paper.w.now)
    assert len(pos) == 1 and pos[0].volume == D("0.04") and pos[0].stop_loss == D("2390.0")
    # giữ chỗ đã chuyển thành vị thế: không tính hai lần
    assert paper.led.reserved_total(ACC) == 0
    assert paper.led.opened_count(ACC, paper.w.now - minutes(1), paper.w.now) == 1


def test_fill_is_idempotent(paper):
    d, i, f = paper.open()
    again = paper.broker.fill(d, i, FEED)
    assert again.ok and again.position_id == f.position_id
    assert len(paper.led.open_positions(ACC, paper.w.now)) == 1


def test_price_moved_against_refuses_fill(paper):
    i = intent(paper.w.now - minutes(0.5))
    d = paper.w.evaluate(i, keep_key=True)
    paper.w.quote = q(paper.w.now - S, "2400.80", "2401.00")      # ask lên 0,80
    f = paper.broker.fill(d, i, FEED)
    # (2401,30 − 2390) × 100 × 0,04 = 45,20 > 42 đã duyệt → không khớp
    assert not f.ok and f.code == "PRICE_MOVED" and D(f.details["risk_at_fill"]) == D("45.2")
    assert paper.led.open_positions(ACC, paper.w.now) == []
    assert paper.led.reserved_total(ACC) == D("42")                # còn giữ chỗ tới khi hết hạn


def test_price_already_below_stop_refuses(paper):
    i = intent(paper.w.now - minutes(0.5))
    d = paper.w.evaluate(i, keep_key=True)
    paper.w.quote = q(paper.w.now - S, "2389.00", "2389.20")
    assert paper.broker.fill(d, i, FEED).code == "PRICE_MOVED"


@pytest.mark.parametrize("quote,code", [
    (None, "QUOTE_STALE"),
    ("old", "QUOTE_STALE"),
    ("future", "QUOTE_STALE"),
    ("closed", "MARKET_CLOSED"),
])
def test_fill_needs_fresh_open_market_quote(paper, quote, code):
    i = intent(paper.w.now - minutes(0.5))
    d = paper.w.evaluate(i, keep_key=True)
    n = paper.w.now
    paper.w.quote = {None: None, "old": q(n - 11 * S, 2400, "2400.2"),
                     "future": q(n + S, 2400, "2400.2"),
                     "closed": q(n - S, 2400, "2400.2", flags=(CALENDAR_CLOSED,))}[quote]
    assert paper.broker.fill(d, i, FEED).code == code


def test_expired_decision_not_filled(paper):
    i = intent(paper.w.now - minutes(0.5))
    d = paper.w.evaluate(i, keep_key=True)
    paper.at(d.expires_at)
    paper.w.quote = q(paper.w.now - S, 2400, "2400.2")
    assert paper.broker.fill(d, i, FEED).code == "DECISION_EXPIRED"


def test_released_reservation_not_filled(paper):
    i = intent(paper.w.now - minutes(0.5))
    d = paper.w.evaluate(i, keep_key=True)
    paper.led.release(ACC, d.reservation_id, "test")
    assert paper.broker.fill(d, i, FEED).code == "RESERVATION_RELEASED"


def test_rejected_decision_never_filled(paper):
    paper.w.commission = None
    i = intent(paper.w.now - minutes(0.5))
    d = paper.w.evaluate(i, keep_key=True)
    assert paper.broker.fill(d, i, FEED).code == "NOT_APPROVED"


# ---------------------------------------------------------------- đóng SL / TP

def _close_with(paper, *quotes):
    paper.open()
    t = paper.w.now
    paper.quotes = [x(t) for x in quotes]
    paper.at(t + minutes(5))
    return paper.broker.check_exits(ACC)


def test_stop_loss_hand_computed(paper):
    out = _close_with(paper, lambda t: q(t + 5 * S, "2395", "2395.2"),
                      lambda t: q(t + 9 * S, "2390.5", "2390.7", bid_low="2389.9"))
    assert len(out) == 1 and out[0].reason == "STOP_LOSS"
    # (2390 − 2400,50) × 100 × 0,04 = −42,00
    assert out[0].amount == D("-42") and out[0].data["exit_price"] == "2390.0"
    assert paper.led.open_positions(ACC, paper.w.now) == []
    tr = paper.led.closed_trades(ACC, paper.w.now - minutes(10), paper.w.now)
    assert len(tr) == 1 and tr[0].net_pnl == D("-42")


def test_gap_through_stop_fills_worse(paper):
    out = _close_with(paper, lambda t: q(t + 5 * S, "2385", "2385.2", bid_low="2384"))
    # khoảng trống: đóng ở bid 2385 (xấu hơn SL) → (2385 − 2400,5) × 4 = −62
    assert out[0].amount == D("-62") and D(out[0].data["exit_price"]) == 2385


def test_take_profit_hand_computed(paper):
    out = _close_with(paper, lambda t: q(t + 5 * S, "2420.1", "2420.3"))
    # đóng đúng TP 2420 (không tính trượt giá có lợi): (2420 − 2400,5) × 4 = 78
    assert out[0].reason == "TAKE_PROFIT" and out[0].amount == D("78")


def test_both_in_one_second_counts_as_stop(paper):
    out = _close_with(paper, lambda t: q(t + 5 * S, "2420.1", "2420.3", bid_low="2389"))
    assert out[0].reason == "STOP_LOSS" and out[0].amount == D("-42")


def test_future_and_late_quotes_respect_available_at(paper):
    paper.open()
    t = paper.w.now
    # giây chạm SL lúc t+5 nhưng hệ thống chỉ BIẾT lúc t+10 phút
    paper.quotes = [q(t + 5 * S, "2389", "2389.2", avail=t + minutes(10))]
    paper.at(t + minutes(5))
    assert paper.broker.check_exits(ACC) == []                    # chưa biết → không đóng
    paper.at(t + minutes(8))
    assert paper.broker.check_exits(ACC) == []                    # quét nhanh (chưa tới 5 phút)
    paper.at(t + minutes(11))                     # quét lại từ lúc mở → thấy giây đến muộn
    out = paper.broker.check_exits(ACC)                           # biết rồi → đóng
    assert len(out) == 1 and out[0].data["trigger_t"] == (t + 5 * S).isoformat()


def test_quote_at_exactly_now_is_seen(paper):
    paper.open()
    t = paper.w.now + minutes(1)
    paper.quotes = [q(t, "2389", "2389.2")]
    paper.at(t)
    assert len(paper.broker.check_exits(ACC)) == 1


def test_closed_market_seconds_ignored_and_no_double_close(paper):
    paper.open()
    t = paper.w.now
    paper.quotes = [q(t + 5 * S, "2389", "2389.2", flags=(CALENDAR_CLOSED,))]
    paper.at(t + minutes(1))
    assert paper.broker.check_exits(ACC) == []
    paper.quotes.append(q(t + minutes(2), "2389", "2389.2"))
    paper.at(t + minutes(3))
    assert len(paper.broker.check_exits(ACC)) == 1
    paper.broker._mark.clear()                                    # "khởi động lại"
    assert paper.broker.check_exits(ACC) == []                    # đã đóng → không đóng lại


def test_modify_sl_only_tightens(paper):
    _, _, f = paper.open()
    pid = f.position_id
    assert not paper.broker.modify_sl(ACC, pid, D("2385"), actor="t", reason="nới")
    assert paper.broker.modify_sl(ACC, pid, D("2400.6"), actor="t", reason="hòa vốn")
    assert paper.led.open_positions(ACC, paper.w.now)[0].stop_loss == D("2400.6")
    t = paper.w.now
    paper.quotes = [q(t + 5 * S, "2400.5", "2400.7")]             # chạm SL mới
    paper.at(t + minutes(1))
    out = paper.broker.check_exits(ACC)
    # (2400,5 − 2400,5) × 4 = 0 (min(SL 2400,6; bid 2400,5))
    assert out[0].amount == 0


def test_risk_sees_paper_positions_and_closed_losses(paper):
    _, _, f = paper.open()
    d = paper.w.evaluate()                                        # pyramiding NONE (hồ sơ test)
    assert "NO_AVERAGING_DOWN" in d.reason_codes
    t = paper.w.now
    paper.quotes = [q(t + 5 * S, "2390.5", "2390.7", bid_low="2389")]
    paper.at(t + minutes(1))
    paper.broker.check_exits(ACC)
    paper.w.quote = q(paper.w.now - S, 2400, "2400.2")
    d = paper.w.evaluate()
    # equity dùng = min(MT5 10.000, paper 10.000 − 42) = 9.958 → 42 / 9.958 = 0,4218 %
    assert d.details["equity_used"] == "9958.00000000" or D(d.details["equity_used"]) == 9958
    assert d.details["daily_loss"] == "0.004218"


# ---------------------------------------------------------------- swap + DST

def test_swap_nights_wednesday_triple_and_weekend():
    tz, hm = "America/New_York", "17:00"
    mon = datetime(2026, 1, 5, 14, tzinfo=UTC)
    assert swap_nights(mon, mon + timedelta(hours=2), tz, hm, 3) == 0
    assert swap_nights(mon, datetime(2026, 1, 6, 12, tzinfo=UTC), tz, hm, 3) == 1   # qua T2
    assert swap_nights(mon, datetime(2026, 1, 8, 12, tzinfo=UTC), tz, hm, 3) == 5   # T2,T3,T4×3
    # qua cuối tuần: T6 (1) + T7, CN không có mốc swap
    fri = datetime(2026, 1, 9, 15, tzinfo=UTC)
    assert swap_nights(fri, datetime(2026, 1, 11, 23, tzinfo=UTC), tz, hm, 3) == 1


def test_swap_nights_follow_dst():
    tz, hm = "America/New_York", "17:00"
    # cùng giờ UTC, hai tuần khác mùa: mốc 17:00 NY = 22:00 UTC (EST) / 21:00 UTC (EDT, từ 8/3)
    a = swap_nights(datetime(2026, 3, 2, 13, tzinfo=UTC),
                    datetime(2026, 3, 3, 21, 30, tzinfo=UTC), tz, hm, 3)
    b = swap_nights(datetime(2026, 3, 9, 13, tzinfo=UTC),
                    datetime(2026, 3, 10, 21, 30, tzinfo=UTC), tz, hm, 3)
    assert (a, b) == (1, 2)


def test_swap_charged_on_close(t0):
    p = Paper(t0)
    # swap mua GIẢ −15 point/lot/đêm (point mode) = 15 $/lot/đêm
    row = spec_row(t0 - timedelta(days=3), swap_long=-15.0)
    p.w.broker = reading(t0, spec=row)
    _, _, f = p.open()
    assert f.ok, f
    t = p.w.now                                              # thứ Hai 14:00 UTC
    p.quotes = [q(datetime(2026, 1, 8, 12, tzinfo=UTC), "2390.5", "2390.7",
                  bid_low="2389")]                                         # thứ Năm, SL
    p.at(datetime(2026, 1, 8, 12, 1, tzinfo=UTC))
    out = p.broker.check_exits(ACC)
    # 5 đêm (T2, T3, T4 ×3) × 15 × 0,04 = 3,00; giá: −42 → ròng −45
    assert D(out[0].data["swap"]) == 3 and out[0].data["swap_nights"] == "5"
    assert out[0].amount == D("-45") and t < out[0].at
    assert [e.type for e in p.led.events(ACC)][-1] is EventType.CLOSE


def test_app_wires_paper_ledger_as_trade_book(tmp_path):
    from gold_trading.api.app import create_app
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'a.db'}")
    repo.create_all()
    app = create_app(repo, auth="env")
    assert isinstance(app.state.paper_ledger, SqlLedger)
    assert app.state.risk_gates.trade_book is app.state.paper_ledger
