import pytest

from gold_trading.ingestion.point_in_time import DuplicateRecordError, PointInTimeStore
from tests.conftest import minutes
from tests.factories import record


def test_late_data_invisible_before_ingested(t0):
    store = PointInTimeStore()
    store.append(record("r1", t0, t0 + minutes(5)))  # đến muộn 5 phút
    assert store.as_of(t0 + minutes(1)) == []
    assert len(store.as_of(t0 + minutes(5))) == 1


def test_revision_does_not_rewrite_past(t0):
    store = PointInTimeStore()
    v0 = record("cpi-v0", t0, t0, kind="macro", payload={"logical_key": "cpi", "value": 3.1})
    v1 = record(
        "cpi-v1",
        t0,
        t0 + minutes(60),
        kind="macro",
        revision=1,
        payload={"logical_key": "cpi", "value": 3.2},
    )
    store.extend([v0, v1])
    assert store.as_of(t0 + minutes(10))[0].payload["value"] == 3.1
    assert store.as_of(t0 + minutes(61))[0].payload["value"] == 3.2


def test_append_is_idempotent(t0):
    store = PointInTimeStore()
    r = record("r1", t0, t0)
    assert store.append(r) is True
    assert store.append(r) is False
    with pytest.raises(DuplicateRecordError):
        store.append(record("r1", t0, t0, raw_ref="other"))
