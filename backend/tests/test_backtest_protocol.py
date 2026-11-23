"""GĐ6 bước 7 — protocol-1 dạng mã: lưới, chia để dành, walk-forward, luật chọn (6-C04)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from gold_trading.backtest import protocol as P
from gold_trading.strategy.trend_m15 import V1

NY = P.TZ


def _ny(t: datetime) -> tuple:
    x = t.astimezone(NY)
    return (x.hour, x.minute)


def test_grid_is_locked_27_in_fixed_order_and_contains_current():
    g = P.grid()
    assert len(g) == 27 and len(set(g)) == 27
    assert g[0] == P.Combo(0.5, Decimal("1.0"), Decimal("1.5"))
    assert g[-1] == P.Combo(0.7, Decimal("2.0"), Decimal("3"))
    cur = P.current_combo()
    assert cur in g
    assert cur.params() == V1                     # tổ hợp hiện tại = đúng tham số đang chạy
    p = g[0].params()
    assert (p.min_confidence, p.sl_atr, p.tp_r) == (0.5, Decimal("1.0"), Decimal("1.5"))
    assert p.cooldown == V1.cooldown and p.blocked_flags == V1.blocked_flags  # nút khác giữ nguyên
    assert cur.key == "P1=0.6|P7=1.5|P8=2"


def test_boundaries_follow_new_york_dst():
    # Trước / sau đổi giờ Mỹ 2026 (08/03): 17:00 NY = 22:00 UTC (mùa đông), 21:00 UTC (mùa hè).
    w = P.boundary_at_or_before(datetime(2026, 3, 6, 23, 0, tzinfo=UTC))
    s = P.boundary_at_or_before(datetime(2026, 3, 10, 23, 0, tzinfo=UTC))
    assert (w.hour, s.hour) == (22, 21)
    assert _ny(w) == _ny(s) == (17, 0)
    t = datetime(2026, 3, 10, 20, 59, tzinfo=UTC)
    assert P.boundary_at_or_after(t) == datetime(2026, 3, 10, 21, 0, tzinfo=UTC)
    assert P.boundary_at_or_after(s) == s


def test_add_months_clamps_month_end_and_keeps_17ny():
    b = P.boundary_at_or_before(datetime(2025, 1, 31, 23, 0, tzinfo=UTC))      # 31/01 17:00 NY
    f = P.add_months(b, 1)
    assert f.astimezone(NY).date().isoformat() == "2025-02-28" and _ny(f) == (17, 0)
    a = P.add_months(b, 3)                                                      # qua đổi giờ
    assert a.astimezone(NY).date().isoformat() == "2025-04-30" and _ny(a) == (17, 0)


def test_split_real_shape_holdout_and_windows():
    first = datetime(2023, 1, 2, 23, 0, tzinfo=UTC)       # nến đầu (mở cửa tuần)
    last = datetime(2026, 11, 20, 21, 45, tzinfo=UTC)     # nến cuối đóng
    s = P.make_split(first, last)
    span = s.data_end - s.data_start
    hold = s.data_end - s.holdout_start
    assert hold >= span * 0.25 - timedelta(days=1)                       # ≈ 25 %
    assert s.holdout_start <= P.add_months(s.data_end, -6)               # ≥ 6 tháng
    for b in (s.data_start, s.dev_end, s.data_end):
        assert _ny(b) == (17, 0)
    w = s.windows
    assert w[0].learn_start == s.data_start
    for x in w:
        assert x.learn_end == P.add_months(x.learn_start, 12)
        assert x.test_end <= s.dev_end and x.test_end > x.test_start
    for a, b in zip(w, w[1:], strict=False):
        assert b.test_start == a.test_end  # kiểm nối liền, không chồng

    for k, x in enumerate(w):
        assert x.learn_start == P.add_months(s.data_start, 3 * k)       # từ mốc gốc, không trôi
    assert w[-1].test_end == s.dev_end                                   # phủ hết phần phát triển
    assert all(x.test_end <= s.holdout_start for x in w)                 # không đụng để dành


def test_split_minimum_six_month_holdout_and_too_short_data():
    first = datetime(2024, 1, 2, 23, 0, tzinfo=UTC)
    s = P.make_split(first, datetime(2025, 11, 1, 0, 0, tzinfo=UTC))   # ~22 tháng: 25 % < 6 tháng
    assert s is not None
    assert s.holdout_start == P.add_months(s.data_end, -6)
    # Phát triển ~16 tháng: vòng 1 kiểm đủ 3 tháng, vòng 2 kiểm bị cắt ở ranh giới để dành.
    assert len(s.windows) == 2
    assert s.windows[0].test_end == P.add_months(s.windows[0].test_start, 3)
    assert s.windows[1].test_end == s.dev_end < P.add_months(s.windows[1].test_start, 3)
    # 20 tháng: không đủ 12 + 3 + 6 → không chạy
    assert P.make_split(first, datetime(2025, 9, 1, 0, 0, tzinfo=UTC)) is None
    assert P.make_split(first, first) is None


def test_select_combo_rules():
    g = P.grid()
    cur = P.current_combo()
    R = P.LearnResult
    res = {c: R(50, 0.05) for c in g}
    assert P.select_combo(res) == cur                          # hòa hết → tổ hợp hiện tại
    res[g[0]] = R(50, 0.30)
    res[g[1]] = R(29, 0.90)                                    # ít hơn 30 lệnh → không được chọn
    assert P.select_combo(res) == g[0]
    res[g[26]] = R(40, 0.30)                                   # hòa g[0]; cả hai khác 3 nút
    assert P.select_combo(res) == g[0]                         # → thứ tự lưới
    near = P.Combo(0.6, Decimal("1.5"), Decimal("3"))         # khác 1 nút
    res[near] = R(40, 0.30)
    assert P.select_combo(res) == near
    assert P.select_combo({c: R(10, 1.0) for c in g}) is None
    assert P.select_combo({c: R(100, None) for c in g}) is None
    assert P.select_combo({P.Combo(0.9, Decimal("9"), Decimal("9")): R(100, 9.0)}) is None


def test_holdout_combo_most_chosen_then_tiebreak():
    g = P.grid()
    cur = P.current_combo()
    assert P.holdout_combo([g[0], g[0], cur, None]) == g[0]
    assert P.holdout_combo([g[0], cur]) == cur
    assert P.holdout_combo([g[0], g[5]]) == min((g[0], g[5]),
                                                key=lambda c: (c.distance_to_current(),
                                                               g.index(c)))
    assert P.holdout_combo([None, None]) is None
    assert P.holdout_combo([]) is None


def test_split_month_end_start_does_not_drift():
    # Lỗi tìm được khi soát 23/11: bắt đầu ngày 31 → cộng dồn 3 tháng bị trôi → kiểm hở / chồng.
    s = P.make_split(datetime(2019, 8, 31, 0, 0, tzinfo=UTC),
                     datetime(2025, 8, 20, 0, 0, tzinfo=UTC))
    w = s.windows
    assert len(w) > 10
    for a, b in zip(w, w[1:], strict=False):
        assert b.test_start == a.test_end
    assert w[-1].test_end == s.dev_end
