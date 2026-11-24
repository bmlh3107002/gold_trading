"""GĐ4 bước 7 — kiểm Gate trên dữ liệu thật (``cli kiem-mv``, chỉ đọc)."""

from datetime import timedelta

import pytest
from sqlalchemy import text

from gold_trading.intelligence import audit as audit_mod
from gold_trading.intelligence import snapshot_builder as SB
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


# --- 24/11: khoảng thiếu ngắn + nguyên nhân (kiểm trên máy: 97,4 %, ~98 phút chưa rõ) ---------

def _holes(res):
    return res.coverage["MT5:fa:XAUUSD:M15"].holes


def _accounting_ok(res):
    """Bất biến: tổng phút các khoảng thiếu = phút mở − phút có MarketView."""
    for cov in res.coverage.values():
        assert sum(h.minutes for h in cov.holes) == cov.open_minutes - cov.covered_minutes


def test_holes_name_limiting_analyst_and_next_view(env, t0):
    produce(env, t0, event_ttl=15)            # mỗi bản hết hạn t+14 vì hạn của Lịch (event)
    res = run(env, t0, t0 + minutes(60))
    _accounting_ok(res)
    holes = _holes(res)
    assert [h.cause for h in holes] == [audit_mod.NONE_YET] + [audit_mod.EXPIRED] * 4
    assert [h.minutes for h in holes] == [1, 1, 1, 1, 1]
    first = holes[1]
    assert first.start == t0 + minutes(14) and first.end == t0 + minutes(15)
    assert "hạn của event" in first.detail
    assert f"bản sau as_of {t0 + minutes(15):%H:%M} tính lúc {t0 + minutes(15):%H:%M:%S}" \
        in first.detail
    lines = render(res)
    summary = next(x for x in lines if "Phút thiếu theo nguyên nhân" in x)
    assert "4 phút (4 lần)" in summary and "chưa có MarketView nào 1 phút (1 lần)" in summary
    assert not any("Khoảng thiếu ≥ 5 phút" in x for x in lines)   # toàn khoảng 1 phút


def test_hole_stops_at_close_and_reopen_labelled(env, t0):
    produce(env, t0, n=1, event_ttl=15)      # hạn t0+14
    env.put_all(t0 + minutes(34))
    assert env.runner.run_feed(FA, t0 + minutes(35)) == "fusion:stored"
    res = run(env, t0, t0 + minutes(45), calendar=ClosedAt(t0 + minutes(14), t0 + minutes(30)))
    _accounting_ok(res)
    holes = _holes(res)
    # t0−1 chưa có; đóng cửa t0+14 … t0+29 (không tính); mở lại t0+30 → có bản mới t0+35
    assert [(h.cause, h.start, h.end, h.minutes) for h in holes] == [
        (audit_mod.NONE_YET, t0 - minutes(1), t0, 1),
        (audit_mod.REOPEN, t0 + minutes(30), t0 + minutes(35), 5),
    ]
    assert any("mở lại phiên" in x and "(5 phút)" in x for x in render(res))


def test_hole_from_gate_rejection_shows_reasons(env, t0):
    produce(env, t0, n=1, event_ttl=15)
    mv = env.views.current(env.runner.scope(FA), t0)
    assert env.runner.run_feed(FA, mv.expires_at) == "fusion:rejected"   # Lịch hết hạn
    res = run(env, t0, t0 + minutes(30))
    _accounting_ok(res)
    h = _holes(res)[-1]
    assert h.cause == audit_mod.GATE_REJECTED and h.start == mv.expires_at
    assert h.end == t0 + minutes(30) and h.minutes == 16
    assert "event" in h.detail
    assert any("Quality Gate từ chối" in x for x in render(res))


def test_hole_from_invalidation(env, t0):
    produce(env, t0, n=1, event_ttl=15)
    mv = env.views.current(env.runner.scope(FA), t0)
    env.views.invalidate(mv.market_view_id, at=t0 + minutes(5), reason="QUALITY_REJECTED")
    res = run(env, t0, t0 + minutes(20))
    _accounting_ok(res)
    h = _holes(res)[-1]
    assert (h.cause, h.detail, h.start, h.minutes) == (
        audit_mod.INVALIDATED, "QUALITY_REJECTED", t0 + minutes(5), 15)


def test_fusion_ttl_cap_named(env, t0):
    env.put_all(t0 - minutes(1), **{a: {"ttl": 600} for a in SB.ANALYSTS})   # hạn dài
    assert env.runner.run_feed(FA, t0) == "fusion:stored"                    # → trần 30 phút
    res = run(env, t0, t0 + minutes(40))
    _accounting_ok(res)
    h = _holes(res)[-1]
    assert h.cause == audit_mod.EXPIRED and "trần 30 phút của Fusion" in h.detail
    assert "chưa có bản sau" in h.detail
    assert any("Khoảng thiếu ≥ 5 phút (1)" in x for x in render(res))


def test_holes_listing_capped(tmp_path, t0):
    e = Env("memory", tmp_path)
    produce(e, t0, n=1, event_ttl=15)
    # 40 khoảng thiếu 10 phút: mở 10 phút / đóng 5 phút xen kẽ, không có bản mới
    class Every15:
        def is_open(self, t):
            return t < t0 + minutes(14) or ((t - t0).total_seconds() // 60) % 15 < 10

    res = audit(e.views, e.snaps, e.reports, e.outs, since=t0 - minutes(1),
                now=t0 + minutes(14 + 15 * 40), calendar=Every15())
    _accounting_ok(res)
    lines = render(res)
    assert any("… và" in x for x in lines)
    listed = [x for x in lines if x.startswith("    ") and "UTC (" in x]
    assert len(listed) == audit_mod.SHORT_GAP_LIST


def test_gate_rejection_then_recovery_still_named(env, t0):
    # Lịch hết hạn → Gate từ chối; 3 phút sau có output mới → MarketView mới (báo cáo ACCEPTED)
    produce(env, t0, n=1, event_ttl=15)
    mv = env.views.current(env.runner.scope(FA), t0)
    assert env.runner.run_feed(FA, mv.expires_at) == "fusion:rejected"
    env.put_all(mv.expires_at + minutes(2.5), **{a: {"tag": "ok"} for a in SB.ANALYSTS})
    assert env.runner.run_feed(FA, mv.expires_at + minutes(3)) == "fusion:stored"
    res = run(env, t0, mv.expires_at + minutes(6))
    _accounting_ok(res)
    h = _holes(res)[-1]
    assert h.cause == audit_mod.GATE_REJECTED and h.minutes == 3


def test_cli_den_reviews_past_window(tmp_path, t0, monkeypatch, capsys):
    """``--den``: xem lại một tuần đã qua (sau khi dựng lại máy) — chỉ dùng dữ liệu tới mốc đó."""
    from datetime import UTC

    from gold_trading.ingestion import cli
    e = Env("sqlite", tmp_path)
    produce(e, t0)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'fr.db'}")
    import gold_trading.api.app as app_mod
    monkeypatch.setattr(app_mod, "calendar_from_env", lambda src: AlwaysOpen())
    # Mốc giữa chừng: chỉ 2 bản tính trước mốc được kiểm (point-in-time)
    den = (t0 + minutes(20)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M")
    assert cli.main(["kiem-mv", "--hours", "1", "--den", den]) == 0
    out = capsys.readouterr().out
    assert "Đã kiểm 2 MarketView" in out and f"đến {t0 + minutes(20):%Y-%m-%d %H:%M} UTC" in out
    assert cli._parse_utc("2026-11-24T12:41+07:00") == cli._parse_utc("2026-11-24T05:41")
    for bad in ("hôm qua", "2999-01-01T00:00"):           # sai dạng / tương lai → mã 2
        assert cli.main(["kiem-mv", "--den", bad]) == 2
