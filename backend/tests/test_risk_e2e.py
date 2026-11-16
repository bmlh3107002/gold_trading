"""RSK-10 (KN-01) đầu-cuối: Risk dùng cổng THẬT của ``create_app`` (``app.state.risk_gates``).

Nến mẫu → orchestrator + analyst thật → Fusion → MarketView thật; lệnh cấm do bộ xử lý làn nhanh
**thật** ghi (thông cáo Fed ngoài lịch, DEC-20); MarketView bị vô hiệu do Fusion **thật** (nguồn
lịch hỏng). Số rủi ro: **chỉ để test**.
"""

from __future__ import annotations

from datetime import timedelta

from gold_trading.common.enums import RiskOutcome, SafetyState
from gold_trading.ingestion.source_status import CheckOutcome, SourceCheck
from gold_trading.market.hours import REFERENCE
from gold_trading.risk import fast_lane as FL
from gold_trading.risk.engine import RiskEngine, RiskPolicy
from gold_trading.risk.ledger import RiskLedger
from tests.factories import intent

# CHỈ ĐỂ TEST — không phải số khuyến nghị
from tests.test_risk_engine import TEST_PROFILE  # noqa: E402  (hồ sơ GIẢ — chỉ để test)

from .test_e2e_market_view import S10, SCOPE, T, pipeline  # noqa: F401  (fixture)
from .test_event_analyst import calendar_record, revise
from .test_fast_lane import ev_of, news

CAL_SOURCES = ("fed_fomc", "bea_schedule", "dol_claims_schedule", "bls_schedule")


def _setup(p, now):
    reg = p.app.state.registry
    reg.get("default").safety.resume("TEST", trigger_source="t", actor="t")
    for src in CAL_SOURCES:                      # nguồn lịch vừa nạp OK
        p.log.record(SourceCheck(src, now - timedelta(seconds=30), CheckOutcome.OK))
    clock = {"now": now}
    p.app.state.risk_profiles.append("default", TEST_PROFILE, created_by="t", reason="test",
                                     at=now - timedelta(days=1))
    eng = RiskEngine(RiskPolicy(version="r-test"), RiskLedger(),
                     p.app.state.risk_gates, clock=lambda: clock["now"])
    return eng, clock


def _intent(p, now):
    view = p.views.current(SCOPE, now)
    assert view is not None
    return intent(now - timedelta(seconds=5), market_view_id=view.market_view_id,
                  entry_reference=2400.0, stop_loss=2390.0,
                  idempotency_key=f"k-{now.isoformat()}")  # mỗi lần là yêu cầu mới


def test_real_gates_approve_then_real_fast_lane_block_rejects(pipeline):  # noqa: F811  5-C14
    now = T + 3 * S10
    eng, clock = _setup(pipeline, now)
    d = eng.evaluate(_intent(pipeline, now), "default")
    # Lúc T lịch thật đang có cửa sổ tin MEDIUM → cổng thật đã chặn (cả lệnh cấm lẫn cờ MV).
    assert d.outcome is RiskOutcome.REJECTED
    assert {"ENTRY_BLOCKED:CALENDAR_MEDIUM", "RISK_FLAGS:EVENT_WINDOW"} <= set(d.reason_codes)
    assert "ENTRY_BLOCKED:FED_UNSCHEDULED_POLICY" not in d.reason_codes
    # Nguồn SAMPLE không có broker → không bao giờ tính được khối lượng (RSK-11)
    assert {"NO_PRICE_FEED", "EQUITY_STALE", "BROKER_SPEC_MISSING"} <= set(d.reason_codes)

    # Thông cáo Fed ngoài lịch → bộ xử lý làn nhanh thật ghi lệnh cấm 15 phút vào kho thật.
    seen = now + timedelta(seconds=2)
    h = FL.fast_lane_handler(pipeline.app.state.block_store, pipeline.st, REFERENCE,
                             clock=lambda: seen)
    h.run(ev_of(news("n:e2e", now, seen)), seen)
    clock["now"] = seen + timedelta(seconds=1)
    assert pipeline.app.state.registry.get("default").safety.state is SafetyState.ACTIVE
    d = eng.evaluate(_intent(pipeline, clock["now"]), "default")
    assert d.outcome is RiskOutcome.REJECTED
    assert "ENTRY_BLOCKED:FED_UNSCHEDULED_POLICY" in d.reason_codes


def test_real_fusion_invalidation_rejects(pipeline):  # noqa: F811             5-C15
    now = T + 3 * S10
    eng, clock = _setup(pipeline, now)
    i = _intent(pipeline, now)              # intent tạo khi MarketView còn hiệu lực
    b = T + timedelta(minutes=2)
    pipeline.log.record(SourceCheck("fed_fomc", b, CheckOutcome.INVALID, error_code="PARSE_ERROR"))
    c = b + timedelta(minutes=1)
    assert pipeline.st.append(revise(calendar_record(pipeline.st, ""), c, note="e2e")).reason \
        is None
    for k in range(3):
        pipeline.orch.tick(c + k * S10)
    clock["now"] = c + 2 * S10
    i = i.model_copy(update={"expiry": clock["now"] + timedelta(minutes=1)})
    d = eng.evaluate(i, "default")
    assert d.outcome is RiskOutcome.REJECTED
    assert "NO_MARKET_VIEW" in d.reason_codes
    assert "CALENDAR_SOURCE_UNHEALTHY:fed_fomc" in d.reason_codes      # Q1: tự kiểm, độc lập


def test_real_calendar_health_without_recent_check_rejects(pipeline):  # noqa: F811     Q1
    now = T + 3 * S10
    eng, clock = _setup(pipeline, now)
    pipeline.log.record(SourceCheck("dol_claims_schedule", now - timedelta(seconds=10),
                                    CheckOutcome.ERROR, error_code="HTTP_500"))
    d = eng.evaluate(_intent(pipeline, now), "default")
    assert d.outcome is RiskOutcome.REJECTED
    assert "CALENDAR_SOURCE_UNHEALTHY:dol_claims_schedule" in d.reason_codes
    assert "NO_MARKET_VIEW" not in d.reason_codes       # MarketView vẫn còn hạn
