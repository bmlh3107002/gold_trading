"""Equity paper + H6 (dừng hẳn khi sụt từ đỉnh) + H10 (nạp / rút tách khỏi lãi lỗ) — GĐ5 bước 6c.
Thiết kế 35 mục 12.5. Số hồ sơ / broker là **số giả chỉ để test**.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from gold_trading.common.enums import RiskOutcome, SafetyState
from gold_trading.risk.ledger import (
    EventType,
    LedgerConflict,
    LedgerEvent,
    RiskLedger,
    replay_equity,
)
from tests.test_paper_fill import Paper
from tests.test_risk_engine import ACC, TEST_PROFILE, World, closed

D = Decimal
T = datetime(2026, 1, 1, tzinfo=UTC)


def ev(n, type, amount, **data):
    return LedgerEvent(f"e{n}", ACC, n, type, f"r{n}", None, D(amount), T + timedelta(hours=n),
                       "u", "x", None, {k: str(v) for k, v in data.items()})


def test_replay_hand_computed():
    evs = [ev(1, EventType.START, "10000"),
           ev(2, EventType.CLOSE, "500"),           # 10.500, đỉnh 10.500
           ev(3, EventType.CLOSE, "-300"),          # 10.200, đỉnh giữ 10.500
           ev(4, EventType.CASH_IN, "1000"),        # 11.200, đỉnh + 1.000 = 11.500 (H10)
           ev(5, EventType.CASH_OUT, "2240", equity_before="11200")]  # rút 20 %
    st = replay_equity(evs)
    # rút: equity 8.960; đỉnh × (1 − 2.240 / 11.200) = 11.500 × 0,8 = 9.200
    assert st.realized == D("8960") and st.peak == D("9200")
    # sụt = (9.200 − 8.960) / 9.200 = 2,6 % — nạp / rút không làm đổi tỷ lệ sụt (H10)
    assert replay_equity(evs[:3]).peak == D("10500")
    assert replay_equity([ev(1, EventType.CLOSE, "5")]) is None          # chưa START
    reset = evs + [ev(6, EventType.DRAWDOWN_RESET, "8960")]
    assert replay_equity(reset).peak == D("8960")
    peak = evs[:1] + [ev(2, EventType.PEAK, "10400")]
    assert replay_equity(peak).peak == D("10400")


def test_not_started_rejects(t0):
    w = World(t0)
    w.book.capital = None
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED and d.reason_codes == ("PAPER_LEDGER_NOT_STARTED",)


def _dd_world(t0, realized_after_loss: str):
    w = World(t0)
    w.book.capital = D(10_000)
    # cả lãi lẫn lỗ ở THÁNG TRƯỚC → bộ đếm lỗ ngày / tuần / tháng = 0; chỉ còn H6
    w.book.add_closed(ACC, closed(1, "600", datetime(2025, 11, 20, tzinfo=UTC)))
    w.book.add_closed(ACC, closed(2, str(D(realized_after_loss) - 10_600),
                                  datetime(2025, 12, 10, tzinfo=UTC)))
    return w


@pytest.mark.parametrize("realized,halt", [("10070", True), ("10071", False)])
def test_drawdown_halt_boundary(t0, realized, halt):                        # H6
    w = _dd_world(t0, realized)
    d = w.evaluate()
    # đỉnh 10.600; 10.070 → sụt 530 / 10.600 = 5,000 % ≥ 5 % → dừng hẳn
    if halt:
        assert d.reason_codes == ("DRAWDOWN_HALT",) and d.details["drawdown"] == "0.050000"
        assert d.details["safety_paused"] == "DRAWDOWN_HALT"
        assert w.registry.get(ACC).safety.state is SafetyState.PAUSED
    else:
        assert d.outcome is not RiskOutcome.REJECTED, d.reason_codes
        assert d.details["drawdown"] == "0.049906"


def test_resume_without_explicit_reset_halts_again(t0):                    # H6
    p = Paper(t0)
    led = p.led
    led.mark_peak(ACC, D(10_600), at=t0 - timedelta(days=1))
    led.append(ACC, EventType.CLOSE, "pos_x", D(-600), at=t0 - timedelta(days=40), actor="paper",
               reason="test", data={"side": "BUY", "opened_at": (t0 - timedelta(days=41))
                                     .isoformat()})
    # equity 9.400, đỉnh 10.600 → sụt 11,3 %
    d = p.w.evaluate()
    assert d.reason_codes == ("DRAWDOWN_HALT",)
    sf = p.w.registry.get(ACC).safety
    sf.resume("NGUOI_DUNG", trigger_source="t", actor="sub-u")     # chỉ bấm resume
    assert p.w.evaluate().reason_codes == ("DRAWDOWN_HALT",)        # vẫn dừng + PAUSED lại
    assert sf.state is SafetyState.PAUSED
    led.drawdown_reset(ACC, D(9_400), actor="sub-u", reason="đã xem lại, chấp nhận mức sụt",
                       at=t0 - timedelta(seconds=1))
    sf.resume("NGUOI_DUNG", trigger_source="t", actor="sub-u")
    d = p.w.evaluate()
    assert d.outcome is not RiskOutcome.REJECTED and d.details["drawdown"] == "0.000000"


def test_unrealized_counts_for_drawdown_and_peak_marks(t0):
    p = Paper(t0)
    p.w.profiles.append(ACC, replace(TEST_PROFILE, pyramiding_policy="ONLY_IF_ALL_SAFE"),
                        created_by="sub-u", reason="t", at=t0 - timedelta(minutes=1))
    _, _, f = p.open()                                            # 0,04 lot vào 2400,50
    assert p.led.mark_peak(ACC, D(9_000), at=p.w.now) is None    # không vượt đỉnh → không ghi
    # tick ghi đỉnh khi equity gồm lãi đang chạy lên 10.500
    assert p.led.mark_peak(ACC, D(10_500), at=p.w.now) is not None
    # giá rơi: bid 2390,2 → lỗ đang chạy (2390,2 − 2400,5) × 4 = −41,2; equity 9.958,8
    from tests.test_paper_fill import q
    p.w.quote = q(p.w.now - timedelta(seconds=1), "2390.2", "2390.4")
    d = p.w.evaluate()
    assert D(d.details["paper_equity"]) == D("9958.8")
    # (10.500 − 9.958,8) / 10.500 = 5,15 % ≥ 5 %
    assert d.details["drawdown"] == "0.051543"
    assert "DRAWDOWN_HALT" in d.reason_codes


def test_sizing_uses_smaller_of_mt5_and_paper(t0):
    w = World(t0)
    w.book.capital = D(8_000)                         # paper nhỏ hơn MT5 10.000
    d = w.evaluate()
    # 0,5 % × 8.000 = 40 → 40 / 1050 = 0,038 → 0,03 lot
    assert d.volume == D("0.03") and d.details["equity_used"] == "8000"


# ---------------------------------------------------------------- H10 nạp / rút

def test_cash_flows(t0):
    led = RiskLedger()
    with pytest.raises(ValueError):                   # chưa bắt đầu
        led.cash_flow(ACC, EventType.CASH_IN, D(1), unrealized=D(0), actor="u", reason="x")
    led.start(ACC, D(10_000), actor="u", reason="bắt đầu paper", at=t0)
    with pytest.raises(LedgerConflict):               # một lần
        led.start(ACC, D(10_000), actor="u", reason="lại", at=t0)
    led.cash_flow(ACC, EventType.CASH_IN, D(2_000), unrealized=D(0), actor="u", reason="nạp",
                  at=t0)
    st = led.equity_state(ACC, t0)
    assert (st.realized, st.peak) == (D(12_000), D(12_000))
    with pytest.raises(ValueError):                   # rút ≥ equity
        led.cash_flow(ACC, EventType.CASH_OUT, D(12_000), unrealized=D(0), actor="u",
                      reason="rút hết", at=t0)
    led.cash_flow(ACC, EventType.CASH_OUT, D(3_000), unrealized=D(0), actor="u", reason="rút",
                  at=t0)
    st = led.equity_state(ACC, t0)
    assert (st.realized, st.peak) == (D(9_000), D(9_000))
    for bad in (D(0), D(-1), 5):
        with pytest.raises(ValueError):
            led.cash_flow(ACC, EventType.CASH_IN, bad, unrealized=D(0), actor="u", reason="x")


def test_deposit_is_not_profit_and_does_not_resume(t0):                    # H10
    p = Paper(t0)
    p.w.registry.get(ACC).safety.pause("DRAWDOWN_HALT", trigger_source="risk", actor="risk")
    p.led.cash_flow(ACC, EventType.CASH_IN, D(5_000), unrealized=D(0), actor="sub-u",
                    reason="nạp", at=t0 - timedelta(hours=1))
    assert p.w.registry.get(ACC).safety.state is SafetyState.PAUSED   # nạp không tự mở lại
    p.w.registry.get(ACC).safety.resume("T", trigger_source="t", actor="sub-u")
    d = p.w.evaluate()
    # bộ đếm lỗ / chuỗi chỉ tính PnL giao dịch: nạp không thành "lãi" bù lỗ ngày
    assert d.details["daily_loss"] == "0.000000" and d.details["drawdown"] == "0.000000"
    assert d.details["paper_equity"].startswith("15000")
    # equity dùng vẫn ≤ MT5 (10.000): nạp vào paper không tăng lot quá tiền thật
    assert D(d.details["equity_used"]) == 10_000
