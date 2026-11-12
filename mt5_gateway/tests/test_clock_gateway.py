"""ING-16 + 1A-C20: Gateway đo lệch đồng hồ máy so với backend và tự hiệu chỉnh khi so giờ —
đồng hồ máy Windows sai không bị hiểu nhầm thành broker đổi giờ."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from mt5_gateway import checks
from mt5_gateway.backend_client import BackendClient
from mt5_gateway.clocksync import ClockSync
from mt5_gateway.sync import Syncer
from tests.fake_mt5 import FakeMt5
from tests.test_gateway import NOW_WINTER, FakeBackend, cfg

S = timedelta(seconds=1)


def test_clocksync_reference_values():
    c = ClockSync()
    assert c.offset == timedelta(0) and not c.known
    t = NOW_WINTER
    # gửi t, nhận t+0,2 s; backend ghi nhận lúc t+45,1 s → lệch = 45,1 − 0,1 = 45 s
    assert c.sample(t, t + 0.2 * S, t + 45.1 * S)
    assert abs(c.offset.total_seconds() - 45.0) < 1e-6
    assert not c.sample(t, t + 3 * S, t)  # khứ hồi > 2 s: bỏ
    assert not c.sample(t, t - S, t)  # đồng hồ nhảy lùi giữa chừng: bỏ
    assert not c.sample(t, t, t + timedelta(days=2))  # vô lý: bỏ
    for _ in range(3):
        c.sample(t, t, t + 45 * S)
    c.sample(t, t, t + 900 * S)  # một mẫu lạ không kéo lệch (trung vị)
    assert abs(c.offset.total_seconds() - 45.0) < 1e-6


class TimeBackend(FakeBackend):
    """Backend trả ``last_seen_at`` theo đồng hồ ĐÚNG; có thể trả giờ máy chủ qua header Date."""

    def __init__(self, true_now):
        super().__init__()
        self.true_now = true_now
        self.reachable = True

    def heartbeat(self, payload):
        self.heartbeats.append(payload)
        if not self.reachable:
            from mt5_gateway.backend_client import BackendError

            raise BackendError(None, "down")
        return {"state": "CONNECTED", "last_seen_at": self.true_now().isoformat()}

    def server_date(self):
        return self.true_now().replace(microsecond=0)


def world(gateway_skew, reachable=True):
    fake = FakeMt5(now_utc=NOW_WINTER)
    be = TimeBackend(lambda: fake.now)
    be.reachable = reachable
    raw = lambda: fake.now + gateway_skew  # noqa: E731 — đồng hồ máy Windows sai
    rep = checks.run_checks(cfg(), fake, be, now=raw, tick_wait_s=1)
    t = [0.0]

    def sleep(x):
        t[0] += x

    s = Syncer(cfg(), rep.reader, be, rep, sleep=sleep, clock=lambda: t[0], now_utc=raw)
    s.quotes = None
    return fake, be, s, rep


def loop(s, fake, n=4):
    for _ in range(n):
        fake.now += timedelta(seconds=30)
        it = iter([False, True])
        s.run_forever(stop=lambda it=it: next(it))


def test_check_corrects_clock_so_server_tz_not_misreported():
    _, _, _, rep = world(-timedelta(hours=3))
    names = {x.name: x for x in rep.steps}
    assert names["Giờ server (tick trực tiếp)"].status == checks.PASS  # không báo nhầm sai múi giờ
    clk = names["Đồng hồ máy"]
    assert clk.status == checks.WARN and "chậm 10800 giây" in clk.detail
    assert rep.ok


def test_check_clock_ok():
    _, _, _, rep = world(timedelta(0))
    assert {x.name: x.status for x in rep.steps}["Đồng hồ máy"] == checks.PASS


def test_run_wrong_windows_clock_does_not_block_after_sync():
    fake, be, s, _ = world(-timedelta(hours=3))
    loop(s, fake)
    assert not s.tzwatch.paused and s.backfilled  # nhờ hiệu chỉnh theo backend
    assert abs(s.clock_sync.offset.total_seconds() - 10800) < 1
    hb = be.heartbeats[-1]
    raw = datetime.fromisoformat(hb["gateway_time"])
    assert abs((raw - fake.now).total_seconds() + 10800) < 1  # gửi giờ máy CHƯA hiệu chỉnh
    assert hb["mt5_clock_residual_s"] is not None and abs(hb["mt5_clock_residual_s"]) < 2


def test_without_backend_clock_wrong_clock_stays_safe():
    fake, be, s, _ = world(-timedelta(hours=3), reachable=False)
    loop(s, fake)
    assert s.tzwatch.paused  # không đo được → không đoán: vẫn chặn (an toàn)


def test_mt5_server_clock_residual_reported():
    fake, be, s, _ = world(timedelta(0))
    real = fake.symbol_info_tick

    def late(name):  # đồng hồ server MT5 chậm 40 giây
        tk = real(name)
        if tk is None:
            return tk
        tk.time_msc -= 40_000
        return tk

    fake.symbol_info_tick = late
    loop(s, fake)
    assert -42 <= s.tzwatch.last_residual_s <= -38
    assert be.heartbeats[-1]["mt5_clock_residual_s"] == s.tzwatch.last_residual_s


def test_backend_client_reads_date_header():
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    d = BackendClient(f"http://127.0.0.1:{srv.server_port}", "x").server_date()
    srv.server_close()
    assert d is not None and abs((d - datetime.now(UTC)).total_seconds()) < 5


def test_heartbeat_reports_terminal_offline_when_mt5_loses_broker():
    """1A-C10: MT5 vẫn mở nhưng mất mạng tới broker → không lỗi nào, nhưng phải báo mất kết nối."""
    fake, be, s, _ = world(timedelta(0))
    assert s.heartbeat_payload()["terminal_connected"] is True
    fake.connected = False
    assert s.heartbeat_payload()["terminal_connected"] is False
    fake.connected = True
    s.terminal_ok = False  # lỗi đọc MT5
    assert s.heartbeat_payload()["terminal_connected"] is False


# --- 2026-11-12: "localhost" chậm 2 giây trên Windows (IPv6 trước), dòng đồng hồ biến mất ---


@pytest.mark.parametrize("url,expected", [
    ("http://localhost:8080", "http://127.0.0.1:8080"),
    ("http://LOCALHOST:8080/", "http://127.0.0.1:8080"),
    ("http://localhost", "http://127.0.0.1"),
    ("http://localhost:9000/sub", "http://127.0.0.1:9000/sub"),
    (" http://localhost:8080 ", "http://127.0.0.1:8080"),
    ("http://127.0.0.1:8080", "http://127.0.0.1:8080"),
    ("http://may-chu.ts.net:8080", "http://may-chu.ts.net:8080"),
    ("http://localhost.example.com:8080", "http://localhost.example.com:8080"),
    ("https://gold.tail1234.ts.net", "https://gold.tail1234.ts.net"),
])
def test_backend_url_localhost_becomes_ipv4(url, expected):
    from mt5_gateway.backend_client import normalize_base_url

    assert normalize_base_url(url) == expected
    assert BackendClient(url, "x").base == expected


def test_default_backend_url_is_ipv4(tmp_path):
    from mt5_gateway.config import load

    env = tmp_path / "gateway.env"
    env.write_text("GT_INGEST_TOKEN=" + "x" * 30 + "\n", encoding="utf-8")
    assert load(env, use_environ=False).backend_url == "http://127.0.0.1:8080"


@pytest.mark.parametrize("answer", ["slow", "no-date"])
def test_check_warns_when_backend_clock_unmeasurable(answer):
    """Không đo được giờ máy chủ → CẢNH BÁO (trước đây dòng này biến mất, im lặng)."""
    fake = FakeMt5(now_utc=NOW_WINTER)
    be = TimeBackend(lambda: fake.now)
    t = [fake.now]

    def now():  # mỗi lần đọc đồng hồ trôi 2,5 giây → khứ hồi > 2 giây
        if answer == "slow":
            t[0] += timedelta(seconds=2.5)
            return t[0]
        return fake.now

    if answer == "no-date":
        be.server_date = lambda: None
    rep = checks.run_checks(cfg(), fake, be, now=now, tick_wait_s=1)
    clk = {x.name: x for x in rep.steps}["Đồng hồ máy"]
    assert clk.status == checks.WARN and "Không đo được" in clk.detail


def test_check_without_clock_support_has_no_clock_line():
    """Backend giả không có server_date (bản cũ) → không thêm dòng (giữ hành vi cũ)."""
    fake = FakeMt5(now_utc=NOW_WINTER)
    rep = checks.run_checks(cfg(), fake, FakeBackend(), tick_wait_s=1)
    assert "Đồng hồ máy" not in {x.name for x in rep.steps}


# --- 2026-11-12 kiểm trên máy: (a) nhịp tim khởi động, (b) log mất/có kết nối broker ---


def test_send_starting_payload_and_failure():
    from mt5_gateway.backend_client import BackendError
    from mt5_gateway.cli import send_starting

    class B:
        sent: list = []

        def heartbeat(self, p):
            self.sent.append(p)
            return {}

    b = B()
    assert send_starting(cfg(), b) is True
    p = b.sent[-1]
    assert p["phase"] == "STARTING" and p["terminal_connected"] is False
    assert "identity" not in p and p["read_only"] is True  # không đọc MT5, không danh tính

    class Down:
        def heartbeat(self, p):
            raise BackendError(None, "down")

    assert send_starting(cfg(), Down()) is False  # backend chưa lên: bỏ qua, không làm sập


def test_broker_loss_and_return_logged_once_each(caplog):
    import logging

    fake, be, s, _ = world(timedelta(0))
    with caplog.at_level(logging.INFO, logger="mt5_gateway"):
        loop(s, fake, n=2)
        fake.connected = False  # MT5 mất mạng tới broker
        loop(s, fake, n=3)
        fake.connected = True
        loop(s, fake, n=2)
    msgs = [r.getMessage() for r in caplog.records]
    lost = [m for m in msgs if "mất kết nối tới máy chủ broker" in m]
    back = [m for m in msgs if "kết nối lại máy chủ broker" in m]
    assert len(lost) == 1 and len(back) == 1
    assert msgs.index(lost[0]) < msgs.index(back[0])
