"""ING-16 + 1A-C20: Gateway đo lệch đồng hồ máy so với backend và tự hiệu chỉnh khi so giờ —
đồng hồ máy Windows sai không bị hiểu nhầm thành broker đổi giờ."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

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
