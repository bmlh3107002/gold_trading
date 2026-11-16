"""Risk Engine — RSK-10 (KN-01): Risk tự đọc cổng thật lúc quyết. 5-C14, 5-C15, 4-C05, 4-C06.

Số rủi ro trong file này (``TEST_POLICY``) là **số giả chỉ để test** — không phải số khuyến nghị;
số thật đến từ hồ sơ rủi ro người dùng chọn (GĐ5 bước 3, DEC-09).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from gold_trading.accounts.runtime import AccountRegistry
from gold_trading.analysts.framework import Scope
from gold_trading.common.enums import RiskOutcome, SafetyState, SourceStatus, TradingMode
from gold_trading.ingestion.source_status import SourceHealth
from gold_trading.market.quote_minutes import QuoteMinute
from gold_trading.market.quotes import QuoteSecond
from gold_trading.risk.blocks import ALL, Block, BlockKind, BlockStore
from gold_trading.risk.engine import RiskEngine, RiskPolicy
from gold_trading.risk.gates import BrokerReading, RiskGates, calendar_health_codes
from gold_trading.risk.ledger import RiskLedger
from gold_trading.storage.broker_history import SpecKey, SpecRow, spec_hash
from gold_trading.storage.commissions import Commission
from gold_trading.storage.market_views import InMemoryMarketViewStore
from gold_trading.storage.repository import InMemoryRepository, Member, TradingAccount
from tests.conftest import minutes
from tests.factories import intent, market_view

# CHỈ ĐỂ TEST — không phải số khuyến nghị (DEC-09: số do người dùng chọn ở bước 3)
TEST_POLICY = dict(max_risk_per_trade=Decimal("0.005"), max_total_reserved=Decimal("0.02"))
ACC = "acc-1"
FEED = "f1"
SCOPE = Scope.of_feed("XAUUSD", "M15", "MT5", FEED)
LOGIN, SERVER, SYM = 123, "Broker-Demo", "XAUUSD"
# Thông số broker GIẢ (chỉ để test): 1 lot = 100 oz, point 0,01, stops 20 / freeze 10 point.
SPEC = dict(digits=2, point=0.01, contract_size=100.0, volume_min=0.01, volume_max=50.0,
            volume_step=0.01, currency_profit="USD", stops_level=20, freeze_level=10,
            swap_mode=1, swap_long=-1.5, swap_short=0.4, swap_rollover3days=3, leverage=100,
            account_currency="USD")


def spec_row(t: datetime, **kw) -> SpecRow:
    spec = SPEC | kw
    return SpecRow(SpecKey(ACC, LOGIN, SERVER, SYM), t, spec, spec_hash(spec), "0.10.3")


def reading(t: datetime, *, equity=10_000.0, spec: SpecRow | None = None, **kw) -> BrokerReading:
    row = spec if spec is not None else spec_row(t - timedelta(days=3))
    base = dict(connected=True, heartbeat_age_s=2.0, equity=equity, account_currency="USD",
                identity=(LOGIN, SERVER), heartbeat_symbol=SYM, live_spec_hash=row.spec_hash,
                locked_symbol=SYM, spec=row)
    return BrokerReading(**(base | kw))


def quote(t: datetime, spread=20, *, flags=(), age=timedelta(seconds=1)) -> QuoteSecond:
    q = t - age
    return QuoteSecond(FEED, q, 2400.0, 2400.0 + spread / 100, 2399.9, 2400.5, spread, spread, 5,
                       tuple(flags), q, q)


def minutes_rows(t: datetime, n=7000, p95=30, *, closed=0) -> list[QuoteMinute]:
    start = t - timedelta(minutes=n + 5)
    return [QuoteMinute(FEED, start + timedelta(minutes=k), 60, 100, 2400.0, 2400.0, 2400.2,
                        2399.0, 2401.0, 10, 15.0, p95, p95 + 5, 0, closed,
                        computed_at=t - timedelta(days=40), available_at=t - timedelta(days=40))
            for k in range(n)]


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
        self.broker = reading(t0)
        self.quote: QuoteSecond | None = quote(t0)
        self.minutes = minutes_rows(t0)
        # Phí GIẢ (chỉ để test): 0 USD / lot do "người dùng" nhập
        self.commission: Commission | None = Commission(ACC, Decimal("0"), "USD",
                                                        t0 - timedelta(days=1), "sub-u", "test")
        self.gates = RiskGates(
            accounts=self.registry, scope_for=lambda acc: self.scope,
            market_views=self.views, calendar_health=lambda at: self.calendar,
            broker=lambda acc, at: self.broker, latest_quote=lambda feed, at: self.quote,
            spread_minutes=lambda feed, lo, hi, as_of: [
                r for r in self.minutes if lo <= r.t < hi and r.available_at <= as_of],
            commission=lambda acc, at: self.commission)
        self.engine = RiskEngine(RiskPolicy(version="r0", **TEST_POLICY), RiskLedger(),
                                 self.gates, clock=lambda: self.now)

    def evaluate(self, i=None):
        return self.engine.evaluate(i or intent(self.now - minutes(0.5)), ACC)


def spread_block(t: datetime, *, end: datetime | None = None, scope: str = FEED) -> Block:
    return Block(BlockKind.SPREAD, scope, "WIDE_SPREAD", t, end or t + minutes(10),
                 f"spread:{t.isoformat()}", t, "p0")


# ---------------------------------------------------------------- đường đi được duyệt

def test_approves_and_sizes_from_risk(t0):
    w = World(t0)
    d = w.evaluate()
    # 0,5 % (số test) của 10k = 50$; khoảng SL thực = 10 + spread 0,20 + đệm 0,30 = 10,5
    # → 1050 $/lot → 0,0476 → 0,04 lot (làm tròn xuống), rủi ro thật 42 $
    assert d.outcome is RiskOutcome.APPROVED, d.reason_codes
    assert d.volume == Decimal("0.04") and d.risk_amount == Decimal("42.00")
    assert w.engine.ledger.reserved_total() == Decimal("42.00")
    assert Decimal(d.details["risk_per_lot"]) == 1050 and d.account_id == ACC


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
    d = w.engine.evaluate(intent(t0), "khong-co")
    assert d.outcome is RiskOutcome.REJECTED and "ACCOUNT_UNKNOWN" in d.reason_codes


@pytest.mark.parametrize("gate", ["accounts", "mode", "price_feed", "market_view",
                                  "calendar_health", "broker", "quote", "spread_minutes",
                                  "commission"])
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
        name = {"quote": "latest_quote"}.get(gate, gate)
        object.__setattr__(w.gates, name, boom)
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
    assert d.volume == Decimal("0.04")


def test_concurrent_intents_never_exceed_total_limit(t0):
    w = World(t0)
    w.engine.policy = RiskPolicy(version="r0",
                                 **(TEST_POLICY | {"max_total_reserved": Decimal("0.01")}))
    intents = [intent(t0 - minutes(0.5), intent_id=f"i{n}", idempotency_key=f"k{n}")
               for n in range(10)]
    with ThreadPoolExecutor(max_workers=10) as pool:
        decisions = list(pool.map(w.evaluate, intents))
    approved = [d for d in decisions if d.outcome is not RiskOutcome.REJECTED]
    # 42 + 42 + (chỗ trống 16 $ → 0,01 lot = 10,5 $, REDUCED) = 94,5 ≤ 100; lệnh thứ tư thiếu chỗ
    assert len(approved) == 3
    assert sorted(d.volume for d in approved) == [Decimal("0.01"), Decimal("0.04"),
                                                  Decimal("0.04")]
    assert w.engine.ledger.reserved_total() == Decimal("94.50")
    assert all("BELOW_MIN_VOLUME" in d.reason_codes for d in decisions
               if d.outcome is RiskOutcome.REJECTED)


def test_decision_time_comes_from_risk_clock(t0):
    w = World(t0)
    d = w.evaluate()
    assert d.decided_at == t0 and d.expires_at == t0 + timedelta(seconds=30)


# ================================================================ RSK-11 (KN-02)
# ---------------------------------------------------------------- 2a thông số broker

def test_spec_missing_rejects(t0):
    w = World(t0)
    w.broker = reading(t0, spec=None)
    object.__setattr__(w.broker, "spec", None)
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED and "BROKER_SPEC_MISSING" in d.reason_codes


@pytest.mark.parametrize("field", ["stops_level", "freeze_level", "currency_profit",
                                   "account_currency"])
def test_spec_null_field_is_unknown_not_zero(t0, field):
    w = World(t0)
    w.broker = reading(t0, spec=spec_row(t0 - timedelta(days=1), **{field: None}))
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED
    assert f"BROKER_SPEC_MISSING:{field}" in d.reason_codes


@pytest.mark.parametrize("kw", [
    {"live_spec_hash": "khac"},                 # nhịp tim báo thông số mới, DB chưa ghi kịp
    {"identity": (999, SERVER)},                # Gateway đang đăng nhập MT5 khác
    {"heartbeat_symbol": "XAUUSD.r"},           # mã broker khác mã đã khóa
])
def test_spec_not_matching_live_heartbeat_is_stale(t0, kw):
    w = World(t0)
    w.broker = reading(t0, **kw)
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED and "BROKER_SPEC_STALE" in d.reason_codes


@pytest.mark.parametrize("kw,code", [
    ({"account_currency": "USC"}, "CURRENCY_UNSUPPORTED"),
    ({"currency_profit": "EUR"}, "CURRENCY_UNSUPPORTED"),
])
def test_non_usd_rejected(t0, kw, code):                                   # Q2
    w = World(t0)
    w.broker = reading(t0, spec=spec_row(t0 - timedelta(days=1), **kw))
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED and code in d.reason_codes


def test_heartbeat_account_currency_non_usd_rejected(t0):
    w = World(t0)
    w.broker = reading(t0, account_currency="EUR")
    assert "CURRENCY_UNSUPPORTED" in w.evaluate().reason_codes


def test_contract_size_from_broker_not_constant(t0):
    # 1 lot = 10 oz: R1 = 10,5 × 10 = 105 $/lot → 50 / 105 = 0,476 → 0,47 lot
    w = World(t0)
    w.broker = reading(t0, spec=spec_row(t0 - timedelta(days=1), contract_size=10.0))
    d = w.evaluate()
    assert d.outcome is RiskOutcome.APPROVED and d.volume == Decimal("0.47")
    assert d.risk_amount == Decimal("49.35")


def test_spec_changed_after_decision_time_not_used(t0):
    # Thông số đổi SAU lúc quyết (observed_at > now) → spec_at không trả → gate thật tự lọc;
    # ở đây: dòng đã biết là dòng cũ, nhịp tim khớp dòng cũ → dùng dòng cũ.
    w = World(t0)
    old = spec_row(t0 - timedelta(days=2))
    w.broker = reading(t0, spec=old)
    assert w.evaluate().outcome is RiskOutcome.APPROVED


# ---------------------------------------------------------------- 2b equity

@pytest.mark.parametrize("kw", [{"connected": False}, {"heartbeat_age_s": 31.0},
                                {"heartbeat_age_s": None}, {"equity": None},
                                {"heartbeat_age_s": -5.0}])
def test_equity_stale_or_missing_rejects(t0, kw):
    w = World(t0)
    w.broker = reading(t0, **kw)
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED and "EQUITY_STALE" in d.reason_codes


def test_disconnected_gateway_also_marks_spec_stale(t0):
    w = World(t0)
    w.broker = reading(t0, connected=False)
    assert "BROKER_SPEC_STALE" in w.evaluate().reason_codes


@pytest.mark.parametrize("eq", [0.0, -100.0])
def test_non_positive_equity_rejects(t0, eq):
    w = World(t0)
    w.broker = reading(t0, equity=eq)
    assert "NO_EQUITY" in w.evaluate().reason_codes


def test_equity_is_read_not_given(t0):
    # Equity thật nhỏ hơn → lot nhỏ hơn (bên gọi không có cách nào đưa equity)
    w = World(t0)
    w.broker = reading(t0, equity=20_000.0)
    assert w.evaluate().volume == Decimal("0.09")         # 100 / 1050 = 0,095 → 0,09


# ---------------------------------------------------------------- 2c chi phí (5-C16, 5-C01)

def test_costs_reduce_volume_exactly(t0):                                 # 5-C16
    # Không chi phí: 50 / (10 × 100) = 0,05 lot. Có spread 0,2 + đệm 0,3 + phí 7 $/lot:
    # R1 = 10,5 × 100 + 7 = 1057 → 50 / 1057 = 0,0473 → 0,04; rủi ro thật 42,28 ≤ 50
    w = World(t0)
    w.commission = Commission(ACC, Decimal("7"), "USD", t0 - timedelta(hours=1), "sub-u", "t")
    d = w.evaluate()
    assert d.volume == Decimal("0.04") and d.risk_amount == Decimal("42.28")
    assert Decimal(d.details["risk_per_lot"]) == Decimal("1057")
    assert d.risk_amount <= Decimal("50")


def test_commission_unknown_rejects(t0):                                  # Q3
    w = World(t0)
    w.commission = None
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED and "COMMISSION_UNKNOWN" in d.reason_codes


def test_below_min_volume_reports_shortfall(t0):                           # 5-C01
    # equity 1000 × 0,5 % = 5 $; 0,01 lot cần 10,5 $ → thiếu 5,5 $; vốn tối thiểu 2100 $
    w = World(t0)
    w.broker = reading(t0, equity=1000.0)
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED and d.reason_codes == ("BELOW_MIN_VOLUME",)
    assert Decimal(d.details["shortfall"]) == Decimal("5.5")
    assert Decimal(d.details["min_equity_for_min_lot"]) == Decimal("2100")
    assert w.engine.ledger.reserved_total() == 0


def test_far_stop_falls_into_below_min_volume(t0):                         # 5-C02 (quá xa)
    w = World(t0)
    d = w.evaluate(intent(t0 - minutes(0.5), stop_loss=1900.0))
    assert d.reason_codes == ("BELOW_MIN_VOLUME",)


def test_volume_capped_at_broker_max(t0):
    w = World(t0)
    w.broker = reading(t0, equity=10_000_000.0,
                       spec=spec_row(t0 - timedelta(days=1), volume_max=1.0))
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REDUCED and d.volume == Decimal("1.00")
    assert d.risk_amount == Decimal("1050.00")


# ---------------------------------------------------------------- 2c/2d nền spread 30 ngày

def test_slippage_buffer_is_p95_of_open_minutes(t0):
    w = World(t0)
    # 95 % phút p95 = 30, 5 % = 80 → p95 (hạng gần nhất) = 30; phút đóng cửa (p95 = 500) bị bỏ
    rows = minutes_rows(t0, n=7000, p95=30)
    for r in rows[:350]:
        object.__setattr__(r, "spread_p95", 80)
    rows += minutes_rows(t0 - timedelta(days=6), n=100, p95=500, closed=60)
    w.minutes = rows
    d = w.evaluate()
    assert d.details["spread_p95_30d_points"] == "30" and Decimal(d.details["slippage"]) == \
        Decimal("0.30")


def test_baseline_too_short_rejects(t0):
    w = World(t0)
    w.minutes = minutes_rows(t0, n=6899)
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED and "SPREAD_BASELINE_MISSING" in d.reason_codes


def test_closed_minutes_do_not_count_towards_baseline(t0):
    w = World(t0)
    w.minutes = minutes_rows(t0, n=7000, closed=3)
    assert "SPREAD_BASELINE_MISSING" in w.evaluate().reason_codes


def test_minutes_not_yet_known_are_ignored(t0):
    # Phút được ghi SAU lúc quyết (available_at > now) không được dùng (point-in-time)
    w = World(t0)
    late = [QuoteMinute(r.feed_id, r.t, *r.values(), available_at=t0 + timedelta(minutes=1),
                        computed_at=t0 + timedelta(minutes=1)) for r in minutes_rows(t0)]
    w.minutes = late
    assert "SPREAD_BASELINE_MISSING" in w.evaluate().reason_codes


def test_spread_above_own_p95_rejects(t0):                                 # Q5, 5-C10
    w = World(t0)
    w.quote = quote(t0, spread=31)                # p95 30 ngày = 30 point
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED and "SPREAD_TOO_WIDE" in d.reason_codes
    assert d.details["spread_points"] == "31" and d.details["spread_p95_30d_points"] == "30"
    w.quote = quote(t0, spread=30)
    assert w.evaluate().outcome is RiskOutcome.APPROVED


def test_spread_uses_max_within_second(t0):
    w = World(t0)
    q = quote(t0, spread=20)
    object.__setattr__(q, "spread_max_points", 45)
    w.quote = q
    assert "SPREAD_TOO_WIDE" in w.evaluate().reason_codes


@pytest.mark.parametrize("q", ["none", "old", "future"])
def test_quote_stale_rejects(t0, q):
    w = World(t0)
    w.quote = {"none": None, "old": quote(t0, age=timedelta(seconds=11)),
               "future": quote(t0, age=timedelta(seconds=-2))}[q]
    assert "QUOTE_STALE" in w.evaluate().reason_codes


def test_market_closed_quote_rejects(t0):
    w = World(t0)
    w.quote = quote(t0, flags=("CALENDAR_CLOSED",))
    assert "MARKET_CLOSED" in w.evaluate().reason_codes


# ---------------------------------------------------------------- 2e SL quá gần (RSK-08, 5-C02)

def test_sl_closer_than_stops_level_rejects(t0):
    w = World(t0)
    # stops 20 point × 0,01 = 0,20; SL cách 0,15 → quá gần
    d = w.evaluate(intent(t0 - minutes(0.5), stop_loss=2399.85))
    assert d.outcome is RiskOutcome.REJECTED and "SL_TOO_CLOSE" in d.reason_codes


def test_sl_closer_than_spread_rejects(t0):
    w = World(t0)
    w.broker = reading(t0, spec=spec_row(t0 - timedelta(days=1), stops_level=0, freeze_level=0))
    w.quote = quote(t0, spread=30)
    d = w.evaluate(intent(t0 - minutes(0.5), stop_loss=2399.75))   # 0,25 < spread 0,30
    assert "SL_TOO_CLOSE" in d.reason_codes


def test_freeze_level_counts(t0):
    w = World(t0)
    w.broker = reading(t0, spec=spec_row(t0 - timedelta(days=1), stops_level=0,
                                         freeze_level=50))
    d = w.evaluate(intent(t0 - minutes(0.5), stop_loss=2399.6))     # 0,40 < 0,50
    assert "SL_TOO_CLOSE" in d.reason_codes


def test_sl_exactly_at_stops_level_allowed(t0):
    w = World(t0)
    d = w.evaluate(intent(t0 - minutes(0.5), stop_loss=2399.8))     # đúng 0,20
    assert "SL_TOO_CLOSE" not in d.reason_codes


def test_sample_source_without_broker_rejected(t0):
    # Nguồn SAMPLE (feed rỗng) không có broker → không bao giờ tính được khối lượng
    w = World(t0)
    w.scope = Scope.of_feed("XAUUSD", "M15", "SAMPLE", "")
    assert "NO_PRICE_FEED" in w.evaluate().reason_codes
