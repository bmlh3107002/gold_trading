"""GĐ4 bước 2 — Snapshot Builder theo nguồn giá + manifest (SNP-01, SNP-02; 4-C06).

Thiết kế 33 mục 3. Kho: bộ nhớ + SQLite (Postgres / TimescaleDB: soát riêng + CI docker).
"""

from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from gold_trading.analysts.framework import GLOBAL_SCOPE, Scope, output_id
from gold_trading.common.enums import SourceStatus
from gold_trading.contracts import AnalystOutput
from gold_trading.intelligence import snapshot_builder as SB
from gold_trading.intelligence.snapshot_builder import (
    SnapshotRebuildError,
    SnapshotRecord,
    build_snapshot,
    rebuild,
    snapshot_at,
)
from gold_trading.storage.analyst_outputs import InMemoryAnalystOutputStore, SqlAnalystOutputStore
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.snapshots import InMemorySnapshotStore, SqlSnapshotStore
from tests.conftest import minutes

FEED_A = Scope("XAUUSD", "M15", "MT5", "feed-a")
FEED_B = Scope("XAUUSD", "M15", "MT5", "feed-b")
SAMPLE = Scope("XAUUSD", "M15", "SAMPLE", "")
TTL = {"technical": 17, "regime": 17, "macro": 17, "event": 15, "positioning": 60 * 24,
       "news": 30}


def out(aid: str, scope: Scope, as_of, *, ttl: float | None = None, tag: str = "x",
        **kw) -> AnalystOutput:
    data = dict(
        output_id=output_id(aid, "1", scope, as_of, f"{tag:0<16}"),
        analyst_id=aid, as_of=as_of,
        expires_at=as_of + minutes(ttl if ttl is not None else TTL[aid]),
        confidence=0.9, source_status=SourceStatus.HEALTHY, version="1", correlation_id="c",
    )
    return AnalystOutput(**(data | kw))


def full_set(t, price=FEED_A, **ttl):
    return {a: out(a, SB.scope_for(a, price), t, ttl=ttl.get(a)) for a in SB.ANALYSTS}


@pytest.fixture(params=["memory", "sqlite"])
def stores(request, tmp_path):
    if request.param == "memory":
        return InMemoryAnalystOutputStore(), InMemorySnapshotStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 's.db'}")
    repo.create_all()
    return SqlAnalystOutputStore(repo.engine), SqlSnapshotStore(repo.engine)


def put(store, o: AnalystOutput, price: Scope, computed_at):
    store.append_scoped(o, SB.scope_for(o.analyst_id, price), computed_at=computed_at)


# ---------- build_snapshot (thuần) ----------

def test_full_snapshot_uses_all_six_and_required_expiry(t0):
    latest = full_set(t0 - minutes(1))
    s = build_snapshot(latest, FEED_A, t0)
    assert set(s.input_manifest) == set(SB.ANALYSTS)
    assert s.excluded_inputs == {} and s.quality_flags == frozenset()
    assert s.available_at == t0 and s.event_time == t0 - minutes(1)
    # Hạn = sớm nhất trong output BẮT BUỘC (event 15 phút), không tính tùy chọn.
    assert s.expires_at == t0 - minutes(1) + minutes(15)
    assert (s.source, s.feed_id, s.builder_version) == ("MT5", "feed-a", SB.BUILDER_VERSION)


def test_optional_short_expiry_does_not_shorten_snapshot(t0):
    latest = full_set(t0 - minutes(1), news=2)
    s = build_snapshot(latest, FEED_A, t0)
    assert s.expires_at == t0 - minutes(1) + minutes(15)


def test_expired_latest_is_excluded_not_replaced(t0):
    latest = full_set(t0 - minutes(1))
    latest["technical"] = out("technical", FEED_A, t0 - minutes(30))  # hết hạn lúc t0−13
    s = build_snapshot(latest, FEED_A, t0)
    assert "technical" not in s.input_manifest
    assert s.excluded_inputs == {"technical": latest["technical"].output_id}
    assert "EXPIRED_EXCLUDED:technical" in s.quality_flags
    # Không còn bắt buộc nào ngắn hơn → hạn theo regime / event còn lại.
    assert s.expires_at == t0 - minutes(1) + minutes(15)


def test_no_required_input_expires_immediately(t0):
    latest = {a: o for a, o in full_set(t0 - minutes(1)).items() if a not in SB.REQUIRED}
    s = build_snapshot(latest, FEED_A, t0)
    assert s.expires_at == s.available_at == t0


def test_empty_snapshot(t0):
    s = build_snapshot({}, FEED_A, t0)
    assert s.analyst_outputs == () and s.event_time == t0 and s.expires_at == t0


def test_expiry_boundary_is_exclusive(t0):
    o = out("technical", FEED_A, t0 - minutes(17))   # expires_at == t0 → đã hết hạn tại t0
    s = build_snapshot({"technical": o}, FEED_A, t0)
    assert s.excluded_inputs == {"technical": o.output_id}


def test_future_as_of_raises(t0):
    o = out("technical", FEED_A, t0 + minutes(1))
    with pytest.raises(ValueError, match="nhìn trước tương lai"):
        build_snapshot({"technical": o}, FEED_A, t0)


def test_output_of_other_feed_rejected(t0):
    with pytest.raises(ValueError, match="phạm vi"):
        build_snapshot({"technical": out("technical", FEED_B, t0)}, FEED_A, t0)


def test_global_analyst_must_be_global(t0):
    with pytest.raises(ValueError, match="phạm vi"):
        build_snapshot({"event": out("event", FEED_A, t0)}, FEED_A, t0)
    with pytest.raises(ValueError, match="phạm vi"):
        build_snapshot({"technical": out("technical", GLOBAL_SCOPE, t0)}, FEED_A, t0)


def test_mislabelled_analyst_rejected(t0):
    with pytest.raises(ValueError, match="không phải của"):
        build_snapshot({"regime": out("technical", FEED_A, t0)}, FEED_A, t0)


def test_unknown_analyst_rejected(t0):
    o = out("technical", FEED_A, t0).model_copy(update={"analyst_id": "rumor"})
    with pytest.raises(ValueError, match="không thuộc snapshot"):
        build_snapshot({"rumor": o}, FEED_A, t0)


def test_global_price_scope_rejected(t0):
    with pytest.raises(ValueError, match="nguồn giá cụ thể"):
        build_snapshot({}, GLOBAL_SCOPE, t0)


def test_sample_price_source_flags_sample(t0):
    s = build_snapshot(full_set(t0, price=SAMPLE), SAMPLE, t0)
    assert "SAMPLE_DATA" in s.quality_flags


def test_sample_flag_from_any_used_input(t0):
    latest = full_set(t0)
    latest["news"] = out("news", GLOBAL_SCOPE, t0, quality_flags=frozenset({"SAMPLE_DATA"}))
    assert "SAMPLE_DATA" in build_snapshot(latest, FEED_A, t0).quality_flags


def test_sample_flag_ignores_excluded_input(t0):
    latest = full_set(t0)
    latest["news"] = out("news", GLOBAL_SCOPE, t0 - minutes(40),
                         quality_flags=frozenset({"SAMPLE_DATA"}))
    s = build_snapshot(latest, FEED_A, t0)
    assert "news" in s.excluded_inputs and "SAMPLE_DATA" not in s.quality_flags


def test_snapshot_id_deterministic_and_sensitive(t0):
    latest = full_set(t0 - minutes(1))
    a = build_snapshot(latest, FEED_A, t0)
    b = build_snapshot(latest, FEED_A, t0 + minutes(2))     # cùng đầu vào, lúc khác
    assert a.snapshot_id == b.snapshot_id and a.snapshot_id.startswith("snap:MT5:feed-a:")
    c = build_snapshot(full_set(t0 - minutes(1), price=FEED_B), FEED_B, t0)
    assert c.snapshot_id != a.snapshot_id
    latest2 = dict(latest, news=out("news", GLOBAL_SCOPE, t0 - minutes(1), tag="y"))
    assert build_snapshot(latest2, FEED_A, t0).snapshot_id != a.snapshot_id
    # Cùng manifest nhưng khác danh sách bị loại → khác id (audit không mất).
    gone = {k: v for k, v in latest.items() if k != "technical"}
    expired = dict(gone, technical=out("technical", FEED_A, t0 - minutes(40)))
    assert build_snapshot(gone, FEED_A, t0).snapshot_id != \
        build_snapshot(expired, FEED_A, t0).snapshot_id


def test_contract_rejects_inconsistent_manifest(t0):
    s = build_snapshot(full_set(t0), FEED_A, t0)
    data = s.model_dump()
    with pytest.raises(ValidationError, match="input_manifest"):
        type(s).model_validate(data | {"input_manifest": {"technical": "x"}})
    with pytest.raises(ValidationError, match="vừa được dùng"):
        type(s).model_validate(data | {"excluded_inputs": {"technical": "y"}})
    with pytest.raises(ValidationError, match="expires_at"):
        type(s).model_validate(data | {"expires_at": t0 - minutes(1)})
    with pytest.raises(ValidationError, match="event_time"):
        type(s).model_validate(data | {"event_time": t0 + minutes(1)})


# ---------- Kho + point-in-time + tái dựng ----------

def test_store_point_in_time_and_feed_isolation(stores, t0):
    outs, _ = stores
    for o in full_set(t0 - minutes(5)).values():
        put(outs, o, FEED_A, t0 - minutes(4))
    put(outs, out("technical", FEED_B, t0 - minutes(2)), FEED_B, t0 - minutes(1))
    s = snapshot_at(outs, FEED_A, t0)
    assert set(s.input_manifest) == set(SB.ANALYSTS)
    assert ":feed-b:" not in s.input_manifest["technical"]


def test_future_outputs_do_not_change_past_snapshot(stores, t0):
    outs, _ = stores
    for o in full_set(t0 - minutes(5)).values():
        put(outs, o, FEED_A, t0 - minutes(4))
    before = snapshot_at(outs, FEED_A, t0)
    # Kết quả mới hơn, ghi SAU t0 (kể cả as_of trước t0 nhưng ghi muộn) → không ảnh hưởng t0.
    for o in full_set(t0 + minutes(1), **{a: 20 for a in SB.ANALYSTS}).values():
        put(outs, o, FEED_A, t0 + minutes(2))
    late = out("regime", FEED_A, t0 - minutes(1), tag="late")
    put(outs, late, FEED_A, t0 + minutes(3))
    again = snapshot_at(outs, FEED_A, t0)
    assert again == before
    assert snapshot_at(outs, FEED_A, t0 + minutes(5)).snapshot_id != before.snapshot_id


def test_append_idempotent_and_rebuild(stores, t0):
    outs, snaps = stores
    latest = full_set(t0 - minutes(5))
    latest["news"] = out("news", GLOBAL_SCOPE, t0 - minutes(50))     # hết hạn → bị loại
    for o in latest.values():
        put(outs, o, FEED_A, t0 - minutes(4) if o.analyst_id != "news" else t0 - minutes(49))
    s = snapshot_at(outs, FEED_A, t0)
    rec = SnapshotRecord.of(s)
    assert snaps.append(rec) is True
    assert snaps.append(rec) is False                                  # ghi lại bị bỏ qua
    stored = snaps.get(s.snapshot_id)
    assert stored == rec
    assert rebuild(stored, outs) == s
    assert snaps.get("snap:none") is None


def test_rebuild_missing_output_raises(t0):
    outs = InMemoryAnalystOutputStore()
    s = build_snapshot(full_set(t0 - minutes(1)), FEED_A, t0)       # chưa ghi vào kho
    with pytest.raises(SnapshotRebuildError, match="không còn output"):
        rebuild(SnapshotRecord.of(s), outs)


def test_rebuild_output_written_after_available_at_raises(t0):
    outs = InMemoryAnalystOutputStore()
    latest = full_set(t0 - minutes(1))
    for o in latest.values():
        put(outs, o, FEED_A, t0 + minutes(1))                         # ghi sau t0
    s = build_snapshot(latest, FEED_A, t0)
    with pytest.raises(SnapshotRebuildError, match="ghi sau available_at"):
        rebuild(SnapshotRecord.of(s), outs)


def test_rebuild_detects_tampered_record(t0):
    outs = InMemoryAnalystOutputStore()
    latest = full_set(t0 - minutes(1))
    for o in latest.values():
        put(outs, o, FEED_A, t0 - minutes(1))
    rec = SnapshotRecord.of(build_snapshot(latest, FEED_A, t0))
    from dataclasses import replace
    for bad in (replace(rec, quality_flags=frozenset({"X"})),
                replace(rec, expires_at=rec.expires_at + timedelta(minutes=5)),
                replace(rec, snapshot_id="snap:forged")):
        with pytest.raises(SnapshotRebuildError, match="lệch nội dung"):
            rebuild(bad, outs)
    with pytest.raises(SnapshotRebuildError, match="phiên bản"):
        rebuild(replace(rec, builder_version="snapshot-0"), outs)


def test_get_scoped_respects_scope(stores, t0):
    outs, _ = stores
    o = out("technical", FEED_A, t0)
    put(outs, o, FEED_A, t0)
    assert outs.get_scoped(o.output_id, FEED_A).output == o
    assert outs.get_scoped(o.output_id, FEED_B) is None
    assert outs.get_scoped("nope", FEED_A) is None


def test_migration_is_append_only():
    src = (Path(__file__).parents[1] / "migrations" / "versions" / "0018_market_snapshots.py"
           ).read_text(encoding="utf-8")
    assert "market_snapshots" in src and "forbid_mutation" in src
    assert "create_hypertable" not in src
