"""GW-07 + 1A-C09: gián đoạn dài (backend tắt, mạng mất) không làm hụt nến. MT5 là "hàng đợi
bền vững": Gateway đọc lùi trong lịch sử MT5 tới khi nối liền nến đã gửi cuối."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from mt5_gateway import checks
from mt5_gateway.backend_client import BackendError
from mt5_gateway.reader import Bar
from mt5_gateway.sync import LIVE_BARS, Syncer, read_overlapping
from tests.fake_mt5 import FakeMt5
from tests.test_fx_gateway import FxBackend, K
from tests.test_gateway import NOW_WINTER, cfg

T0 = datetime(2026, 1, 14, tzinfo=UTC)


def bar(i):
    return Bar(T0 + timedelta(minutes=15 * i), 1, 1, 1, 1, 1, 1)


def series(total):
    """MT5 giả: ``total`` nến, đọc ``n`` nến cuối."""
    calls = []

    def read(n):
        calls.append(n)
        return [bar(i) for i in range(max(0, total - n), total)]

    return read, calls


def test_read_overlapping_reference():
    read, calls = series(1000)
    assert read_overlapping(read, None, 20, 500) == (read(20), True)  # chưa có mốc
    read, calls = series(1000)
    bars, ok = read_overlapping(read, bar(990), 20, 500)
    assert ok and calls == [20] and bars[0].open_time_utc <= bar(990).open_time_utc
    read, calls = series(1000)
    bars, ok = read_overlapping(read, bar(900), 20, 500)  # gián đoạn 100 nến
    assert ok and calls == [20, 80, 320] and bars[0].open_time_utc <= bar(900).open_time_utc
    read, calls = series(1000)
    bars, ok = read_overlapping(read, bar(100), 20, 500)  # dài hơn lịch sử cấu hình
    assert not ok and calls[-1] == 500 and len(bars) == 500
    read, calls = series(150)  # MT5 không có đủ lịch sử
    bars, ok = read_overlapping(read, bar(-50), 20, 5000)
    assert not ok and len(bars) == 150 and calls == [20, 80, 320]


def world(fx=False):
    pairs = (("EURUSD", "EURUSD"),) if fx else ()
    fake = FakeMt5(now_utc=NOW_WINTER)
    fake.extra_symbols = {"EURUSD": K["EURUSD"]} if fx else {}
    be = Gate()
    conf = cfg(timeframes=("M15", "H1"), usd_pairs=pairs)
    rep = checks.run_checks(conf, fake, be, now=lambda: NOW_WINTER, tick_wait_s=1)
    t = [0.0]

    def sleep(x):
        t[0] += x

    clock = {"skew": timedelta(0)}
    s = Syncer(conf, rep.reader, be, rep, sleep=sleep, clock=lambda: t[0],
               now_utc=lambda: fake.now + clock["skew"])
    s.quotes = None  # chỉ xét nến
    return fake, be, s, t, clock


class Gate(FxBackend):
    """Backend có thể "tắt"."""

    def __init__(self):
        super().__init__()
        self.down = False

    def post_candles(self, **kw):
        if self.down and not kw.get("dry_run"):
            raise BackendError(None, "Không kết nối được backend")
        return super().post_candles(**kw)

    def post_fx_candles(self, body):
        if self.down:
            raise BackendError(None, "Không kết nối được backend")
        return super().post_fx_candles(body)


def times(posts, tf):
    return sorted({b["open_time"] for p in posts if p["timeframe"] == tf and not p["dry_run"]
                   for b in p["bars"]})


def contiguous(ts, minutes, now=None):
    """Đủ mọi nến MT5 thật sự có trong khoảng [đầu, cuối] (giờ nghỉ / cuối tuần không có nến)."""
    from tests.gold_trading_sample import bars_until

    ds = [datetime.fromisoformat(x) for x in ts]
    if not ds:
        return False
    m15 = [b["open_time"] for b in bars_until(ds[-1] + timedelta(days=1), days=120)]
    width = timedelta(minutes=minutes)
    expected = {t - (t - T0) % width for t in m15}
    expected = {t for t in expected if ds[0] <= t <= ds[-1]}
    return expected == set(ds)


def loop(s, n=1):
    it = iter([False] * n + [True])
    s.run_forever(stop=lambda: next(it))


def test_backend_down_8_hours_no_missing_bars():
    fake, be, s, t, _ = world(fx=True)
    loop(s, 2)
    assert s.backfilled
    be.down = True
    for _ in range(32):  # 8 giờ, mỗi 15 phút thử một lần
        fake.now += timedelta(minutes=15)
        t[0] += 900
        loop(s)
    be.down = False
    be.posts.clear()
    be.fx.clear()
    t[0] += 61
    loop(s)
    m15 = times(be.posts, "M15")
    assert len(m15) >= 32 and contiguous(m15, 15)  # 32 nến M15 của 8 giờ, liền mạch
    assert all(not p["backfill"] for p in be.posts)  # tới muộn: available_at = lúc nhận
    h1 = times(be.posts, "H1")
    assert len(h1) >= 8 and contiguous(h1, 60)  # trước đây chỉ gửi 3 nến H1 → hụt 5 giờ
    fx = sorted({b["open_time"] for p in be.fx for b in p["bars"]})
    assert len(fx) >= 32 and contiguous(fx, 15)
    assert fake.order_send_called is False


def test_catchup_does_not_depend_on_gateway_clock():
    fake, be, s, t, clock = world()
    loop(s, 2)
    clock["skew"] = -timedelta(hours=6)  # đồng hồ máy Windows chậm 6 giờ
    s.watch_tz = lambda: None  # (lệch đồng hồ làm TzWatch tự chặn — xét riêng ở ING-16)
    be.down = True
    for _ in range(24):
        fake.now += timedelta(minutes=15)
        loop(s)
    be.down = False
    be.posts.clear()
    loop(s)
    m15 = times(be.posts, "M15")
    assert len(m15) >= 24 and contiguous(m15, 15)


def test_large_catchup_split_into_batches():
    fake, be, s, t, _ = world()
    loop(s, 2)
    be.down = True
    fake.now += timedelta(days=15)  # ~1.000+ nến M15
    loop(s)
    be.down = False
    be.posts.clear()
    loop(s)
    m15 = [p for p in be.posts if p["timeframe"] == "M15"]
    assert len(m15) >= 2 and all(len(p["bars"]) <= 1000 for p in m15)
    assert contiguous(times(be.posts, "M15"), 15)
    assert len(times(be.posts, "M15")) > 1000


def test_gap_longer_than_history_warns_clearly(caplog):
    fake, be, s, t, _ = world()
    loop(s, 2)
    be.down = True
    fake.now += timedelta(days=80)  # > 5.000 nến M15
    loop(s)
    be.down = False
    caplog.set_level(logging.WARNING)
    loop(s)
    assert any("có thể THIẾU nến M15" in r.message for r in caplog.records)
    n = sum(1 for r in caplog.records if "THIẾU nến M15" in r.message)
    loop(s)
    assert sum(1 for r in caplog.records if "THIẾU nến M15" in r.message) == n  # báo một lần


def test_normal_operation_reads_only_live_bars():
    fake, be, s, t, _ = world()
    loop(s, 2)
    fake.rate_requests.clear()
    fake.now += timedelta(minutes=15)
    loop(s)
    m15_counts = [c for tf, c in fake.rate_requests if tf == fake.TIMEFRAME_M15]
    assert m15_counts and max(m15_counts) == LIVE_BARS + 1  # không đọc thừa khi không gián đoạn
