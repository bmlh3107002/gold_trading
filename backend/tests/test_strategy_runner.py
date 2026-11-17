"""Nối chiến lược v1 → Risk → sổ cái paper (GĐ5 bước 7 — STR-05). Thiết kế 36 mục 9.

Số hồ sơ / broker GIẢ chỉ để test (``test_risk_engine``: rủi ro 0,5 %, equity 10.000, spread 0,20,
đệm 0,30, phí 0). Tính tay: bid 2.400 / ask 2.400,20, ATR 6, EMA20 2.398 → SL 2.391, TP 2.418;
R1 = (9 + 0,20 + 0,30) × 100 = 950 → 50 / 950 = 0,0526 → 0,05 lot, rủi ro 47,50; khớp 2.400,50.
"""

from __future__ import annotations

import ast
import pathlib
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gold_trading.common.enums import RiskOutcome, TradingMode
from gold_trading.market.hours import REFERENCE
from gold_trading.risk.paper import PaperMonitor
from gold_trading.storage.repository import SqlRepository
from gold_trading.strategy.runner import (
    Evaluation,
    InMemoryEvaluationStore,
    SqlEvaluationStore,
    StrategyRunner,
)
from gold_trading.strategy.trend_m15 import STRATEGY_REF, Manager
from tests.test_paper_fill import Paper, q
from tests.test_paper_ledger import KINDS, PG_URL
from tests.test_risk_engine import ACC, FEED, SCOPE

D = Decimal
TECH = {"atr14": 6.0, "ema20": 2398.0, "close": 2400.0}


def build(t0, store=None, paper=None, accounts=None):
    p = paper or Paper(t0)
    w = p.w
    mon = PaperMonitor(p.broker, feed_for=lambda a: FEED,
                       risk_profile=lambda a, t: w.profiles.at(a, t),
                       entry_blocks=lambda a, t: w.blocks.active(t, FEED),
                       market_calendar=REFERENCE, managers=(Manager(),))
    r = StrategyRunner(
        accounts=accounts or (lambda: [ACC]), mode=w.registry.mode, feed_for=lambda a: FEED,
        view_for=lambda a, t: w.views.current(SCOPE, t), technical_for=lambda v: TECH,
        point_for=lambda a, t: D("0.01"), risk_profile=w.profiles.at, engine=w.engine,
        broker=p.broker, monitor=mon, store=store or InMemoryEvaluationStore(),
        clock=lambda: w.now)
    return p, r


def test_full_flow_hand_computed(t0):
    p, r = build(t0)
    assert r.tick()[ACC] == "intent:APPROVED"
    ev = r.store.recent(ACC)[0]
    assert (ev.outcome, ev.risk_outcome, ev.fill_code) == ("INTENT", "APPROVED", "FILLED")
    assert ev.market_view_id == "mv1" and ev.strategy_ref == STRATEGY_REF
    pos = p.led.open_positions(ACC, p.w.now)
    assert len(pos) == 1 and pos[0].volume == D("0.05") and pos[0].stop_loss == D("2391.00")
    opened = p.led.open_position_events(ACC)[0]
    assert opened.data["strategy_id"] == STRATEGY_REF
    assert D(opened.data["take_profit"]) == D("2418") and D(opened.data["entry_price"]) == D(
        "2400.50")
    assert D(opened.data["risk_at_fill"]) == D("47.5")         # = rủi ro Risk đã duyệt
    # nhịp sau, cùng MarketView → không xét lại, không lệnh mới
    assert r.tick()[ACC] == "skip:seen"
    assert len(r.store.recent(ACC)) == 1 and len(p.led.open_positions(ACC, p.w.now)) == 1


def test_skip_is_recorded_with_reasons(t0):
    p, r = build(t0)
    r.technical_for = lambda v: {"atr14": 6.0, "ema20": 2380.0}     # cách 3,3 ATR → đuổi giá
    assert r.tick()[ACC] == "skipped:PRICE_EXTENDED"
    ev = r.store.recent(ACC)[0]
    assert ev.outcome == "SKIPPED" and ev.reasons == ("PRICE_EXTENDED",)
    assert [e.type.value for e in p.led.events(ACC)] == ["START"]   # không giữ chỗ nào


def test_risk_rejection_recorded_no_position(t0):
    p, r = build(t0)
    p.w.commission = None
    assert r.tick()[ACC] == "intent:REJECTED"
    ev = r.store.recent(ACC)[0]
    assert ev.risk_outcome == "REJECTED" and "COMMISSION_UNKNOWN" in ev.reasons
    assert ev.fill_code is None and p.led.open_positions(ACC, p.w.now) == []


@pytest.mark.parametrize("mode", [TradingMode.SHADOW, TradingMode.LIVE])
def test_only_paper_mode_creates_intents(t0, mode):
    p, r = build(t0)
    r.mode = lambda a: mode
    assert r.tick()[ACC] == "skip:mode"
    assert r.store.recent(ACC) == [] and p.led.reserved_total(ACC) == 0


def test_monitor_runs_even_outside_paper(t0):
    p, r = build(t0)
    r.tick()                                                   # mở lệnh ở PAPER
    r.mode = lambda a: TradingMode.SHADOW
    t = p.w.now
    p.quotes = [q(t + timedelta(seconds=5), "2391.5", "2391.7", bid_low="2390.9")]
    p.at(t + timedelta(minutes=1))
    p.w.quote = q(p.w.now - timedelta(seconds=1), "2391.5", "2391.7")
    r.tick()
    assert p.led.open_positions(ACC, p.w.now) == []            # SL vẫn được xử lý
    # (2391 − 2400,50) × 100 × 0,05 = −47,50 = đúng rủi ro đã duyệt
    assert p.led.closed_trades(ACC, t, p.w.now)[0].net_pnl == D("-47.5")


def test_crash_between_risk_and_fill_is_safe(t0):                   # LED-05
    p, r = build(t0)
    real = p.broker.fill

    def crash(*a, **k):
        raise RuntimeError("tiến trình chết")
    p.broker.fill = crash
    assert r.tick()[ACC] == "error"
    assert r.store.recent(ACC) == []                           # chưa ghi nhật ký
    assert len(p.led.open_reservations(ACC)) == 1              # giữ chỗ còn (tính vào heat)
    p.broker.fill = real
    # nhịp sau: có giữ chỗ đang mở → một lệnh một lúc → bỏ qua, không giữ chỗ lần hai
    assert r.tick()[ACC] == "skipped:POSITION_OPEN"
    assert len(p.led.open_reservations(ACC)) == 1
    # quá hạn quyết định (30 giây) → tick nhả giữ chỗ
    p.at(p.w.now + timedelta(seconds=31))
    p.w.quote = q(p.w.now - timedelta(seconds=1), "2400", "2400.2")
    r.tick()
    assert p.led.reserved_total(ACC) == 0 and p.led.open_positions(ACC, p.w.now) == []


def test_restart_does_not_reevaluate_same_view(t0, tmp_path):
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'e.db'}")
    repo.create_all()
    store = SqlEvaluationStore(repo.engine)
    p, r = build(t0, store=store)
    r.tick()
    _, r2 = build(t0, store=SqlEvaluationStore(repo.engine), paper=p)   # "khởi động lại"
    assert r2.tick()[ACC] == "skip:seen"
    assert len(p.led.open_positions(ACC, p.w.now)) == 1


def test_one_account_error_does_not_block_others(t0):
    p, r = build(t0, accounts=lambda: ["acc-loi", ACC])
    real = r.monitor.tick

    def tick(a):
        if a == "acc-loi":
            raise OSError("db")
        return real(a)
    r.monitor.tick = tick
    out = r.tick()
    assert out == {"acc-loi": "error", ACC: "intent:APPROVED"}


def test_no_view_no_intent(t0):
    p, r = build(t0)
    p.at(t0 + timedelta(minutes=30))                          # MarketView hết hạn (15 phút)
    assert r.tick()[ACC] == "skip:no_view"


def test_new_view_after_close_respects_cooldown(t0):
    from tests.factories import market_view
    p, r = build(t0)
    r.tick()
    t = p.w.now
    p.quotes = [q(t + timedelta(seconds=5), "2391.5", "2391.7", bid_low="2390.9")]   # SL
    p.at(t + timedelta(minutes=10))
    p.w.quote = q(p.w.now - timedelta(seconds=1), "2400", "2400.2")
    p.w.views.append(market_view(p.w.now - timedelta(minutes=1), market_view_id="mv2"),
                     report_id="r2", computed_at=p.w.now - timedelta(minutes=1))
    assert r.tick()[ACC] == "skipped:COOLDOWN"


# ---------------------------------------------------------------- kho nhật ký

@pytest.mark.parametrize("kind", KINDS)
def test_evaluation_store(kind, tmp_path, t0):
    if kind == "memory":
        s = InMemoryEvaluationStore()
    elif kind == "postgres":
        from sqlalchemy import create_engine, text

        from gold_trading.storage.schema import metadata
        eng = create_engine(PG_URL, future=True)
        with eng.begin() as c:
            metadata.create_all(c, tables=[metadata.tables["strategy_evaluations"]])
            c.execute(text("TRUNCATE strategy_evaluations"))
        s = SqlEvaluationStore(eng)
    else:
        repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 's.db'}")
        repo.create_all()
        s = SqlEvaluationStore(repo.engine)
    e = Evaluation(ACC, STRATEGY_REF, "mv1", t0, "SKIPPED", ("OUT_OF_SESSION",), {"a": "1"})
    assert s.record(e) is True and s.record(replace(e, outcome="INTENT")) is False
    assert s.exists(ACC, STRATEGY_REF, "mv1") and not s.exists(ACC, STRATEGY_REF, "mv2")
    got = s.recent(ACC)[0]
    assert (got.outcome, got.reasons, got.evaluated_at) == ("SKIPPED", ("OUT_OF_SESSION",), t0)


# ---------------------------------------------------------------- an toàn

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "gold_trading"
FORBIDDEN = ("gold_trading.api", "gold_trading.accounts.mt5_link", "httpx", "requests",
             "urllib", "socket", "MetaTrader5")


@pytest.mark.parametrize("mod", ["strategy/trend_m15.py", "strategy/runner.py",
                                 "risk/paper.py", "risk/ledger.py"])
def test_no_path_to_gateway_or_network(mod):                         # STR-05
    tree = ast.parse((PKG / mod).read_text(encoding="utf-8"))
    names = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module]
    names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    bad = [m for m in names if m.startswith(FORBIDDEN)]
    assert bad == [], bad
    assert "gateway" not in (PKG / mod).read_text(encoding="utf-8").lower().replace(
        "không có đường nào tới gateway", "")


def test_app_wires_strategy(tmp_path, monkeypatch):
    from gold_trading.api.app import create_app
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'a.db'}")
    repo.create_all()
    app = create_app(repo, auth="env")
    assert app.state.paper_strategy_enabled is True
    assert app.state.strategy_runner.ledger is app.state.paper_ledger
    assert app.state.risk_engine.gates is app.state.risk_gates
    monkeypatch.setenv("GT_PAPER_STRATEGY", "0")
    repo2 = SqlRepository.from_url(f"sqlite:///{tmp_path / 'b.db'}")
    repo2.create_all()
    assert create_app(repo2, auth="env").state.paper_strategy_enabled is False


def test_risk_decision_stored_for_intent(t0):
    p, r = build(t0)
    r.tick()
    ev = r.store.recent(ACC)[0]
    res = p.led.open_position_events(ACC)[0]
    assert res.data["risk_decision_id"] == ev.risk_decision_id
    assert RiskOutcome(ev.risk_outcome) is RiskOutcome.APPROVED
