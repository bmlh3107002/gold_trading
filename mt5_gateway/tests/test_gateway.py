import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from mt5_gateway import checks
from mt5_gateway.backend_client import BackendError
from mt5_gateway.config import Config
from mt5_gateway.reader import Mt5Reader
from mt5_gateway.sync import Syncer
from mt5_gateway.timeconv import detect_offset_hours, server_epoch_to_utc
from tests.fake_mt5 import FakeMt5

ATHENS = ZoneInfo("Europe/Athens")
NOW_WINTER = datetime(2026, 1, 14, 10, 7, 30, tzinfo=UTC)  # thứ Tư, thị trường mở
NOW_SUMMER = datetime(2026, 7, 15, 10, 7, 30, tzinfo=UTC)
TOKEN = "k" * 32


def cfg(**kw) -> Config:
    base = dict(
        backend_url="http://x",
        token=TOKEN,
        broker_symbol="XAUUSD",
        symbol="XAUUSD",
        server_tz="Europe/Athens",
        terminal_path=None,
        history_bars=5000,
        poll_seconds=5,
        heartbeat_seconds=10,
        gateway_id="win-1",
    )
    return Config(**(base | kw))


class FakeBackend:
    base = "http://x"

    def __init__(self, fail_health=False, dry_status=None):
        self.posts: list[dict] = []
        self.heartbeats: list[dict] = []
        self.fail_health = fail_health
        self.dry_status = dry_status

    def health(self):
        if self.fail_health:
            raise BackendError(None, "Không kết nối được backend")
        return {"status": "ok", "storage": "postgres"}

    def post_candles(
        self, *, symbol, bars, backfill, gateway_id, dry_run=False, timeframe="M15", server_tz=None
    ):
        if dry_run and self.dry_status:
            raise BackendError(self.dry_status, "lỗi")
        self.posts.append(
            dict(
                symbol=symbol,
                bars=bars,
                backfill=backfill,
                dry_run=dry_run,
                timeframe=timeframe,
                server_tz=server_tz,
            )
        )
        return {
            "received": len(bars),
            "accepted": len(bars),
            "duplicates": 0,
            "revised": 0,
            "quarantined": 0,
            "reasons": {},
            "session_outside_fraction": 0.0,
        }

    def heartbeat(self, payload):
        self.heartbeats.append(payload)
        return {"state": "CONNECTED"}


# ---- Quy đổi giờ ----


def test_server_epoch_to_utc_winter_and_summer():
    # 12:00 giờ server mùa đông (GMT+2) = 10:00 UTC; mùa hè (GMT+3) = 09:00 UTC
    w = int(datetime(2026, 1, 14, 12, 0, tzinfo=UTC).timestamp())
    s = int(datetime(2026, 7, 15, 12, 0, tzinfo=UTC).timestamp())
    assert server_epoch_to_utc(w, ATHENS) == datetime(2026, 1, 14, 10, 0, tzinfo=UTC)
    assert server_epoch_to_utc(s, ATHENS) == datetime(2026, 7, 15, 9, 0, tzinfo=UTC)


def test_ambiguous_dst_hour_returns_none():
    amb = int(datetime(2026, 10, 25, 3, 30, tzinfo=UTC).timestamp())  # 03:30 Athens xảy ra hai lần
    gap = int(datetime(2026, 3, 29, 3, 30, tzinfo=UTC).timestamp())  # 03:30 Athens không tồn tại
    assert server_epoch_to_utc(amb, ATHENS) is None
    assert server_epoch_to_utc(gap, ATHENS) is None


def test_detect_offset_only_for_fresh_ticks():
    now = 1_800_000_000
    assert detect_offset_hours(now + 2 * 3600 + 3, now) == 2
    assert detect_offset_hours(now + 3 * 3600 - 120, now) == 3
    assert detect_offset_hours(now + 2 * 3600 + 1800, now) is None  # lệch nửa giờ: không đoán


# ---- Đọc nến ----


def test_closed_bars_exclude_forming_bar_and_convert_to_utc():
    fake = FakeMt5(now_utc=NOW_WINTER)
    r = Mt5Reader(fake, broker_symbol="XAUUSD", server_tz=ATHENS)
    bars = r.closed_bars(10)
    assert len(bars) == 10
    assert bars[-1].open_time_utc == datetime(
        2026, 1, 14, 9, 45, tzinfo=UTC
    )  # nến 10:00 đang chạy bị loại
    assert all(b.open_time_utc + timedelta(minutes=15) <= NOW_WINTER for b in bars)


def test_read_only_wrapper_blocks_trading_functions():
    fake = FakeMt5(now_utc=NOW_WINTER)
    r = Mt5Reader(fake, broker_symbol="XAUUSD", server_tz=ATHENS)
    with pytest.raises(AttributeError, match="chỉ đọc"):
        r.mt5.order_send({})
    assert fake.order_send_called is False


def test_source_contains_no_trading_calls():
    src = Path(__file__).resolve().parents[1] / "src" / "mt5_gateway"
    forbidden = re.compile(
        r"\b(order_send|order_check|order_calc|positions_get|positions_total|"
        r"orders_get|orders_total|history_orders|history_deals)\b"
    )
    hits = [
        f"{p.name}: {m.group(0)}"
        for p in src.glob("*.py")
        for m in forbidden.finditer(p.read_text(encoding="utf-8"))
    ]
    assert hits == []


# ---- Lệnh check ----


def names(rep):
    return {s.name: s.status for s in rep.steps}


def test_check_all_pass_on_demo_with_correct_timezone():
    rep = checks.run_checks(
        cfg(), FakeMt5(now_utc=NOW_WINTER), FakeBackend(), now=lambda: NOW_WINTER, tick_wait_s=1
    )
    assert rep.ok, [(s.name, s.status, s.detail) for s in rep.steps]
    assert names(rep)["Giờ server (tick trực tiếp)"] == checks.PASS
    assert names(rep)["Tài khoản"] == checks.PASS


def test_check_summer_offset_also_matches():
    rep = checks.run_checks(
        cfg(), FakeMt5(now_utc=NOW_SUMMER), FakeBackend(), now=lambda: NOW_SUMMER, tick_wait_s=1
    )
    assert rep.ok and rep.offset_now == 3


def test_check_fails_when_declared_timezone_wrong():
    # Broker thật GMT+2/+3 nhưng người dùng khai báo UTC
    rep = checks.run_checks(
        cfg(server_tz="UTC"),
        FakeMt5(now_utc=NOW_WINTER),
        FakeBackend(),
        now=lambda: NOW_WINTER,
        tick_wait_s=1,
    )
    assert not rep.ok and names(rep)["Giờ server (tick trực tiếp)"] == checks.FAIL


def test_check_warns_when_no_live_tick_but_does_not_guess():
    rep = checks.run_checks(
        cfg(),
        FakeMt5(now_utc=NOW_WINTER, live_ticks=False),
        FakeBackend(),
        now=lambda: NOW_WINTER,
        tick_wait_s=1,
    )
    assert names(rep)["Giờ server (tick trực tiếp)"] == checks.WARN and rep.offset_now is None


@pytest.mark.parametrize(
    ("kw", "fake_kw", "backend_kw", "step"),
    [
        ({"server_tz": ""}, {}, {}, "Cấu hình múi giờ server"),
        ({"server_tz": "Mars/Base"}, {}, {}, "Cấu hình múi giờ server"),
        ({"token": "short"}, {}, {}, "Token"),
        ({}, {"init_ok": False}, {}, "Kết nối MT5"),
        ({}, {"connected": False}, {}, "Kết nối MT5"),
        ({"broker_symbol": "GOLD"}, {}, {}, "Symbol"),
        ({}, {}, {"fail_health": True}, "Backend"),
        ({}, {}, {"dry_status": 401}, "Chạy thử gửi dữ liệu (không lưu)"),
    ],
)
def test_check_failures(kw, fake_kw, backend_kw, step):
    rep = checks.run_checks(
        cfg(**kw),
        FakeMt5(now_utc=NOW_WINTER, **fake_kw),
        FakeBackend(**backend_kw),
        now=lambda: NOW_WINTER,
        tick_wait_s=1,
    )
    assert not rep.ok and names(rep)[step] == checks.FAIL


def test_check_real_account_is_warning_not_failure():
    rep = checks.run_checks(
        cfg(),
        FakeMt5(now_utc=NOW_WINTER, trade_mode=2),
        FakeBackend(),
        now=lambda: NOW_WINTER,
        tick_wait_s=1,
    )
    assert rep.ok and names(rep)["Tài khoản"] == checks.WARN


def test_check_suggests_similar_symbols():
    rep = checks.run_checks(
        cfg(broker_symbol="GOLD"),
        FakeMt5(now_utc=NOW_WINTER),
        FakeBackend(),
        now=lambda: NOW_WINTER,
        tick_wait_s=1,
    )
    sym = next(s for s in rep.steps if s.name == "Symbol")
    assert "XAUUSD.r" in sym.fix


def test_check_dry_run_does_not_store():
    be = FakeBackend()
    checks.run_checks(cfg(), FakeMt5(now_utc=NOW_WINTER), be, now=lambda: NOW_WINTER, tick_wait_s=1)
    assert be.posts and all(p["dry_run"] for p in be.posts)


# ---- Đồng bộ ----


def test_sync_backfill_then_live_and_heartbeat():
    fake, be = FakeMt5(now_utc=NOW_WINTER), FakeBackend()
    rep = checks.run_checks(cfg(), fake, be, now=lambda: NOW_WINTER, tick_wait_s=1)
    be.posts.clear()
    s = Syncer(cfg(), rep.reader, be, rep, sleep=lambda _: None, clock=lambda: 0.0)
    s.backfill()
    assert all(p["backfill"] for p in be.posts) and all(len(p["bars"]) <= 1000 for p in be.posts)
    assert sum(len(p["bars"]) for p in be.posts) == len(rep.reader.closed_bars(5000))
    be.posts.clear()
    loops = iter([False, True])
    s.run_forever(stop=lambda: next(loops))
    assert (
        len(be.posts) == 1 and be.posts[0]["backfill"] is False and len(be.posts[0]["bars"]) == 20
    )
    hb = be.heartbeats[0]
    assert hb["read_only"] is True and hb["account_type"] == "DEMO"
    assert hb["symbol"]["contract_size"] == 100.0 and hb["server_offset_hours_now"] == 2
    assert fake.order_send_called is False


def test_sync_backs_off_on_backend_error():
    fake = FakeMt5(now_utc=NOW_WINTER)
    rep = checks.run_checks(cfg(), fake, FakeBackend(), now=lambda: NOW_WINTER, tick_wait_s=1)

    class Down(FakeBackend):
        def post_candles(self, **kw):
            raise BackendError(None, "down")

    sleeps: list[float] = []
    n = iter([False, False, False, True])
    Syncer(cfg(), rep.reader, Down(), rep, sleep=sleeps.append, clock=lambda: 0.0).run_forever(
        stop=lambda: next(n)
    )
    assert sleeps == [1.0, 2.0, 4.0]


class SessionCheckingBackend(FakeBackend):
    """Giả lập R1 của backend: từ chối nếu có nến rơi vào giờ đóng cửa (theo giờ New York)."""

    def post_candles(self, *, symbol, bars, backfill, gateway_id, dry_run=False, **kw):
        from tests.gold_trading_sample import _open

        outside = sum(not _open(datetime.fromisoformat(b["open_time"])) for b in bars) / len(bars)
        if outside > 0.01:
            raise BackendError(422, f"Từ chối: {outside:.1%} số nến rơi vào giờ đóng cửa")
        return super().post_candles(
            symbol=symbol, bars=bars, backfill=backfill, gateway_id=gateway_id, dry_run=dry_run
        )


def test_wrong_timezone_suggests_iana_name_not_fixed_offset():
    # Lịch sử trải qua đổi giờ (mùa hè GMT+3 → mùa đông GMT+2), không có tick để đối chiếu
    fake = FakeMt5(now_utc=datetime(2026, 11, 18, 10, 7, tzinfo=UTC), live_ticks=False)
    rep = checks.run_checks(
        cfg(server_tz="UTC", history_bars=5000),
        fake,
        SessionCheckingBackend(),
        now=lambda: datetime(2026, 11, 18, 10, 7, tzinfo=UTC),
        tick_wait_s=1,
    )
    step = next(s for s in rep.steps if s.name == "Chạy thử gửi dữ liệu (không lưu)")
    assert step.status == checks.FAIL
    assert step.fix.startswith("Đặt GT_SERVER_TZ=Europe/Athens")
    assert "Etc/GMT-2" not in step.fix and "Etc/GMT-3" not in step.fix  # độ lệch cố định đều sai


# ---- ING-14 / 1A-C19: khung H1, H4, D1 ----

ALL_TF = ("M15", "H1", "H4", "D1")


def test_parse_timeframes():
    from mt5_gateway.config import parse_timeframes

    assert parse_timeframes("d1, h4,M15,H1") == ALL_TF
    assert parse_timeframes("H4") == ("M15", "H4")  # M15 luôn có
    with pytest.raises(ValueError, match="W1"):
        parse_timeframes("M15,W1")


def test_config_default_syncs_all_timeframes(tmp_path, monkeypatch):
    from mt5_gateway import config

    monkeypatch.delenv("GT_TIMEFRAMES", raising=False)
    assert config.load(tmp_path / "none.env").timeframes == ALL_TF


def test_d1_h4_bars_keep_server_boundaries_and_skip_forming_bar():
    r = Mt5Reader(FakeMt5(now_utc=NOW_WINTER), broker_symbol="XAUUSD", server_tz=ATHENS)
    d1 = r.closed_bars(10, "D1")
    # 00:00 giờ Athens mùa đông = 22:00 UTC; nến của hôm nay (14/01, đang chạy) không có
    assert all(b.open_time_utc.astimezone(ATHENS).hour == 0 for b in d1)
    assert all(b.open_time_utc.hour == 22 for b in d1)
    assert d1[-1].open_time_utc == datetime(2026, 1, 12, 22, tzinfo=UTC)
    h4 = r.closed_bars(50, "H4")
    assert all(b.open_time_utc.astimezone(ATHENS).hour % 4 == 0 for b in h4)
    assert h4[-1].open_time_utc + timedelta(hours=4) <= NOW_WINTER
    h1 = r.closed_bars(5, "H1")
    assert h1[-1].open_time_utc == datetime(2026, 1, 14, 9, tzinfo=UTC)
    with pytest.raises(ValueError):
        r.closed_bars(5, "W1")


def test_d1_summer_server_midnight_is_21_utc():
    r = Mt5Reader(FakeMt5(now_utc=NOW_SUMMER), broker_symbol="XAUUSD", server_tz=ATHENS)
    assert {b.open_time_utc.hour for b in r.closed_bars(20, "D1")} == {21}


def test_check_higher_timeframes_pass_and_send_server_tz():
    be = FakeBackend()
    rep = checks.run_checks(
        cfg(timeframes=ALL_TF),
        FakeMt5(now_utc=NOW_WINTER),
        be,
        now=lambda: NOW_WINTER,
        tick_wait_s=1,
    )
    step = next(s for s in rep.steps if s.name == "Khung H1/H4/D1")
    assert step.status == checks.PASS and rep.ok
    assert rep.timeframes_ok == list(ALL_TF)
    d1 = [p for p in be.posts if p["timeframe"] == "D1"]
    assert d1 and all(p["dry_run"] and p["server_tz"] == "Europe/Athens" for p in d1)


def test_check_missing_timeframe_warns_and_excludes_it():
    fake = FakeMt5(now_utc=NOW_WINTER, missing_tfs={FakeMt5.TIMEFRAME_D1})
    rep = checks.run_checks(
        cfg(timeframes=ALL_TF), fake, FakeBackend(), now=lambda: NOW_WINTER, tick_wait_s=1
    )
    step = next(s for s in rep.steps if s.name == "Khung H1/H4/D1")
    assert step.status == checks.WARN and "D1" in step.detail
    assert rep.ok and rep.timeframes_ok == ["M15", "H1", "H4"]


class RejectingBackend(FakeBackend):
    """Backend từ chối một khung (ví dụ backend cũ) hoặc cách ly vì lệch ranh giới."""

    def __init__(self, reject_tf=None, misaligned_tf=None, live_fail_tf=None):
        super().__init__()
        self.reject_tf, self.misaligned_tf, self.live_fail_tf = (
            reject_tf,
            misaligned_tf,
            live_fail_tf,
        )

    def post_candles(self, **kw):
        tf = kw.get("timeframe", "M15")
        if tf == self.reject_tf:
            raise BackendError(422, "Input should be 'M15'")
        if tf == self.live_fail_tf and not kw.get("dry_run"):
            raise BackendError(503, "lỗi tạm thời")
        r = super().post_candles(**kw)
        if tf == self.misaligned_tf:
            n = len(kw["bars"])
            r |= {"accepted": 0, "quarantined": n, "reasons": {"MISALIGNED_TIME": n}}
        return r


@pytest.mark.parametrize("kw", [{"reject_tf": "H4"}, {"misaligned_tf": "H4"}])
def test_check_backend_problem_excludes_timeframe(kw):
    rep = checks.run_checks(
        cfg(timeframes=ALL_TF),
        FakeMt5(now_utc=NOW_WINTER),
        RejectingBackend(**kw),
        now=lambda: NOW_WINTER,
        tick_wait_s=1,
    )
    assert rep.ok and rep.timeframes_ok == ["M15", "H1", "D1"]
    assert next(s for s in rep.steps if s.name == "Khung H1/H4/D1").status == checks.WARN


def test_sync_higher_timeframes_backfill_then_only_on_new_bar_or_resend():
    fake, be = FakeMt5(now_utc=NOW_WINTER), FakeBackend()
    c = cfg(timeframes=ALL_TF)
    rep = checks.run_checks(c, fake, be, now=lambda: NOW_WINTER, tick_wait_s=1)
    be.posts.clear()
    t = [0.0]
    s = Syncer(c, rep.reader, be, rep, sleep=lambda _: None, clock=lambda: t[0])
    s.backfill()
    by_tf = {tf: [p for p in be.posts if p["timeframe"] == tf] for tf in ALL_TF}
    assert all(by_tf[tf] and all(p["backfill"] for p in by_tf[tf]) for tf in ALL_TF)
    assert all(p["server_tz"] == "Europe/Athens" for p in be.posts)
    be.posts.clear()
    s.push_recent()  # lần đầu: gửi lại 3 nến mỗi khung lớn (bắt bản sửa)
    assert sorted(p["timeframe"] for p in be.posts) == sorted(ALL_TF)
    assert all(len(p["bars"]) == 3 for p in be.posts if p["timeframe"] != "M15")
    be.posts.clear()
    t[0] = 30.0
    s.push_recent()  # chưa có nến mới, chưa tới hạn gửi lại → chỉ M15
    assert [p["timeframe"] for p in be.posts] == ["M15"]
    be.posts.clear()
    fake.now = NOW_WINTER + timedelta(hours=1)  # có nến H1 mới đóng
    s.push_recent()
    assert sorted(p["timeframe"] for p in be.posts) == ["H1", "M15"]
    be.posts.clear()
    t[0] = 91.0
    s.push_recent()  # tới hạn gửi lại định kỳ
    assert sorted(p["timeframe"] for p in be.posts) == sorted(ALL_TF)
    assert s.heartbeat_payload()["timeframes"] == list(ALL_TF)
    assert fake.order_send_called is False


def test_higher_timeframe_error_does_not_stop_m15():
    fake = FakeMt5(now_utc=NOW_WINTER)
    c = cfg(timeframes=ALL_TF)
    be = RejectingBackend(live_fail_tf="H4")
    rep = checks.run_checks(c, fake, be, now=lambda: NOW_WINTER, tick_wait_s=1)
    assert rep.timeframes_ok == list(ALL_TF)
    s = Syncer(c, rep.reader, be, rep, sleep=lambda _: None, clock=lambda: 0.0)
    s.backfill()  # H4 lỗi khi nạp bù → tắt H4, các khung khác vẫn chạy
    assert s.timeframes == ["M15", "H1", "D1"]
    be.posts.clear()
    loops = iter([False, True])
    s.run_forever(stop=lambda: next(loops))
    assert s.terminal_ok and "M15" in [p["timeframe"] for p in be.posts]
    assert "H4" not in [p["timeframe"] for p in be.posts]


def test_mt5_read_error_on_higher_timeframe_live_is_isolated():
    fake = FakeMt5(now_utc=NOW_WINTER)
    c = cfg(timeframes=ALL_TF)
    be = FakeBackend()
    rep = checks.run_checks(c, fake, be, now=lambda: NOW_WINTER, tick_wait_s=1)
    s = Syncer(c, rep.reader, be, rep, sleep=lambda _: None, clock=lambda: 0.0)
    s.backfill()
    fake.missing_tfs = {FakeMt5.TIMEFRAME_D1}  # MT5 không trả D1 nữa
    be.posts.clear()
    s.push_recent()
    sent = [p["timeframe"] for p in be.posts]
    assert "M15" in sent and "D1" not in sent and s.terminal_ok


def test_higher_timeframes_request_bounded_history_and_report_progress():
    # Lỗi thật 2026-11-07: xin 5.000 nến D1 (~20 năm) làm MT5 đứng rất lâu, màn hình không hiện gì
    fake = FakeMt5(now_utc=NOW_WINTER)
    c = cfg(timeframes=ALL_TF)
    msgs: list[str] = []
    rep = checks.run_checks(
        c, fake, FakeBackend(), now=lambda: NOW_WINTER, tick_wait_s=1, progress=msgs.append
    )
    asked = {tf: n for tf, n in fake.rate_requests}
    assert asked[FakeMt5.TIMEFRAME_M15] == 5000
    assert asked[FakeMt5.TIMEFRAME_H1] == 2000
    assert asked[FakeMt5.TIMEFRAME_H4] == 1000
    assert asked[FakeMt5.TIMEFRAME_D1] == 500
    assert any("D1" in m for m in msgs) and any("M15" in m for m in msgs)
    fake.rate_requests.clear()
    Syncer(c, rep.reader, FakeBackend(), rep, sleep=lambda _: None, clock=lambda: 0.0).backfill()
    assert max(n for tf, n in fake.rate_requests if tf == FakeMt5.TIMEFRAME_D1) == 500
    # GT_HISTORY_BARS nhỏ hơn thì không vượt
    from mt5_gateway.config import history_bars_for

    assert history_bars_for(cfg(history_bars=300), "D1") == 300
