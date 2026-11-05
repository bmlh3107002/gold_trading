from datetime import datetime

import pytest
from pydantic import ValidationError

from gold_trading.common.enums import Side
from tests.conftest import minutes
from tests.factories import intent, market_view, record


def test_naive_datetime_rejected():
    with pytest.raises(ValidationError):
        record("r1", datetime(2026, 1, 1), datetime(2026, 1, 1))


def test_ingested_before_event_rejected(t0):
    with pytest.raises(ValidationError):
        record("r1", t0, t0 - minutes(1))


def test_buy_stop_loss_must_be_below_entry(t0):
    with pytest.raises(ValidationError):
        intent(t0, stop_loss=2410.0)


def test_sell_intent_valid(t0):
    i = intent(t0, side=Side.SELL, stop_loss=2410.0, take_profit=2380.0)
    assert i.stop_distance == 10.0


def test_market_view_probabilities_bounded(t0):
    with pytest.raises(ValidationError):
        market_view(t0, p_up=0.7, p_down=0.5)


def test_contracts_are_immutable(t0):
    mv = market_view(t0)
    with pytest.raises(ValidationError):
        mv.confidence = 0.1
