from gold_trading.analysts.framework import Scope
from gold_trading.common.enums import QualityVerdict, SourceStatus
from gold_trading.intelligence import snapshot_builder as SB
from gold_trading.intelligence.quality_gate import QualityPolicy, evaluate
from gold_trading.intelligence.snapshot_builder import build_snapshot
from tests.conftest import minutes
from tests.test_snapshot_builder import out

FEED = Scope("XAUUSD", "M15", "MT5", "f1")
POLICY = QualityPolicy(
    version="q0", required=frozenset({"technical", "event"}), optional_penalty={"news": 0.8}
)


def snap(t0, *aids, **kw):
    return build_snapshot({a: out(a, SB.scope_for(a, FEED), t0, **kw.get(a, {})) for a in aids},
                          FEED, t0)


def test_missing_required_rejects(t0):
    report = evaluate(snap(t0, "technical"), POLICY, t0)
    assert report.verdict is QualityVerdict.REJECTED
    assert "REQUIRED_MISSING:event" in report.reasons


def test_stale_required_rejects(t0):
    s = snap(t0, "technical", "event", technical={"source_status": SourceStatus.STALE})
    assert evaluate(s, POLICY, t0).verdict is QualityVerdict.REJECTED


def test_missing_optional_degrades_confidence(t0):
    report = evaluate(snap(t0, "technical", "event"), POLICY, t0)
    assert report.verdict is QualityVerdict.DEGRADED
    assert report.confidence_multiplier == 0.8


def test_all_present_accepted(t0):
    report = evaluate(snap(t0, "technical", "event", "news"), POLICY, t0)
    assert report.verdict is QualityVerdict.ACCEPTED
    assert report.confidence_multiplier == 1.0


def test_snapshot_expired_later_rejects(t0):
    report = evaluate(snap(t0, "technical", "event", "news"), POLICY, t0 + minutes(20))
    assert report.verdict is QualityVerdict.REJECTED
