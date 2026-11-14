"""GĐ2 bước 4c — chặn theo spread (FAST-01; DEC-20 câu 2).

Case: giãn > 3 × trung vị 60 phút liên tục ≥ 5 giây → chặn đúng nguồn; 4 giây → chưa; một giây
bình thường xen giữa → đếm lại; gỡ khi < 1,5 × liên tục 2 phút; 1,5–3 × không chặn mới nhưng
không gỡ; giá cũ / mất giá → không gỡ; chưa đủ mốc → chặn ``SPREAD_UNRATED``; giây đóng cửa không
vào mốc; point-in-time (giây đến muộn); idempotent; mốc giữ lúc chặn.
"""

from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.market.quotes import CALENDAR_CLOSED, QuoteSecond
from gold_trading.risk import spread_lane as SL
from gold_trading.risk.blocks import BlockKind, BlockStore
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.risk_blocks import SqlBlockStore

S = timedelta(seconds=1)
M = timedelta(minutes=1)
T0 = datetime(2026, 12, 10, 13, 0, tzinfo=UTC)
FEED = "pf_a"


def q(t, sp, *, late=timedelta(0), flags=(), feed=FEED):
    return QuoteSecond(feed, t, 2400.0, 2400.0 + sp * 0.01, 2400.0, 2400.0 + sp * 0.01, sp, sp,
                       5, tuple(flags), t + S + late, t + S + late)


def series(start, n, sp):
    return [q(start + k * S, sp) for k in range(n)]


def hour_base(sp=20, end=T0):
    return series(end - 60 * M, 3600, sp)


@pytest.fixture(params=["memory", "sqlite"])
def bs(request, tmp_path):
    if request.param == "memory":
        return BlockStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 's.db'}")
    repo.create_all()
    return SqlBlockStore(repo.engine)


def run(bs, rows, now, feed=FEED):
    c = SL.check_feed(feed, rows, bs.open_spread(now), now)
    SL.apply(c, bs)
    return c


def test_wide_5_seconds_blocks_only_that_feed(bs):
    rows = hour_base() + series(T0, 5, 70)            # 70 > 3 × 20
    now = T0 + 5 * S + 300 * timedelta(milliseconds=1)
    c = run(bs, rows, now)
    assert c.status == "WIDE" and c.baseline == 20
    b = c.block
    assert (b.kind, b.scope, b.reason_code, b.start_at, b.end_at) == (
        BlockKind.SPREAD, FEED, "SPREAD_WIDE", T0 + 5 * S, None)
    assert b.created_at == now and b.latency_ms == 300
    assert [x.block_id for x in bs.active(now, FEED)] == [b.block_id]
    assert bs.active(now, "pf_khac") == [] and bs.active(now, None) == []


def test_four_seconds_not_enough_and_gap_resets(bs):
    rows = hour_base() + series(T0, 4, 70)
    assert run(bs, rows, T0 + 4 * S).block is None
    # giây bình thường xen giữa → đếm lại từ đầu
    rows = hour_base() + series(T0, 3, 70) + [q(T0 + 3 * S, 20)] + series(T0 + 4 * S, 4, 70)
    c = run(bs, rows, T0 + 8 * S)
    assert c.status == "WIDE" and c.block is None
    assert run(bs, rows + [q(T0 + 8 * S, 70)], T0 + 9 * S).block.start_at == T0 + 9 * S


def test_exactly_three_times_is_not_wide(bs):
    rows = hour_base() + series(T0, 10, 60)
    c = run(bs, rows, T0 + 10 * S)
    assert c.status == "NORMAL" and c.block is None


def test_idempotent_and_no_duplicate_while_open(bs):
    rows = hour_base() + series(T0, 30, 70)
    run(bs, rows[:-20], T0 + 10 * S)
    for k in range(11, 31):
        assert run(bs, rows, T0 + k * S).block is None
    assert len(bs.open_spread(T0 + 31 * S)) == 1


def test_lift_after_2_minutes_calm_baseline_frozen(bs):
    wide = series(T0, 600, 70)                         # 10 phút giãn
    calm = series(T0 + 600 * S, 120, 25)               # 25 < 1,5 × 20 = 30
    rows = hour_base() + wide + calm
    run(bs, rows[:3600 + 10], T0 + 10 * S)
    (b,) = bs.open_spread(T0 + 10 * S)
    # Trung vị trượt lúc này đã bị 10 phút giãn kéo lên? Không — mốc giữ lúc chặn (20).
    now = T0 + 719 * S
    assert run(bs, rows[:-1], now).lifts == ()          # mới 119 giây
    now = T0 + 720 * S + 500 * timedelta(milliseconds=1)
    c = run(bs, rows, now)
    assert [x.block_id for x in c.lifts] == [b.block_id] and c.lifts[0].lifted_at == now
    assert bs.active(now, FEED) == [] and bs.open_spread(now) == []
    # quá khứ không bị viết lại
    assert [x.block_id for x in bs.active(T0 + 700 * S, FEED)] == [b.block_id]


def test_mid_range_neither_blocks_nor_lifts(bs):
    rows = hour_base() + series(T0, 10, 70) + series(T0 + 10 * S, 300, 40)   # 40: 1,5–3 ×
    run(bs, rows[:3610], T0 + 10 * S)
    c = run(bs, rows, T0 + 310 * S)
    assert c.block is None and c.lifts == () and len(bs.open_spread(T0 + 310 * S)) == 1


def test_stale_or_missing_quotes_never_lift(bs):
    rows = hour_base() + series(T0, 10, 70) + series(T0 + 10 * S, 200, 20)
    run(bs, rows[:3610], T0 + 10 * S)
    c = run(bs, rows, T0 + 210 * S + 11 * S)            # giá mới nhất cũ 11 giây
    assert c.status == "STALE" and c.lifts == () and c.block is None
    assert SL.check_feed(FEED, [], bs.open_spread(T0), T0).status == "STALE"
    assert len(bs.open_spread(T0 + 230 * S)) == 1


def test_unrated_blocks_until_baseline_then_lifts(bs):
    # Mở cửa sau cuối tuần: giây đóng cửa không tính vào mốc
    closed = [q(T0 - 60 * M + k * S, 20, flags=(CALENDAR_CLOSED,)) for k in range(3000)]
    rows = closed + series(T0, 30, 20)
    c = run(bs, rows, T0 + 30 * S)
    assert c.status == "UNRATED" and c.block.reason_code == "SPREAD_UNRATED"
    assert len(bs.active(T0 + 30 * S, FEED)) == 1
    rows = closed + series(T0, 200, 20)
    c = run(bs, rows, T0 + 200 * S)
    assert c.status == "NORMAL" and len(c.lifts) == 1
    assert bs.active(T0 + 200 * S, FEED) == []


def test_point_in_time_late_quotes_ignored(bs):
    rows = hour_base() + [q(T0 + k * S, 70, late=30 * S) for k in range(6)]
    assert run(bs, rows, T0 + 7 * S).block is None      # chưa biết các giây giãn
    c = run(bs, rows, T0 + 37 * S)                       # biết trễ (giá cũ) nhưng vẫn chặn
    assert c.status == "WIDE" and c.block.start_at == T0 + 5 * S
    assert c.block.created_at == T0 + 37 * S and bs.active(T0 + 36 * S, FEED) == []


def test_zero_or_bad_baseline_is_unrated(bs):
    rows = series(T0 - 60 * M, 3600, 0) + series(T0, 5, 70)
    c = run(bs, rows, T0 + 5 * S)
    assert c.status == "UNRATED" and c.block.reason_code == "SPREAD_UNRATED"


def test_wide_seconds_do_not_raise_their_own_baseline(bs):
    """Lỗi tìm được khi soát lại: mốc sát ngưỡng — nửa giờ trước 18, nửa giờ gần 22 → trung vị
    tại giây bắt đầu giãn = 20. Cửa sổ trượt (bỏ dần giây 18, thêm giây giãn) kéo trung vị lên 22
    → giây 65 (> 3 × 20 nhưng ≤ 3 × 22) bị coi là bình thường. Mốc giữ tại giây bắt đầu giãn →
    chặn."""
    rows = (series(T0 - 60 * M, 1800, 18) + series(T0 - 30 * M, 1800, 22)
            + [q(T0 + k * S, sp) for k, sp in enumerate([200, 65, 90, 200, 65, 65, 90])])
    assert SL.baseline_at(rows, T0) == 20 and SL.baseline_at(rows, T0 + 6 * S) == 22
    c = run(bs, rows, T0 + 7 * S)
    assert c.status == "WIDE" and c.baseline == 20
    assert c.block is not None and c.block.start_at == T0 + 5 * S


def test_wide_run_matches_slow_reference():
    """Mốc trượt nhanh (danh sách đã sắp) = tính lại cả giờ cho từng giây."""
    import random
    rng = random.Random(3)
    for _ in range(8):
        rows = [q(T0 - 3600 * S + k * S, rng.choice([18, 20, 22]),
                  flags=(CALENDAR_CLOSED,) if rng.random() < 0.05 else ())
                for k in range(3600) if rng.random() > 0.02]
        rows += [q(T0 + k * S, rng.choice([20, 45, 61, 65, 70, 200])) for k in range(40)]
        run_, base = SL._wide_run(rows)
        # tham chiếu chậm
        # tham chiếu chậm: giây đầu sớm nhất trong 30 phút sao cho mọi giây tới cuối > 3 × mốc
        best = None
        for i in range(len(rows) - 1, -1, -1):
            if rows[-1].t - rows[i].t > SL.MAX_RUN_LOOKBACK:
                break
            b = SL.baseline_at(rows, rows[i].t)
            if b is not None and min(r.spread_max_points for r in rows[i:]) > 3 * b:
                best = i
        assert (len(run_) if run_ else None) == (len(rows) - best if best is not None else None)
