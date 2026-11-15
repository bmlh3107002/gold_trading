"""GĐ4 bước 5b — FusionRunner (việc mỗi nhịp) + job INVALIDATE_MARKETVIEW (MKV-02; ORC-07; 2-C06).

Thiết kế 33 mục 7.
"""

from types import SimpleNamespace

import pytest

from gold_trading.analysts.framework import GLOBAL_SCOPE, Scope
from gold_trading.common.enums import Bias, SourceStatus
from gold_trading.intelligence import snapshot_builder as SB
from gold_trading.intelligence.fusion_runner import FusionRunner, invalidate_handler
from gold_trading.orchestrator.scanner import expired_event
from gold_trading.storage.analyst_outputs import (
    ExpiredOutput,
    InMemoryAnalystOutputStore,
    SqlAnalystOutputStore,
)
from gold_trading.storage.market_views import InMemoryMarketViewStore, SqlMarketViewStore
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.snapshots import (
    InMemoryQualityReportStore,
    InMemorySnapshotStore,
    SqlQualityReportStore,
    SqlSnapshotStore,
)
from tests.conftest import minutes
from tests.test_fusion import TREND_UP, UP
from tests.test_quality_gate import FEATURES
from tests.test_snapshot_builder import out

MARKET = SimpleNamespace(symbol="XAUUSD", timeframe="M15", source="MT5")
FA, FB = "fa", "fb"


def scope(feed):
    return Scope("XAUUSD", "M15", "MT5", feed)


class Env:
    def __init__(self, kind, tmp_path, feeds=(FA,)):
        self.feeds = list(feeds)
        if kind == "sqlite":
            repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'fr.db'}")
            repo.create_all()
            e = repo.engine
            self.outs, self.snaps = SqlAnalystOutputStore(e), SqlSnapshotStore(e)
            self.reports, self.views = SqlQualityReportStore(e), SqlMarketViewStore(e)
        else:
            self.outs, self.snaps = InMemoryAnalystOutputStore(), InMemorySnapshotStore()
            self.reports, self.views = InMemoryQualityReportStore(), InMemoryMarketViewStore()
        self.runner = FusionRunner(market=MARKET, out_store=self.outs, snapshot_store=self.snaps,
                                   report_store=self.reports, view_store=self.views,
                                   active_feeds=lambda: self.feeds)

    def put(self, aid, t, feed=FA, computed_at=None, tag="x", **kw):
        feats = {"technical": UP, "regime": TREND_UP}.get(aid, {})
        kw.setdefault("features", FEATURES[aid] | feats)
        sc = scope(feed) if aid in SB.PRICE_ANALYSTS else GLOBAL_SCOPE
        o = out(aid, sc, t, tag=tag, **kw)
        self.outs.append_scoped(o, sc, computed_at=computed_at or t)
        return o

    def put_all(self, t, feed=FA, **kw):
        return {a: self.put(a, t, feed=feed, **kw.get(a, {})) for a in SB.ANALYSTS}


@pytest.fixture(params=["memory", "sqlite"])
def env(request, tmp_path):
    return Env(request.param, tmp_path)


def test_stores_market_view_then_unchanged(env, t0):
    env.put_all(t0 - minutes(1))
    assert env.runner.run_feed(FA, t0) == "fusion:stored"
    mv = env.views.current(scope(FA), t0)
    assert mv.bias is Bias.LONG and {"UNVALIDATED_RULES", "UNCALIBRATED"} <= mv.quality_flags
    assert env.runner.run_feed(FA, t0 + minutes(0.1)) == "fusion:unchanged"
    # Bản ghi snapshot + báo cáo Gate có lưu, truy được từ MarketView
    assert env.snaps.get(mv.snapshot_id) is not None
    assert env.reports.for_snapshot(mv.snapshot_id)


def test_restart_recomputes_idempotently(env, t0):
    env.put_all(t0 - minutes(1))
    env.runner.run_feed(FA, t0)
    fresh = FusionRunner(market=MARKET, out_store=env.outs, snapshot_store=env.snaps,
                         report_store=env.reports, view_store=env.views,
                         active_feeds=lambda: [FA])
    assert fresh.run_feed(FA, t0) == "fusion:unchanged"      # ghi lại cùng id bị bỏ qua


def test_optional_expiry_produces_new_view(env, t0):
    env.put_all(t0 - minutes(1), news={"ttl": 5})
    env.runner.run_feed(FA, t0)
    first = env.views.current(scope(FA), t0)
    assert env.runner.run_feed(FA, t0 + minutes(6)) == "fusion:stored"
    second = env.views.current(scope(FA), t0 + minutes(6))
    assert second.market_view_id != first.market_view_id
    assert "OPTIONAL_EXPIRED:news" in second.quality_flags


def test_rejection_invalidates_current_view(env, t0):
    # Lỗ hổng tìm thấy khi thiết kế 5a: nguồn lịch hỏng → Gate REJECTED → MarketView cũ còn hạn
    # KHÔNG được dùng tiếp.
    env.put_all(t0 - minutes(1))
    env.runner.run_feed(FA, t0)
    old = env.views.current(scope(FA), t0)
    env.put("event", t0 + minutes(2), tag="stale", source_status=SourceStatus.STALE,
            features={"input": {}})
    assert old.is_valid_at(t0 + minutes(2))
    assert env.runner.run_feed(FA, t0 + minutes(2)) == "fusion:rejected"
    assert env.views.current(scope(FA), t0 + minutes(2)) is None
    sv = env.views.latest(scope(FA), known_by=t0 + minutes(2))
    assert sv.view.market_view_id == old.market_view_id and sv.reason == "QUALITY_REJECTED"
    assert sv.ref.startswith("qr:quality-policy-1:")
    # Trước lúc vô hiệu vẫn thấy (point-in-time)
    assert env.views.current(scope(FA), t0 + minutes(1)) == old


def test_recovery_after_rejection(env, t0):
    env.put_all(t0 - minutes(1))
    env.runner.run_feed(FA, t0)
    env.put("event", t0 + minutes(2), tag="stale", source_status=SourceStatus.STALE,
            features={"input": {}})
    env.runner.run_feed(FA, t0 + minutes(2))
    env.put("event", t0 + minutes(3), tag="ok")
    assert env.runner.run_feed(FA, t0 + minutes(3)) == "fusion:stored"
    assert env.views.current(scope(FA), t0 + minutes(3)) is not None


def test_timestamp_conflict_rejects_and_invalidates(env, t0):
    env.put_all(t0 - minutes(16), **{a: {"ttl": 600} for a in SB.REQUIRED})
    env.runner.run_feed(FA, t0 - minutes(15))
    assert env.views.current(scope(FA), t0) is not None       # MarketView cũ còn hạn (trần 30')
    env.put("technical", t0 - minutes(1), tag="new")          # Regime chưa tính nến mới
    assert env.runner.run_feed(FA, t0) == "fusion:rejected"
    assert env.views.current(scope(FA), t0) is None
    sv = env.views.latest(scope(FA), known_by=t0)
    assert sv.reason == "QUALITY_REJECTED"                    # MarketView cũ bị vô hiệu
    assert env.reports.get(sv.ref).reasons == ("TIMESTAMP_CONFLICT:technical,regime",)
    env.put("regime", t0 - minutes(1), tag="new", computed_at=t0 + minutes(0.05))
    assert env.runner.run_feed(FA, t0 + minutes(0.1)) == "fusion:stored"


def test_required_expired_no_view(env, t0):
    env.put_all(t0 - minutes(1))
    env.runner.run_feed(FA, t0)
    mv = env.views.current(scope(FA), t0)
    assert env.runner.run_feed(FA, mv.expires_at) == "fusion:rejected"
    assert env.views.current(scope(FA), mv.expires_at) is None


def test_outputs_written_after_now_not_used(env, t0):
    env.put_all(t0 - minutes(1), **{a: {"computed_at": t0 + minutes(1)} for a in SB.ANALYSTS})
    assert env.runner.run_feed(FA, t0) == "fusion:rejected"
    assert env.views.current(scope(FA), t0) is None


def test_feeds_isolated_and_inactive_skipped(tmp_path, t0):
    e = Env("memory", tmp_path, feeds=(FA, FB))
    e.put_all(t0 - minutes(1), feed=FA)
    e.put_all(t0 - minutes(1), feed=FB)
    res = e.runner.tick(t0)
    assert res == {FA: "fusion:stored", FB: "fusion:stored"}
    a, b = e.views.current(scope(FA), t0), e.views.current(scope(FB), t0)
    assert a.feed_id == FA and b.feed_id == FB and a.market_view_id != b.market_view_id
    e.feeds = [FA]
    assert set(e.runner.tick(t0 + minutes(1))) == {FA}


def test_error_in_one_feed_does_not_block_others(tmp_path, t0, monkeypatch):
    e = Env("memory", tmp_path, feeds=(FA, FB))
    e.put_all(t0 - minutes(1), feed=FB)
    real = e.outs.latest_scoped

    def boom(aid, sc, **kw):
        if sc.feed == FA:
            raise RuntimeError("db")
        return real(aid, sc, **kw)

    monkeypatch.setattr(e.outs, "latest_scoped", boom)
    res = e.runner.tick(t0)
    assert res == {FA: "fusion:error", FB: "fusion:stored"}


def test_no_price_source(tmp_path, t0):
    e = Env("memory", tmp_path)
    e.runner.market = SimpleNamespace(symbol="XAUUSD", timeframe="M15", source=None)
    assert e.runner.run_feed(FA, t0) == "fusion:no_source"


def _expired(aid, feed, t):
    src = "GLOBAL" if aid in SB.GLOBAL_ANALYSTS else "MT5"
    sym, tf, f = ("*", "*", "") if src == "GLOBAL" else ("XAUUSD", "M15", feed)
    return expired_event(ExpiredOutput(aid, sym, tf, src, f, f"{aid}:id", t))


def test_invalidate_handler_global_runs_all_feeds(tmp_path, t0):
    e = Env("memory", tmp_path, feeds=(FA, FB))
    e.put_all(t0 - minutes(1), feed=FA)
    e.put_all(t0 - minutes(1), feed=FB)
    e.runner.tick(t0)
    mv = e.views.current(scope(FA), t0)
    h = invalidate_handler(e.runner)
    # Analyst toàn cục (Lịch) hết hạn → MỌI nguồn giá được tính lại (lỗi đã sửa: "" ≠ "fa")
    out_ref = h.run(_expired("event", "", mv.expires_at), mv.expires_at)
    assert out_ref == "fa=fusion:rejected;fb=fusion:rejected"


def test_invalidate_handler_price_scope_only_that_feed(tmp_path, t0):
    e = Env("memory", tmp_path, feeds=(FA, FB))
    e.put_all(t0 - minutes(1), feed=FA)
    e.put_all(t0 - minutes(1), feed=FB)
    h = invalidate_handler(e.runner)
    assert h.run(_expired("technical", FB, t0), t0) == "fb=fusion:stored"
    assert h.run(_expired("technical", "fz", t0), t0) == "skipped:feed_inactive"


def test_invalidate_handler_rejects_other_events(tmp_path, t0):
    from gold_trading.orchestrator.model import Event, EventType
    e = Env("memory", tmp_path)
    h = invalidate_handler(e.runner)
    ev = Event(EventType.CANDLE_CLOSED, "MT5:fa:XAUUSD:M15", "v", occurred_at=t0, known_at=t0)
    with pytest.raises(ValueError):
        h.run(ev, t0)
