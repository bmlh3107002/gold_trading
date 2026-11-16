"""Risk Engine — RSK-10 (KN-01): Risk tự đọc cổng thật lúc quyết. 5-C14, 5-C15, 4-C05, 4-C06.

Số rủi ro trong file này (``TEST_PROFILE``) là **số giả chỉ để test** — không phải số khuyến nghị;
số thật đến từ hồ sơ rủi ro người dùng chọn (GĐ5 bước 3, DEC-09).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from gold_trading.accounts.runtime import AccountRegistry
from gold_trading.analysts.framework import Scope
from gold_trading.common.enums import (
    RiskOutcome,
    SafetyState,
    Side,
    SourceStatus,
    TradingMode,
)
from gold_trading.ingestion.source_status import SourceHealth
from gold_trading.market.hours import REFERENCE
from gold_trading.market.quote_minutes import QuoteMinute
from gold_trading.market.quotes import QuoteSecond
from gold_trading.risk.blocks import ALL, Block, BlockKind, BlockStore
from gold_trading.risk.book import ClosedTrade, InMemoryTradeBook, OpenPosition
from gold_trading.risk.engine import RiskEngine, RiskPolicy
from gold_trading.risk.gates import BrokerReading, RiskGates, calendar_health_codes
from gold_trading.risk.ledger import RiskLedger
from gold_trading.storage.broker_history import SpecKey, SpecRow, spec_hash
from gold_trading.storage.commissions import Commission
from gold_trading.storage.market_views import InMemoryMarketViewStore
from gold_trading.storage.repository import InMemoryRepository, Member, TradingAccount
from gold_trading.storage.risk_profiles import InMemoryRiskProfileStore, RiskProfileValues
from tests.conftest import minutes
from tests.factories import intent, market_view

# CHỈ ĐỂ TEST — không phải số khuyến nghị (DEC-09: số do người dùng chọn ở bước 3)
# Hồ sơ rủi ro GIẢ — CHỈ ĐỂ TEST (0,5 %/lệnh, heat 2 %); hồ sơ thật do người dùng chọn (H1–H11).
TEST_PROFILE = RiskProfileValues(
    risk_per_trade=Decimal("0.005"), min_reward_risk=Decimal("1.5"),
    max_open_risk=Decimal("0.02"), max_daily_loss=Decimal("0.01"),
    max_weekly_loss=Decimal("0.02"), max_monthly_loss=Decimal("0.04"),
    max_consecutive_losses=5, day_reset_tz="America/New_York", day_reset_time="17:00",
    max_trades_per_day=4, max_drawdown_halt=Decimal("0.05"), news_hold_policy="CLOSE_ALL",
    weekend_policy="CLOSE_ALL", weekend_close_before_min=30,
    max_effective_leverage=Decimal(3), cash_flow_policy="SEPARATE",
    pyramiding_policy="NONE", notes="chỉ để test")
ACC = "acc-1"
FEED = "f1"
SCOPE = Scope.of_feed("XAUUSD", "M15", "MT5", FEED)
LOGIN, SERVER, SYM = 123, "Broker-Demo", "XAUUSD"
# Thông số broker GIẢ (chỉ để test): 1 lot = 100 oz, point 0,01, stops 20 / freeze 10 point.
SPEC = dict(digits=2, point=0.01, contract_size=100.0, volume_min=0.01, volume_max=50.0,
            volume_step=0.01, currency_profit="USD", stops_level=20, freeze_level=10,
            swap_mode=1, swap_long=0.0, swap_short=0.4, swap_rollover3days=3, leverage=100,
            account_currency="USD")


def spec_row(t: datetime, **kw) -> SpecRow:
    spec = SPEC | kw
    return SpecRow(SpecKey(ACC, LOGIN, SERVER, SYM), t, spec, spec_hash(spec), "0.10.3")


def reading(t: datetime, *, equity=10_000.0, spec: SpecRow | None = None, **kw) -> BrokerReading:
    row = spec if spec is not None else spec_row(t - timedelta(days=3))
    base = dict(connected=True, heartbeat_age_s=2.0, equity=equity, margin_free=equity,
                account_currency="USD",
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

    def __init__(self, t0: datetime, ledger=None) -> None:
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
        # Vốn đầu paper GIẢ (chỉ để test) = equity MT5 giả 10.000
        self.book = InMemoryTradeBook(capital=Decimal(10_000))
        # Mốc Safety về ACTIVE (đồng hồ test khác đồng hồ thật của SafetySupervisor)
        self.active_at: datetime | None = t0 - timedelta(days=60)
        self.registry.active_since = lambda acc: self.active_at  # type: ignore[method-assign]
        self.gates = RiskGates(
            accounts=self.registry, scope_for=lambda acc: self.scope,
            market_views=self.views, calendar_health=lambda at: self.calendar,
            broker=lambda acc, at: self.broker, latest_quote=lambda feed, at: self.quote,
            spread_minutes=lambda feed, lo, hi, as_of: [
                r for r in self.minutes if lo <= r.t < hi and r.available_at <= as_of],
            commission=lambda acc, at: self.commission,
            risk_profile=lambda acc, at: self.profiles.at(acc, at),
            trade_book=self.book, market_calendar=REFERENCE)
        self.profiles = InMemoryRiskProfileStore()
        self.profiles.append(ACC, TEST_PROFILE, created_by="sub-u", reason="test",
                             at=t0 - timedelta(days=1))
        self.engine = RiskEngine(RiskPolicy(version="r0"), ledger or RiskLedger(),
                                 self.gates, clock=lambda: self.now)

    def evaluate(self, i=None, *, keep_key: bool = False):
        """Mỗi lần gọi là một yêu cầu mới (khóa idempotency riêng) — trừ khi ``keep_key``; test
        idempotency (LED-05) ở ``test_paper_ledger.py``."""
        i = i or intent(self.now - minutes(0.5))
        if not keep_key and i.idempotency_key == "k1":
            self._n = getattr(self, "_n", 0) + 1
            i = i.model_copy(update={"idempotency_key": f"k1-{self._n}"})
        return self.engine.evaluate(i, ACC)


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


def test_policy_has_no_risk_numbers():
    # DEC-09 / KN-12: không có số rủi ro đặt sẵn trong code — chỉ trong hồ sơ người dùng
    names = set(RiskPolicy.__dataclass_fields__)
    assert not names & {"max_risk_per_trade", "max_total_reserved", "max_spread"}


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
    w.engine.policy = RiskPolicy(version="r1", blocking_quality_flags=pol)
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
    w.profiles.append(ACC, replace(TEST_PROFILE, max_open_risk=Decimal("0.01")),
                      created_by="sub-u", reason="test", at=t0 - timedelta(hours=1))
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
    assert w.evaluate().volume == Decimal("0.04")      # 6c: equity dùng = min(MT5, paper 10.000)
    w.book.capital = Decimal(20_000)
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
    # TP đủ xa để R:R đạt (lời 1500 USD/oz) → còn lại đúng một lý do: không đủ lot tối thiểu
    d = w.evaluate(intent(t0 - minutes(0.5), stop_loss=1900.0, take_profit=3900.0))
    assert d.reason_codes == ("BELOW_MIN_VOLUME",)


def test_volume_capped_at_broker_max(t0):
    w = World(t0)
    w.broker = reading(t0, equity=10_000_000.0,
                       spec=spec_row(t0 - timedelta(days=1), volume_max=1.0))
    w.book.capital = Decimal(10_000_000)
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


# ================================================================ bước 3 — hồ sơ rủi ro (RPF-01)

def test_no_risk_profile_rejects(t0):
    w = World(t0)
    w.profiles = InMemoryRiskProfileStore()
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED and "NO_RISK_PROFILE" in d.reason_codes
    assert w.engine.ledger.reserved_total() == 0


def test_profile_created_after_decision_time_not_used(t0):
    w = World(t0)
    w.profiles = InMemoryRiskProfileStore()
    w.profiles.append(ACC, TEST_PROFILE, created_by="sub-u", reason="t",
                      at=t0 + timedelta(seconds=1))
    assert "NO_RISK_PROFILE" in w.evaluate().reason_codes


def test_user_v1_profile_sizes_at_quarter_percent(t0):
    # Hồ sơ v1 người dùng chốt 16/11 (H1 = 0,25 %): 10.000 × 0,25 % = 25 $ → 25 / 1050 → 0,02 lot
    w = World(t0)
    w.profiles.append(ACC, replace(TEST_PROFILE, risk_per_trade=Decimal("0.0025"),
                                   max_open_risk=Decimal("0.005")),
                      created_by="sub-u", reason="H1–H11", at=t0 - timedelta(minutes=1))
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REDUCED          # intent xin 0,5 % → cắt về 0,25 %
    assert d.volume == Decimal("0.02") and d.risk_amount == Decimal("21.00")
    assert d.risk_profile_version == 2 and d.details["risk_profile_version"] == "2"


def test_heat_from_profile_limits_second_trade(t0):
    # heat 0,5 % = 50 $; mỗi lệnh 0,25 % → 21 $; lệnh 3: chỗ trống 8 $ < 10,5 $ → từ chối
    w = World(t0)
    w.profiles.append(ACC, replace(TEST_PROFILE, risk_per_trade=Decimal("0.0025"),
                                   max_open_risk=Decimal("0.005")),
                      created_by="sub-u", reason="t", at=t0 - timedelta(minutes=1))
    out = [w.evaluate(intent(t0 - minutes(0.5), intent_id=f"i{k}", idempotency_key=f"k{k}"))
           for k in range(3)]
    assert [d.outcome for d in out[:2]] == [RiskOutcome.REDUCED] * 2
    assert out[2].reason_codes == ("BELOW_MIN_VOLUME",)
    assert w.engine.ledger.reserved_total() == Decimal("42.00")


def test_profile_changed_between_check_and_lock_is_reread(t0):          # 5-C13
    w = World(t0)
    calls = {"n": 0}
    newer = replace(TEST_PROFILE, risk_per_trade=Decimal("0.0025"))
    base = w.profiles.at

    def profile(acc, at):
        calls["n"] += 1
        if calls["n"] == 2:     # lần đọc dưới khóa: người dùng vừa lưu bản mới
            w.profiles.append(ACC, newer, created_by="sub-u", reason="đổi", at=t0)
        return base(acc, at)

    object.__setattr__(w.gates, "risk_profile", profile)
    d = w.evaluate()
    assert d.details["profile_reread"] == "1->2" and d.risk_profile_version == 2
    assert d.volume == Decimal("0.02")              # tính theo bản mới 0,25 %


def test_profile_read_error_under_lock_rejects(t0):
    w = World(t0)
    calls = {"n": 0}
    base = w.profiles.at

    def profile(acc, at):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("db down")
        return base(acc, at)

    object.__setattr__(w.gates, "risk_profile", profile)
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED
    assert "GATE_READ_ERROR:risk_profile" in d.reason_codes
    assert w.engine.ledger.reserved_total() == 0


# ================================================================ bước 4b — R:R sau chi phí (H2)

@pytest.mark.parametrize("tp,ok", [
    (2420.0, True),      # (20 − 0,2) × 100 = 1980 / 1050 = 1,886
    (2415.95, True),     # (15,95 − 0,2) × 100 = 1575 / 1050 = 1,5 đúng ngưỡng → được
    (2415.94, False),    # 1574 / 1050 = 1,499
    (2410.5, False),
])
def test_min_reward_risk_after_costs(t0, tp, ok):
    w = World(t0)
    d = w.evaluate(intent(t0 - minutes(0.5), take_profit=tp))
    if ok:
        assert d.outcome is not RiskOutcome.REJECTED, d.reason_codes
    else:
        assert d.reason_codes == ("REWARD_RISK_TOO_LOW",)
        assert w.engine.ledger.reserved_total() == 0


def test_commission_reduces_reward_and_raises_risk(t0):
    # Có phí 7 $/lot: lời = 1980 − 7 = 1973; R1 = 1057 → 1,866 (vẫn đạt); TP 2416: (15,8 × 100 − 7)
    # = 1573 / 1057 = 1,488 → không đạt (không phí thì 1580 / 1050 = 1,505 đạt)
    w = World(t0)
    w.commission = Commission(ACC, Decimal("7"), "USD", t0 - timedelta(hours=1), "sub-u", "t")
    assert w.evaluate(intent(t0 - minutes(0.5), take_profit=2420.0)).outcome \
        is not RiskOutcome.REJECTED
    d = w.evaluate(intent(t0 - minutes(0.5), take_profit=2416.0))
    assert d.reason_codes == ("REWARD_RISK_TOO_LOW",)
    assert d.details["reward_risk"] == "1.4882"


def test_sell_reward_risk(t0):
    w = World(t0)
    i = intent(t0 - minutes(0.5), side="SELL", entry_reference=2400.0, stop_loss=2410.0,
               take_profit=2384.0)       # (16 − 0,2) × 100 = 1580 / 1050 = 1,505
    assert w.evaluate(i).outcome is not RiskOutcome.REJECTED
    i2 = i.model_copy(update={"take_profit": 2384.5})
    assert w.evaluate(i2).reason_codes == ("REWARD_RISK_TOO_LOW",)


def test_no_take_profit_rejected(t0):
    w = World(t0)
    d = w.evaluate(intent(t0 - minutes(0.5), take_profit=None))
    assert d.outcome is RiskOutcome.REJECTED and "NO_TAKE_PROFIT" in d.reason_codes


def test_min_reward_risk_from_profile(t0):
    w = World(t0)
    w.profiles.append(ACC, replace(TEST_PROFILE, min_reward_risk=Decimal(2)), created_by="sub-u",
                      reason="t", at=t0 - timedelta(minutes=1))
    d = w.evaluate()                        # 1,886 < 2
    assert d.reason_codes == ("REWARD_RISK_TOO_LOW",) and d.details["min_reward_risk"] == "2"


# ================================================================ bước 4c — sổ lệnh (RSK-04/05)
# T0 = thứ Hai 05/01/2026 14:00 UTC. Ngày + tuần giao dịch bắt đầu CN 04/01 22:00 UTC (17:00 NY);
# tháng bắt đầu 31/12/2025 22:00 UTC. Hồ sơ TEST: lỗ ngày 1 % / tuần 2 % / tháng 4 %, chuỗi 5,
# 4 lệnh / ngày, heat 2 %, nhồi lệnh NONE. Equity 10.000; giá bid 2400,00 / ask 2400,20.

def closed(k, pnl, at, opened=None, side="BUY"):
    return ClosedTrade(f"c{k}", Side(side), opened or at - timedelta(minutes=30), at,
                       Decimal(str(pnl)))


def pos(k, side, entry, sl, vol="0.10", opened=None, comm="0"):
    return OpenPosition(f"p{k}", Side(side), Decimal(vol), Decimal(str(entry)), Decimal(str(sl)),
                        opened, Decimal(comm))


def test_no_trade_book_rejects(t0):
    w = World(t0)
    object.__setattr__(w.gates, "trade_book", None)
    assert "TRADE_BOOK_UNAVAILABLE" in w.evaluate().reason_codes


def test_trade_book_read_error_rejects(t0):
    w = World(t0)

    def boom(*a, **k):
        raise RuntimeError("db down")

    w.book.open_positions = boom  # type: ignore[method-assign]
    d = w.evaluate()
    assert d.outcome is RiskOutcome.REJECTED and "GATE_READ_ERROR:trade_book" in d.reason_codes
    assert w.engine.ledger.reserved_total() == 0


@pytest.mark.parametrize("pnl,blocked", [("-100", True), ("-99.99", False)])
def test_daily_loss_limit_pauses(t0, pnl, blocked):                       # 5-C05
    w = World(t0)
    w.book.capital = 10_000 - Decimal(pnl)        # equity paper sau lỗ = 10.000 (= MT5)
    w.book.add_closed(ACC, closed(1, pnl, t0 - timedelta(hours=1)))
    d = w.evaluate()
    if blocked:
        assert d.reason_codes == ("DAILY_LOSS_LIMIT",) and d.details["daily_loss"] == "0.010000"
        assert d.details["safety_paused"] == "DAILY_LOSS_LIMIT"
        assert w.registry.get(ACC).safety.state is SafetyState.PAUSED
        assert "SAFETY_PAUSED" in w.evaluate().reason_codes     # lần sau: Safety đã chặn
    else:
        assert d.outcome is not RiskOutcome.REJECTED
        assert w.registry.get(ACC).safety.state is SafetyState.ACTIVE


def test_loss_before_day_start_not_daily_but_monthly(t0):
    w = World(t0)
    w.book.add_closed(ACC, closed(1, "-350", t0 - timedelta(days=3)))   # thứ Sáu 02/01
    d = w.evaluate()
    assert d.outcome is not RiskOutcome.REJECTED                        # tháng 3,5 % < 4 %
    assert d.details["daily_loss"] == "0.000000" and d.details["weekly_loss"] == "0.000000"
    w.book.add_closed(ACC, closed(2, "-50", t0 - timedelta(days=3)))
    assert w.evaluate().reason_codes == ("MONTHLY_LOSS_LIMIT",)


def test_last_month_loss_not_counted(t0):
    w = World(t0)
    w.book.capital = Decimal(11_000)              # sụt 1.000 / 11.000 = 9 % → H6 riêng (test 6c)
    w.profiles.append(ACC, replace(TEST_PROFILE, max_drawdown_halt=Decimal("0.5")),
                      created_by="sub-u", reason="t", at=t0 - timedelta(minutes=1))
    w.book.add_closed(ACC, closed(1, "-1000", t0 - timedelta(days=6)))  # 30/12/2025
    assert w.evaluate().outcome is not RiskOutcome.REJECTED


def test_weekly_loss_limit(t0):
    w = World(t0 + timedelta(days=2))                    # thứ Tư 07/01
    w.book.add_closed(ACC, closed(1, "-200", t0 + timedelta(hours=1)))  # thứ Hai, tuần này
    d = w.evaluate()
    assert d.reason_codes == ("WEEKLY_LOSS_LIMIT",) and d.details["daily_loss"] == "0.000000"


def test_unrealized_loss_counts(t0):
    # SELL 0,1 lot vào 2390, ask 2400,20 → đang lỗ 10,2 × 100 × 0,1 = 102 $ ≥ 1 % → chạm lỗ ngày
    w = World(t0)
    w.book.add_open(ACC, pos(1, "SELL", 2390, 2420, opened=t0 - timedelta(hours=2)))
    d = w.evaluate()
    assert "DAILY_LOSS_LIMIT" in d.reason_codes and d.details["unrealized_pnl"] == "-102.0000"


def test_loss_streak_pauses_and_restarts_after_resume(t0):              # 5-C06
    w = World(t0)
    for k in range(5):      # hôm qua (không tính vào lệnh / ngày), sau lần mở lại gần nhất
        w.book.add_closed(ACC, closed(k, "-1", t0 - timedelta(days=1, minutes=50 - k)))
    d = w.evaluate()
    assert d.reason_codes == ("LOSS_STREAK_LIMIT",) and d.details["loss_streak"] == "5"
    assert w.registry.get(ACC).safety.state is SafetyState.PAUSED
    # Người dùng xem rồi mở lại → chuỗi đếm lại từ lúc mở
    w.registry.get(ACC).safety.resume("XEM_XONG", trigger_source="t", actor="sub-u")
    w.active_at = t0 - timedelta(minutes=1)
    d = w.evaluate()
    assert d.outcome is not RiskOutcome.REJECTED and d.details["loss_streak"] == "0"


def test_win_breaks_streak_but_breakeven_does_not(t0):
    w = World(t0)
    pnls = ["-1", "-1", "5", "-1", "0", "-1", "-1", "-1"]       # cũ → mới (hôm qua)
    for k, p in enumerate(pnls):
        w.book.add_closed(ACC, closed(k, p, t0 - timedelta(days=1, minutes=50 - k)))
    d = w.evaluate()
    assert d.details["loss_streak"] == "4" and d.outcome is not RiskOutcome.REJECTED
    w.book.add_closed(ACC, closed(99, "-1", t0 - timedelta(days=1)))
    assert w.evaluate().reason_codes == ("LOSS_STREAK_LIMIT",)


def test_daily_trade_limit_no_pause(t0):                                  # H5
    w = World(t0)
    for k in range(4):
        w.book.add_closed(ACC, closed(k, "1", t0 - timedelta(minutes=40 - k)))
    w.book.add_closed(ACC, closed(9, "1", t0 - timedelta(days=1, minutes=1)))  # hôm qua
    d = w.evaluate()
    assert d.reason_codes == ("DAILY_TRADE_LIMIT",) and d.details["trades_today"] == "4"
    assert w.registry.get(ACC).safety.state is SafetyState.ACTIVE


def test_reservations_count_as_trades_today(t0):
    w = World(t0)
    for k in range(3):
        w.book.add_closed(ACC, closed(k, "1", t0 - timedelta(minutes=40 - k)))
    assert w.evaluate().outcome is not RiskOutcome.REJECTED          # lệnh thứ 4 (giữ chỗ)
    assert w.evaluate(intent(t0 - minutes(0.5), intent_id="i2", idempotency_key="k2")) \
        .reason_codes == ("DAILY_TRADE_LIMIT",)


def test_heat_includes_open_positions(t0):
    # SELL 1 lot, SL cách 15 → còn rủi ro (15 + đệm 0,3) × 100 = 1530 $ > heat 200 $ → hết chỗ
    w = World(t0)
    w.book.add_open(ACC, pos(1, "SELL", 2400, 2415, vol="1", opened=t0 - timedelta(minutes=5)))
    d = w.evaluate()
    assert d.reason_codes == ("BELOW_MIN_VOLUME",) and d.details["open_risk"] == "1530.000"


def test_position_with_sl_past_breakeven_has_no_heat(t0):
    w = World(t0)
    w.book.add_open(ACC, pos(1, "SELL", 2401, 2400, vol="0.05", opened=t0 - timedelta(minutes=5)))
    d = w.evaluate()
    assert d.outcome is RiskOutcome.APPROVED and Decimal(d.details["open_risk"]) == 0


@pytest.mark.parametrize("policy,entry,sl,blocked", [
    ("NONE", 2390, 2395, True),                       # có lệnh cùng chiều → chặn
    ("ONLY_IF_ALL_IN_PROFIT", 2390, 2380, False),     # lời 10 × 100 × 0,1 = 100 $
    ("ONLY_IF_ALL_IN_PROFIT", 2400, 2380, True),      # hòa (bid 2400) → chặn
    ("ONLY_IF_ALL_IN_PROFIT", 2405, 2380, True),      # đang lỗ → chặn (bình quân giá lỗ)
    ("ONLY_IF_ALL_SAFE", 2390, 2385, True),           # đang lời nhưng SL chưa qua hòa vốn
    ("ONLY_IF_ALL_SAFE", 2390, 2391, False),          # SL trên giá vào + đệm 0,3 → an toàn
])
def test_pyramiding_policies(t0, policy, entry, sl, blocked):            # H11
    w = World(t0)
    w.profiles.append(ACC, replace(TEST_PROFILE, pyramiding_policy=policy), created_by="sub-u",
                      reason="t", at=t0 - timedelta(minutes=1))
    w.book.add_open(ACC, pos(1, "BUY", entry, sl, opened=t0 - timedelta(minutes=5)))
    d = w.evaluate()
    assert ("NO_AVERAGING_DOWN" in d.reason_codes) is blocked, d.reason_codes


def test_opposite_side_position_is_not_pyramiding(t0):
    w = World(t0)
    w.book.add_open(ACC, pos(1, "SELL", 2390, 2391, vol="0.01", opened=t0 - timedelta(minutes=5)))
    assert "NO_AVERAGING_DOWN" not in w.evaluate().reason_codes


def test_commission_makes_small_profit_a_loss(t0):
    # Lời 0,10 × 100 × 0,1 = 1 $ nhưng phí 20 $/lot × 0,1 = 2 $ → ròng −1 $ → coi là lỗ
    w = World(t0)
    w.profiles.append(ACC, replace(TEST_PROFILE, pyramiding_policy="ONLY_IF_ALL_IN_PROFIT"),
                      created_by="sub-u", reason="t", at=t0 - timedelta(minutes=1))
    w.book.add_open(ACC, pos(1, "BUY", "2399.90", 2380, opened=t0 - timedelta(minutes=5),
                             comm="20"))
    assert "NO_AVERAGING_DOWN" in w.evaluate().reason_codes


def test_pause_request_failure_still_rejects(t0):
    w = World(t0)

    def boom(*a, **k):
        raise RuntimeError("db down")

    w.registry.request_pause = boom  # type: ignore[method-assign]
    w.book.add_closed(ACC, closed(1, "-150", t0 - timedelta(hours=1)))
    d = w.evaluate()
    assert d.reason_codes == ("DAILY_LOSS_LIMIT",)
    assert d.details["safety_pause_error"] == "DAILY_LOSS_LIMIT"


def test_future_trades_not_seen(t0):
    w = World(t0)
    w.book.add_closed(ACC, closed(1, "-500", t0 + timedelta(minutes=5)))   # đóng SAU lúc quyết
    assert w.evaluate().outcome is not RiskOutcome.REJECTED



def test_reduced_says_which_limit(t0):                                    # RSK-06
    w = World(t0)
    d = w.evaluate(intent(t0 - minutes(0.5), risk_budget_requested=0.02))
    assert d.reason_codes == ("REDUCED_BY_RISK_PER_TRADE",)
    # Lệnh SELL 0,1 lot SL cách 16,7 → còn rủi ro (16,7 + 0,3) × 100 × 0,1 = 170 $; heat 200 $ →
    # chỗ trống 30 $ < 50 $ → cắt theo heat: 30 / 1050 → 0,02 lot (21 $). Đòn bẩy: đang mở
    # 24.002 $, trần 30.000 $ → tối đa 0,02 lot nữa → không cắt thêm.
    w2 = World(t0)
    w2.book.capital = Decimal(10_102)             # lỗ đang chạy 102 → equity paper 10.000
    w2.book.add_open(ACC, pos(1, "SELL", 2400, "2416.7", vol="0.1",
                              opened=t0 - timedelta(minutes=5)))
    d2 = w2.evaluate()
    assert d2.reason_codes == ("REDUCED_BY_OPEN_RISK",) and d2.volume == Decimal("0.02")
    assert Decimal(d2.details["risk_money_allowed"]) == 30



# ================================================================ bước 5a — đòn bẩy + ký quỹ

def test_effective_leverage_cap_reduces(t0):                             # H9
    # Equity 100.000 $, rủi ro 0,5 % = 500 $ → 500 / 1050 = 0,47 lot (giá trị 112.809 $).
    # Trần 3 lần = 300.000 $; đang mở BUY 1 lot (bid 2400 → 240.000 $) → còn 60.000 $ →
    # 60.000 / (100 × 2400,20) = 0,2499 → 0,24 lot
    w = World(t0)
    w.broker = reading(t0, equity=100_000.0)
    w.book.capital = Decimal(100_000)
    w.profiles.append(ACC, replace(TEST_PROFILE, pyramiding_policy="ONLY_IF_ALL_IN_PROFIT"),
                      created_by="sub-u", reason="t", at=t0 - timedelta(minutes=1))
    w.book.add_open(ACC, pos(1, "BUY", 2390, "2399.8", vol="1", opened=t0 - timedelta(minutes=5)))
    d = w.evaluate()
    assert d.reason_codes == ("REDUCED_BY_LEVERAGE",) and d.volume == Decimal("0.24")
    assert d.details["max_volume_leverage"] == "0.24"
    assert d.risk_amount == Decimal("0.24") * 1050


def test_effective_leverage_full_rejects(t0):
    w = World(t0)
    w.broker = reading(t0, equity=100_000.0)
    w.profiles.append(ACC, replace(TEST_PROFILE, pyramiding_policy="ONLY_IF_ALL_IN_PROFIT"),
                      created_by="sub-u", reason="t", at=t0 - timedelta(minutes=1))
    w.book.add_open(ACC, pos(1, "BUY", 2390, "2399.8", vol="1.25",
                             opened=t0 - timedelta(minutes=5)))   # 300.000 $ = đủ trần
    assert w.evaluate().reason_codes == ("LEVERAGE_LIMIT",)


def test_margin_reduces_then_rejects(t0):                                  # 5-C09
    # Ký quỹ / lot = 100 × 2400,20 / 100 = 2400,20 $; margin trống 100 $ → 0,04 lot (96 $) đủ
    w = World(t0)
    w.broker = reading(t0, margin_free=100.0)
    d = w.evaluate()
    assert d.outcome is RiskOutcome.APPROVED and d.volume == Decimal("0.04")
    w.broker = reading(t0, margin_free=50.0)                  # → 0,02 lot
    d = w.evaluate(intent(t0 - minutes(0.5), intent_id="i2", idempotency_key="k2"))
    assert d.reason_codes == ("REDUCED_BY_MARGIN",) and d.volume == Decimal("0.02")
    w.broker = reading(t0, margin_free=20.0)
    d = w.evaluate(intent(t0 - minutes(0.5), intent_id="i3", idempotency_key="k3"))
    assert d.reason_codes == ("INSUFFICIENT_MARGIN",)


def test_paper_positions_use_margin(t0):
    # Lệnh paper đang mở SELL 0,03 lot (ask 2400,20 → 7.200,6 $ / 100 = 72,006 $ ký quỹ) mà MT5
    # không biết → margin trống 100 $ chỉ còn 27,99 $ → 0,01 lot
    w = World(t0)
    w.broker = reading(t0, margin_free=100.0)
    w.book.add_open(ACC, pos(1, "SELL", 2401, 2400, vol="0.03", opened=t0 - timedelta(minutes=5)))
    d = w.evaluate()
    assert d.reason_codes == ("REDUCED_BY_MARGIN",) and d.volume == Decimal("0.01")


def test_margin_unknown_rejects(t0):
    w = World(t0)
    w.broker = reading(t0, margin_free=None)
    assert "MARGIN_UNKNOWN" in w.evaluate().reason_codes


def test_leverage_null_rejects(t0):
    w = World(t0)
    w.broker = reading(t0, spec=spec_row(t0 - timedelta(days=1), leverage=None))
    assert "BROKER_SPEC_MISSING:leverage" in w.evaluate().reason_codes


def test_broker_leverage_change_used_at_decision(t0):
    # Sàn hạ đòn bẩy 1:100 → 1:10: ký quỹ / lot 24.002 $ > margin trống 10.000 → 0,41 lot đủ
    # cho 0,04; hạ còn 1:1 → 240.020 $ / lot → 0,04 lot cần 9.600,8 $ ≤ 10.000 → vẫn được;
    # margin trống 5.000 → 0,02 lot
    w = World(t0)
    w.broker = reading(t0, margin_free=5000.0,
                       spec=spec_row(t0 - timedelta(hours=1), leverage=1))
    d = w.evaluate()
    assert d.reason_codes == ("REDUCED_BY_MARGIN",) and d.volume == Decimal("0.02")



# ================================================================ bước 5b — swap (RSK-09, 5-C08)

@pytest.mark.parametrize("mode,long_,days,expected_r1,expected_swap", [
    # T0 thứ Hai → chốt ngày kế tiếp là thứ Hai 17:00 NY (MT5 = 1) → một đêm
    (1, -15.0, 3, "1065", "15"),          # 15 point × 0,01 × 100 oz = 15 $/lot
    (4, -15.0, 3, "1065", "15"),          # 15 $/lot theo tiền gửi
    (1, -15.0, 1, "1095", "45"),          # đêm thứ Hai là đêm ×3 → 45 $
    (1, 20.0, 1, "1050", "0"),            # swap dương: không tính là lời
    (0, -15.0, 1, "1050", "0"),           # sàn không tính swap
])
def test_swap_added_to_risk(t0, mode, long_, days, expected_r1, expected_swap):
    w = World(t0)
    w.broker = reading(t0, spec=spec_row(t0 - timedelta(days=1), swap_mode=mode,
                                         swap_long=long_, swap_rollover3days=days))
    d = w.evaluate()
    assert Decimal(d.details["risk_per_lot"]) == Decimal(expected_r1)
    assert Decimal(d.details["swap_per_lot"]) == Decimal(expected_swap)


def test_swap_reduces_reward_too(t0):
    # TP 2416: lời (15,8 × 100) − 15 = 1565; R1 = 1065 → 1,469 < 1,5 (không swap: 1,505 đạt)
    w = World(t0)
    w.broker = reading(t0, spec=spec_row(t0 - timedelta(days=1), swap_long=-15.0))
    d = w.evaluate(intent(t0 - minutes(0.5), take_profit=2416.0))
    assert d.reason_codes == ("REWARD_RISK_TOO_LOW",) and d.details["reward_risk"] == "1.4695"


def test_wednesday_triple_swap(t0):
    w = World(t0 + timedelta(days=2))          # thứ Tư 07/01 14:00 UTC → chốt thứ Tư 17:00 NY
    w.broker = reading(w.now, spec=spec_row(w.now - timedelta(days=1), swap_long=-15.0))
    d = w.evaluate()
    assert d.details["swap_nights"] == "3" and Decimal(d.details["swap_per_lot"]) == 45


def test_sell_uses_swap_short(t0):
    w = World(t0)
    w.broker = reading(t0, spec=spec_row(t0 - timedelta(days=1), swap_short=-10.0))
    i = intent(t0 - minutes(0.5), side="SELL", entry_reference=2400.0, stop_loss=2410.0,
               take_profit=2380.0)
    d = w.evaluate(i)
    assert Decimal(d.details["swap_per_lot"]) == 10


@pytest.mark.parametrize("mode", [2, 3, 5, 7])
def test_unknown_swap_mode_rejects(t0, mode):
    w = World(t0)
    w.broker = reading(t0, spec=spec_row(t0 - timedelta(days=1), swap_mode=mode))
    assert "SWAP_MODE_UNSUPPORTED" in w.evaluate().reason_codes


@pytest.mark.parametrize("field", ["swap_mode", "swap_long", "swap_short", "swap_rollover3days"])
def test_swap_field_null_rejects(t0, field):
    w = World(t0)
    w.broker = reading(t0, spec=spec_row(t0 - timedelta(days=1), **{field: None}))
    assert f"BROKER_SPEC_MISSING:{field}" in w.evaluate().reason_codes



# ================================================================ bước 5c — cuối tuần / lễ (H8)

def _at(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


@pytest.mark.parametrize("now,blocked", [
    (_at(2026, 1, 9, 21, 29), False),   # thứ Sáu 16:29 NY: còn 31 phút
    (_at(2026, 1, 9, 21, 30), True),    # 16:30 NY: đúng 30 phút trước đóng cửa tuần
    (_at(2026, 1, 9, 21, 59), True),
    (_at(2026, 1, 8, 21, 45), False),   # thứ Năm 16:45 NY: chỉ là nghỉ hằng ngày → không chặn
    (_at(2026, 7, 10, 20, 35), True),   # mùa hè (EDT): thứ Sáu 16:35 NY = 20:35 UTC
    (_at(2026, 7, 10, 20, 29), False),
])
def test_weekend_close_window(now, blocked):                             # 5-C07
    w = World(now)
    d = w.evaluate()
    assert ("WEEKEND_CLOSE_WINDOW" in d.reason_codes) is blocked, d.reason_codes


def test_holiday_early_close_blocks():
    # Lễ MLK 19/01/2026 (đóng sớm): 30 phút trước giờ đóng → chặn
    w = World(_at(2026, 1, 19, 12, 0))
    ok = w.evaluate()
    assert "WEEKEND_CLOSE_WINDOW" not in ok.reason_codes
    for k in range(0, 600, 5):                  # tìm phút đầu tiên bị chặn trong ngày
        w = World(_at(2026, 1, 19, 12, 0) + timedelta(minutes=k))
        if "WEEKEND_CLOSE_WINDOW" in w.evaluate().reason_codes:
            break
    else:
        raise AssertionError("ngày lễ đóng sớm không bị chặn")
    t = _at(2026, 1, 19, 12, 0) + timedelta(minutes=k)
    assert REFERENCE.session_at(t + timedelta(minutes=30)).value in ("HOLIDAY", "WEEKEND")


def test_calendar_missing_or_not_covering_rejects(t0):
    w = World(t0)
    object.__setattr__(w.gates, "market_calendar", None)
    assert "MARKET_CALENDAR_UNKNOWN" in w.evaluate().reason_codes
    w2 = World(_at(2028, 3, 1, 14, 0))            # bảng ngày lễ chỉ phủ 2024–2027
    assert "MARKET_CALENDAR_UNKNOWN" in w2.evaluate().reason_codes


def test_weekend_window_from_profile(t0):
    w = World(_at(2026, 1, 9, 20, 30))             # 15:30 NY thứ Sáu: còn 90 phút
    assert "WEEKEND_CLOSE_WINDOW" not in w.evaluate().reason_codes
    w.profiles.append(ACC, replace(TEST_PROFILE, weekend_close_before_min=120),
                      created_by="sub-u", reason="t", at=w.now - timedelta(minutes=1))
    assert "WEEKEND_CLOSE_WINDOW" in w.evaluate().reason_codes
