import pytest

from gold_trading.common.enums import OrderState as S
from gold_trading.execution.order_fsm import InvalidOrderTransition, transition


def test_happy_path():
    s = S.REQUESTED
    for nxt in (S.VALIDATED, S.SUBMITTED, S.ACKNOWLEDGED, S.PARTIALLY_FILLED, S.FILLED):
        s = transition(s, nxt)
    assert s is S.FILLED


def test_unknown_cannot_be_resubmitted():
    with pytest.raises(InvalidOrderTransition):
        transition(S.UNKNOWN, S.SUBMITTED)


def test_terminal_is_final():
    with pytest.raises(InvalidOrderTransition):
        transition(S.FILLED, S.CANCELLED)
