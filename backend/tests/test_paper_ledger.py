"""Sổ cái paper bền vững — GĐ5 bước 6a (DB-06, LED-02, LED-05, CORE-05). Thiết kế 35 mục 12.

Chạy trên bộ nhớ + SQLite; thêm Postgres thật khi đặt ``GT_TEST_PG_URL`` (CI job ``docker`` chạy
kịch bản tương tự trên TimescaleDB: ``ops/scripts/ledger_race_check.py``).
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from gold_trading.common.enums import RiskOutcome
from gold_trading.risk.ledger import (
    EventType,
    LedgerConflict,
    RiskLedger,
    SqlLedger,
    end_key,
)
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.schema import metadata
from tests.conftest import minutes
from tests.factories import intent
from tests.test_risk_engine import ACC, World

D = Decimal
PG_URL = os.environ.get("GT_TEST_PG_URL")
KINDS = ["memory", "sqlite"] + (["postgres"] if PG_URL else [])


class Crash(Exception):
    """Crash giả lập (tiến trình chết giữa giao dịch = giao dịch không commit)."""


def make_ledger(kind: str, tmp_path, name: str = "l.db"):
    if kind == "memory":
        return RiskLedger()
    if kind == "sqlite":
        repo = SqlRepository.from_url(f"sqlite:///{tmp_path / name}")
        repo.create_all()
        return SqlLedger(repo.engine)
    eng = create_engine(PG_URL, future=True)
    with eng.begin() as c:            # DB thử riêng: làm sạch hai bảng của sổ cái
        metadata.create_all(c, tables=[metadata.tables["risk_decisions"],
                                       metadata.tables["paper_ledger_events"]])
        c.execute(text("TRUNCATE risk_decisions, paper_ledger_events"))
    return SqlLedger(eng)


@pytest.fixture(params=KINDS)
def kind(request):
    return request.param


@pytest.fixture
def ledger(kind, tmp_path):
    return make_ledger(kind, tmp_path)


# ---------------------------------------------------------------- sổ cái

def test_reserve_and_release_per_account(ledger, t0):
    a = ledger.reserve("A", "XAUUSD", D("42.00"), "intent:i1", at=t0)
    ledger.reserve("B", "XAUUSD", D("10.5"), "intent:i2", at=t0)
    # Lỗi cũ (12.1): sổ cộng chung mọi tài khoản → B tiêu trần của A.
    assert ledger.reserved_total("A") == D("42.00")
    assert ledger.reserved_total("B") == D("10.5")
    assert ledger.reserved_total() == D("52.50")
    assert ledger.open_since("A", t0) == 1 and ledger.open_since("A", t0 + minutes(1)) == 0
    assert ledger.release("A", a, "RESERVATION_EXPIRED", actor="system") is True
    assert ledger.release("A", a, "again") is False                 # idempotent
    assert ledger.release("B", a, "wrong account") is False         # không nhả chéo tài khoản
    assert ledger.reserved_total("A") == 0
    evs = ledger.events("A")
    assert [e.type for e in evs] == [EventType.RESERVE, EventType.RELEASE]
    assert [e.account_seq for e in evs] == [1, 2]
    rel = evs[1]
    # Sự kiện bù trừ: số âm, trỏ về bản gốc, có lý do + người làm
    assert rel.amount == D("-42.00") and rel.links == evs[0].event_id
    assert (rel.actor, rel.reason, rel.once_key) == ("system", "RESERVATION_EXPIRED", end_key(a))


def test_reservation_ends_only_once(ledger, t0):
    rid = ledger.reserve("A", "XAUUSD", D("5"), "r", at=t0)
    ledger.append("A", EventType.OPEN, "pos_1", D(0), actor="paper", reason="fill",
                  once_key=end_key(rid), data={"reservation_id": rid})
    with pytest.raises(LedgerConflict):
        ledger.append("A", EventType.RELEASE, rid, D("-5"), actor="x", reason="late",
                      once_key=end_key(rid))
    assert ledger.release("A", rid, "late") is False
    assert ledger.reserved_total("A") == 0


@pytest.mark.parametrize("bad", [5, 5.0, D("NaN"), D("1.123456789")])
def test_amount_must_be_exact_decimal(ledger, bad):
    with pytest.raises(ValueError):
        ledger.append("A", EventType.CASH_IN, "c1", bad, actor="u", reason="x")


def test_events_need_actor_and_reason(ledger):
    with pytest.raises(ValueError):
        ledger.append("A", EventType.CASH_IN, "c1", D(1), actor="", reason="x")
    with pytest.raises(ValueError):
        ledger.append("A", EventType.CASH_IN, "c1", D(1), actor="u", reason="")


@pytest.mark.parametrize("point", ["after_reserve", "before_commit"])
def test_crash_inside_transaction_leaves_nothing(ledger, t0, point):            # LED-05
    def fault(p):
        if p == point:
            raise Crash(p)
    ledger.fault = fault
    with pytest.raises(Crash), ledger.locked("A"):
        ledger.reserve("A", "XAUUSD", D("42"), "r", at=t0)
    ledger.fault = None
    assert ledger.reserved_total("A") == 0 and ledger.events("A") == []
    # sau "khởi động lại" ghi tiếp bình thường, số thứ tự không thủng
    ledger.reserve("A", "XAUUSD", D("1"), "r", at=t0)
    assert [e.account_seq for e in ledger.events("A")] == [1]


def test_concurrent_reservations_never_exceed_budget(ledger, t0):             # 5-C12
    """8 luồng cùng tranh ngân sách 50 (mỗi lần 10): đúng 5 giữ chỗ."""
    def worker(n):
        with ledger.locked("A"):
            if ledger.reserved_total("A") + 10 <= 50:
                ledger.reserve("A", "XAUUSD", D(10), f"w{n}", at=t0)
                return True
        return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        got = list(pool.map(worker, range(40)))
    assert sum(got) == 5 and ledger.reserved_total("A") == 50
    seqs = [e.account_seq for e in ledger.events("A")]
    assert seqs == list(range(1, 6))


def test_restart_reads_back_from_db(tmp_path, t0):                             # LED-02
    url = f"sqlite:///{tmp_path / 'r.db'}"
    repo = SqlRepository.from_url(url)
    repo.create_all()
    l1 = SqlLedger(repo.engine)
    rid = l1.reserve("A", "XAUUSD", D("42.36"), "r", at=t0)
    l2 = SqlLedger(create_engine(url, future=True))          # tiến trình mới, cùng DB
    assert l2.reserved_total("A") == D("42.36")
    assert l2.open_reservations("A")[0].ref_id == rid


# ---------------------------------------------------------------- Risk + sổ cái (idempotency)

@pytest.fixture
def world(kind, tmp_path, t0):
    return World(t0, ledger=make_ledger(kind, tmp_path, "w.db"))


def test_same_key_returns_same_decision_and_one_reservation(world, t0):        # LED-05
    i = intent(t0 - minutes(0.5))
    d1 = world.evaluate(i, keep_key=True)
    assert d1.outcome is RiskOutcome.APPROVED
    # gửi lại cùng yêu cầu với mã intent mới (chiến lược khởi động lại) → cùng quyết định
    d2 = world.evaluate(i.model_copy(update={"intent_id": "i-retry"}), keep_key=True)
    assert d2 == d1
    assert world.engine.ledger.reserved_total(ACC) == d1.risk_amount
    assert len(world.engine.ledger.open_reservations(ACC)) == 1


def test_same_key_other_content_rejected_without_new_reservation(world, t0):
    i = intent(t0 - minutes(0.5))
    d1 = world.evaluate(i, keep_key=True)
    d2 = world.evaluate(i.model_copy(update={"stop_loss": 2395.0}), keep_key=True)
    assert d2.outcome is RiskOutcome.REJECTED
    assert d2.reason_codes == ("IDEMPOTENCY_KEY_REUSED",)
    assert d2.details["prior_decision"] == d1.risk_decision_id
    assert len(world.engine.ledger.open_reservations(ACC)) == 1


def test_rejection_is_stored_and_replayed(world, t0):
    world.commission = None
    i = intent(t0 - minutes(0.5))
    d1 = world.evaluate(i, keep_key=True)
    assert "COMMISSION_UNKNOWN" in d1.reason_codes
    world.commission = World(t0).commission            # sửa xong cũng không tính lại cùng khóa
    assert world.evaluate(i, keep_key=True) == d1
    assert world.engine.ledger.decision_for(ACC, i.idempotency_key).decision == d1


@pytest.mark.parametrize("point", ["after_reserve", "after_decision", "before_commit"])
def test_crash_between_reserve_and_decision_rolls_back(world, t0, point):     # LED-05
    led = world.engine.ledger

    def fault(p):
        if p == point:
            raise Crash(p)
    led.fault = fault
    i = intent(t0 - minutes(0.5))
    d = world.evaluate(i, keep_key=True)
    assert d.outcome is RiskOutcome.REJECTED and d.reason_codes == ("GATE_READ_ERROR:ledger",)
    assert led.reserved_total(ACC) == 0 and led.events(ACC) == []
    assert led.decision_for(ACC, i.idempotency_key) is None      # lỗi sổ cái → không lưu
    led.fault = None
    d2 = world.evaluate(i, keep_key=True)                         # chạy lại → quyết bình thường
    assert d2.outcome is RiskOutcome.APPROVED and led.reserved_total(ACC) == d2.risk_amount


def test_crash_after_commit_recovers_same_decision(tmp_path, t0):               # LED-05
    url = f"sqlite:///{tmp_path / 'c.db'}"
    repo = SqlRepository.from_url(url)
    repo.create_all()
    w1 = World(t0, ledger=SqlLedger(repo.engine))
    i = intent(t0 - minutes(0.5))
    d1 = w1.evaluate(i, keep_key=True)        # commit xong, "tiến trình chết" trước khi khớp
    w2 = World(t0, ledger=SqlLedger(create_engine(url, future=True)))   # khởi động lại
    d2 = w2.evaluate(i, keep_key=True)
    assert d2 == d1 and w2.engine.ledger.reserved_total(ACC) == d1.risk_amount


def test_ledger_read_error_rejects_without_storing(world, t0):
    led = world.engine.ledger

    def boom(*a, **k):
        raise OSError("db down")
    led.decision_for = boom                                    # type: ignore[method-assign]
    d = world.evaluate()
    assert d.reason_codes == ("GATE_READ_ERROR:ledger",)
    assert led.reserved_total(ACC) == 0


def test_eight_threads_same_key_one_flow(world, t0):                            # LED-05
    i = intent(t0 - minutes(0.5))
    with ThreadPoolExecutor(max_workers=8) as pool:
        ds = list(pool.map(lambda _: world.evaluate(i, keep_key=True), range(8)))
    assert len({d.risk_decision_id for d in ds}) == 1
    assert len(world.engine.ledger.open_reservations(ACC)) == 1


def test_eight_threads_budget_on_sql(world, t0):                                # 5-C12
    from dataclasses import replace

    from tests.test_risk_engine import TEST_PROFILE
    world.profiles.append(ACC, replace(TEST_PROFILE, max_open_risk=Decimal("0.01"),
                                       max_trades_per_day=100),
                          created_by="sub-u", reason="test", at=t0 - minutes(60))
    ins = [intent(t0 - minutes(0.5), intent_id=f"i{n}", idempotency_key=f"k{n}")
           for n in range(16)]
    barrier = threading.Barrier(8)

    def run(i):
        try:
            barrier.wait(timeout=5)
        except threading.BrokenBarrierError:
            pass
        return world.evaluate(i, keep_key=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        ds = list(pool.map(run, ins))
    ok = [d for d in ds if d.outcome is not RiskOutcome.REJECTED]
    total = world.engine.ledger.reserved_total(ACC)
    # 1 % của 10.000 = 100 $; mỗi lệnh 42 $ → 42 + 42 + 10,5 (REDUCED) = 94,5
    assert total == Decimal("94.50") and len(ok) == 3
    assert total == sum((d.risk_amount for d in ok), Decimal(0))


@pytest.mark.skipif(not PG_URL, reason="cần Postgres thật (GT_TEST_PG_URL)")
def test_two_processes_share_budget_via_db_lock(t0):                             # 5-C12
    """Hai "tiến trình" (hai sổ cái riêng, khóa luồng riêng) → chỉ khóa DB bảo vệ ngân sách."""
    l1 = make_ledger("postgres", None)
    l2 = SqlLedger(create_engine(PG_URL, future=True))

    def worker(n):
        led = (l1, l2)[n % 2]
        with led.locked("A"):
            if led.reserved_total("A") + 10 <= 50:
                led.reserve("A", "XAUUSD", D(10), f"w{n}", at=t0)
                return True
        return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        got = sum(pool.map(worker, range(40)))
    assert got == 5 and l1.reserved_total("A") == 50


def test_other_account_reservations_do_not_eat_budget(world, t0):              # 12.1
    from dataclasses import replace

    from tests.test_risk_engine import TEST_PROFILE
    world.profiles.append(ACC, replace(TEST_PROFILE, max_open_risk=Decimal("0.01")),
                          created_by="sub-u", reason="test", at=t0 - minutes(60))
    led = world.engine.ledger
    for n in range(4):                 # tài khoản khác: 90 $ giữ chỗ + 4 lệnh hôm nay
        led.reserve("acc-other", "XAUUSD", D("22.5"), f"o{n}", at=t0 - minutes(1))
    d = world.evaluate()
    assert d.outcome is RiskOutcome.APPROVED, d.reason_codes
    assert d.volume == D("0.04") and d.details["trades_today"] == "0"
