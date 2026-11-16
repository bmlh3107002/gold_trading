"""Risk Engine — RSK-10 (KN-01): Risk tự đọc cổng thật lúc quyết. 5-C14, 5-C15, 4-C05, 4-C06.

Số rủi ro trong file này (``TEST_POLICY``) là **số giả chỉ để test** — không phải số khuyến nghị;
số thật đến từ hồ sơ rủi ro người dùng chọn (GĐ5 bước 3, DEC-09).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest

from gold_trading.accounts.runtime import AccountRegistry
from gold_trading.analysts.framework import Scope
from gold_trading.common.enums import RiskOutcome, SafetyState, SourceStatus, TradingMode
from gold_trading.ingestion.source_status import SourceHealth
from gold_trading.risk.blocks import ALL, Block, BlockKind, BlockStore
from gold_trading.risk.engine import RiskEngine, RiskPolicy, SizingInputs
from gold_trading.risk.gates import RiskGates, calendar_health_codes
from gold_trading.risk.ledger import RiskLedger
from gold_trading.storage.market_views import InMemoryMarketViewStore
from gold_trading.storage.repository import InMemoryRepository, Member, TradingAccount
from tests.conftest import minutes
from tests.factories import intent, market_view

# CHỈ ĐỂ TEST — không phải số khuyến nghị (DEC-09: số do người dùng chọn ở bước 3)
TEST_POLICY = dict(max_risk_per_trade=0.005, max_total_reserved=0.02, max_spread=0.5)
ACC = "acc-1"
FEED = "f1"
SCOPE = Scope.of_feed("XAUUSD", "M15", "MT5", FEED)


class World:
    """Cổng thật: ``AccountRegistry`` (Safety + khóa + lệnh cấm), kho MarketView thật."""

    def __init__(self, t0: datetime) -> None:
        self.now = t0
        self.repo = InMemoryRepository()
        self.repo.ensure_default_account()
        self.repo.create_account(TradingAccount(ACC, "A", t0, "system", False))
        self.repo.upsert_user("sub-u", "u", None, None, t0)
        self.repo.set_member(Member(ACC, "sub-u", "OWNER", t0, "system"))
        self.blocks = BlockStore()
        self.registry = AccountRegistry(
            self.repo, policy_version="p0", default_mode=TradingMode.PAPER, live_unlocked=True,
            mode_guard=lambda m: None,
            entry_blocks=lambda acc, at: self.blocks.active(at, FEED))
        self.registry.get(ACC).safety.resume("TEST", trigger_source="t", actor="t")
        self.views = InMemoryMarketViewStore()
        self.views.append(market_view(t0 - minutes(1)), report_id="r1",
                          computed_at=t0 - minutes(1))
        self.calendar: list[str] = []
        self.scope: Scope | None = SCOPE
        self.gates = RiskGates(accounts=self.registry, scope_for=lambda acc: self.scope,
                               market_views=self.views, calendar_health=lambda at: self.calendar)
        self.engine = RiskEngine(RiskPolicy(version="r0", **TEST_POLICY), RiskLedger(),
                                 self.gates, clock=lambda: self.now)

    def evaluate(self, i=None, *, equity=10_000.0, spread=0.2):
        return self.engine.evaluate(i or intent(self.now - minutes(0.5)), ACC,
                                    SizingInputs(equity=equity, spread=spread))


def spread_block(t: datetime, *, end: datetime | None = None, scope: str = FEED) -> Block:
    return Block(BlockKind.SPREAD, scope, "WIDE_SPREAD", t, end or t + minutes(10),
                 f"spread:{t.isoformat()}", t, "p0")


# ---------------------------------------------------------------- đường đi được duyệt

def test_approves_and_sizes_from_risk(t0):
    w = World(t0)
    d = w.evaluate()
    # 0,5 % (số test) của 10k = 50$, SL 10$ × 100 oz = 1000$/lot → 0,05 lot
    assert d.outcome is RiskOutcome.APPROVED, d.reason_codes
    assert d.volume == 0.05
    assert w.engine.ledger.reserved_total() == 50.0


def test_policy_has_no_default_risk_numbers():
    # DEC-09 / KN-12: không có số rủi ro đặt sẵn trong code
    with pytest.raises(TypeError):
        RiskPolicy(version="x")  # type: ignore[call-arg]


# ---------------------------------------------------------------- cổng tài khoản (5-C14)

def test_fast_lane_block_rejects_even_when_safety_active(t0):           # 5-C14
    w = World(t0)
    w.blocks.add(spread_block(t0 - minutes(2)))
    assert w.registry.get(ACC).safety.state is SafetyState.ACTIVE
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED
    assert "ENTRY_BLOCKED:WIDE_SPREAD" in d.reason_codes
    assert w.engine.ledger.reserved_total() == 0


def test_expired_fast_lane_block_no_longer_rejects(t0):
    w = World(t0)
    w.blocks.add(spread_block(t0 - minutes(20), end=t0 - minutes(5)))
    assert w.evaluate().outcome is RiskOutcome.APPROVED


def test_block_for_other_feed_does_not_apply(t0):
    w = World(t0)
    w.blocks.add(spread_block(t0 - minutes(2), scope="other-feed"))
    assert w.evaluate().outcome is RiskOutcome.APPROVED
    w.blocks.add(spread_block(t0 - minutes(1), scope=ALL))
    assert "ENTRY_BLOCKED:WIDE_SPREAD" in w.evaluate().reason_codes


def test_rejects_when_safety_paused(t0):
    w = World(t0)
    w.registry.get(ACC).safety.pause("NEWS", trigger_source="t", actor="t")
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED and "SAFETY_PAUSED" in d.reason_codes


def test_rejects_when_owner_locked(t0):
    w = World(t0)
    w.repo.set_user_status("sub-u", "LOCKED", t0)
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED and "ACCOUNT_LOCKED" in d.reason_codes


def test_unknown_account_rejected(t0):
    w = World(t0)
    d = w.engine.evaluate(intent(t0), "khong-co", SizingInputs(10_000.0, 0.2))
    assert d.outcome is RiskOutcome.REJECTED and "ACCOUNT_UNKNOWN" in d.reason_codes


@pytest.mark.parametrize("gate", ["accounts", "mode", "price_feed", "market_view",
                                  "calendar_health"])
def test_gate_read_error_rejects_and_does_not_raise(t0, gate):
    w = World(t0)

    def boom(*a, **k):
        raise RuntimeError("đọc lỗi")

    if gate == "accounts":
        w.registry.entry_denials = boom  # type: ignore[method-assign]
    elif gate == "mode":
        w.registry.mode = boom  # type: ignore[method-assign]
    elif gate == "price_feed":
        object.__setattr__(w.gates, "scope_for", boom)
    elif gate == "market_view":
        w.views.current = boom  # type: ignore[method-assign]
    else:
        object.__setattr__(w.gates, "calendar_health", boom)
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED
    assert f"GATE_READ_ERROR:{gate}" in d.reason_codes
    assert w.engine.ledger.reserved_total() == 0


def test_repository_read_error_rejects(t0):
    w = World(t0)

    def boom(*a, **k):
        raise RuntimeError("db down")

    w.repo.members = boom  # type: ignore[method-assign]
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED and "GATE_READ_ERROR:accounts" in d.reason_codes


# ---------------------------------------------------------------- MarketView hiện hành (5-C15)

def test_market_view_invalidated_after_intent_rejects(t0):              # 5-C15
    w = World(t0)
    i = intent(t0 - minutes(0.5))
    w.views.invalidate("mv1", at=t0 - minutes(0.1), reason="CALENDAR_SOURCE_DOWN")
    d = w.evaluate(i)
    assert d.outcome is RiskOutcome.REJECTED and "NO_MARKET_VIEW" in d.reason_codes


def test_newer_market_view_replaces_intent_view(t0):
    w = World(t0)
    w.views.append(market_view(t0 - minutes(0.2), market_view_id="mv2"), report_id="r2",
                   computed_at=t0 - minutes(0.2))
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED and "MARKET_VIEW_MISMATCH" in d.reason_codes


def test_other_feed_market_view_not_seen(t0):
    w = World(t0)
    w.scope = Scope.of_feed("XAUUSD", "M15", "MT5", "f2")
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED and "NO_MARKET_VIEW" in d.reason_codes


def test_no_price_feed_rejects(t0):
    w = World(t0)
    w.scope = None
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED and "NO_PRICE_FEED" in d.reason_codes


def test_market_view_expires_while_in_use(t0):                          # 4-C05
    w = World(t0)
    mv = market_view(t0 - minutes(1))
    i = intent(t0 - minutes(0.5), expiry=mv.expires_at + minutes(5))
    w.now = mv.expires_at - minutes(0.01)
    assert "NO_MARKET_VIEW" not in w.evaluate(i).reason_codes
    w.now = mv.expires_at
    d = w.evaluate(i)
    assert d.outcome is RiskOutcome.REJECTED and "NO_MARKET_VIEW" in d.reason_codes


def test_rejects_blocking_risk_flags_and_expired_intent(t0):
    w = World(t0)
    w.views = InMemoryMarketViewStore()
    w.views.append(market_view(t0 - minutes(1), risk_flags=frozenset({"NEWS_SHOCK"})),
                   report_id="r", computed_at=t0 - minutes(1))
    object.__setattr__(w.gates, "market_views", w.views)
    i = intent(t0 - minutes(5))   # hết hạn sau 2 phút
    d = w.evaluate(i)
    assert "RISK_FLAGS:NEWS_SHOCK" in d.reason_codes and "INTENT_EXPIRED" in d.reason_codes


def test_symbol_mismatch_rejected(t0):
    w = World(t0)
    d = w.evaluate(intent(t0 - minutes(0.5), symbol="XAGUSD"))
    assert d.outcome is RiskOutcome.REJECTED and "SYMBOL_MISMATCH" in d.reason_codes


# ---------------------------------------------------------------- nguồn lịch (Q1)

def test_unhealthy_calendar_source_rejects_while_market_view_valid(t0):
    w = World(t0)
    w.calendar = ["CALENDAR_SOURCE_UNHEALTHY:dol_claims_schedule"]
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED
    assert "CALENDAR_SOURCE_UNHEALTHY:dol_claims_schedule" in d.reason_codes


def _health(src, status=SourceStatus.HEALTHY, failures=0):
    t = datetime(2026, 11, 16, tzinfo=None)
    return SourceHealth(src, t, status, "OK", None, None, failures, None, None, frozenset())


def test_calendar_health_codes_rules():
    srcs = ("a", "b", "c", "d")
    details = {"a": _health("a"), "b": _health("b", SourceStatus.STALE),
               "c": _health("c", failures=1)}
    assert calendar_health_codes(details, srcs) == [
        "CALENDAR_SOURCE_UNHEALTHY:b", "CALENDAR_SOURCE_UNHEALTHY:c",
        "CALENDAR_SOURCE_UNHEALTHY:d"]      # d: chưa biết → không khỏe
    assert calendar_health_codes({"a": _health("a")}, ("a",)) == []


# ---------------------------------------------------------------- chế độ + cờ chất lượng (DEC-25)

SAMPLE_FLAGS = frozenset({"UNCALIBRATED", "UNVALIDATED_RULES", "SAMPLE_DATA"})


@pytest.mark.parametrize("mode", [TradingMode.PAPER, TradingMode.BACKTEST])
def test_unvalidated_rules_allowed_in_paper_and_backtest(t0, mode):
    w = World(t0)
    w.registry.mode = lambda acc: mode  # type: ignore[method-assign]
    assert w.evaluate().outcome is RiskOutcome.APPROVED


@pytest.mark.parametrize("mode", [TradingMode.SHADOW, TradingMode.LIVE])
def test_unvalidated_rules_blocked_in_shadow_and_live(t0, mode):
    w = World(t0)
    w.registry.mode = lambda acc: mode  # type: ignore[method-assign]
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED
    assert f"QUALITY_FLAGS_{mode.value}:UNVALIDATED_RULES" in d.reason_codes
    assert w.engine.ledger.reserved_total() == 0.0


@pytest.mark.parametrize("mode", [TradingMode.SHADOW, TradingMode.LIVE])
def test_sample_data_blocked_in_shadow_and_live(t0, mode):            # 4-C06
    w = World(t0)
    w.registry.mode = lambda acc: mode  # type: ignore[method-assign]
    w.views.append(market_view(t0 - minutes(0.5), market_view_id="mv-s", source="SAMPLE",
                               quality_flags=SAMPLE_FLAGS), report_id="r", computed_at=t0)
    w.scope = Scope.of_feed("XAUUSD", "M15", "SAMPLE", FEED)
    d = w.evaluate(intent(t0 - minutes(0.5), market_view_id="mv-s"))
    assert d.outcome is RiskOutcome.REJECTED
    assert f"QUALITY_FLAGS_{mode.value}:SAMPLE_DATA,UNVALIDATED_RULES" in d.reason_codes


def test_sample_data_still_blocked_even_if_rules_validated_later(t0):
    w = World(t0)
    w.registry.mode = lambda acc: TradingMode.LIVE  # type: ignore[method-assign]
    pol = {TradingMode.LIVE: frozenset({"SAMPLE_DATA"})}
    w.engine.policy = RiskPolicy(version="r1", blocking_quality_flags=pol, **TEST_POLICY)
    w.views.append(market_view(t0 - minutes(0.5), market_view_id="mv-s", source="SAMPLE",
                               quality_flags=SAMPLE_FLAGS), report_id="r", computed_at=t0)
    w.scope = Scope.of_feed("XAUUSD", "M15", "SAMPLE", FEED)
    d = w.evaluate(intent(t0 - minutes(0.5), market_view_id="mv-s"))
    assert d.outcome is RiskOutcome.REJECTED and "QUALITY_FLAGS_LIVE:SAMPLE_DATA" in d.reason_codes


@pytest.mark.parametrize("mode", ["LIVE", "PAPER", None])
def test_mode_must_be_enum(t0, mode):
    # Chế độ không rõ (chuỗi thô / thiếu) → chặn, không ngầm coi là PAPER.
    w = World(t0)
    w.registry.mode = lambda acc: mode  # type: ignore[method-assign]
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED and "MODE_UNKNOWN" in d.reason_codes


def test_mode_is_read_from_account_not_caller(t0):
    # Tài khoản thật đang LIVE → luật chưa kiểm chứng bị chặn dù bên gọi không khai gì
    w = World(t0)
    w.registry.get(ACC).modes._mode = TradingMode.LIVE  # type: ignore[attr-defined]
    d = w.evaluate()
    assert "QUALITY_FLAGS_LIVE:UNVALIDATED_RULES" in d.reason_codes


# ---------------------------------------------------------------- hạn mức (tạm, tới bước 3–4)

def test_reduces_when_request_exceeds_per_trade_limit(t0):
    w = World(t0)
    d = w.evaluate(intent(t0 - minutes(0.5), risk_budget_requested=0.02))
    assert d.outcome is RiskOutcome.REDUCED
    assert d.volume == 0.05


def test_concurrent_intents_never_exceed_total_limit(t0):
    w = World(t0)
    w.engine.policy = RiskPolicy(version="r0", **(TEST_POLICY | {"max_total_reserved": 0.01}))
    intents = [intent(t0 - minutes(0.5), intent_id=f"i{n}", idempotency_key=f"k{n}")
               for n in range(10)]
    with ThreadPoolExecutor(max_workers=10) as pool:
        decisions = list(pool.map(w.evaluate, intents))
    approved = [d for d in decisions if d.outcome is not RiskOutcome.REJECTED]
    assert len(approved) == 2
    assert w.engine.ledger.reserved_total() <= 100.0 + 1e-9


def test_decision_time_comes_from_risk_clock(t0):
    w = World(t0)
    d = w.evaluate()
    assert d.decided_at == t0 and d.expires_at == t0 + timedelta(seconds=30)
