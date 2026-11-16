"""Kiểm sổ cái paper trên TimescaleDB thật (GĐ5 bước 6a — LED-02, LED-05, 5-C12).

Chạy trong container backend của CI (``ci_stack.sh``): ``python - < ops/scripts/ledger_race_check.py``
(đọc ``DATABASE_URL``). Ghi vào một tài khoản thử riêng (mã ngẫu nhiên); DB của CI bị bỏ sau đó.
1. 8 luồng của hai "tiến trình" tranh ngân sách 50 (mỗi lần 10) → đúng 5 giữ chỗ, số thứ tự 1..5 liền.
2. 8 luồng cùng một idempotency_key → đúng một quyết định được lưu.
3. Crash giữa giao dịch → không còn gì.
4. Bảng chỉ-thêm: UPDATE bị trigger chặn.
"""

import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, text

from gold_trading.common.enums import RiskOutcome, Side
from gold_trading.contracts.risk import RiskDecision
from gold_trading.contracts.trade_intent import TradeIntent
from gold_trading.risk.ledger import SqlLedger

eng = create_engine(os.environ["DATABASE_URL"], pool_size=10, future=True)
led = SqlLedger(eng)
led2 = SqlLedger(create_engine(os.environ["DATABASE_URL"], pool_size=10, future=True))
acc = f"ci-ledger-{uuid.uuid4().hex[:8]}"
now = datetime.now(UTC)
fail = []


def worker(n):
    lg = (led, led2)[n % 2]          # hai "tiến trình": khóa luồng riêng, chỉ khóa DB bảo vệ
    with lg.locked(acc):
        if lg.reserved_total(acc) + 10 <= 50:
            lg.reserve(acc, "XAUUSD", Decimal(10), f"w{n}", at=now)
            return True
    return False


with ThreadPoolExecutor(max_workers=8) as pool:
    got = sum(pool.map(worker, range(40)))
seqs = [e.account_seq for e in led.events(acc)]
if got != 5 or led.reserved_total(acc) != 50 or seqs != [1, 2, 3, 4, 5]:
    fail.append(f"tranh ngân sách: {got} giữ chỗ, tổng {led.reserved_total(acc)}, seq {seqs}")

intent = TradeIntent(intent_id="i", strategy_id="s", symbol="XAUUSD", side=Side.BUY,
                     entry_type="MARKET", entry_reference=2400.0, stop_loss=2390.0,
                     take_profit=2420.0, expiry=now + timedelta(minutes=2),
                     risk_budget_requested=0.0025, market_view_id="mv", policy_version="p",
                     created_at=now, reason="ci", idempotency_key="same", correlation_id="c")
barrier = threading.Barrier(8)


def decide(n):
    barrier.wait(timeout=10)
    d = RiskDecision(risk_decision_id=f"rd-{acc}-{n}", intent_id="i", account_id=acc,
                     outcome=RiskOutcome.REJECTED, reason_codes=("CI",), decided_at=now,
                     expires_at=now + timedelta(seconds=30), policy_version="p")
    return led.record_decision(d, intent).decision.risk_decision_id


with ThreadPoolExecutor(max_workers=8) as pool:
    ids = set(pool.map(decide, range(8)))
with eng.connect() as c:
    n = c.execute(text("select count(*) from risk_decisions where account_id = :a"),
                  {"a": acc}).scalar_one()
if len(ids) != 1 or n != 1:
    fail.append(f"cùng khóa: {len(ids)} quyết định trả về, {n} dòng lưu")


class Crash(Exception):
    pass


def fault(p):
    if p == "after_reserve":
        raise Crash()


led.fault = fault
try:
    with led.locked(acc):
        led.reserve(acc, "XAUUSD", Decimal(1), "crash", at=now)
except Crash:
    pass
led.fault = None
if len(led.events(acc)) != 5:
    fail.append("crash giữa giao dịch vẫn để lại sự kiện")

try:
    with eng.begin() as c:
        c.execute(text("update paper_ledger_events set reason = 'x' where account_id = :a"),
                  {"a": acc})
    fail.append("UPDATE paper_ledger_events không bị chặn")
except Exception:
    pass

if fail:
    print("LỖI sổ cái:", *fail, sep="\n  ")
    sys.exit(1)
print(f"Sổ cái paper trên TimescaleDB: 8 luồng → 5 giữ chỗ, cùng khóa → 1 quyết định, crash → "
      f"không ghi, UPDATE bị chặn ({acc})")
