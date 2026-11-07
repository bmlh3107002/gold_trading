"""MT-12 + GW-09: nhịp tim báo danh tính MT5, tài khoản, symbol — đọc trực tiếp, không bịa."""

import json
import math
from datetime import UTC, datetime

from mt5_gateway import checks, snapshot
from mt5_gateway.sync import Syncer
from tests.fake_mt5 import FakeMt5
from tests.test_gateway import FakeBackend, cfg

NOW = datetime(2026, 1, 14, 10, 7, 30, tzinfo=UTC)


def _syncer(fake: FakeMt5) -> Syncer:
    be = FakeBackend()
    rep = checks.run_checks(cfg(), fake, be, now=lambda: NOW, tick_wait_s=1)
    return Syncer(cfg(), rep.reader, be, rep, sleep=lambda _: None, clock=lambda: 0.0)


def test_heartbeat_reports_identity_account_and_symbol():
    fake = FakeMt5(now_utc=NOW)
    hb = _syncer(fake).heartbeat_payload()
    assert hb["identity"] == {
        "login": 51234567,
        "server": "DemoBroker-Demo",
        "company": "Demo Broker Ltd",
        "account_type": "DEMO",
        "terminal_name": "MetaTrader 5",
        "terminal_path": r"C:\Program Files\MetaTrader 5",
    }
    a = hb["account"]
    assert a["currency"] == "USD" and a["balance"] == 10000.0 and a["equity"] == 10012.5
    assert a["leverage"] == 100 and a["trade_allowed"] is True
    # margin = 0 (không có vị thế) → margin_level không xác định, không gửi số 0 của MT5
    assert a["margin"] == 0.0 and a["margin_level"] is None
    s = hb["symbol"]
    assert s["stops_level"] == 10 and s["freeze_level"] == 5
    assert s["swap_long"] == -25.3 and s["swap_short"] == 8.1 and s["swap_mode"] == 1
    assert s["swap_rollover3days"] == 3
    assert "commission" not in s  # MT5 không cung cấp → không đoán
    # trường cũ cùng nguồn
    assert (hb["account_type"], hb["server"]) == ("DEMO", "DemoBroker-Demo")
    json.dumps(hb, allow_nan=False)  # JSON chuẩn
    assert fake.order_send_called is False


def test_margin_level_sent_when_margin_positive():
    fake = FakeMt5(now_utc=NOW)
    fake.account_extra.update(margin=500.0, margin_level=2002.5)
    assert _syncer(fake).heartbeat_payload()["account"]["margin_level"] == 2002.5


def test_identity_is_read_live_not_cached_from_check():
    """Người dùng đổi tài khoản trong terminal khi Gateway đang chạy → nhịp tim báo login mới."""
    fake = FakeMt5(now_utc=NOW)
    s = _syncer(fake)
    assert s.heartbeat_payload()["identity"]["login"] == 51234567
    fake.login, fake.server, fake.trade_mode = 99887766, "OtherBroker-Live", 2
    hb = s.heartbeat_payload()
    assert hb["identity"]["login"] == 99887766 and hb["identity"]["server"] == "OtherBroker-Live"
    assert hb["identity"]["account_type"] == "REAL" and hb["account_type"] == "REAL"


def test_logged_out_terminal_reports_no_identity():
    fake = FakeMt5(now_utc=NOW)
    s = _syncer(fake)
    fake.account_none = True
    hb = s.heartbeat_payload()
    assert hb["identity"] is None and hb["account"] is None
    assert hb["account_type"] == "UNKNOWN" and hb["server"] is None
    fake.account_none, fake.account_raises = False, True
    hb = s.heartbeat_payload()
    assert hb["identity"] is None and hb["account"] is None


def test_login_zero_or_empty_server_means_no_identity():
    fake = FakeMt5(now_utc=NOW)
    s = _syncer(fake)
    fake.login = 0
    assert s.heartbeat_payload()["identity"] is None
    assert s.heartbeat_payload()["account"] is None
    fake.login, fake.server = 123, "  "
    assert s.heartbeat_payload()["identity"] is None


def test_non_finite_or_wrong_type_numbers_become_none():
    fake = FakeMt5(now_utc=NOW)
    s = _syncer(fake)
    fake.account_extra.update(
        equity=math.nan, balance=math.inf, leverage=0, margin="1", trade_allowed=1
    )
    fake.symbol_extra.update(swap_long=math.nan, trade_stops_level=-1, swap_short=True)
    hb = s.heartbeat_payload()
    a = hb["account"]
    assert a["equity"] is None and a["balance"] is None and a["leverage"] is None
    assert a["margin"] is None and a["margin_level"] is None and a["trade_allowed"] is None
    sym = hb["symbol"]
    assert sym["swap_long"] is None and sym["stops_level"] is None and sym["swap_short"] is None
    json.dumps(hb, allow_nan=False)


def test_symbol_missing_core_fields_is_not_sent_half_filled():
    fake = FakeMt5(now_utc=NOW)
    s = _syncer(fake)
    fake.symbol_extra.update(point=0.0)
    assert s.heartbeat_payload()["symbol"] is None
    fake.symbol_extra.update(point=0.01, volume_step=math.nan)
    assert s.heartbeat_payload()["symbol"] is None


def test_symbol_read_error_gives_none():
    fake = FakeMt5(now_utc=NOW)
    s = _syncer(fake)
    fake.symbol = "OTHER"  # symbol_info trả None
    assert s.heartbeat_payload()["symbol"] is None


def test_terminal_info_failure_keeps_identity_without_path():
    fake = FakeMt5(now_utc=NOW)
    s = _syncer(fake)

    def boom():
        raise RuntimeError("x")

    fake.terminal_info = boom
    ident = s.heartbeat_payload()["identity"]
    assert ident["login"] == 51234567 and ident["terminal_path"] is None


def test_long_text_is_truncated():
    fake = FakeMt5(now_utc=NOW)
    s = _syncer(fake)
    fake.server = "S" * 1000
    assert len(s.heartbeat_payload()["identity"]["server"]) == snapshot.MAX_TEXT


def test_check_shows_login():
    fake = FakeMt5(now_utc=NOW)
    rep = checks.run_checks(cfg(), fake, FakeBackend(), now=lambda: NOW, tick_wait_s=1)
    acc_line = next(c for c in rep.steps if c.name == "Tài khoản")
    assert "login 51234567" in acc_line.detail


def test_symbol_override_really_applies():
    """Chống test qua nhờ lỗi khác: ghi đè point=0 phải tới được snapshot (không phải exception)."""
    fake = FakeMt5(now_utc=NOW)
    fake.symbol_extra.update(point=0.0)
    assert fake.symbol_info("XAUUSD").point == 0.0
