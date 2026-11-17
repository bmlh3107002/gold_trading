"""API trang Rủi ro — GĐ5 bước 8b (RPF-05, DSH-05). Thiết kế 37 mục 3.

Số trong hồ sơ là bản H1–H11 người dùng chốt 16/11 (giá trị thật của người dùng, không phải số
khuyến nghị của hệ thống). Số broker / equity: GIẢ, chỉ để test.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from gold_trading.contracts.candle import DataSource
from gold_trading.risk.gates import BrokerReading
from gold_trading.risk.ledger import EventType
from gold_trading.storage.repository import InMemoryRepository
from tests.auth_helpers import admin_client, login_owner, user_client

D = Decimal
BASE = "/api/accounts/default/risk"
H1_H11 = {"risk_per_trade": "0.0025", "min_reward_risk": "1.5", "max_open_risk": "0.005",
          "max_daily_loss": "0.0075", "max_weekly_loss": "0.015", "max_monthly_loss": "0.03",
          "max_consecutive_losses": 5, "day_reset_tz": "America/New_York",
          "day_reset_time": "17:00", "max_trades_per_day": 4, "max_drawdown_halt": "0.05",
          "news_hold_policy": "KEEP_SAFE_ONLY", "weekend_policy": "CLOSE_ALL",
          "weekend_close_before_min": 30, "max_effective_leverage": "3",
          "cash_flow_policy": "SEPARATE", "pyramiding_policy": "ONLY_IF_ALL_IN_PROFIT",
          "notes": ""}


@pytest.fixture
def c():
    repo = InMemoryRepository()
    cl = user_client(repo, data_source=DataSource.SAMPLE, run_sample_feed=False,
                     run_analysts=False, external_runner=None)
    cl.repo = repo
    return cl


def equity(c, value=10_000.0, age=2.0):
    """Nhịp tim GIẢ (chỉ để test) cho cổng broker của Risk."""
    g = c.app.state.risk_gates
    reading = BrokerReading(connected=True, heartbeat_age_s=age, equity=value, margin_free=value,
                            account_currency="USD", identity=None, heartbeat_symbol=None,
                            live_spec_hash=None, locked_symbol=None, spec=None)
    object.__setattr__(g, "broker", lambda acc, at: reading)


def test_overview_before_anything(c):
    b = c.get(f"{BASE}/overview").json()
    assert b["readiness"] == {"profile": False, "commission": False, "paper_started": False}
    assert b["profile"] is None and b["usage"] is None and b["paper"]["started"] is False
    assert b["is_sample"] is True and b["strategy_enabled"] is True
    assert b["decisions"] == [] and b["evaluations"] == []


def test_create_profile_and_history(c):
    r = c.post(f"{BASE}/profile", json={"values": H1_H11, "reason": "H1–H11 chốt 16/11"})
    assert r.status_code == 201, r.text
    assert r.json()["version"] == 1 and r.json()["values"]["risk_per_trade"] == "0.0025"
    v2 = H1_H11 | {"risk_per_trade": "0.004"}
    assert c.post(f"{BASE}/profile", json={"values": v2, "reason": "tăng"}).json()["version"] == 2
    b = c.get(f"{BASE}/overview").json()
    assert b["readiness"]["profile"] and b["profile"]["version"] == 2
    assert [p["version"] for p in b["profile_history"]] == [2, 1]
    u = b["usage"]
    assert (u["trades_today"], u["max_trades_per_day"], u["loss_streak"]) == (0, 4, 0)
    assert u["daily_loss"] is None                       # sổ paper chưa bắt đầu → chưa có tỷ lệ


@pytest.mark.parametrize("bad", [{"risk_per_trade": "0.01"},          # DEC-09
                                 {"risk_per_trade": "0.002"},
                                 {"max_daily_loss": "0.5"},
                                 {"news_hold_policy": "KEEP"},
                                 {"day_reset_tz": "Mars/Base"}])
def test_profile_hard_limits(c, bad):
    r = c.post(f"{BASE}/profile", json={"values": H1_H11 | bad, "reason": "thử"})
    assert r.status_code == 422
    assert c.get(f"{BASE}/overview").json()["profile"] is None


def test_profile_rejects_extra_fields_and_missing_reason(c):
    assert c.post(f"{BASE}/profile", json={"values": H1_H11 | {"x": 1}, "reason": "a"}
                  ).status_code == 422
    assert c.post(f"{BASE}/profile", json={"values": H1_H11, "reason": ""}).status_code == 422


def test_commission(c):
    r = c.post(f"{BASE}/commission", json={"per_lot": "7", "reason": "theo trang sàn"})
    assert r.status_code == 201 and r.json()["per_lot"] == "7"
    for bad in ("-1", "5000", "0.0000001"):
        assert c.post(f"{BASE}/commission", json={"per_lot": bad, "reason": "x"}
                      ).status_code == 422
    assert c.post(f"{BASE}/commission", json={"per_lot": "0", "reason": "sàn không thu"}
                  ).status_code == 201                    # 0 chỉ khi người dùng chủ động nhập
    b = c.get(f"{BASE}/overview").json()
    assert b["commission"]["per_lot"] == "0" and len(b["commission_history"]) == 2


def test_paper_start_needs_fresh_mt5_equity(c):
    r = c.post(f"{BASE}/paper/start", json={"reason": "bắt đầu"})
    assert r.status_code == 409                          # nguồn mẫu: không có equity MT5
    equity(c, age=45.0)                                  # nhịp tim cũ 45 giây
    assert c.post(f"{BASE}/paper/start", json={"reason": "bắt đầu"}).status_code == 409
    equity(c)
    b = c.post(f"{BASE}/paper/start", json={"reason": "bắt đầu"}).json()
    # vốn đầu = equity MT5 đọc lúc bấm (không cho gõ tay)
    assert b["paper"]["started"] and D(b["paper"]["capital"]) == 10_000
    assert b["readiness"]["paper_started"] is True
    assert c.post(f"{BASE}/paper/start", json={"reason": "lại"}).status_code == 409
    assert c.post(f"{BASE}/paper/start", json={"reason": "x", "capital": "99"}
                  ).status_code == 422


def test_cash_flows_adjust_peak(c):                                   # H10
    equity(c)
    c.post(f"{BASE}/paper/start", json={"reason": "bắt đầu"})
    b = c.post(f"{BASE}/paper/cash", json={"kind": "CASH_IN", "amount": "1000",
                                           "reason": "nạp"}).json()
    assert D(b["paper"]["realized_equity"]) == 11_000 and D(b["paper"]["peak"]) == 11_000
    b = c.post(f"{BASE}/paper/cash", json={"kind": "CASH_OUT", "amount": "1100",
                                           "reason": "rút"}).json()
    assert D(b["paper"]["realized_equity"]) == 9_900 and D(b["paper"]["peak"]) == 9_900
    assert c.post(f"{BASE}/paper/cash", json={"kind": "CASH_OUT", "amount": "9900",
                                              "reason": "rút hết"}).status_code == 409
    assert c.post(f"{BASE}/paper/cash", json={"kind": "CASH_IN", "amount": "0",
                                              "reason": "x"}).status_code == 422


def test_halted_and_explicit_reset(c):                                  # H6
    c.post(f"{BASE}/profile", json={"values": H1_H11, "reason": "v1"})
    equity(c)
    c.post(f"{BASE}/paper/start", json={"reason": "bắt đầu"})
    led = c.app.state.paper_ledger
    led.append("default", EventType.CLOSE, "pos_x", D(-600), actor="paper", reason="test",
               data={"side": "BUY", "opened_at": "2026-01-01T00:00:00+00:00"})
    b = c.get(f"{BASE}/overview").json()
    assert b["paper"]["halted"] is True and b["paper"]["drawdown"] == "0.060000"
    assert c.post(f"{BASE}/paper/drawdown-reset", json={"confirm": False, "reason": "x"}
                  ).status_code == 422                     # phải xác nhận rõ
    b = c.post(f"{BASE}/paper/drawdown-reset",
               json={"confirm": True, "reason": "đã xem lại"}).json()
    assert b["paper"]["halted"] is False and D(b["paper"]["peak"]) == 9_400


def test_feasibility_sample_is_illustrative(c):                        # RPF-04
    b = c.get(f"{BASE}/feasibility").json()
    assert b["status"] == "CHI_MINH_HOA" and b["label"].startswith("CHỈ MINH HỌA")


def test_writes_are_audited(c):
    c.post(f"{BASE}/commission", json={"per_lot": "7", "reason": "theo sàn"})
    c.post(f"{BASE}/profile", json={"values": H1_H11 | {"risk_per_trade": "0.01"},
                                    "reason": "thử"})
    acts = {(a.action, a.outcome) for a in c.repo.audit(limit=100, account_id="default")}
    assert ("risk.commission", "ACCEPTED") in acts and ("risk.profile", "REJECTED") in acts


def test_only_owner_can_read_or_write():
    repo = InMemoryRepository()
    owner = user_client(repo, data_source=DataSource.SAMPLE, run_sample_feed=False,
                        run_analysts=False, external_runner=None)
    other = login_owner(owner.app, owner.kc, repo, username="other", account="acc-other")
    assert other.get(f"{BASE}/overview").status_code == 404
    assert other.post(f"{BASE}/commission", json={"per_lot": "1", "reason": "x"}
                      ).status_code == 404
    adm = admin_client(repo, data_source=DataSource.SAMPLE, run_sample_feed=False,
                       run_analysts=False, external_runner=None)
    assert adm.get(f"{BASE}/overview").status_code == 404           # DEC-16
    assert adm.post(f"{BASE}/profile", json={"values": H1_H11, "reason": "x"}
                    ).status_code == 404


def test_overview_lists_decisions_and_evaluations(c):
    from datetime import timedelta

    from gold_trading.common.time import utcnow
    from gold_trading.strategy.runner import Evaluation
    from tests.factories import intent
    now = utcnow()
    d = c.app.state.risk_engine.evaluate(intent(now - timedelta(seconds=5)), "default")
    c.app.state.strategy_evaluations.record(Evaluation(
        "default", "xu-huong-m15@1.0.0", "mv1", now, "SKIPPED", ("OUT_OF_SESSION",), {}))
    b = c.get(f"{BASE}/overview").json()
    assert b["decisions"][0]["risk_decision_id"] == d.risk_decision_id
    assert b["decisions"][0]["outcome"] == "REJECTED" and b["decisions"][0]["reason_codes"]
    assert b["evaluations"][0]["reasons"] == ["OUT_OF_SESSION"]
