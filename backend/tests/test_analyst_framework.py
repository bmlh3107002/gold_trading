"""GĐ3 bước 1 — khung chung analyst (ANA-01; 3-C01..C07). Thiết kế: docs/thiet-ke/27."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import pytest

from gold_trading.analysts.framework import (
    GLOBAL_SCOPE,
    InputCheck,
    LookAheadError,
    Scope,
    assess,
    build_output,
    input_digest,
    output_id,
)
from gold_trading.common.enums import SourceStatus
from gold_trading.contracts.candle import DataSource
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.analyst_outputs import (
    InMemoryAnalystOutputStore,
    SqlAnalystOutputStore,
)
from gold_trading.storage.repository import SqlRepository

T0 = datetime(2026, 11, 16, 13, 30, tzinfo=UTC)
H = timedelta(hours=1)


# --- Analyst mẫu tối giản dùng khung (đại diện cho analyst toàn cục GĐ3) ---------------------

@dataclass(frozen=True)
class Rec:
    known_at: datetime
    value: float


VERSION = "toy-1.0.0"


def toy(records: list[Rec], as_of: datetime, *, version: str = VERSION, sample=False,
        optional: list[Rec] | None = None, min_history: int = 3):
    """Trung bình các giá trị đã biết tại as_of. Point-in-time: chỉ dùng known_at <= as_of."""
    seen = sorted((r for r in records if r.known_at <= as_of), key=lambda r: r.known_at)
    opt = sorted((r for r in (optional or []) if r.known_at <= as_of), key=lambda r: r.known_at)
    spikes = sum(1 for r in seen if abs(r.value) > 1000)
    checks = [
        InputCheck("main", seen[-1].known_at if seen else None, max_age=6 * H,
                   history=len(seen), min_history=min_history, spikes=spikes, sample=sample),
        InputCheck("extra", opt[-1].known_at if opt else None, max_age=6 * H, required=False),
    ]
    a = assess(checks, as_of)
    vals = [r.value for r in seen if abs(r.value) <= 1000]
    feats = {"mean": sum(vals) / len(vals)} if vals else {}
    return build_output(
        analyst_id="toy", version=version, scope=GLOBAL_SCOPE, as_of=as_of,
        expires_at=as_of + H, correlation_id="c1", assessment=a,
        digest_of={"main": [(r.known_at, r.value) for r in seen],
                   "extra": [(r.known_at, r.value) for r in opt]},
        features=feats, drivers=("TOY",), confidence=0.9)


def good() -> list[Rec]:
    return [Rec(T0 - 3 * H, 1.0), Rec(T0 - 2 * H, 2.0), Rec(T0 - H, 3.0)]


# --- Scope ------------------------------------------------------------------------------------

def test_global_scope_values_cannot_collide_with_real_feed_values():
    assert "*" not in {t.value for t in Timeframe}
    assert "GLOBAL" not in {s.value for s in DataSource}
    assert GLOBAL_SCOPE.is_global and GLOBAL_SCOPE.key == "GLOBAL::*:*"


@pytest.mark.parametrize("args", [
    ("*", "*", "GLOBAL", "f1"),          # toàn cục không có feed
    ("XAUUSD", "*", "GLOBAL", ""),       # toàn cục phải (*, *)
    ("*", "*", "MT5", ""),               # (*, *) chỉ dành cho toàn cục
    ("XAU:USD", "M15", "MT5", ""),       # dấu ':' phá khóa
    ("", "M15", "MT5", ""),
])
def test_scope_rejects_ambiguous(args):
    with pytest.raises(ValueError):
        Scope(*args)


def test_scope_of_feed_accepts_enums():
    s = Scope.of_feed("XAUUSD", Timeframe.M15, DataSource.MT5, "f1")
    assert s.key == "MT5:f1:XAUUSD:M15" and not s.is_global


# --- output_id / digest (3-C07) ----------------------------------------------------------------

def test_digest_is_canonical_and_strict():
    a = input_digest({"b": 1, "a": [1.5, T0]})
    b = input_digest({"a": [1.5, T0.astimezone(timezone(timedelta(hours=7)))], "b": 1})
    assert a == b                                     # thứ tự khóa / múi giờ không đổi băm
    assert a != input_digest({"b": 1, "a": [1.5000001, T0]})
    with pytest.raises(ValueError):
        input_digest({"t": datetime(2026, 1, 1)})      # datetime không múi giờ
    with pytest.raises(TypeError):
        input_digest({"x": {1, 2}})                    # kiểu lạ: không âm thầm str()
    with pytest.raises(ValueError):
        input_digest({"x": float("nan")})


def test_output_id_deterministic_and_versioned():
    o1, o2 = toy(good(), T0), toy(good(), T0)
    assert o1.output_id == o2.output_id
    assert o1.output_id.startswith("toy:toy-1.0.0:GLOBAL::*:*:2026-11-16T13:30:00+00:00:")
    o3 = toy(good(), T0, version="toy-1.1.0")
    assert o3.output_id != o1.output_id               # 3-C07: đổi phiên bản → id mới
    assert output_id("a", "v", GLOBAL_SCOPE, T0, "f" * 64).endswith(":" + "f" * 16)


# --- Kiểm đầu vào 3-C01..C05 -------------------------------------------------------------------

def test_healthy_output_has_features_and_trace():
    o = toy(good(), T0)
    assert o.source_status is SourceStatus.HEALTHY
    assert o.features["mean"] == 2.0 and o.confidence == 0.9
    inp = o.features["input"]
    assert inp["scope"] == "GLOBAL::*:*" and len(inp["input_digest"]) == 64
    main = next(i for i in inp["inputs"] if i["name"] == "main")
    assert main["age_s"] == 3600 and main["history"] == 3
    assert "OPTIONAL_MISSING:extra" in o.quality_flags   # tùy chọn thiếu chỉ gắn cờ


def test_c01_missing_required_input_no_features():
    o = toy([], T0)
    assert o.source_status is SourceStatus.MISSING
    assert o.confidence == 0.0 and set(o.features) == {"input"}
    assert o.drivers == ("MISSING_INPUT:main",)


def test_c02_stale_required_input():
    o = toy([Rec(T0 - 9 * H, 1.0), Rec(T0 - 8 * H, 1.0), Rec(T0 - 7 * H, 1.0)], T0)
    assert o.source_status is SourceStatus.STALE
    assert "STALE_INPUT:main" in o.drivers and set(o.features) == {"input"}


def test_c02_exactly_max_age_is_not_stale():
    o = toy([Rec(T0 - 8 * H, 1.0), Rec(T0 - 7 * H, 1.0), Rec(T0 - 6 * H, 1.0)], T0)
    assert o.source_status is SourceStatus.HEALTHY


def test_c03_insufficient_history():
    o = toy(good()[:2], T0)
    assert o.source_status is SourceStatus.INVALID
    assert o.drivers == ("INSUFFICIENT_HISTORY:main",)


def test_stale_and_short_history_reports_both_worst_status_wins():
    o = toy([Rec(T0 - 7 * H, 1.0)], T0)
    assert o.source_status is SourceStatus.STALE
    assert set(o.drivers) == {"STALE_INPUT:main", "INSUFFICIENT_HISTORY:main"}


def test_c04_spike_flags_and_caps_confidence():
    o = toy(good() + [Rec(T0 - H / 2, 99999.0)], T0)
    assert o.source_status is SourceStatus.HEALTHY
    assert "SPIKE_IN_INPUT:main" in o.quality_flags and o.confidence == 0.5
    assert o.features["mean"] == 2.0                  # analyst tự loại điểm cực đoan


def test_c05_sample_flag():
    assert "SAMPLE_DATA" in toy(good(), T0, sample=True).quality_flags
    assert "SAMPLE_DATA" not in toy(good(), T0).quality_flags


def test_optional_stale_only_flags():
    o = toy(good(), T0, optional=[Rec(T0 - 10 * H, 1.0)])
    assert o.source_status is SourceStatus.HEALTHY and "OPTIONAL_STALE:extra" in o.quality_flags


def test_lookahead_input_raises():
    with pytest.raises(LookAheadError):
        assess([InputCheck("x", T0 + timedelta(seconds=1), max_age=H)], T0)


def test_assess_rejects_duplicate_names_and_naive_times():
    with pytest.raises(ValueError):
        assess([InputCheck("x", T0, max_age=H), InputCheck("x", T0, max_age=H)], T0)
    with pytest.raises(ValueError):
        assess([InputCheck("x", T0, max_age=H)], datetime(2026, 11, 16))
    with pytest.raises(ValueError):
        InputCheck("x", T0, max_age=timedelta(0))


def test_build_output_guards():
    a = assess([InputCheck("x", T0, max_age=H)], T0)
    kw = dict(analyst_id="toy", version="v", scope=GLOBAL_SCOPE, as_of=T0, expires_at=T0 + H,
              correlation_id="c", assessment=a, digest_of={})
    with pytest.raises(ValueError):
        build_output(**kw, features={"input": 1})     # khóa dành riêng
    with pytest.raises(ValueError):
        build_output(**kw, confidence=1.5)
    with pytest.raises(ValueError):
        build_output(**{**kw, "expires_at": T0})      # hết hạn phải sau as_of


# --- 3-C06: thêm dữ liệu tương lai rồi tính lại tại thời điểm cũ → không đổi ------------------

def test_c06_future_data_does_not_change_past_result():
    past = toy(good(), T0)
    later = good() + [Rec(T0 + timedelta(minutes=1), 50.0), Rec(T0 + H, 7.0)]
    again = toy(later, T0)
    assert again == past
    assert toy(later, T0 + H).output_id != past.output_id


# --- Kho: phạm vi toàn cục + theo nguồn, chỉ-thêm, point-in-time --------------------------------

@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryAnalystOutputStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'a.db'}")
    repo.create_all()
    return SqlAnalystOutputStore(repo.engine)


def test_store_global_scope_roundtrip_idempotent(store):
    o = toy(good(), T0)
    assert store.append_scoped(o, GLOBAL_SCOPE, computed_at=T0) is True
    assert store.append_scoped(o, GLOBAL_SCOPE, computed_at=T0 + H) is False   # ghi lại: bỏ qua
    got = store.latest_scoped("toy", GLOBAL_SCOPE)
    assert got.output == o and got.computed_at == T0 and got.scope == GLOBAL_SCOPE


def test_store_version_change_keeps_old(store):
    o1, o2 = toy(good(), T0), toy(good(), T0, version="toy-1.1.0")
    store.append_scoped(o1, GLOBAL_SCOPE, computed_at=T0)
    store.append_scoped(o2, GLOBAL_SCOPE, computed_at=T0 + timedelta(seconds=1))
    ids = {r[5] for r in store.computed_between(T0 - H, T0 + H)}
    assert ids == {o1.output_id, o2.output_id}


def test_store_latest_scoped_point_in_time(store):
    o1, o2 = toy(good(), T0), toy(good(), T0 + H)
    store.append_scoped(o1, GLOBAL_SCOPE, computed_at=T0 + timedelta(seconds=5))
    store.append_scoped(o2, GLOBAL_SCOPE, computed_at=T0 + H + timedelta(seconds=5))
    assert store.latest_scoped("toy", GLOBAL_SCOPE).output == o2
    assert store.latest_scoped("toy", GLOBAL_SCOPE, known_by=T0 + H).output == o1
    assert store.latest_scoped("toy", GLOBAL_SCOPE, known_by=T0) is None
    assert store.latest_scoped("other", GLOBAL_SCOPE) is None


def test_store_rejects_output_of_other_scope(store):
    o = toy(good(), T0)
    with pytest.raises(ValueError):
        store.append_scoped(o, Scope.of_feed("XAUUSD", "M15", "MT5", "f1"), computed_at=T0)
    with pytest.raises(TypeError):
        store.append_scoped(o, "GLOBAL", computed_at=T0)


def test_store_global_does_not_mix_with_feed_series(store):
    o = toy(good(), T0)
    store.append_scoped(o, GLOBAL_SCOPE, computed_at=T0)
    assert store.latest("toy", symbol="XAUUSD", tf=Timeframe.M15, source=DataSource.MT5) is None


def test_store_expired_unreplaced_global(store):
    o1 = toy(good(), T0)                                  # hết hạn T0 + 1h
    store.append_scoped(o1, GLOBAL_SCOPE, computed_at=T0)
    exp = store.expired_unreplaced(T0, T0 + 2 * H)
    assert [(e.analyst_id, e.source, e.feed, e.symbol, e.timeframe) for e in exp] == \
        [("toy", "GLOBAL", "", "*", "*")]
    # kết quả mới tính trước khi cái cũ hết hạn → không còn "hết hạn mà chưa thay"
    store.append_scoped(toy(good(), T0 + H / 2), GLOBAL_SCOPE, computed_at=T0 + H / 2)
    assert [e.output_id for e in store.expired_unreplaced(T0, T0 + H)] == []


def test_expired_global_event_subject():
    from gold_trading.orchestrator.scanner import expired_event
    from gold_trading.storage.analyst_outputs import ExpiredOutput
    e = expired_event(ExpiredOutput("event", "*", "*", "GLOBAL", "", "id", T0))
    assert e.subject == "event:GLOBAL::*:*"
