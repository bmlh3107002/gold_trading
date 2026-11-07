"""1A-C21: nến cuối phiên (vị trí 0 của MT5) trước cuối tuần / ngày lễ / giờ nghỉ.

Giá trị tham chiếu tính tay (lịch broker giống máy người dùng: Mon-Fri 00:00-23:00 Europe/Athens):
- Mùa đông: Athens = UTC+2, NY = UTC−5 → broker đóng 23:00 Athens = 21:00 UTC (NY 16:00).
- Tuần lệch DST tháng 3 (NY đã EDT, Athens còn EET): broker đóng 21:00 UTC = NY 17:00.
- Mùa hè: Athens = UTC+3 → broker đóng 23:00 Athens = 20:00 UTC.
- Lễ Tạ ơn 26/11/2026: đóng sớm 14:30 NY (EST) = 19:30 UTC, mở lại 18:00 NY = 23:00 UTC.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import gold_trading.api.ingest as ingest_api
from gold_trading.contracts.candle import CandleFlag, DataSource
from gold_trading.ingestion.candles import TAIL_GRACE, TailStatus, tail_status
from gold_trading.market.hours import (
    REFERENCE,
    WEEKLY_ONLY,
    BrokerSessions,
    BrokerSpecialHours,
    MarketCalendar,
)
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.candles import InMemoryCandleStore
from gold_trading.storage.repository import InMemoryRepository
from tests.auth_helpers import user_client

ATHENS = ZoneInfo("Europe/Athens")
BROKER = BrokerSessions.parse("Mon-Fri 00:00-23:00", "Europe/Athens")
CAL = MarketCalendar(BROKER)
M15, H1, H4, D1 = Timeframe.M15, Timeframe.H1, Timeframe.H4, Timeframe.D1


def u(*a) -> datetime:
    return datetime(*a, tzinfo=UTC)


# ---------------------------------------------------------------- hàm quyết định


def test_friday_last_m15_winter_included_only_after_grace():
    tail = u(2026, 1, 16, 20, 45)  # 22:45 Athens thứ Sáu, nến cuối trước khi broker đóng 23:00
    assert tail_status(tail, None, M15, u(2026, 1, 16, 20, 59), CAL) is TailStatus.HELD_NOT_CLOSED
    just_before = u(2026, 1, 16, 21) + TAIL_GRACE - timedelta(seconds=1)
    assert tail_status(tail, None, M15, just_before, CAL) is TailStatus.HELD_NOT_CLOSED
    assert tail_status(tail, None, M15, u(2026, 1, 16, 21, 2), CAL) is TailStatus.INCLUDED
    # Thứ Bảy, Chủ nhật trước giờ mở: vẫn coi là đã đóng
    assert tail_status(tail, None, M15, u(2026, 1, 17, 12), CAL) is TailStatus.INCLUDED
    assert tail_status(tail, None, M15, u(2026, 1, 18, 21, 59), CAL) is TailStatus.INCLUDED
    # Thị trường mở lại (Chủ nhật 18:00 NY = 23:00 UTC; broker Mon 00:00 Athens = 22:00 UTC)
    assert tail_status(tail, None, M15, u(2026, 1, 18, 23, 1), CAL) is TailStatus.HELD_MARKET_OPEN


def test_friday_last_h1_h4_d1_winter():
    now = u(2026, 1, 16, 22, 2)  # Sat 00:02 Athens
    assert tail_status(u(2026, 1, 16, 20), None, H1, u(2026, 1, 16, 21, 2), CAL) is (
        TailStatus.INCLUDED
    )
    # H4 20:00 Athens = 18:00 UTC → đóng 00:00 Athens thứ Bảy = 22:00 UTC
    h4 = u(2026, 1, 16, 18)
    assert tail_status(h4, None, H4, u(2026, 1, 16, 21, 30), CAL, ATHENS) is (
        TailStatus.HELD_NOT_CLOSED
    )
    assert tail_status(h4, None, H4, now, CAL, ATHENS) is TailStatus.INCLUDED
    # D1 thứ Sáu: mở 00:00 Athens = 15/01 22:00 UTC, đóng 16/01 22:00 UTC
    d1 = u(2026, 1, 15, 22)
    # Broker đã đóng cửa lúc 21:00 UTC nhưng nến D1 chưa hết thời gian → chưa nhận
    assert tail_status(d1, None, D1, u(2026, 1, 16, 21, 30), CAL, ATHENS) is (
        TailStatus.HELD_NOT_CLOSED
    )
    assert tail_status(d1, None, D1, now, CAL, ATHENS) is TailStatus.INCLUDED


def test_dst_mismatch_week_march_and_summer():
    # 13/03/2026: NY đã EDT (UTC−4), Athens còn EET (UTC+2)
    assert tail_status(u(2026, 3, 13, 20, 45), None, M15, u(2026, 3, 13, 21, 2), CAL) is (
        TailStatus.INCLUDED
    )
    # Mùa hè 17/07/2026: broker đóng 23:00 Athens = 20:00 UTC
    assert tail_status(u(2026, 7, 17, 19, 45), None, M15, u(2026, 7, 17, 20, 2), CAL) is (
        TailStatus.INCLUDED
    )
    # D1 hè: mở 16/07 21:00 UTC, đóng 17/07 21:00 UTC (00:00 Athens thứ Bảy)
    d1 = u(2026, 7, 16, 21)
    assert tail_status(d1, None, D1, u(2026, 7, 17, 21, 1), CAL, ATHENS) is (
        TailStatus.HELD_NOT_CLOSED
    )
    assert tail_status(d1, None, D1, u(2026, 7, 17, 21, 2), CAL, ATHENS) is TailStatus.INCLUDED


def test_d1_on_dst_day_uses_real_25h_length():
    # Chủ nhật 25/10/2026 Athens lùi giờ: D1 mở 24/10 21:00 UTC (00:00 EEST), dài 25 giờ →
    # đóng 25/10 22:00 UTC (00:00 EET thứ Hai). Tính sai 24 giờ sẽ nhận sớm lúc 21:02.
    d1 = u(2026, 10, 24, 21)
    assert tail_status(d1, None, D1, u(2026, 10, 25, 21, 2), CAL, ATHENS) is (
        TailStatus.HELD_NOT_CLOSED
    )
    # Tới 22:02 UTC thì broker đã mở (thứ Hai 00:02 Athens) → không còn "đóng cửa suốt"
    assert tail_status(d1, None, D1, u(2026, 10, 25, 22, 2), CAL, ATHENS) is (
        TailStatus.HELD_MARKET_OPEN
    )


def test_daily_break_mid_week():
    # Thứ Ba 22:45 Athens (20:45 UTC): broker nghỉ 23:00–24:00 Athens
    tail = u(2026, 1, 13, 20, 45)
    assert tail_status(tail, None, M15, u(2026, 1, 13, 21, 2), CAL) is TailStatus.INCLUDED
    # Broker mở lại 00:00 Athens = 22:00 UTC, nhưng lịch tham chiếu nghỉ 17:00–18:00 NY
    # (22:00–23:00 UTC) → lịch giao nhau đóng tới 23:00 UTC
    assert tail_status(tail, None, M15, u(2026, 1, 13, 22, 59), CAL) is TailStatus.INCLUDED
    # Sau khi mở lại mà vẫn chưa có nến mới → giữ lại
    assert tail_status(tail, None, M15, u(2026, 1, 13, 23, 1), CAL) is TailStatus.HELD_MARKET_OPEN


def test_market_open_quiet_or_disconnected_is_held():
    # Giữa phiên thứ Tư: hết giờ nến nhưng thị trường mở → có thể do terminal mất kết nối
    assert tail_status(u(2026, 1, 14, 10), None, M15, u(2026, 1, 14, 10, 30), CAL) is (
        TailStatus.HELD_MARKET_OPEN
    )
    # Thứ Sáu nến 22:15 Athens: 22:30–23:00 broker còn mở mà không có nến mới → không chắc nến đủ
    tail = u(2026, 1, 16, 20, 15)
    assert tail_status(tail, None, M15, u(2026, 1, 17, 10), CAL) is TailStatus.HELD_MARKET_OPEN


def test_without_broker_sessions_never_included_early():
    # Thiếu GT_BROKER_SESSIONS: lịch tham chiếu mở tới 17:00 NY = 22:00 UTC → nến 20:45 UTC bị giữ
    # (an toàn: chậm như cũ, không bao giờ nhận sớm)
    tail = u(2026, 1, 16, 20, 45)
    assert tail_status(tail, None, M15, u(2026, 1, 17, 10), REFERENCE) is (
        TailStatus.HELD_MARKET_OPEN
    )
    # Nến cuối theo lịch tham chiếu (21:45 UTC) thì vẫn nhận được
    assert tail_status(u(2026, 1, 16, 21, 45), None, M15, u(2026, 1, 16, 22, 2), REFERENCE) is (
        TailStatus.INCLUDED
    )


def test_thanksgiving_early_close():
    tail = u(2026, 11, 26, 19, 15)  # 14:15 NY, nến cuối trước khi đóng sớm 14:30 NY
    assert tail_status(tail, None, M15, u(2026, 11, 26, 19, 32), CAL) is TailStatus.INCLUDED
    # Không có bảng ngày lễ → coi là mở cửa → giữ
    no_hol = MarketCalendar(BROKER, holidays=None)
    assert tail_status(tail, None, M15, u(2026, 11, 26, 19, 32), no_hol) is (
        TailStatus.HELD_MARKET_OPEN
    )
    # Mở lại 18:00 NY = 23:00 UTC
    assert tail_status(tail, None, M15, u(2026, 11, 26, 23, 1), CAL) is TailStatus.HELD_MARKET_OPEN


def test_broker_special_hours_close_earlier():
    special = BrokerSpecialHours.parse("2026-11-26 00:00-21:00")  # 21:00 Athens = 19:00 UTC
    cal = MarketCalendar(BROKER, special=special)
    tail = u(2026, 11, 26, 18, 45)
    assert tail_status(tail, None, M15, u(2026, 11, 26, 19, 2), cal) is TailStatus.INCLUDED
    assert tail_status(tail, None, M15, u(2026, 11, 26, 19, 2), CAL) is (
        TailStatus.HELD_MARKET_OPEN
    )


def test_not_latest_and_too_long_span_are_held():
    t = u(2026, 1, 16, 20, 45)
    assert tail_status(t, t, M15, u(2026, 1, 17, 10), CAL) is TailStatus.HELD_NOT_LATEST
    assert tail_status(t, t + M15.delta, M15, u(2026, 1, 17, 10), CAL) is (
        TailStatus.HELD_NOT_LATEST
    )
    # Khoảng đóng cửa > 7 ngày: không xác minh được → giữ (lịch tuần vẫn mở giữa chừng)
    assert tail_status(t, None, M15, u(2026, 1, 24, 10), WEEKLY_ONLY) is (
        TailStatus.HELD_MARKET_OPEN
    )


# ---------------------------------------------------------------- qua API

TOKEN = "t" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def ohlc(t, close=2405.0):
    return {"open_time": t.isoformat(), "open": 2400, "high": 2410, "low": 2390, "close": close}


def stored(store, tf=M15):
    return store.query("XAUUSD", tf, DataSource.MT5, as_of=u(2030, 1, 1))


@pytest.fixture
def api(monkeypatch):
    store = InMemoryCandleStore()
    c = user_client(
        InMemoryRepository(),
        candle_store=store,
        data_source=DataSource.MT5,
        run_sample_feed=False,
        run_analysts=False,
        ingest_token=TOKEN,
        calendar=CAL,
    )
    clock = {"now": u(2026, 1, 16, 21, 2)}
    monkeypatch.setattr(ingest_api, "utcnow", lambda: clock["now"])
    return c, store, clock


def post(c, bars, tail, tf="M15", backfill=False, dry=False):
    body = {
        "symbol": "XAUUSD",
        "timeframe": tf,
        "backfill": backfill,
        "gateway_id": "win-1",
        "server_tz": "Europe/Athens",
        "bars": bars,
    }
    if tail is not None:
        body["tail_bar"] = tail
    return c.post(f"/api/ingest/mt5/candles{'?dry_run=true' if dry else ''}", json=body,
                  headers=AUTH)


CLOSED = [ohlc(u(2026, 1, 16, 20, m)) for m in (0, 15, 30)]
TAIL = u(2026, 1, 16, 20, 45)


def test_api_tail_included_point_in_time(api):
    c, store, clock = api
    r = post(c, CLOSED, ohlc(TAIL)).json()
    assert r["tail"] == "INCLUDED" and r["accepted"] == 4 and r["quarantined"] == 0
    last = stored(store)[-1]
    assert last.open_time == TAIL and last.available_at == clock["now"]
    assert CandleFlag.BACKFILL not in last.flags
    # Thứ Hai: MT5 chuyển nến sang vị trí 1, Gateway gửi như nến thường → trùng, không nhân đôi
    clock["now"] = u(2026, 1, 18, 23, 20)
    r = post(c, [ohlc(TAIL)], None).json()
    assert r["duplicates"] == 1 and r["accepted"] == 0 and r["tail"] == "NONE"


def test_api_tail_later_corrected_becomes_revision(api):
    c, store, clock = api
    post(c, CLOSED, ohlc(TAIL))
    clock["now"] = u(2026, 1, 18, 23, 20)
    r = post(c, [ohlc(TAIL, close=2406.0)], None).json()
    assert r["revised"] == 1
    last = stored(store)[-1]
    assert last.revision == 1 and CandleFlag.REVISED in last.flags


def test_api_tail_held_not_stored(api):
    c, store, clock = api
    clock["now"] = u(2026, 1, 16, 21, 1)  # chưa qua thời gian chờ
    r = post(c, CLOSED, ohlc(TAIL)).json()
    assert r["tail"] == "HELD_NOT_CLOSED" and r["accepted"] == 3 and r["quarantined"] == 0
    assert stored(store)[-1].open_time == u(2026, 1, 16, 20, 30)
    clock["now"] = u(2026, 1, 14, 10, 30)
    r = post(c, [ohlc(u(2026, 1, 14, 9, 45))], ohlc(u(2026, 1, 14, 10))).json()
    assert r["tail"] == "HELD_MARKET_OPEN" and r["accepted"] == 1
    # Nến "đang chạy" thật (chưa hết giờ) không bao giờ bị lưu, cũng không bị cách ly
    clock["now"] = u(2026, 1, 14, 10, 7)
    r = post(c, [], ohlc(u(2026, 1, 14, 10))).json()
    assert r["tail"] == "HELD_NOT_CLOSED" and r["received"] == 0 and r["quarantined"] == 0


def test_api_tail_not_latest_held(api):
    c, _, _ = api
    r = post(c, CLOSED, ohlc(u(2026, 1, 16, 20, 30))).json()
    assert r["tail"] == "HELD_NOT_LATEST" and r["accepted"] == 3


def test_api_tail_rejected_with_backfill(api):
    c, store, _ = api
    r = post(c, CLOSED, ohlc(TAIL), backfill=True)
    assert r.status_code == 422 and "tail_bar" in r.json()["detail"]
    assert stored(store) == []


def test_api_tail_goes_through_normal_checks(api):
    c, store, clock = api
    bad = ohlc(TAIL) | {"high": 2395}  # high < open → OHLC sai
    r = post(c, CLOSED, bad).json()
    assert r["tail"] == "INCLUDED" and r["reasons"] == {"INVALID_OHLC": 1}
    clock["now"] = u(2026, 1, 16, 21, 10)
    misaligned = ohlc(TAIL + timedelta(minutes=5))
    r = post(c, CLOSED, misaligned).json()
    assert r["reasons"] == {"MISALIGNED_TIME": 1}
    assert len(stored(store)) == 3


def test_api_tail_dry_run_not_stored(api):
    c, store, _ = api
    r = post(c, CLOSED, ohlc(TAIL), dry=True).json()
    assert r["tail"] == "INCLUDED" and r["accepted"] == 4
    assert stored(store) == []


def test_api_tail_d1_friday(api):
    c, store, clock = api
    d1_closed = [ohlc(u(2026, 1, d, 22)) for d in (11, 12, 13, 14)]
    d1_tail = ohlc(u(2026, 1, 15, 22))
    r = post(c, d1_closed, d1_tail, tf="D1").json()  # 21:02 UTC: D1 chưa hết giờ
    assert r["tail"] == "HELD_NOT_CLOSED" and r["accepted"] == 4
    clock["now"] = u(2026, 1, 16, 22, 2)
    r = post(c, d1_closed, d1_tail, tf="D1").json()
    assert r["tail"] == "INCLUDED" and r["accepted"] == 1 and r["duplicates"] == 4
    last = stored(store, D1)[-1]
    assert last.close_time == u(2026, 1, 16, 22) and last.available_at == u(2026, 1, 16, 22, 2)
