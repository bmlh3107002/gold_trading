"""GĐ4 bước 5a — kho MarketView + vô hiệu (MKV-02; 4-C05; 2-C06). Thiết kế 33 mục 7."""

from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from gold_trading.analysts.framework import GLOBAL_SCOPE, Scope
from gold_trading.intelligence.snapshot_builder import SnapshotRecord
from gold_trading.storage.market_views import InMemoryMarketViewStore, SqlMarketViewStore
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.snapshots import SqlQualityReportStore, SqlSnapshotStore
from tests.conftest import minutes
from tests.test_fusion import TREND_UP, UP, view

FEED = Scope("XAUUSD", "M15", "MT5", "f1")
OTHER = Scope("XAUUSD", "M15", "MT5", "f2")


class Env:
    def __init__(self, kind, tmp_path):
        self.sql = kind == "sqlite"
        if self.sql:
            repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'mv.db'}")
            repo.create_all()
            self.engine = repo.engine
            self.store = SqlMarketViewStore(repo.engine)
        else:
            self.store = InMemoryMarketViewStore()

    def put(self, t, computed_at=None, **kw):
        snap, report, mv = view(t, tech=UP, reg=TREND_UP, **kw)
        if self.sql:   # khóa ngoại: snapshot + báo cáo phải có trước
            SqlSnapshotStore(self.engine).append(SnapshotRecord.of(snap))
            SqlQualityReportStore(self.engine).append(report)
        assert self.store.append(mv, report_id=report.report_id,
                                 computed_at=computed_at or t) is True
        return mv, report


@pytest.fixture(params=["memory", "sqlite"])
def env(request, tmp_path):
    return Env(request.param, tmp_path)


def test_append_idempotent_and_round_trip(env, t0):
    mv, report = env.put(t0)
    assert env.store.append(mv, report_id=report.report_id, computed_at=t0) is False
    sv = env.store.latest(FEED, known_by=t0)
    assert sv.view == mv and sv.report_id == report.report_id and sv.invalidated_at is None
    assert env.store.current(FEED, t0) == mv


def test_expired_view_not_returned(env, t0):                      # 4-C05
    mv, _ = env.put(t0)
    assert env.store.current(FEED, mv.expires_at - minutes(0.01)) == mv
    assert env.store.current(FEED, mv.expires_at) is None


def test_not_known_before_computed(env, t0):
    env.put(t0, computed_at=t0 + minutes(1))
    assert env.store.current(FEED, t0) is None
    assert env.store.latest(FEED, known_by=t0) is None
    assert env.store.current(FEED, t0 + minutes(1)) is not None


def test_invalidation_is_point_in_time(env, t0):                  # 2-C06
    mv, _ = env.put(t0)
    assert env.store.invalidate(mv.market_view_id, at=t0 + minutes(3),
                                reason="REQUIRED_OUTPUT_EXPIRED", ref="event:x") is True
    assert env.store.current(FEED, t0 + minutes(2)) == mv           # trước lúc vô hiệu
    assert env.store.current(FEED, t0 + minutes(3)) is None
    sv = env.store.latest(FEED, known_by=t0 + minutes(4))
    assert (sv.reason, sv.ref, sv.invalidated_at) == ("REQUIRED_OUTPUT_EXPIRED", "event:x",
                                                      t0 + minutes(3))
    assert env.store.latest(FEED, known_by=t0 + minutes(2)).invalidated_at is None


def test_invalidate_once_and_unknown(env, t0):
    mv, _ = env.put(t0)
    assert env.store.invalidate(mv.market_view_id, at=t0, reason="A") is True
    assert env.store.invalidate(mv.market_view_id, at=t0 + minutes(1), reason="B") is False
    assert env.store.latest(FEED, known_by=t0 + minutes(2)).reason == "A"
    with pytest.raises(KeyError):
        env.store.invalidate("mv:none", at=t0, reason="A")
    for bad in ("", "X" * 65):
        with pytest.raises(ValueError):
            env.store.invalidate(mv.market_view_id, at=t0, reason=bad)


def test_no_fallback_to_older_view(env, t0):
    old, _ = env.put(t0, **{a: {"ttl": 600} for a in ("technical", "regime", "event")})
    new, _ = env.put(t0 + minutes(5))
    assert old.is_valid_at(t0 + minutes(6))                         # bản cũ còn hạn (trần 30')
    env.store.invalidate(new.market_view_id, at=t0 + minutes(6), reason="QUALITY_REJECTED")
    assert env.store.current(FEED, t0 + minutes(6)) is None           # không lùi về bản cũ
    assert env.store.current(FEED, t0 + minutes(5)) == new
    # Bản mới hết hạn (sự kiện 15') → cũng không lùi về bản cũ còn hạn
    assert env.store.current(FEED, new.expires_at) is None


def test_feed_isolation_and_global_scope(env, t0):
    env.put(t0)
    assert env.store.current(OTHER, t0) is None
    with pytest.raises(ValueError, match="toàn cục"):
        env.store.current(GLOBAL_SCOPE, t0)


def test_sql_requires_stored_snapshot_and_report(tmp_path, t0):
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'fk.db'}")
    repo.create_all()
    _, report, mv = view(t0, tech=UP, reg=TREND_UP)
    with pytest.raises(IntegrityError):
        SqlMarketViewStore(repo.engine).append(mv, report_id=report.report_id, computed_at=t0)


def test_migration_is_append_only():
    src = (Path(__file__).parents[1] / "migrations" / "versions" / "0020_market_views.py"
           ).read_text(encoding="utf-8")
    assert "market_views" in src and "market_view_invalidations" in src
    assert "forbid_mutation" in src and "create_hypertable" not in src
