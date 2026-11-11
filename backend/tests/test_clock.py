"""OPS-12: kiểm tra đồng hồ. Case 0-C09 (đồng hồ lệch → cảnh báo / chặn nạp nến)."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from email.utils import format_datetime

import httpx
import pytest

from gold_trading.contracts.candle import DataSource
from gold_trading.market.timeframes import Timeframe
from gold_trading.ops.clock import SOURCES, ClockMonitor, classify, measure_offset
from gold_trading.storage.candles import InMemoryCandleStore
from gold_trading.storage.repository import InMemoryRepository
from tests.auth_helpers import client, make_app
from tests.mt5_helpers import FEED, link_active
from tests.test_ingest_api import HB, bars, batch

LOCAL_NOW = 1_800_000_000.25  # đồng hồ backend (giây epoch)
TOKEN = "t" * 32


def transport(true_offsets: dict[str, float | None]):
    """Mỗi nguồn trả Date = giờ chuẩn; local nhanh hơn giờ chuẩn ``offset`` giây.
    None = nguồn lỗi kết nối; 'bad' = header hỏng."""

    def handler(req: httpx.Request) -> httpx.Response:
        off = true_offsets.get(str(req.url), 0.0)
        if off is None:
            raise httpx.ConnectError("down", request=req)
        if off == "bad":
            return httpx.Response(200, headers={"date": "not a date"})
        server = math.floor(LOCAL_NOW - off)  # Date bị cắt xuống tới giây
        dt = datetime.fromtimestamp(server, UTC)
        return httpx.Response(200, headers={"date": format_datetime(dt, usegmt=True)})

    return httpx.Client(transport=httpx.MockTransport(handler))


def monitor(offsets, **kw):
    return ClockMonitor(transport(offsets), now=lambda: LOCAL_NOW, **kw)


def all_sources(off):
    return {u: off for u in SOURCES}


@pytest.mark.parametrize(
    "off,state", [(0.0, "OK"), (1.5, "OK"), (-1.5, "OK"), (5, "WARN"), (-12, "WARN"),
                  (31, "BLOCKED"), (-45, "BLOCKED"), (3600, "BLOCKED")],
)
def test_offset_classification(off, state):
    st = monitor(all_sources(off)).check()
    assert st.state == state
    assert st.offset_s == pytest.approx(off, abs=1.0)  # sai số do Date chỉ tới giây
    assert st.sources_ok == 5


def test_median_ignores_one_wrong_source():
    offs = all_sources(0.0)
    offs[SOURCES[0]] = 7200  # một máy chủ trả giờ sai
    assert monitor(offs).check().state == "OK"


def test_too_few_sources_is_unknown_not_ok():
    offs = {u: None for u in SOURCES}
    offs[SOURCES[0]] = 0.0
    offs[SOURCES[1]] = "bad"
    offs[SOURCES[2]] = 0.0
    st = monitor(offs).check()
    assert st.state == "UNKNOWN" and st.offset_s is None and st.sources_ok == 2
    assert monitor(offs, unknown_blocks=True).check().state == "BLOCKED"


def test_classify_boundaries():
    assert classify(2.0) == "OK" and classify(2.01) == "WARN"
    assert classify(30.0) == "WARN" and classify(30.01) == "BLOCKED"
    assert classify(None) == "UNKNOWN"


def test_measure_offset_slow_responses_dropped():
    t = iter([0.0, 10.0] * 5)
    off, n = measure_offset(transport(all_sources(0.0)), now=lambda: LOCAL_NOW + next(t))
    assert off is None and n == 0


def ingest_world(mon: ClockMonitor):
    store = InMemoryCandleStore()
    repo = InMemoryRepository()
    link_active(repo)
    app, kc = make_app(repo, candle_store=store, data_source=DataSource.MT5,
                       run_analysts=False, ingest_token=TOKEN, clock=mon)
    c = client(app)
    kc.login(c, "admin", admin=True)
    return c, store


def test_blocked_clock_stops_candle_ingest_until_fixed():
    """0-C09: lệch > 30 s (ví dụ Docker Desktop sau khi máy ngủ) → ngừng nhận nến, lỗi rõ."""
    offs = all_sources(-40.0)
    mon = ClockMonitor(transport(offs), now=lambda: LOCAL_NOW)
    mon.check()
    c, store = ingest_world(mon)
    auth = {"Authorization": f"Bearer {TOKEN}"}
    r = c.post("/api/ingest/mt5/candles", json=batch(bars(20)), headers=auth)
    assert r.status_code == 503 and "đồng hồ" in r.json()["detail"]
    assert store.stats("XAUUSD", Timeframe.M15, DataSource.MT5, feed=FEED).count == 0
    # Nhịp tim vẫn nhận để Dashboard thấy Gateway còn sống
    assert c.post("/api/ingest/mt5/heartbeat", json=HB, headers=auth).status_code == 200
    h = c.get("/api/system/health").json()["clock"]
    assert h["state"] == "BLOCKED" and h["offset_s"] == pytest.approx(-40, abs=1)

    offs.update(all_sources(0.5))  # đồng hồ được sửa
    mon._client = transport(offs)
    mon.check()
    r = c.post("/api/ingest/mt5/candles", json=batch(bars(20)), headers=auth)
    assert r.status_code == 200 and r.json()["accepted"] == 20


def test_warn_and_unknown_do_not_block_ingest():
    for offs in (all_sources(8.0), {u: None for u in SOURCES}):
        mon = monitor(offs)
        mon.check()
        c, _ = ingest_world(mon)
        r = c.post("/api/ingest/mt5/candles", json=batch(bars(5)),
                   headers={"Authorization": f"Bearer {TOKEN}"})
        assert r.status_code == 200, mon.status


def test_health_requires_login():
    mon = monitor(all_sources(0))
    app, _ = make_app(InMemoryRepository(), clock=mon, data_source=None)
    anon = client(app)
    assert anon.get("/api/system/health").status_code == 401
