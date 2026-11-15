from concurrent.futures import ThreadPoolExecutor

import pytest

from gold_trading.common.enums import RiskOutcome, SafetyState, TradingMode
from gold_trading.risk.engine import MarketContext, RiskEngine, RiskPolicy
from gold_trading.risk.ledger import RiskLedger
from gold_trading.safety.supervisor import SafetySupervisor
from tests.conftest import minutes
from tests.factories import intent, market_view


def make_engine(**policy_kw) -> RiskEngine:
    return RiskEngine(
        RiskPolicy(version="r0", **policy_kw),
        RiskLedger(),
        SafetySupervisor("p0", initial_state=SafetyState.ACTIVE),
    )


def ctx(t0, **kw) -> MarketContext:
    return MarketContext(**({"equity": 10_000.0, "spread": 0.2, "now": t0,
                             "mode": TradingMode.PAPER} | kw))


def test_approves_and_sizes_from_risk(t0):
    eng = make_engine()
    d = eng.evaluate(intent(t0), market_view(t0), ctx(t0))
    # 0.5% của 10k = 50$, SL 10$ * 100oz = 1000$/lot -> 0.05 lot
    assert d.outcome is RiskOutcome.APPROVED
    assert d.volume == 0.05
    assert eng.ledger.reserved_total() == 50.0


def test_rejects_when_safety_paused(t0):
    eng = make_engine()
    eng.safety.pause("NEWS", trigger_source="t", actor="t")
    d = eng.evaluate(intent(t0), market_view(t0), ctx(t0))
    assert d.outcome is RiskOutcome.REJECTED
    assert "SAFETY_PAUSED" in d.reason_codes
    assert eng.ledger.reserved_total() == 0


def test_rejects_expired_market_view_and_blocking_flags(t0):
    eng = make_engine()
    later = t0 + minutes(1)
    mv = market_view(t0 - minutes(20), risk_flags=frozenset({"NEWS_SHOCK"}))
    d = eng.evaluate(intent(later), mv, ctx(later))
    assert "MARKET_VIEW_EXPIRED" in d.reason_codes
    assert "RISK_FLAGS:NEWS_SHOCK" in d.reason_codes


def test_reduces_when_request_exceeds_per_trade_limit(t0):
    eng = make_engine()
    d = eng.evaluate(intent(t0, risk_budget_requested=0.02), market_view(t0), ctx(t0))
    assert d.outcome is RiskOutcome.REDUCED
    assert d.volume == 0.05


def test_concurrent_intents_never_exceed_total_limit(t0):
    eng = make_engine(max_total_reserved=0.01)  # tối đa 100$ -> 2 lệnh 50$
    intents = [intent(t0, intent_id=f"i{n}", idempotency_key=f"k{n}") for n in range(10)]
    with ThreadPoolExecutor(max_workers=10) as pool:
        decisions = list(pool.map(lambda i: eng.evaluate(i, market_view(t0), ctx(t0)), intents))
    approved = [d for d in decisions if d.outcome is not RiskOutcome.REJECTED]
    assert len(approved) == 2
    assert eng.ledger.reserved_total() <= 100.0 + 1e-9


# ---------- GĐ4 bước 5c: cờ chất lượng MarketView theo chế độ (DEC-25; 4-C05, 4-C06) ----------

SAMPLE_FLAGS = frozenset({"UNCALIBRATED", "UNVALIDATED_RULES", "SAMPLE_DATA"})


@pytest.mark.parametrize("mode", [TradingMode.PAPER, TradingMode.BACKTEST])
def test_unvalidated_rules_allowed_in_paper_and_backtest(t0, mode):
    d = make_engine().evaluate(intent(t0), market_view(t0), ctx(t0, mode=mode))
    assert d.outcome is RiskOutcome.APPROVED


@pytest.mark.parametrize("mode", [TradingMode.SHADOW, TradingMode.LIVE])
def test_unvalidated_rules_blocked_in_shadow_and_live(t0, mode):
    eng = make_engine()
    d = eng.evaluate(intent(t0), market_view(t0), ctx(t0, mode=mode))
    assert d.outcome is RiskOutcome.REJECTED
    assert f"QUALITY_FLAGS_{mode.value}:UNVALIDATED_RULES" in d.reason_codes
    assert eng.ledger.reserved_total() == 0.0


@pytest.mark.parametrize("mode", [TradingMode.SHADOW, TradingMode.LIVE])
def test_sample_data_blocked_in_shadow_and_live(t0, mode):            # 4-C06
    mv = market_view(t0, source="SAMPLE", quality_flags=SAMPLE_FLAGS)
    d = make_engine().evaluate(intent(t0), mv, ctx(t0, mode=mode))
    assert d.outcome is RiskOutcome.REJECTED
    assert f"QUALITY_FLAGS_{mode.value}:SAMPLE_DATA,UNVALIDATED_RULES" in d.reason_codes


def test_sample_data_still_blocked_even_if_rules_validated_later(t0):
    # Giả lập chính sách sau GĐ6 chỉ còn chặn SAMPLE_DATA → SAMPLE vẫn bị chặn ở LIVE.
    pol = {TradingMode.LIVE: frozenset({"SAMPLE_DATA"})}
    eng = make_engine(blocking_quality_flags=pol)
    mv = market_view(t0, source="SAMPLE", quality_flags=SAMPLE_FLAGS)
    d = eng.evaluate(intent(t0), mv, ctx(t0, mode=TradingMode.LIVE))
    assert d.outcome is RiskOutcome.REJECTED and "QUALITY_FLAGS_LIVE:SAMPLE_DATA" in d.reason_codes


@pytest.mark.parametrize("mode", ["LIVE", "PAPER", None])
def test_mode_must_be_enum(t0, mode):
    # Chế độ không rõ (chuỗi thô / thiếu) → chặn, không ngầm coi là PAPER.
    d = make_engine().evaluate(intent(t0), market_view(t0), ctx(t0, mode=mode))
    assert d.outcome is RiskOutcome.REJECTED and "MODE_UNKNOWN" in d.reason_codes


def test_market_view_expires_while_in_use(t0):                          # 4-C05
    mv = market_view(t0)
    i = intent(t0)
    ok = make_engine().evaluate(i, mv, ctx(mv.expires_at - minutes(0.01)))
    assert "MARKET_VIEW_EXPIRED" not in ok.reason_codes
    d = make_engine().evaluate(i, mv, ctx(mv.expires_at))
    assert d.outcome is RiskOutcome.REJECTED and "MARKET_VIEW_EXPIRED" in d.reason_codes
