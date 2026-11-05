"""Lịch broker (giờ server) giao với lịch tham chiếu.

Bối cảnh (2026-11-05, MT5 demo thật MetaQuotes-Demo): Specification → Sessions của XAUUSD là
Mon–Fri 00:00–23:00 giờ server (Europe/Athens). Dữ liệu thật thiếu đúng 4 nến/ngày lúc
23:00–23:45 giờ server, nên với lịch tham chiếu độ phủ luôn ~96% và analyst bị chặn vĩnh viễn.
"""

from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.analysts import technical
from gold_trading.api.app import calendar_from_env, create_app
from gold_trading.common.enums import SourceStatus
from gold_trading.contracts.candle import Candle, DataSource
from gold_trading.ingestion.sources import sample
from gold_trading.market.hours import (
    REFERENCE,
    BrokerSessions,
    MarketCalendar,
    MarketSession,
)
from gold_trading.market.quality import assess_window
from gold_trading.market.service import Freshness, MarketDataService
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.candles import InMemoryCandleStore
from gold_trading.storage.repository import InMemoryRepository

TF = Timeframe.M15
MQ = MarketCalendar(BrokerSessions.parse("Mon-Fri 00:00-23:00", "Europe/Athens"))


def u(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def mk(t, o, h, lo, c, source=DataSource.MT5):
    return Candle(
        symbol="XAUUSD",
        timeframe=TF,
        source=source,
        open_time=t,
        close_time=t + TF.delta,
        open=o,
        high=h,
        low=lo,
        close=c,
        spread_points=20,
        ingested_at=t + TF.delta,
        available_at=t + TF.delta,
    )


def broker_rows(start, end, keep=MQ.bar_in_session):
    """Nến như broker thật tạo ra: chỉ khi cả lịch tham chiếu và lịch broker đều mở."""
    bars = sample.generate(start=start, end=end, tf=TF, prev_close=4000.0, seed=7)
    return [
        mk(b.open_time, b.open, b.high, b.low, b.close)
        for b in bars
        if keep(b.open_time, b.open_time + TF.delta)
    ]


def analyze(rows, calendar):
    return technical.analyze(
        rows,
        symbol="XAUUSD",
        timeframe=TF,
        source=DataSource.MT5,
        expected_last_close=rows[-1].close_time,
        correlation_id="t",
        calendar=calendar,
    )


# ---- Cú pháp ----


def test_parse_ok_and_24h():
    b = BrokerSessions.parse("Mon 01:00-24:00; Tue-Fri 00:00-12:00, 13:00-23:00", "Europe/Athens")
    assert b.windows[0] == ((60, 1440),)
    assert b.windows[1] == ((0, 720), (780, 1380))
    assert b.windows[5] == () and b.windows[6] == ()


@pytest.mark.parametrize(
    ("spec", "tz"),
    [
        ("", "Europe/Athens"),
        ("Mon-Fri", "Europe/Athens"),
        ("Fri-Mon 00:00-23:00", "Europe/Athens"),
        ("Xyz 00:00-23:00", "Europe/Athens"),
        ("Mon 23:00-01:00", "Europe/Athens"),
        ("Mon 00:00-24:30", "Europe/Athens"),
        ("Mon 00:60-23:00", "Europe/Athens"),
        ("Mon 0000-2300", "Europe/Athens"),
        ("Mon 00:00-12:00,11:00-23:00", "Europe/Athens"),
        ("Mon-Fri 00:00-23:00", "GMT+2"),
        ("Mon-Fri 00:00-23:00", "Mars/Olympus"),
    ],
)
def test_parse_rejects_bad_input(spec, tz):
    with pytest.raises(ValueError):
        BrokerSessions.parse(spec, tz)


# ---- Quy đổi giờ server, qua cả hai lần đổi giờ (châu Âu 25/10, Mỹ 01/11/2026) ----


def test_winter_daily_break_is_23_to_01_server():
    # Thứ Năm 05/11/2026: server UTC+2, New York UTC-5
    assert MQ.is_open(u(2026, 11, 5, 20, 45))  # 22:45 server
    assert not MQ.is_open(u(2026, 11, 5, 21, 0))  # 23:00 server: broker đóng
    assert not MQ.is_open(u(2026, 11, 5, 22, 0))  # 00:00 server, NY 17:00: tham chiếu đóng
    assert MQ.is_open(u(2026, 11, 5, 23, 0))  # 01:00 server, NY 18:00
    assert REFERENCE.is_open(u(2026, 11, 5, 21, 0))  # lịch cũ tưởng là mở → gây thiếu nến


def test_summer_daily_break():
    # Thứ Tư 19/08/2026: server UTC+3, New York UTC-4
    assert MQ.is_open(u(2026, 8, 19, 19, 45))  # 22:45 server
    assert not MQ.is_open(u(2026, 8, 19, 20, 0))  # 23:00 server
    assert MQ.is_open(u(2026, 8, 19, 22, 0))  # 01:00 server, NY 18:00


def test_mixed_dst_week_only_one_hour_break():
    # Thứ Tư 28/10/2026: châu Âu đã đổi giờ (UTC+2), Mỹ chưa (UTC-4).
    # Dữ liệu thật tuần này KHÔNG thiếu nến 16:xx NY — lịch kết hợp phải khớp điều đó.
    assert MQ.is_open(u(2026, 10, 28, 20, 45))  # 22:45 server, NY 16:45
    assert not MQ.is_open(u(2026, 10, 28, 21, 0))  # 23:00 server = NY 17:00
    assert MQ.is_open(u(2026, 10, 28, 22, 0))  # 00:00 server = NY 18:00


def test_weekly_open_and_friday_close():
    assert not MQ.is_open(u(2026, 11, 1, 22, 45))  # CN 17:45 NY
    assert MQ.is_open(u(2026, 11, 1, 23, 0))  # CN 18:00 NY = T2 01:00 server
    assert MQ.is_open(u(2026, 11, 6, 20, 45))  # T6 22:45 server
    assert not MQ.is_open(u(2026, 11, 6, 21, 0))  # T6 23:00 server: broker đóng tuần sớm 1 giờ


def test_well_defined_over_server_dst_change():
    # 25/10/2026 01:00 UTC châu Âu lùi giờ: quy đổi UTC → giờ server không mơ hồ, không lỗi
    t = u(2026, 10, 24, 12)
    while t < u(2026, 10, 26, 12):
        MQ.is_open(t)
        t += timedelta(minutes=15)


def test_session_labels():
    assert MQ.session_at(u(2026, 11, 5, 21, 30)) is MarketSession.DAILY_BREAK
    assert MQ.session_at(u(2026, 11, 6, 21, 30)) is MarketSession.WEEKEND  # T6 sau 23:00 server
    assert MQ.session_at(u(2026, 11, 5, 12)) is MarketSession.OPEN


# ---- Độ phủ: tái hiện lỗi thật và kiểm tra bản sửa ----

END = u(2026, 11, 5, 15)  # giống dữ liệu thật: lịch sử đi qua cả hai lần đổi giờ
START = u(2026, 10, 19, 0)


def test_reference_calendar_reproduces_real_failure():
    rows = broker_rows(START, END)
    q = assess_window(rows[-300:], TF, REFERENCE)
    assert q.coverage < 0.99
    assert {t.astimezone(MQ.broker.tz).strftime("%H:%M") for t in q.missing} <= {
        "23:00",
        "23:15",
        "23:30",
        "23:45",
    }
    out = analyze(rows, REFERENCE)
    assert "LOW_COVERAGE" in out.drivers


def test_broker_calendar_full_coverage_and_analysis_runs():
    rows = broker_rows(START, END)
    q = assess_window(rows, TF, MQ)
    assert q.coverage == 1.0 and not q.missing and not q.outside_session
    out = analyze(rows, MQ)
    assert out.source_status is SourceStatus.HEALTHY
    assert "LOW_COVERAGE" not in out.quality_flags
    assert out.features["input"]["calendar"].endswith("[Mon-Fri 00:00-23:00, Europe/Athens]")


def test_real_gap_still_detected_with_broker_calendar():
    rows = broker_rows(START, END)
    gap_start = u(2026, 11, 4, 8)  # 4 giờ mất dữ liệu giữa phiên
    rows = [c for c in rows if not gap_start <= c.open_time < gap_start + timedelta(hours=4)]
    q = assess_window(rows[-300:], TF, MQ)
    assert len(q.missing) == 16
    assert "LOW_COVERAGE" in analyze(rows, MQ).drivers


def test_misconfigured_calendar_blocks():
    # Khai báo broker đóng lúc 22:00 nhưng thật ra có nến 22:xx → lịch sai, phải chặn
    wrong = MarketCalendar(BrokerSessions.parse("Mon-Fri 00:00-22:00", "Europe/Athens"))
    rows = broker_rows(START, END)
    q = assess_window(rows[-300:], TF, wrong)
    assert q.outside_session
    out = analyze(rows, wrong)
    assert "CALENDAR_MISMATCH" in out.drivers
    assert out.source_status is SourceStatus.INVALID


def test_wrong_server_tz_blocks():
    wrong = MarketCalendar(BrokerSessions.parse("Mon-Fri 00:00-23:00", "UTC"))
    rows = broker_rows(START, END)
    assert "CALENDAR_MISMATCH" in analyze(rows, wrong).drivers


# ---- Độ mới dữ liệu trong giờ nghỉ của broker ----


def _service(calendar, rows):
    store = InMemoryCandleStore()
    store.append(rows, [])
    return MarketDataService(store, source=DataSource.MT5, calendar=calendar)


def test_freshness_during_broker_break():
    now = u(2026, 11, 5, 21, 40)  # 23:40 server, broker đang nghỉ
    rows = broker_rows(START, now)
    assert rows[-1].close_time == u(2026, 11, 5, 21, 0)
    assert _service(REFERENCE, rows).summary(now).freshness is Freshness.STALE  # báo nhầm cũ
    s = _service(MQ, rows).summary(now)
    assert s.session is MarketSession.DAILY_BREAK
    assert s.freshness is Freshness.MARKET_CLOSED


def test_freshness_still_stale_when_feed_dies_before_break():
    now = u(2026, 11, 5, 21, 40)
    rows = [c for c in broker_rows(START, now) if c.close_time <= u(2026, 11, 5, 20, 0)]
    assert _service(MQ, rows).summary(now).freshness is Freshness.STALE


def test_freshness_friday_after_broker_close():
    now = u(2026, 11, 7, 10)  # thứ Bảy
    rows = broker_rows(START, now)
    assert rows[-1].close_time == u(2026, 11, 6, 21, 0)
    assert _service(MQ, rows).summary(now).freshness is Freshness.MARKET_CLOSED


# ---- Cấu hình qua biến môi trường ----


def test_env_not_set_uses_reference(monkeypatch):
    monkeypatch.delenv("GT_BROKER_SESSIONS", raising=False)
    assert calendar_from_env(DataSource.MT5) is REFERENCE


def test_env_applied_for_mt5(monkeypatch):
    monkeypatch.setenv("GT_BROKER_SESSIONS", "Mon-Fri 00:00-23:00")
    monkeypatch.setenv("GT_BROKER_SERVER_TZ", "Europe/Athens")
    assert calendar_from_env(DataSource.MT5) == MQ
    assert calendar_from_env(DataSource.CSV) == MQ


def test_env_ignored_for_sample(monkeypatch):
    monkeypatch.setenv("GT_BROKER_SESSIONS", "Mon-Fri 00:00-23:00")
    monkeypatch.setenv("GT_BROKER_SERVER_TZ", "Europe/Athens")
    assert calendar_from_env(DataSource.SAMPLE) is REFERENCE


def test_env_missing_tz_fails_startup(monkeypatch):
    monkeypatch.setenv("GT_BROKER_SESSIONS", "Mon-Fri 00:00-23:00")
    monkeypatch.delenv("GT_BROKER_SERVER_TZ", raising=False)
    with pytest.raises(ValueError):
        create_app(InMemoryRepository(), data_source=DataSource.MT5, run_analysts=False)


def test_env_bad_spec_fails_startup(monkeypatch):
    monkeypatch.setenv("GT_BROKER_SESSIONS", "Mon-Fri 23:00-01:00")
    monkeypatch.setenv("GT_BROKER_SERVER_TZ", "Europe/Athens")
    with pytest.raises(ValueError):
        create_app(InMemoryRepository(), data_source=DataSource.MT5, run_analysts=False)
