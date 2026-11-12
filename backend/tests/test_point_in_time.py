"""ING-13 + DB-08: store point-in-time cho nguồn không phải nến (bộ nhớ + SQL cùng quy tắc)."""

import math
import random
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from gold_trading.ingestion.point_in_time import AppendOutcome, PointInTimeStore, fingerprint
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.repository import SqlRepository
from tests.conftest import minutes
from tests.factories import record

INS, DUP, CON, INV = (AppendOutcome.INSERTED, AppendOutcome.DUPLICATE, AppendOutcome.CONFLICT,
                      AppendOutcome.INVALID)


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return PointInTimeStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'x.db'}")
    repo.create_all()
    return SqlExternalRecordStore(repo.engine)


def quarantine(store):
    return store.quarantine if isinstance(store, PointInTimeStore) else store.quarantined()


def macro(rid, t0, ing, **kw):
    kw.setdefault("kind", "macro")
    kw.setdefault("source", "fred")
    return record(rid, t0, ing, **kw)


def test_late_data_invisible_before_ingested(store, t0):
    assert store.append(macro("r1", t0, t0 + minutes(5))).outcome is INS  # đến muộn 5 phút
    assert store.as_of(t0 + minutes(1)) == []
    assert len(store.as_of(t0 + minutes(5))) == 1


def test_available_after_ingest_invisible_until_published(store, t0):
    """1E-C01 (nền): số của ngày D, nguồn ghi công bố D+1 — dù đã nạp sớm cũng chưa được dùng."""
    pub = t0 + timedelta(days=1)
    r = macro("dgs10-d", t0, t0 + minutes(1), available_at=pub, logical_key="DGS10:D")
    assert r.known_at == pub
    store.append(r)
    assert store.as_of(pub - timedelta(seconds=1)) == []
    assert [x.record_id for x in store.as_of(pub)] == ["dgs10-d"]


def test_available_before_ingest_uses_ingest_time(store, t0):
    """Nguồn công bố từ trước nhưng hệ thống nạp sau → chỉ thấy từ lúc nạp (không lùi quá khứ)."""
    store.append(macro("old", t0, t0 + minutes(30), available_at=t0 + minutes(1)))
    assert store.as_of(t0 + minutes(29)) == []
    assert len(store.as_of(t0 + minutes(30))) == 1


def test_revision_does_not_rewrite_past(store, t0):
    v0 = macro("cpi-v0", t0, t0, logical_key="cpi", payload={"value": 3.1})
    v1 = macro("cpi-v1", t0, t0 + minutes(60), logical_key="cpi", revision=1,
               payload={"value": 3.2})
    assert store.extend([v0, v1]).inserted == 2
    assert store.as_of(t0 + minutes(10))[0].payload["value"] == 3.1
    assert store.as_of(t0 + minutes(61))[0].payload["value"] == 3.2
    assert [r.revision for r in store.history("fred", "cpi", t0 + minutes(61))] == [0, 1]
    assert [r.revision for r in store.history("fred", "cpi", t0 + minutes(10))] == [0]


def test_revision_arriving_out_of_order(store, t0):
    """Revision 2 đến trước revision 1: tại mọi thời điểm lấy revision lớn nhất đã biết."""
    store.append(macro("v0", t0, t0, logical_key="k", payload={"v": 0}))
    store.append(macro("v2", t0, t0 + minutes(10), logical_key="k", revision=2, payload={"v": 2}))
    store.append(macro("v1", t0, t0 + minutes(20), logical_key="k", revision=1, payload={"v": 1}))
    assert store.as_of(t0 + minutes(5))[0].payload["v"] == 0
    assert store.as_of(t0 + minutes(15))[0].payload["v"] == 2
    assert store.as_of(t0 + minutes(25))[0].payload["v"] == 2


def test_append_is_idempotent_and_keeps_first_ingest(store, t0):
    r = macro("r1", t0, t0, payload={"v": 1})
    assert store.append(r).outcome is INS
    assert store.append(r).outcome is DUP
    # nạp lại cùng số liệu lúc khác (nguồn trả lại): vẫn trùng, giữ ingested_at đầu tiên
    again = macro("r1", t0, t0 + minutes(90), payload={"v": 1}, raw_ref="other",
                  quality_flags=frozenset({"X"}))
    assert store.append(again).outcome is DUP
    assert store.as_of(t0)[0].ingested_at == t0
    assert quarantine(store) == []


def test_same_identity_other_content_is_conflict_not_overwrite(store, t0):
    store.append(macro("r1", t0, t0, logical_key="k", payload={"v": 1}))
    res = store.append(macro("r1", t0, t0 + minutes(5), logical_key="k", payload={"v": 9}))
    assert (res.outcome, res.reason) == (CON, "REVISION_CONFLICT")
    assert store.as_of(t0 + minutes(10))[0].payload["v"] == 1
    q = quarantine(store)
    assert [e.reason for e in q] == ["REVISION_CONFLICT"]
    assert q[0].raw["record"]["payload"] == {"v": 9}


def test_record_id_reused_for_other_fact_is_conflict(store, t0):
    store.append(macro("r1", t0, t0, logical_key="a"))
    assert store.append(macro("r1", t0, t0, logical_key="b")).reason == "RECORD_ID_CONFLICT"
    assert [r.logical_key for r in store.as_of(t0)] == ["a"]


def test_kind_change_between_revisions_is_conflict(store, t0):
    store.append(macro("a0", t0, t0, logical_key="a"))
    res = store.append(macro("a1", t0, t0, logical_key="a", revision=1, kind="news"))
    assert (res.outcome, res.reason) == (CON, "KIND_CHANGED")
    assert store.as_of(t0, kind="news") == []


@pytest.mark.parametrize("kw,reason", [
    (dict(kind="price"), "KIND_INVALID"),
    (dict(payload={"value": math.nan}), "PAYLOAD_NON_FINITE"),
    (dict(payload={"v": [1.0, math.inf]}), "PAYLOAD_NON_FINITE"),
    (dict(payload={"v": object()}), "PAYLOAD_NOT_JSON"),
    (dict(payload={"body": "x" * (256 * 1024 + 1)}), "PAYLOAD_TOO_LARGE"),
    (dict(logical_key="k" * 257), "FIELD_TOO_LONG"),
    (dict(source="s" * 65), "SOURCE_INVALID"),
    (dict(source=""), "SOURCE_INVALID"),
])
def test_invalid_records_quarantined(store, t0, kw, reason):
    res = store.append(macro("bad", t0, t0, **kw))
    assert (res.outcome, res.reason) == (INV, reason)
    assert store.as_of(t0 + timedelta(days=1)) == []
    q = quarantine(store)
    assert len(q) == 1 and q[0].reason == reason


def test_invalid_raw_quarantined(store, t0):
    assert store.append(macro("r", t0, t0), raw={"x": -math.inf}).reason == "RAW_NON_FINITE"
    assert store.append(macro("r", t0, t0), raw={"x": {1, 2}}).reason == "RAW_NOT_JSON"
    assert store.append(macro("r", t0, t0), raw="y" * (300 * 1024)).reason == "RAW_TOO_LARGE"
    assert store.as_of(t0) == []
    assert len(quarantine(store)) == 3


def test_raw_is_stored_with_record(t0, tmp_path):
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'r.db'}")
    repo.create_all()
    s = SqlExternalRecordStore(repo.engine)
    s.append(macro("r", t0, t0), raw={"observations": [{"date": "2026-01-05", "value": "."}]})
    with repo.engine.connect() as conn:
        from gold_trading.storage.schema import external_records
        raw = conn.execute(external_records.select()).mappings().one()["raw"]
    assert raw == {"observations": [{"date": "2026-01-05", "value": "."}]}


def test_calendar_may_be_known_before_event(store, t0):
    """Lịch công bố biết trước giờ sự kiện; các loại khác thì không."""
    rel = t0 + timedelta(days=7)
    store.append(record("cpi-sched", rel, t0, kind="calendar", source="bls"))
    assert [r.event_time for r in store.as_of(t0, kind="calendar")] == [rel]
    with pytest.raises(ValidationError):
        macro("future", rel, t0)
    with pytest.raises(ValidationError):
        macro("future", t0, t0 + minutes(1), available_at=t0 - minutes(1))


def test_naive_datetime_rejected_and_timezones_normalised(store):
    with pytest.raises(ValidationError):
        macro("n", datetime(2026, 3, 8, 12), datetime(2026, 3, 8, 13))
    ny = ZoneInfo("America/New_York")
    # 8:30 ET ngay sau khi Mỹ đổi giờ mùa hè (08/03/2026) = 12:30 UTC
    ev = datetime(2026, 3, 9, 8, 30, tzinfo=ny)
    store.append(record("cpi", ev, ev, kind="calendar", source="bls"))
    got = store.as_of(datetime(2026, 3, 9, 12, 30, tzinfo=UTC))
    assert got[0].event_time == datetime(2026, 3, 9, 12, 30, tzinfo=UTC)
    assert got[0].event_time.tzinfo == UTC
    assert store.as_of(datetime(2026, 3, 9, 12, 29, tzinfo=UTC)) == []


def test_filters(store, t0):
    store.append(macro("a", t0, t0, source="fred"))
    store.append(macro("b", t0 + minutes(10), t0 + minutes(10), source="fred"))
    store.append(record("c", t0, t0, kind="news", source="fed-rss"))
    later = t0 + minutes(30)
    assert {r.record_id for r in store.as_of(later)} == {"a", "b", "c"}
    assert {r.record_id for r in store.as_of(later, source="fred")} == {"a", "b"}
    assert {r.record_id for r in store.as_of(later, kind="news")} == {"c"}
    assert {r.record_id for r in store.as_of(later, logical_key="b")} == {"b"}
    win = store.as_of(later, event_from=t0 + minutes(5), event_to=t0 + minutes(10))
    assert win == []
    win = store.as_of(later, event_from=t0 + minutes(5), event_to=t0 + minutes(11))
    assert [r.record_id for r in win] == ["b"]


def test_roundtrip_preserves_record_and_fingerprint(store, t0):
    r = macro("x", t0, t0 + minutes(1), available_at=t0 + minutes(2), logical_key="K",
              revision=3, payload={"value": 4.25, "unit": "%", "nested": {"a": [1, None]}},
              quality_flags=frozenset({"B", "A"}))
    store.append(r)
    got = store.as_of(t0 + minutes(2))[0]
    assert got == r
    assert fingerprint(got) == fingerprint(r)


def test_replay_any_order_same_result(t0, tmp_path):
    """ING-34 (nền): nạp cùng dữ liệu theo thứ tự khác, nạp hai lần → cùng kết quả ở mọi as_of."""
    recs = []
    for k in range(5):
        for rev in range(3):
            recs.append(macro(f"k{k}r{rev}", t0, t0 + minutes(10 * rev + k), logical_key=f"k{k}",
                              revision=rev, payload={"v": k * 10 + rev}))
    stores = []
    for i, seed in enumerate((1, 2)):
        shuffled = recs[:]
        random.Random(seed).shuffle(shuffled)
        repo = SqlRepository.from_url(f"sqlite:///{tmp_path / f'{i}.db'}")
        repo.create_all()
        s = SqlExternalRecordStore(repo.engine)
        s.extend(shuffled)
        assert s.extend(shuffled).duplicate == len(recs)
        stores.append(s)
    mem = PointInTimeStore()
    mem.extend(reversed(recs))
    stores.append(mem)
    for m in range(0, 40, 3):
        views = [s.as_of(t0 + minutes(m)) for s in stores]
        assert views[0] == views[1] == views[2]


@pytest.mark.parametrize("kw,raw,reason", [
    (dict(payload={"t": "a\x00b"}), None, "PAYLOAD_NUL_CHAR"),
    ({}, {"t": "a\x00b"}, "RAW_NUL_CHAR"),
    (dict(logical_key="k\x00"), None, "FIELD_NUL_CHAR"),
    (dict(source="fr\x00ed"), None, "FIELD_NUL_CHAR"),
])
def test_nul_char_quarantined_not_crash(store, t0, kw, raw, reason):
    """Postgres không lưu được NUL: phải vào cách ly (cách ly cũng không được hỏng)."""
    res = store.append(macro("n", t0, t0, **kw), raw=raw)
    assert (res.outcome, res.reason) == (INV, reason)
    q = quarantine(store)
    assert len(q) == 1 and "\x00" not in q[0].source
