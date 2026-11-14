"""GĐ3 bước 5 — Positioning COT (POSN-01, POSN-02). Thiết kế: docs/thiet-ke/31."""

from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.analysts import positioning as P
from gold_trading.analysts.framework import GLOBAL_SCOPE
from gold_trading.common.enums import SourceStatus
from gold_trading.contracts.records import NormalizedRecord
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.ingestion.source_status import SourceCheckLog
from gold_trading.ingestion.sources import cftc_cot as C
from gold_trading.orchestrator.dispatcher import routes_for
from gold_trading.orchestrator.scanner import expired_event, record_event
from gold_trading.storage.analyst_outputs import ExpiredOutput, InMemoryAnalystOutputStore
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.repository import SqlRepository

from .test_cftc_cot import PAGE, REL

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
TUE = datetime(2026, 11, 3, 5, 0, tzinfo=UTC)          # hết ngày chốt 03/11 (ET) ≈ 04/11 05:00


@pytest.fixture(params=["memory", "sqlite"])
def st(request, tmp_path):
    if request.param == "memory":
        return PointInTimeStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'p.db'}")
    repo.create_all()
    return SqlExternalRecordStore(repo.engine)


def real(st):
    C.run_once(store=st, log=SourceCheckLog(), get=lambda: PAGE, now=NOW)
    return st


def report(week: int, net: int, oi: int = 400_000, rev: int = 0, known=None, end=TUE):
    """Báo cáo tổng hợp tuần thứ ``week`` trước ``end`` (0 = mới nhất)."""
    et = end - timedelta(weeks=week)
    rel = et + timedelta(days=3, hours=15)
    return NormalizedRecord(
        record_id=f"{P.SOURCE}:W{week}:r{rev}", source=P.SOURCE, kind="positioning",
        logical_key=f"GOLD_088691:{et.date()}", revision=rev, event_time=et,
        ingested_at=known or rel, available_at=known or rel,
        source_status=SourceStatus.HEALTHY, payload_version="t", raw_ref="t",
        payload={"as_of": et.date().isoformat(), "open_interest": oi, "noncomm_net": net,
                 "changes": {"noncomm_long": 10, "noncomm_short": 4},
                 "release_at": rel.isoformat()})


def history(st, nets, end=TUE):
    """``nets[-1]`` là tuần mới nhất."""
    n = len(nets)
    for i, v in enumerate(nets):
        st.append(report(n - 1 - i, v, end=end))


# ------------------------------------------------------------------ báo cáo thật

def test_real_report_one_week_no_extremes(st):
    o = P.compute(real(st), NOW)
    f = o.features
    assert o.source_status is SourceStatus.HEALTHY
    assert f["noncomm_net"] == 220530 - 40982 and f["open_interest"] == 399169
    r = C.parse(PAGE)
    assert f["noncomm_net_change"] == r.changes["noncomm_long"] - r.changes["noncomm_short"]
    assert f["net_pct_oi"] == round((220530 - 40982) / 399169 * 100, 2)
    assert f["report_date"] == "2026-11-03" and f["horizon"] == "WEEKS"
    assert f["crowding"] == "INSUFFICIENT_DATA" and f["z_net_pct_oi"] is None
    assert {"COT_LAGGED", "COT_HISTORY_SHORT"} <= o.quality_flags and o.confidence == 0.5
    assert {"OPTIONAL_MISSING:etf_flows", "OPTIONAL_MISSING:central_banks"} <= o.quality_flags
    assert f["data_lag_days"] > 9


def test_not_visible_before_official_release(st):
    C.run_once(store=st, log=SourceCheckLog(), get=lambda: PAGE, now=REL - timedelta(hours=1))
    assert P.compute(st, REL - timedelta(seconds=1)).source_status is SourceStatus.MISSING
    assert P.compute(st, REL + timedelta(seconds=1)).source_status is SourceStatus.HEALTHY


# ------------------------------------------------------------------ cực trị (tham chiếu tay)

def test_hand_reference_z_and_percentile(st):
    """26 tuần 20 % + 26 tuần 40 % (tuần mới nhất 40 %): trung bình 30 %, σ = 10 % → z = 1,
    thứ hạng = 1,0 (mọi tuần ≤ 40 %) → bình thường."""
    history(st, [160_000 if i % 2 else 80_000 for i in range(52)])     # tuần cuối (i=51) = 40 %
    o = P.compute(st, NOW)
    f = o.features
    assert f["history_weeks"] == 52 and f["net_pct_oi"] == 40.0
    assert f["z_net_pct_oi"] == 1.0 and f["percentile"] == 1.0
    assert f["crowding"] == "NORMAL" and o.confidence == 1.0


@pytest.mark.parametrize("last,want,hyp", [
    (360_000, "CROWDED_LONG", "CONTRARIAN_DOWNSIDE_RISK"),
    (-200_000, "CROWDED_SHORT", "CONTRARIAN_UPSIDE_RISK"),
])
def test_crowded_extremes_are_hypotheses(st, last, want, hyp):
    history(st, [80_000 if i % 2 else 160_000 for i in range(60)] + [last])
    o = P.compute(st, NOW)
    assert o.features["crowding"] == want and o.features["contrarian_hypothesis"] == hyp
    assert "CROWDING_RISK" in o.risk_flags and f"HYPOTHESIS_{hyp}" in o.drivers
    assert "giả thuyết" in o.features["hypothesis_note"]


def test_lookback_capped_at_156_weeks(st):
    history(st, [0] * 100 + [80_000 if i % 2 else 160_000 for i in range(156)])
    assert P.compute(st, NOW).features["history_weeks"] == 156


def test_zero_dispersion_flag(st):
    history(st, [100_000] * 60)
    o = P.compute(st, NOW)
    assert o.features["z_net_pct_oi"] is None and "COT_ZERO_DISPERSION" in o.quality_flags


# ------------------------------------------------------------------ đầu vào xấu

def test_missing_and_stale(st):
    assert P.compute(st, NOW).source_status is SourceStatus.MISSING
    st.append(report(0, 100_000))
    late = TUE + P.MAX_REPORT_AGE + timedelta(hours=1)
    o = P.compute(st, late)
    assert o.source_status is SourceStatus.STALE and "STALE_INPUT:cot_gold" in o.drivers
    ok = P.compute(st, NOW)
    assert ok.expires_at == min(NOW + P.TTL, TUE + P.MAX_REPORT_AGE + timedelta(seconds=1))


def test_unusable_report_skipped_not_zero(st):
    history(st, [100_000, 120_000])
    fix = TUE + timedelta(days=3, hours=16)
    st.append(report(0, 999, oi=0, rev=1, known=fix))                  # bản sửa OI 0 → bỏ
    o = P.compute(st, fix + timedelta(hours=1))
    assert "COT_REPORT_UNUSABLE_SKIPPED" in o.quality_flags
    assert o.features["noncomm_net"] == 100_000          # tuần trước, không phải 999 / 0
    # Báo cáo còn dùng được đã quá 14 ngày → STALE (không đưa số cũ ra như số mới)
    assert P.compute(st, NOW).source_status is SourceStatus.STALE


def test_revision_known_later_does_not_change_past(st):
    history(st, [100_000, 120_000])
    before = P.compute(st, NOW)
    st.append(report(0, 300_000, rev=1, known=NOW + timedelta(hours=1)))
    assert P.compute(st, NOW) == before
    assert P.compute(st, NOW + timedelta(hours=2)).features["noncomm_net"] == 300_000


# ------------------------------------------------------------------ orchestrator + API

def test_router_and_handler(st):
    e = expired_event(ExpiredOutput("positioning", "*", "*", "GLOBAL", "", "id", NOW))
    assert [r.job_type for r in routes_for(e)] == ["INVALIDATE_MARKETVIEW", "POSITIONING"]
    real(st)
    outs = InMemoryAnalystOutputStore()
    pa = P.PositioningAnalyst(st, outs)
    rec = st.as_of(NOW, source=P.SOURCE, kind="positioning")[0]
    h = P.positioning_handler(pa)
    ev = record_event(rec)
    assert h.run(ev, NOW) == "positioning:stored"
    assert h.run(ev, NOW + timedelta(seconds=1)) == "positioning:unchanged"
    assert outs.latest_scoped("positioning", GLOBAL_SCOPE).output.as_of == NOW   # lúc biết
    assert pa.ensure_fresh(NOW + timedelta(seconds=2)) is False


def test_api_positioning_latest():
    from fastapi.testclient import TestClient

    from gold_trading.common.time import utcnow
    from gold_trading.storage.repository import InMemoryRepository

    from .auth_helpers import make_app, user_client
    outs = InMemoryAnalystOutputStore()
    c = user_client(InMemoryRepository(), analyst_store=outs, data_source=None,
                    run_analysts=False, external_runner=None)
    assert c.get("/api/analysts/positioning/latest").json()["output"] is None
    st = real(PointInTimeStore())
    P.PositioningAnalyst(st, outs).run_at(NOW, utcnow())
    body = c.get("/api/analysts/positioning/latest").json()
    assert body["output"]["features"]["crowding"] == "INSUFFICIENT_DATA"
    app, _ = make_app(InMemoryRepository(), analyst_store=outs, data_source=None,
                      run_analysts=False, external_runner=None)
    assert TestClient(app).get("/api/analysts/positioning/latest").status_code == 401
