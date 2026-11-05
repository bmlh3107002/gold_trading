import pytest

from gold_trading.common.enums import TradingMode
from gold_trading.modes.manager import LIVE_CHECKLIST, ModeChangeError, ModeManager

FULL = {k: True for k in LIVE_CHECKLIST}


def test_cannot_start_in_live():
    with pytest.raises(ModeChangeError):
        ModeManager(TradingMode.LIVE)


def test_live_locked_by_default():
    m = ModeManager()
    with pytest.raises(ModeChangeError, match="khóa"):
        m.set_mode(TradingMode.LIVE, actor="a", approver="b", checklist=FULL)


def test_live_needs_second_approver_and_checklist():
    m = ModeManager(live_unlocked=True)
    with pytest.raises(ModeChangeError):
        m.set_mode(TradingMode.LIVE, actor="a", approver="a", checklist=FULL)
    with pytest.raises(ModeChangeError, match="Checklist"):
        m.set_mode(TradingMode.LIVE, actor="a", approver="b", checklist={})
    m.set_mode(TradingMode.LIVE, actor="a", approver="b", checklist=FULL)
    assert m.mode is TradingMode.LIVE


def test_non_live_modes_switch_freely():
    m = ModeManager()
    m.set_mode(TradingMode.SHADOW, actor="a")
    assert m.mode is TradingMode.SHADOW
