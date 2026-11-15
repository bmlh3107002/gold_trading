"""GĐ4 bước 7 — kiểm Gate trên dữ liệu thật (``cli kiem-mv``, chỉ đọc)."""

from datetime import timedelta

import pytest
from sqlalchemy import text

from gold_trading.intelligence.audit import audit, render
from gold_trading.storage.market_views import InMemoryMarketViewStore
from gold_trading.storage.snapshots import InMemoryQualityReportStore, InMemorySnapshotStore
from tests.conftest import minutes
from tests.test_fusion_runner import FA, Env


class AlwaysOpen:
    def is_open(self, t):
        return True


class ClosedAt:
    def __init__(self, lo, hi):
        self.lo, self.hi = lo, hi

    def is_open(self, t):
        return not (self.lo <= t < self.hi)


def produce(env, t0, n=4, event_ttl=20):
    """n lần bar 15 phút liên tiếp, mỗi lần đủ 6 analyst + Fusion. Lịch hạn ``event_ttl`` phút
    (20 → phủ liên tục; 15 → mỗi chu kỳ hở 1 phút trước bản mới)."""
    for i in range(n):
        t = t0 + minutes(15 * i)
        kw = {a: {"tag": f"b{i}"} for a in ("technical", "regime", "event", "macro",
                                            "positioning", "news")}
        kw["event"]["ttl"] = event_ttl
        env.put_all(t - minutes(1), **kw)
        assert env.runner.run_feed(FA, t) == "fusion:stored"


def run(env, t0, now, **kw):
    return audit(env.views, env.snaps, env.reports, env.outs, since=t0 - minutes(1), now=now,
                 calendar=kw.pop("calendar", AlwaysOpen()), **kw)


@pytest.fixture(params=["memory", "sqlite"])
def env(request, tmp_path):
    return Env(request.param, tmp_path)


def test_all_views_rebuild_exactly(env, t0):
    produce(env, t0)
    res = run(env, t0, t0 + minutes(60))
    assert res.ok and res.checked == 4 and res.errors == []
    assert res.bias == {"LONG": 4}
    cov = res.coverage["MT5:fa:XAUUSD:M15"]
    # t0−1 … t0+59 = 61 phút mở; phút t0−1 chưa có MarketView (tính lúc t0)
    assert cov.open_minutes == 61 and cov.covered_minutes == 60 and cov.gaps == []
    assert any("khớp 100 %" in line for line in render(res))


def test_short_input_ttl_holes_counted(env, t0):
    produce(env, t0, event_ttl=15)       # mỗi bản hết hạn t+14, bản mới tới t+15 → hở 1 phút
    cov = run(env, t0, t0 + minutes(60)).coverage["MT5:fa:XAUUSD:M15"]
    assert cov.covered_minutes == 61 - 1 - 4 and cov.gaps == []     # hở < 30 phút: không liệt kê


def test_gap_and_invalidation_reported(env, t0):
    produce(env, t0, n=1, event_ttl=15)         # một MarketView, hạn tới t0+14 (Lịch)
    res = run(env, t0, t0 + minutes(60))
    cov = res.coverage["MT5:fa:XAUUSD:M15"]
    assert cov.gaps and cov.gaps[0][0] == t0 + minutes(14)        # hết hạn lúc t0+14
    assert cov.gaps[0][1] == t0 + minutes(60)
    assert any("khoảng trống" in line for line in render(res))
    mv = env.views.current(env.runner.scope(FA), t0)
    env.views.invalidate(mv.market_view_id, at=t0 + minutes(5), reason="QUALITY_REJECTED")
    res = run(env, t0, t0 + minutes(60))
    assert res.invalidations == {"QUALITY_REJECTED": 1}
    assert res.coverage["MT5:fa:XAUUSD:M15"].covered_minutes == 5   # t0 … t0+4


def test_closed_market_minutes_not_counted(env, t0):
    produce(env, t0, n=1, event_ttl=15)
    res = run(env, t0, t0 + minutes(60),
              calendar=ClosedAt(t0 + minutes(14), t0 + minutes(60)))
    cov = res.coverage["MT5:fa:XAUUSD:M15"]
    # mở t0−1 … t0+13 (15 phút); có MarketView t0 … t0+13 (14); sau đó đóng cửa → không là trống
    assert (cov.open_minutes, cov.covered_minutes, cov.gaps) == (15, 14, [])


def test_missing_snapshot_or_report_is_error(tmp_path, t0):
    e = Env("memory", tmp_path)
    produce(e, t0, n=1)
    res = audit(e.views, InMemorySnapshotStore(), e.reports, e.outs, since=t0 - minutes(1),
                now=t0 + minutes(5), calendar=AlwaysOpen())
    assert not res.ok and "thiếu snapshot" in res.errors[0]
    res = audit(e.views, e.snaps, InMemoryQualityReportStore(), e.outs, since=t0 - minutes(1),
                now=t0 + minutes(5), calendar=AlwaysOpen())
    assert "thiếu báo cáo" in res.errors[0]


def test_missing_analyst_output_is_error(tmp_path, t0):
    e = Env("memory", tmp_path)
    produce(e, t0, n=1)

    class Hiding:                                 # giả lập output analyst bị mất khỏi kho
        def get_scoped(self, oid, scope):
            return None if oid.startswith("regime:") else e.outs.get_scoped(oid, scope)

    res = audit(e.views, e.snaps, e.reports, Hiding(), since=t0 - minutes(1),
                now=t0 + minutes(5), calendar=AlwaysOpen())
    assert not res.ok and "không tái dựng được snapshot" in res.errors[0]


@pytest.mark.parametrize("update,msg", [
    ({"confidence": 0.95}, "Fusion ra MarketView khác"),
    ({"drivers": ("PRICE_LEAN_SHORT",)}, "Fusion ra MarketView khác"),
    ({"risk_flags": frozenset()}, "Fusion ra MarketView khác"),
])
def test_tampered_view_is_error(tmp_path, t0, update, msg):
    e = Env("memory", tmp_path)
    produce(e, t0, n=1)
    real = e.views.current(e.runner.scope(FA), t0)
    sv = e.views.latest(e.runner.scope(FA), known_by=t0)
    forged = real.model_copy(update={"market_view_id": real.market_view_id + "x", **update})
    views = InMemoryMarketViewStore()
    views.append(forged, report_id=sv.report_id, computed_at=t0)
    res = audit(views, e.snaps, e.reports, e.outs, since=t0 - minutes(1), now=t0 + minutes(5),
                calendar=AlwaysOpen())
    assert not res.ok and msg in res.errors[0]


def test_wrong_expiry_is_error(tmp_path, t0):
    e = Env("memory", tmp_path)
    produce(e, t0, n=1)
    real = e.views.current(e.runner.scope(FA), t0)
    sv = e.views.latest(e.runner.scope(FA), known_by=t0)
    forged = real.model_copy(update={"expires_at": real.expires_at + minutes(10)})
    views = InMemoryMarketViewStore()
    views.append(forged, report_id=sv.report_id, computed_at=t0)
    res = audit(views, e.snaps, e.reports, e.outs, since=t0 - minutes(1), now=t0 + minutes(5),
                calendar=AlwaysOpen())
    assert "hạn MarketView sai" in res.errors[0]


def test_old_version_skipped(tmp_path, t0):
    e = Env("memory", tmp_path)
    produce(e, t0, n=1)
    real = e.views.current(e.runner.scope(FA), t0)
    views = InMemoryMarketViewStore()
    views.append(real.model_copy(update={"model_version": "fusion-rules-0.9.0"}),
                 report_id="qr:x", computed_at=t0)
    res = audit(views, e.snaps, e.reports, e.outs, since=t0 - minutes(1), now=t0 + minutes(5),
                calendar=AlwaysOpen())
    assert res.ok and res.checked == 0 and res.skipped_version == 1


def test_cli_read_only_and_exit_codes(tmp_path, t0, capsys):
    from gold_trading.ingestion import cli
    e = Env("sqlite", tmp_path)
    produce(e, t0)
    eng = e.outs.engine
    tables = ("market_views", "market_view_invalidations", "market_snapshots",
              "quality_reports", "analyst_outputs")

    def counts():
        with eng.connect() as c:
            return {t: c.execute(text(f"select count(*) from {t}")).scalar() for t in tables}

    before = counts()
    assert cli._kiem_mv(2, engine=eng, now=t0 + minutes(60), calendar=AlwaysOpen()) == 0
    assert counts() == before                                   # chỉ đọc
    out = capsys.readouterr().out
    assert "Đã kiểm 4 MarketView" in out and "khớp 100 %" in out
    assert cli._kiem_mv(2, env={}) == 2                          # thiếu DATABASE_URL
    # Kho bị thiếu một output analyst (giả lập bằng cách xóa thẳng — vượt trigger SQLite)
    with eng.begin() as c:
        c.execute(text("delete from analyst_outputs where analyst_id = 'regime'"))
    assert cli._kiem_mv(2, engine=eng, now=t0 + minutes(60), calendar=AlwaysOpen()) == 1
    assert "LỖI" in capsys.readouterr().out


def test_empty_range(tmp_path, t0):
    e = Env("memory", tmp_path)
    res = audit(e.views, e.snaps, e.reports, e.outs, since=t0, now=t0 + timedelta(hours=1),
                calendar=AlwaysOpen())
    assert res.ok and res.checked == 0
    assert "Chưa có MarketView nào" in "\n".join(render(res))
