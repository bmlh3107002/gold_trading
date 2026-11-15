"""GĐ4 bước 3 — Data Quality Gate `quality-policy-1` (DQG-01..03; 4-C01, 4-C02, 4-C07; 2-C04).

Thiết kế 33 mục 4. DEC-24: bắt buộc Technical / Regime / Event; tùy chọn Macro / Positioning / News.
"""

import pytest
from pydantic import ValidationError

from gold_trading.analysts.framework import Scope, input_digest
from gold_trading.common.enums import QualityVerdict, SourceStatus
from gold_trading.contracts.snapshot import QualityReport
from gold_trading.intelligence import snapshot_builder as SB
from gold_trading.intelligence.quality_gate import POLICY_V1, QualityPolicy, evaluate
from gold_trading.intelligence.snapshot_builder import SnapshotRecord, build_snapshot
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.snapshots import (
    InMemoryQualityReportStore,
    InMemorySnapshotStore,
    SqlQualityReportStore,
    SqlSnapshotStore,
)
from tests.conftest import minutes
from tests.test_snapshot_builder import out

FEED = Scope("XAUUSD", "M15", "MT5", "f1")
SAMPLE = Scope("XAUUSD", "M15", "SAMPLE", "")
FEATURES = {
    "technical": {"trend": "UP", "mtf_alignment": "ALIGNED_UP",
                  "vol_forecast": {"sigma_bar_pct": 0.09, "sigma_day_pct": 0.9}},
    "regime": {"regime": "TREND", "direction": "UP", "ambiguous": False},
    "event": {"event_risk": "NONE"},
    "macro": {"macro_bias": "INSUFFICIENT_DATA"},
    "positioning": {"crowding": "INSUFFICIENT_DATA"},
    "news": {"tone_score": None},
}
OPTIONAL = ("macro", "positioning", "news")


def outputs(t, price=FEED, skip=(), **over):
    """Output hợp lệ cho cả 6 analyst; ``over[a]`` = trường AnalystOutput ghi đè."""
    res = {}
    for a in SB.ANALYSTS:
        if a in skip:
            continue
        kw = {"features": FEATURES[a]} | over.get(a, {})
        res[a] = out(a, SB.scope_for(a, price), kw.pop("as_of", t), **kw)
    return res


def gate(t0, at=None, price=FEED, **kw):
    snap = build_snapshot(outputs(t0 - minutes(1), price=price, **kw), price, t0)
    return snap, evaluate(snap, POLICY_V1, at or t0)


def test_all_healthy_accepted(t0):
    _, r = gate(t0)
    assert (r.verdict, r.reasons, r.confidence_multiplier) == (QualityVerdict.ACCEPTED, (), 1.0)
    assert r.policy_version == "quality-policy-1" and r.evaluated_at == t0


@pytest.mark.parametrize("a", sorted(SB.REQUIRED))
def test_required_missing_rejects(t0, a):          # 4-C01
    _, r = gate(t0, skip=(a,))
    assert r.verdict is QualityVerdict.REJECTED and r.confidence_multiplier == 0.0
    assert r.reasons == (f"REQUIRED_MISSING:{a}",)


@pytest.mark.parametrize("a", sorted(SB.REQUIRED))
def test_required_expired_rejects_and_says_expired(t0, a):   # 2-C04: không dùng bản cũ quá hạn
    _, r = gate(t0, **{a: {"as_of": t0 - minutes(40)}})
    assert r.verdict is QualityVerdict.REJECTED
    assert f"REQUIRED_EXPIRED:{a}" in r.reasons


@pytest.mark.parametrize("status", [SourceStatus.STALE, SourceStatus.MISSING, SourceStatus.INVALID])
@pytest.mark.parametrize("a", sorted(SB.REQUIRED))
def test_required_unhealthy_rejects(t0, a, status):
    _, r = gate(t0, **{a: {"source_status": status, "features": {"input": {}}}})
    assert r.verdict is QualityVerdict.REJECTED
    assert f"REQUIRED_{status.value}:{a}" in r.reasons


@pytest.mark.parametrize("a,features", [
    ("technical", {"trend": "SIDEWAYS", "mtf_alignment": "MIXED", "vol_forecast": None}),
    ("technical", {"trend": "UP", "vol_forecast": None}),                       # thiếu khóa
    ("technical", {"trend": "UP", "mtf_alignment": "MIXED",
                   "vol_forecast": {"sigma_day_pct": -0.1}}),
    ("technical", {"trend": "UP", "mtf_alignment": "MIXED",
                   "vol_forecast": {"sigma_day_pct": float("nan")}}),
    ("technical", {"trend": "UP", "mtf_alignment": "MIXED",
                   "vol_forecast": {"sigma_day_pct": True}}),
    ("technical", {"trend": "UP", "mtf_alignment": "MIXED", "vol_forecast": 0.9}),
    ("regime", {"regime": "TREND", "direction": "UP"}),                        # thiếu ambiguous
    ("regime", {"regime": "BULL", "direction": "UP", "ambiguous": False}),
    ("regime", {"regime": "TREND", "direction": "SIDEWAYS", "ambiguous": False}),
    ("regime", {"regime": "TREND", "direction": "UP", "ambiguous": "no"}),
    ("event", {}),
    ("event", {"event_risk": "EXTREME"}),
])
def test_required_schema_rejects(t0, a, features):            # DQG-02
    _, r = gate(t0, **{a: {"features": features}})
    assert r.verdict is QualityVerdict.REJECTED
    assert f"REQUIRED_SCHEMA:{a}" in r.reasons


def test_vol_forecast_may_be_absent_value(t0):
    _, r = gate(t0, technical={"features": FEATURES["technical"] | {"vol_forecast": None}})
    assert r.verdict is QualityVerdict.ACCEPTED


def test_technical_and_regime_on_different_bars_rejects(t0):  # 4-C07
    _, r = gate(t0, regime={"as_of": t0 - minutes(16)})
    assert r.verdict is QualityVerdict.REJECTED
    assert r.reasons == ("TIMESTAMP_CONFLICT:technical,regime",)


def test_global_inputs_may_have_other_timestamps(t0):
    _, r = gate(t0, event={"as_of": t0 - minutes(3)}, news={"as_of": t0 - minutes(9)})
    assert r.verdict is QualityVerdict.ACCEPTED


@pytest.mark.parametrize("a", OPTIONAL)
def test_optional_missing_degrades(t0, a):                     # 4-C02
    _, r = gate(t0, skip=(a,))
    assert r.verdict is QualityVerdict.DEGRADED
    assert r.reasons == (f"OPTIONAL_MISSING:{a}",) and r.confidence_multiplier == 0.9


def test_all_optional_missing_multiplies(t0):
    _, r = gate(t0, skip=OPTIONAL)
    assert r.verdict is QualityVerdict.DEGRADED
    assert r.confidence_multiplier == pytest.approx(0.729)
    assert r.reasons == ("OPTIONAL_MISSING:macro", "OPTIONAL_MISSING:news",
                         "OPTIONAL_MISSING:positioning")


@pytest.mark.parametrize("over,reason", [
    ({"news": {"as_of": "OLD"}}, "OPTIONAL_EXPIRED:news"),
    ({"macro": {"source_status": SourceStatus.STALE, "features": {}}}, "OPTIONAL_STALE:macro"),
    ({"positioning": {"features": {"crowding": "PANIC"}}}, "OPTIONAL_SCHEMA:positioning"),
    ({"news": {"features": {}}}, "OPTIONAL_SCHEMA:news"),
    ({"news": {"features": {"tone_score": "3"}}}, "OPTIONAL_SCHEMA:news"),
    ({"macro": {"features": {"macro_bias": None}}}, "OPTIONAL_SCHEMA:macro"),
])
def test_optional_problems_degrade(t0, over, reason):
    if over.get("news", {}).get("as_of") == "OLD":
        over = {"news": {"as_of": t0 - minutes(60)}}
    _, r = gate(t0, **over)
    assert r.verdict is QualityVerdict.DEGRADED and r.reasons == (reason,)
    assert r.confidence_multiplier == 0.9


def test_rejected_does_not_list_optional_or_multiplier(t0):
    _, r = gate(t0, skip=("event", "news"))
    assert r.reasons == ("REQUIRED_MISSING:event",) and r.confidence_multiplier == 0.0


def test_evaluated_after_required_expiry_rejects(t0):
    snap, _ = gate(t0)
    r = evaluate(snap, POLICY_V1, snap.expires_at)
    assert r.verdict is QualityVerdict.REJECTED and "REQUIRED_EXPIRED:event" in r.reasons


def test_evaluating_before_snapshot_exists_raises(t0):
    snap, _ = gate(t0)
    with pytest.raises(ValueError, match="nhìn trước"):
        evaluate(snap, POLICY_V1, t0 - minutes(1))


def test_flags_passed_down(t0):
    _, r = gate(t0, price=SAMPLE,
                macro={"quality_flags": frozenset({"EXTREME_INPUT:real_yield_10y", "OTHER"})},
                technical={"quality_flags": frozenset({"SPIKE_IN_INPUT:candles"})})
    assert r.flags == {"SAMPLE_DATA", "macro:EXTREME_INPUT:real_yield_10y",
                       "technical:SPIKE_IN_INPUT:candles"}


def test_report_id_deterministic(t0):
    snap, r1 = gate(t0)
    r2 = evaluate(snap, POLICY_V1, t0 + minutes(1))           # cùng kết quả, lúc khác
    assert r1.report_id == r2.report_id and r1.report_id.startswith("qr:quality-policy-1:")
    r3 = evaluate(snap, POLICY_V1, snap.expires_at)           # kết quả khác
    assert r3.report_id != r1.report_id


@pytest.mark.parametrize("kw", [
    {"verdict": QualityVerdict.REJECTED, "reasons": ("X",), "confidence_multiplier": 0.5},
    {"verdict": QualityVerdict.REJECTED, "reasons": (), "confidence_multiplier": 0.0},
    {"verdict": QualityVerdict.DEGRADED, "reasons": ("X",), "confidence_multiplier": 0.0},
    {"verdict": QualityVerdict.DEGRADED, "reasons": (), "confidence_multiplier": 0.9},
    {"verdict": QualityVerdict.ACCEPTED, "reasons": ("X",), "confidence_multiplier": 1.0},
    {"verdict": QualityVerdict.ACCEPTED, "reasons": (), "confidence_multiplier": 0.9},
])
def test_report_contract_consistency(t0, kw):
    with pytest.raises(ValidationError):
        QualityReport(report_id="r", snapshot_id="s", evaluated_at=t0, policy_version="p", **kw)


def test_policy_validation():
    with pytest.raises(ValueError, match="vừa bắt buộc"):
        QualityPolicy("x", required=frozenset({"news"}), optional_penalty={"news": 0.9})
    for p in (0.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="hệ số"):
            QualityPolicy("x", required=frozenset(), optional_penalty={"news": p})


def test_policy_v1_fingerprint():
    # Đổi nội dung chính sách mà KHÔNG tăng phiên bản → test này đỏ (thiết kế 33 mục 4).
    content = {"version": POLICY_V1.version, "required": sorted(POLICY_V1.required),
               "optional": dict(sorted(POLICY_V1.optional_penalty.items())),
               "schema": sorted(POLICY_V1.schema), "same_bar": list(POLICY_V1.same_bar)}
    assert content == {"version": "quality-policy-1",
                       "required": ["event", "regime", "technical"],
                       "optional": {"macro": 0.9, "news": 0.9, "positioning": 0.9},
                       "schema": ["event", "macro", "news", "positioning", "regime", "technical"],
                       "same_bar": ["technical", "regime"]}
    assert input_digest(content)  # băm được (không có kiểu lạ)


@pytest.fixture(params=["memory", "sqlite"])
def stores(request, tmp_path):
    if request.param == "memory":
        return InMemorySnapshotStore(), InMemoryQualityReportStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'q.db'}")
    repo.create_all()
    return SqlSnapshotStore(repo.engine), SqlQualityReportStore(repo.engine)


def test_report_store_append_only_idempotent(stores, t0):      # DQG-03
    snaps, reports = stores
    snap, r1 = gate(t0, skip=("news",))
    snaps.append(SnapshotRecord.of(snap))
    assert reports.append(r1) is True and reports.append(r1) is False
    r2 = evaluate(snap, POLICY_V1, snap.expires_at)
    assert reports.append(r2) is True
    assert reports.get(r1.report_id) == r1
    assert reports.for_snapshot(snap.snapshot_id) == [r1, r2]
    assert reports.get("qr:none") is None and reports.for_snapshot("snap:none") == []


def test_sql_report_requires_stored_snapshot(tmp_path, t0):
    from sqlalchemy.exc import IntegrityError
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'fk.db'}")
    repo.create_all()
    _, r = gate(t0)
    with pytest.raises(IntegrityError):              # không nuốt lỗi khóa ngoại thành "trùng"
        SqlQualityReportStore(repo.engine).append(r)


def test_sql_snapshot_check_violation_not_swallowed(tmp_path, t0):
    from dataclasses import replace

    from sqlalchemy.exc import IntegrityError
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'ck.db'}")
    repo.create_all()
    snap, _ = gate(t0)
    bad = replace(SnapshotRecord.of(snap), expires_at=snap.available_at - minutes(1))
    with pytest.raises(IntegrityError):
        SqlSnapshotStore(repo.engine).append(bad)


def test_migration_is_append_only():
    from pathlib import Path
    src = (Path(__file__).parents[1] / "migrations" / "versions" / "0019_quality_reports.py"
           ).read_text(encoding="utf-8")
    assert "quality_reports" in src and "forbid_mutation" in src


def test_latest_report_for_scope(stores, t0):                     # GĐ4 bước 6 (API)
    snaps, reports = stores
    s1, r1 = gate(t0)
    snaps.append(SnapshotRecord.of(s1))
    reports.append(r1)
    r2 = evaluate(s1, POLICY_V1, s1.expires_at)                    # REJECTED, muộn hơn
    reports.append(r2)
    key = FEED.key
    assert reports.latest_for_scope(key, t0) == r1
    assert reports.latest_for_scope(key, s1.expires_at) == r2
    assert reports.latest_for_scope(key, t0 - minutes(1)) is None   # chưa đánh giá
    assert reports.latest_for_scope("MT5:khac:XAUUSD:M15", s1.expires_at) is None
