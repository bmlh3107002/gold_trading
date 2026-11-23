"""Giao thức đánh giá ``protocol-1`` dạng mã (GĐ6 bước 7 — thiết kế 38 mục 3–4, thiết kế 39 mục 10).

Hàm **thuần**: lưới 27 tổ hợp, chia phần phát triển / đoạn để dành, cửa sổ walk-forward, luật chọn
tổ hợp. Mọi ranh giới là **mốc ngày giao dịch 17:00 New York** (tự theo đổi giờ mùa hè / đông) —
không cắt đôi một ngày giao dịch. Mọi quy tắc ở đây ghi **trước** khi có kết quả; đổi = phiên bản
giao thức mới (``PROTOCOL_ID``).
"""

from __future__ import annotations

import calendar
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from gold_trading.strategy.trend_m15 import V1, Params

PROTOCOL_ID = "protocol-1"
TZ = ZoneInfo("America/New_York")
DAY_BOUNDARY = time(17, 0)

# Lưới khóa trước (thiết kế 38 mục 4) — chỉ 3 nút loại A.
P1_VALUES = (0.5, 0.6, 0.7)
P7_VALUES = (Decimal("1.0"), Decimal("1.5"), Decimal("2.0"))
P8_VALUES = (Decimal("1.5"), Decimal("2"), Decimal("3"))
CURRENT = (0.6, Decimal("1.5"), Decimal("2"))          # tổ hợp đang dùng (V1)

HOLDOUT_FRACTION = 0.25
HOLDOUT_MIN_MONTHS = 6
LEARN_MONTHS = 12
TEST_MONTHS = 3
MIN_LEARN_TRADES = 30          # tổ hợp ít lệnh hơn trên đoạn học không được chọn


@dataclass(frozen=True, order=True)
class Combo:
    """Một tổ hợp của lưới. ``key`` ổn định, dùng làm tên trong báo cáo / PBO."""

    min_confidence: float
    sl_atr: Decimal
    tp_r: Decimal

    @property
    def key(self) -> str:
        return f"P1={self.min_confidence:g}|P7={self.sl_atr}|P8={self.tp_r}"

    def params(self, base: Params = V1) -> Params:
        return replace(base, min_confidence=self.min_confidence, sl_atr=self.sl_atr,
                       tp_r=self.tp_r)

    def distance_to_current(self) -> int:
        return sum(a != b for a, b in zip((self.min_confidence, self.sl_atr, self.tp_r), CURRENT,
                                          strict=True))


def grid() -> tuple[Combo, ...]:
    """27 tổ hợp theo **thứ tự lưới cố định** (P1, rồi P7, rồi P8 tăng dần)."""
    return tuple(Combo(a, b, c) for a in P1_VALUES for b in P7_VALUES for c in P8_VALUES)


def current_combo() -> Combo:
    return Combo(*CURRENT)


# ---------------------------------------------------------------------- mốc thời gian


def _boundary(d: date) -> datetime:
    return datetime.combine(d, DAY_BOUNDARY, tzinfo=TZ).astimezone(UTC)


def boundary_at_or_before(t: datetime) -> datetime:
    """Mốc 17:00 NY gần nhất ≤ ``t``."""
    if t.tzinfo is None:
        raise ValueError("thời điểm phải có múi giờ")
    d = t.astimezone(TZ).date()
    for k in range(3):
        b = _boundary(d - timedelta(days=k))
        if b <= t:
            return b
    raise AssertionError("không tìm được mốc")  # pragma: no cover


def boundary_at_or_after(t: datetime) -> datetime:
    b = boundary_at_or_before(t)
    if b == t:
        return b
    d = b.astimezone(TZ).date()
    for k in range(1, 4):
        n = _boundary(d + timedelta(days=k))
        if n >= t:
            return n
    raise AssertionError("không tìm được mốc")  # pragma: no cover


def add_months(b: datetime, months: int) -> datetime:
    """Cộng ``months`` tháng lịch vào một mốc 17:00 NY (ngày lớn hơn số ngày của tháng → ngày cuối
    tháng), giữ đúng 17:00 NY sau đổi giờ."""
    d = b.astimezone(TZ).date()
    m0 = d.month - 1 + months
    y, m = d.year + m0 // 12, m0 % 12 + 1
    return _boundary(date(y, m, min(d.day, calendar.monthrange(y, m)[1])))


# ---------------------------------------------------------------------- chia dữ liệu


@dataclass(frozen=True)
class Window:
    learn_start: datetime
    learn_end: datetime          # = test_start
    test_end: datetime

    @property
    def test_start(self) -> datetime:
        return self.learn_end


@dataclass(frozen=True)
class Split:
    data_start: datetime         # mốc đầu tiên ≥ nến đầu
    dev_end: datetime            # = đầu đoạn để dành
    data_end: datetime           # mốc cuối cùng ≤ hết nến cuối
    windows: tuple[Window, ...]

    @property
    def holdout_start(self) -> datetime:
        return self.dev_end


def make_split(first_bar: datetime, last_bar_close: datetime) -> Split | None:
    """Chia theo protocol-1 mục 3. Đoạn để dành = phần **mới nhất**, ≈ 25 % thời gian (cắt ở mốc
    ngày ≤ ranh giới tính được), **tối thiểu 6 tháng**. Walk-forward trên phần phát triển: học 12
    tháng → kiểm 3 tháng, cuốn chiếu 3 tháng; cửa sổ kiểm cuối bị **cắt ở ranh giới để dành** nếu
    không đủ 3 tháng (ghi trước: không bỏ dữ liệu phát triển). Không đủ cho một vòng (12 + 3 tháng)
    + 6 tháng để dành → ``None`` (không đủ dữ liệu, không chạy)."""
    start = boundary_at_or_after(first_bar)
    end = boundary_at_or_before(last_bar_close)
    if end <= start:
        return None
    cut = boundary_at_or_before(end - (end - start) * HOLDOUT_FRACTION)
    six = add_months(end, -HOLDOUT_MIN_MONTHS)
    dev_end = min(cut, six)
    if add_months(start, LEARN_MONTHS + TEST_MONTHS) > dev_end:
        return None
    # Mọi mốc tính **từ cùng mốc gốc** (không cộng dồn): cộng dồn tháng có ngày 29–31 bị trôi
    # (31/8 → 30/11 → 28/2 …) làm các đoạn kiểm hở / chồng nhau.
    windows = []
    k = 0
    while True:
        ls = add_months(start, TEST_MONTHS * k)
        le = add_months(start, LEARN_MONTHS + TEST_MONTHS * k)
        if le >= dev_end:
            break
        te = min(add_months(start, LEARN_MONTHS + TEST_MONTHS * (k + 1)), dev_end)
        windows.append(Window(ls, le, te))
        if te >= dev_end:
            break
        k += 1
    return Split(start, dev_end, end, tuple(windows))


# ---------------------------------------------------------------------- chọn tổ hợp


@dataclass(frozen=True)
class LearnResult:
    trades: int
    expectancy_r: float | None    # kỳ vọng / lệnh theo R, sau chi phí; None = không có lệnh


def _tiebreak(c: Combo, order: Mapping[Combo, int]) -> tuple[int, int]:
    return (c.distance_to_current(), order[c])


def select_combo(results: Mapping[Combo, LearnResult]) -> Combo | None:
    """Chọn tổ hợp cho một vòng walk-forward: kỳ vọng / lệnh (R) **cao nhất** trên đoạn học, chỉ
    trong các tổ hợp có ≥ ``MIN_LEARN_TRADES`` lệnh. Hòa → gần tổ hợp hiện tại nhất (số nút khác),
    rồi thứ tự lưới. Không tổ hợp nào đủ → ``None`` (đoạn kiểm đó không giao dịch)."""
    order = {c: i for i, c in enumerate(grid())}
    ok = [c for c, r in results.items()
          if c in order and r.trades >= MIN_LEARN_TRADES and r.expectancy_r is not None]
    if not ok:
        return None
    best = max(results[c].expectancy_r for c in ok)      # type: ignore[type-var]
    tied = [c for c in ok if results[c].expectancy_r == best]
    return min(tied, key=lambda c: _tiebreak(c, order))


def holdout_combo(chosen: Sequence[Combo | None]) -> Combo | None:
    """Tổ hợp duy nhất cho đoạn để dành: được chọn **nhiều vòng nhất**; hòa → gần tổ hợp hiện tại
    nhất, rồi thứ tự lưới. Không vòng nào chọn được → ``None``."""
    counts = Counter(c for c in chosen if c is not None)
    if not counts:
        return None
    order = {c: i for i, c in enumerate(grid())}
    top = max(counts.values())
    return min((c for c, n in counts.items() if n == top), key=lambda c: _tiebreak(c, order))
