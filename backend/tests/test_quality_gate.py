from gold_trading.common.enums import QualityVerdict, SourceStatus
from gold_trading.intelligence.quality_gate import QualityPolicy, evaluate
from gold_trading.intelligence.snapshot_builder import build_snapshot
from tests.conftest import minutes
from tests.factories import analyst

POLICY = QualityPolicy(
    version="q0", required=frozenset({"technical", "event"}), optional_penalty={"news": 0.8}
)


def test_snapshot_picks_latest_valid_output(t0):
    old = analyst("technical", t0 - minutes(30))  # đã hết hạn
    new = analyst("technical", t0 - minutes(1))
    snap = build_snapshot([old, new], t0)
    assert snap.input_manifest == {"technical": new.output_id}


def test_missing_required_rejects(t0):
    snap = build_snapshot([analyst("technical", t0)], t0)
    report = evaluate(snap, POLICY, t0)
    assert report.verdict is QualityVerdict.REJECTED
    assert "REQUIRED_MISSING:event" in report.reasons


def test_stale_required_rejects(t0):
    snap = build_snapshot(
        [analyst("technical", t0, source_status=SourceStatus.STALE), analyst("event", t0)], t0
    )
    assert evaluate(snap, POLICY, t0).verdict is QualityVerdict.REJECTED


def test_missing_optional_degrades_confidence(t0):
    snap = build_snapshot([analyst("technical", t0), analyst("event", t0)], t0)
    report = evaluate(snap, POLICY, t0)
    assert report.verdict is QualityVerdict.DEGRADED
    assert report.confidence_multiplier == 0.8


def test_all_present_accepted(t0):
    outs = [analyst(a, t0) for a in ("technical", "event", "news")]
    report = evaluate(build_snapshot(outs, t0), POLICY, t0)
    assert report.verdict is QualityVerdict.ACCEPTED
    assert report.confidence_multiplier == 1.0
