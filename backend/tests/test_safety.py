import pytest

from gold_trading.common.enums import SafetyState
from gold_trading.safety.supervisor import SafetySupervisor, SafetyTransitionError

KW = {"trigger_source": "test", "actor": "tester"}


def test_starts_paused_and_blocks_orders():
    s = SafetySupervisor("p0")
    assert s.state is SafetyState.PAUSED
    assert not s.allows_new_orders()


def test_resume_then_pause_records_events():
    s = SafetySupervisor("p0")
    s.resume("STARTUP_OK", **KW)
    assert s.allows_new_orders()
    s.pause("NEWS_SHOCK", **KW)
    assert [t.to_state for t in s.history] == [SafetyState.ACTIVE, SafetyState.PAUSED]
    assert s.history[-1].reason_code == "NEWS_SHOCK"


def test_halt_requires_operator_to_exit():
    s = SafetySupervisor("p0", initial_state=SafetyState.ACTIVE)
    s.halt("EQUITY_BREACH", **KW)
    with pytest.raises(SafetyTransitionError):
        s.resume("AUTO", **KW)
    assert s.pause("SPREAD", **KW) is None  # không hạ HALTED xuống PAUSED
    assert s.state is SafetyState.HALTED
    s.resume("OPERATOR_REVIEWED", operator_approved=True, **KW)
    assert s.state is SafetyState.ACTIVE


def test_repeat_command_is_idempotent():
    s = SafetySupervisor("p0")
    s.halt("KILL", **KW)
    assert s.halt("KILL", **KW) is None
    assert len(s.history) == 1
