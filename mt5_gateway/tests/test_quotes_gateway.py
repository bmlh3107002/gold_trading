"""GW-08 + 1A-C13 (phía Gateway) + 1A-C08: gom tick thành giây, gửi giá sống, phát hiện đổi
múi giờ server khi đang chạy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from mt5_gateway import checks
from mt5_gateway.backend_client import BackendError
from mt5_gateway.quotes import (
    MAX_GAP_S,
    QuoteCollector,
    TickRequestMismatch,
    TzWatch,
    server_now,
)
from mt5_gateway.reader import Mt5Error, Mt5Reader
from mt5_gateway.sync import Syncer
from tests.fake_mt5 import FakeMt5
from tests.test_gateway import NOW_WINTER, FakeBackend, cfg

ATH = ZoneInfo("Europe/Athens")
SNOW = server_now(ATH, NOW_WINTER)  # 12:07:30 giờ server (GMT+2)


def tick(sec_off, ms, bid, ask):
    """Tick ở giây server SNOW + sec_off."""
    s = SNOW + sec_off
    return {"time": s, "time_msc": s * 1000 + ms, "bid": bid, "ask": ask, "last": 0.0,
            "volume": 0, "flags": 6}


def collector(rows=None, cursor=None, now=NOW_WINTER, **fake_kw):
    fake = FakeMt5(now_utc=now, **fake_kw)
    fake.tick_rows = rows
    r = Mt5Reader(fake, broker_symbol="XAUUSD", server_tz=ATH)
    return QuoteCollector(r, ATH, 0.01, now=lambda: now, cursor=cursor), fake


def test_server_now_reference():
    # 10:07:30 UTC mùa đông = 12:07:30 giờ server Athens viết như UTC
    assert SNOW == int(datetime(2026, 1, 14, 12, 7, 30, tzinfo=UTC).timestamp())


def test_aggregate_seconds_reference_values():
    rows = [tick(-10, 100, 2400.10, 2400.30), tick(-10, 400, 2400.05, 2400.40),
            tick(-10, 900, 2400.20, 2400.35), tick(-9, 0, 2401.0, 2401.2)]
    c, _ = collector(rows, cursor=SNOW - 10)
    got = c.collect()
    first = got.seconds[0]
    assert first == {
        "t": "2026-01-14T10:07:20+00:00",  # giây server 12:07:20 → UTC 10:07:20
        "bid": 2400.20, "ask": 2400.35,  # tick cuối giây
        "bid_low": 2400.05, "ask_high": 2400.40,
        "spread_max_points": 35,  # (2400.40 − 2400.05) / 0.01 tick thứ hai
        "ticks": 3,
    }
    assert len(got.seconds) == 2 and got.dropped == {}
    # chốt tới giây SNOW−3 (đã kết thúc ≥ 2 giây; giờ server đang ở SNOW + 0,5)
    assert got.next_cursor == SNOW - 2


def test_unfinished_second_not_sent():
    rows = [tick(-1, 100, 2400.1, 2400.3), tick(-1, 900, 2400.2, 2400.4)]
    c, _ = collector(rows, cursor=SNOW - 2)
    got = c.collect()
    assert got.seconds == []  # giây SNOW−1 chưa trọn: chưa có tick giây sau, mới qua < 2 giây
    assert got.next_cursor == SNOW - 1  # giây SNOW−2 (không có tick) đã qua


def test_later_tick_finalizes_previous_second():
    rows = [tick(-1, 100, 2400.1, 2400.3), tick(0, 50, 2400.2, 2400.4)]
    c, _ = collector(rows, cursor=SNOW - 2)
    got = c.collect()
    assert [s["ticks"] for s in got.seconds] == [1]
    assert got.next_cursor == SNOW


@pytest.mark.parametrize("bad, reason", [
    ((2400.5, 2400.3), "CROSSED"),
    ((0.0, 2400.3), "NON_POSITIVE"),
    ((-1.0, 2400.3), "NON_POSITIVE"),
    ((float("nan"), 2400.3), "NON_POSITIVE"),
    ((2400.1, float("inf")), "NON_POSITIVE"),
])
def test_bad_ticks_dropped_and_counted(bad, reason):
    rows = [tick(-10, 100, 2400.1, 2400.3), tick(-10, 200, *bad), tick(-10, 300, 2400.2, 2400.4)]
    c, _ = collector(rows, cursor=SNOW - 10)
    got = c.collect()
    assert got.dropped == {reason: 1}
    assert got.seconds[0]["ticks"] == 2 and got.seconds[0]["bid_low"] == 2400.1


def test_out_of_order_and_duplicate_ticks():
    rows = [tick(-10, 500, 2400.1, 2400.3), tick(-10, 500, 2400.1, 2400.3),  # lặp y hệt
            tick(-10, 200, 2399.0, 2399.2),  # đi lùi
            tick(-10, 700, 2400.2, 2400.4)]
    c, _ = collector(rows, cursor=SNOW - 10)
    got = c.collect()
    assert got.dropped == {"DUPLICATE": 1, "OUT_OF_ORDER": 1}
    assert got.seconds[0]["bid_low"] == 2400.1 and got.seconds[0]["ticks"] == 2


def test_same_msc_different_price_is_kept():
    rows = [tick(-10, 500, 2400.1, 2400.3), tick(-10, 500, 2400.2, 2400.4)]
    c, _ = collector(rows, cursor=SNOW - 10)
    assert c.collect().seconds[0]["ticks"] == 2


def test_ticks_before_cursor_ignored_not_counted():
    rows = [tick(-11, 900, 2400.1, 2400.3), tick(-10, 100, 2400.2, 2400.4)]
    c, _ = collector(rows, cursor=SNOW - 10)
    got = c.collect()
    assert [s["ticks"] for s in got.seconds] == [1] and got.dropped == {}


def test_request_skew_detected_too_early():
    rows = [tick(-3600, 100, 2400.1, 2400.3)]  # thư viện trả tick sớm 1 giờ
    c, fake = collector(rows, cursor=SNOW - 10)
    fake.tick_rows = rows
    fake.copy_ticks_from = lambda *a: rows  # bỏ lọc theo mốc
    with pytest.raises(TickRequestMismatch):
        c.collect()


def test_request_skew_detected_empty_but_ticks_exist():
    c, fake = collector(None, cursor=SNOW - 30)
    fake.tick_shift_s = 3600  # thư viện hiểu mốc muộn 1 giờ → luôn rỗng
    with pytest.raises(TickRequestMismatch):
        c.collect()


def test_quiet_market_empty_is_fine():
    c, fake = collector([], cursor=SNOW - 30, live_ticks=False)
    got = c.collect()
    assert got.seconds == [] and got.next_cursor == SNOW - 2


def test_start_60_seconds_back_and_gap_skipped():
    c, fake = collector(None)
    c.collect()
    assert fake.tick_requests[-1][0] == SNOW - 60
    c2, fake2 = collector(None, cursor=SNOW - 5000)
    got = c2.collect()
    assert fake2.tick_requests[-1][0] == SNOW - MAX_GAP_S
    assert got.skipped_gap_s == 5000 - MAX_GAP_S


def test_large_backlog_split_across_posts(monkeypatch):
    from mt5_gateway import quotes

    monkeypatch.setattr(quotes, "MAX_SECONDS_PER_POST", 100)
    c, _ = collector(None, cursor=SNOW - MAX_GAP_S)
    got = c.collect()
    assert len(got.seconds) == 100
    assert got.next_cursor == SNOW - MAX_GAP_S + 100
    c.cursor = got.next_cursor
    got2 = c.collect()
    assert got2.seconds and got2.seconds[0]["t"] > got.seconds[-1]["t"]


def test_dst_ambiguous_second_dropped_not_guessed():
    # 25/10/2026 03:30 giờ Athens xảy ra hai lần
    now = datetime(2026, 10, 25, 1, 0, 0, tzinfo=UTC)  # 03:00 lần 2 (GMT+2)… dùng mốc cố định
    amb = int(datetime(2026, 10, 25, 3, 30, tzinfo=UTC).timestamp())
    rows = [{"time": amb, "time_msc": amb * 1000 + 1, "bid": 2400.0, "ask": 2400.2},
            {"time": amb + 1, "time_msc": (amb + 1) * 1000 + 1, "bid": 2400.0, "ask": 2400.2}]
    fake = FakeMt5(now_utc=now)
    fake.tick_rows = rows
    r = Mt5Reader(fake, broker_symbol="XAUUSD", server_tz=ATH)
    c = QuoteCollector(r, ATH, 0.01, now=lambda: now, cursor=amb)
    got = c.collect()
    assert got.seconds == [] and got.dropped == {"AMBIGUOUS_TIME": 1}


def test_bad_point_refused():
    c, _ = collector(None)
    c.point = 0
    with pytest.raises(Mt5Error):
        c.collect()


# ---------- 1A-C08: TzWatch ----------


def fresh(offset_h, at=NOW_WINTER):
    return at.timestamp() + offset_h * 3600 + 1


def obs(w, offset_h, sec):
    at = NOW_WINTER + timedelta(seconds=sec)
    w.observe(fresh(offset_h, at), at)


def test_tzwatch_first_observation_and_repeated_tick_ignored():
    w = TzWatch(ATH)
    obs(w, 3, 0)  # lần đầu: không biết tick đã cũ bao lâu
    assert w.last_offset is None and not w.paused
    stale = fresh(3)
    w.observe(stale, NOW_WINTER + timedelta(seconds=5))
    w.observe(stale, NOW_WINTER + timedelta(seconds=10))  # cùng tick, không có tick mới
    assert not w.paused


def test_stale_tick_one_hour_old_never_misread():
    """Sau giờ đóng cửa: tick cuối đứng yên, lệch đúng 1 giờ so với đồng hồ — không được báo."""
    w = TzWatch(ATH)
    last = NOW_WINTER.timestamp() + 2 * 3600
    for k in range(0, 7200, 30):
        w.observe(last, NOW_WINTER + timedelta(seconds=k))
    assert not w.paused and not w.blocked


def test_tzwatch_pauses_on_first_mismatch_blocks_after_three_over_a_minute():
    w = TzWatch(ATH)
    obs(w, 2, 0)
    obs(w, 3, 10)
    assert w.paused and not w.blocked  # tạm dừng ngay
    obs(w, 3, 20)
    obs(w, 3, 30)
    assert not w.blocked  # 3 lần nhưng chưa đủ 60 giây
    obs(w, 3, 80)
    assert w.blocked and w.last_offset == 3
    obs(w, 2, 90)
    obs(w, 2, 95)
    assert w.blocked  # cần 3 lần khớp liên tiếp
    obs(w, 2, 100)
    assert not w.blocked and not w.paused


def test_tzwatch_broker_moving_clock_back_is_seen():
    """Broker lùi giờ: tick mới có giờ server NHỎ hơn tick trước vẫn phải được xét."""
    w = TzWatch(ATH)
    obs(w, 2, 0)
    obs(w, 1, 10)
    assert w.paused and w.last_offset == 1


def test_tzwatch_single_glitch_resumes_on_next_good():
    w = TzWatch(ATH)
    obs(w, 2, 0)
    obs(w, 3, 10)
    assert w.paused
    obs(w, 2, 20)
    assert not w.paused and not w.blocked


def test_tzwatch_summer_expected_offset():
    summer = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
    w = TzWatch(ATH)
    for i in range(5):
        at = summer + timedelta(seconds=30 * i)
        w.observe(fresh(3, at), at)
    assert not w.paused and w.last_offset == 3


# ---------- check + Syncer ----------


class QuoteBackend(FakeBackend):
    def __init__(self, status=None):
        super().__init__()
        self.quote_posts: list[dict] = []
        self.status = status

    def post_quotes(self, body):
        if self.status:
            raise BackendError(self.status[0], self.status[1])
        self.quote_posts.append(body)
        return {"received": len(body["seconds"]), "accepted": len(body["seconds"]),
                "duplicates": 0, "conflicts": 0, "dropped": {}, "wide_spread": 0,
                "calendar_closed": 0, "calendar_mismatch": False}


def world(backend=None, fake_kw=None):
    fake = FakeMt5(now_utc=NOW_WINTER, **(fake_kw or {}))
    be = backend or QuoteBackend()
    conf = cfg()
    rep = checks.run_checks(conf, fake, be, now=lambda: NOW_WINTER, tick_wait_s=1)
    t = [0.0]

    def sleep(s):
        t[0] += s

    s = Syncer(conf, rep.reader, be, rep, sleep=sleep, clock=lambda: t[0],
               now_utc=lambda: fake.now)
    return fake, be, s, rep


def test_check_quotes_step_pass():
    _, _, _, rep = world()
    step = [x for x in rep.steps if x.name == "Giá sống (bid/ask)"][0]
    assert step.status == checks.PASS and "bid 2400.1" in step.detail and rep.quotes_ok


def test_check_quotes_quiet_market_warns_but_enabled():
    _, _, _, rep = world(fake_kw={"live_ticks": False})
    step = [x for x in rep.steps if x.name == "Giá sống (bid/ask)"][0]
    assert step.status == checks.WARN and rep.quotes_ok and rep.ok


def test_check_quotes_skew_disables_quotes_only():
    fake = FakeMt5(now_utc=NOW_WINTER)
    fake.tick_shift_s = 7200
    rep = checks.run_checks(cfg(), fake, QuoteBackend(), now=lambda: NOW_WINTER, tick_wait_s=1)
    step = [x for x in rep.steps if x.name == "Giá sống (bid/ask)"][0]
    assert step.status == checks.WARN and not rep.quotes_ok and rep.ok  # nến vẫn chạy


def test_sync_sends_quotes_with_identity_and_advances():
    fake, be, s, _ = world()
    s.backfill()
    r = s.push_quotes()
    assert r and be.quote_posts
    body = be.quote_posts[-1]
    assert body["mt5_login"] == 51234567 and body["broker_symbol"] == "XAUUSD"
    # từ 60 giây trước tới giây đã có tick của giây sau
    assert body["point"] == 0.01 and len(body["seconds"]) == 59
    n = len(be.quote_posts)
    s.push_quotes()  # không có giây mới đã trọn: không gửi lại
    assert len(be.quote_posts) == n
    fake.now += timedelta(seconds=10)
    s.push_quotes()
    assert len(be.quote_posts[-1]["seconds"]) == 10
    sent = [x["t"] for p in be.quote_posts for x in p["seconds"]]
    assert len(sent) == len(set(sent))  # không gửi trùng giây
    assert fake.order_send_called is False


def test_sync_quote_post_failure_retries_same_seconds():
    fake, be, s, _ = world(QuoteBackend(status=(503, "lưu trữ lỗi")))
    s.backfill()
    cur = s.quotes.cursor
    s.push_quotes()
    assert s.quotes is not None and s.quotes.cursor == cur  # chưa gửi được: không bỏ giây nào
    be.status = None
    s.push_quotes()
    assert be.quote_posts and len(be.quote_posts[0]["seconds"]) == 59


def test_sync_old_backend_404_disables_quotes_candles_continue():
    fake, be, s, _ = world(QuoteBackend(status=(404, "Not Found")))
    s.backfill()
    s.push_quotes()
    assert s.quotes is None
    be.posts.clear()
    fake.now += timedelta(minutes=15)
    s.push_recent()
    assert be.posts  # nến vẫn gửi


def test_sync_link_wait_propagates_to_loop():
    fake, be, s, _ = world(QuoteBackend(status=(409, "MT5_LINK_MISMATCH: x")))
    s.backfill()
    with pytest.raises(BackendError):
        s.push_quotes()


def test_sync_account_switch_during_tick_read_drops_batch():
    fake, be, s, _ = world()
    s.backfill()
    real = fake.copy_ticks_from

    def switch(*a):
        out = real(*a)
        fake.login = 999
        return out

    fake.copy_ticks_from = switch
    from mt5_gateway.sync import IdentityUnstable

    with pytest.raises(IdentityUnstable):
        s.push_quotes()
    assert be.quote_posts == []


def test_sync_tz_change_blocks_candles_and_quotes_then_recovers():
    fake, be, s, _ = world()
    n_loops = iter([False, True])
    s.run_forever(stop=lambda: next(n_loops))  # nạp bù + chạy bình thường
    be.posts.clear()
    be.quote_posts.clear()
    # broker chuyển sang GMT+3 giữa mùa đông: tick mới mang giờ server lệch thêm 1 giờ
    fake.tz = ZoneInfo("Etc/GMT-3")
    for _ in range(4):
        fake.now += timedelta(seconds=30)
        loops = iter([False, True])
        s.run_forever(stop=lambda it=loops: next(it))
    assert s.tzwatch.blocked
    sent_after = len(be.posts) + len(be.quote_posts)
    fake.now += timedelta(seconds=30)
    loops = iter([False, True])
    s.run_forever(stop=lambda: next(loops))
    assert len(be.posts) + len(be.quote_posts) == sent_after  # đang chặn: không gửi gì
    assert s.heartbeat_payload()["server_offset_hours_now"] == 3
    fake.tz = ATH
    for _ in range(4):
        fake.now += timedelta(seconds=30)
        loops = iter([False, True])
        s.run_forever(stop=lambda it=loops: next(it))
    assert not s.tzwatch.blocked and s.backfilled
