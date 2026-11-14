"""GĐ3 bước 4 — Macro bằng luật (MAC-01, MAC-02; 3-C01..C08). Thiết kế: docs/thiet-ke/30."""

import math
from datetime import UTC, date, datetime, timedelta

import pytest

from gold_trading.analysts import macro as MA
from gold_trading.analysts.framework import Scope
from gold_trading.common.enums import SourceStatus
from gold_trading.contracts.candle import DataSource
from gold_trading.contracts.records import NormalizedRecord
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.market import usd_index as U
from gold_trading.market.feeds import feed_id_for
from gold_trading.market.service import MarketDataService
from gold_trading.market.timeframes import Timeframe
from gold_trading.orchestrator.dispatcher import routes_for
from gold_trading.orchestrator.model import Event, EventType
from gold_trading.orchestrator.scanner import candle_event, expired_event
from gold_trading.storage.analyst_outputs import ExpiredOutput, InMemoryAnalystOutputStore
from gold_trading.storage.candles import InMemoryCandleStore
from gold_trading.storage.repository import InMemoryRepository, PriceFeed

from .test_usd_index import PRICES, SERVER, bar

NOW = datetime(2026, 11, 12, 14, 0, tzinfo=UTC)          # thứ Năm
M15 = timedelta(minutes=15)
GOLD = feed_id_for(SERVER, "XAUUSD")


def h15(series, day: date, value, known=None, rev=0, status="AVAILABLE"):
    et = datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(days=1, hours=5)
    return NormalizedRecord(
        record_id=f"fed_h15:{series}:{day}:r{rev}", source="fed_h15", kind="macro",
        logical_key=f"{series}:{day.isoformat()}", revision=rev, event_time=et,
        ingested_at=known or et, available_at=None,
        source_status=SourceStatus.HEALTHY, payload_version="t", raw_ref="t",
        payload={"series": series, "date": day.isoformat(), "value": value,
                 "value_status": status})


def workdays(n, end=date(2026, 11, 11)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def rate_path(start: float, changes_bp: list[float]) -> list[str]:
    v, out = start, [f"{start:.2f}"]
    for c in changes_bp:
        v += c / 100
        out.append(f"{v:.2f}")
    return out


def load_rates(st, series, values, end=date(2026, 11, 11)):
    for d, v in zip(workdays(len(values), end), values, strict=True):
        st.append(h15(series, d, v))


def alternating(n, step=2.0, last=None):
    ch = [step if i % 2 == 0 else -step for i in range(n)]
    if last is not None:
        ch[-1] = last
    return ch


def load_usd(repo, candles, n_bars, end=NOW, jpy=None):
    times = [end - M15 * (n_bars - i) for i in range(n_bars)]
    items = []
    for pair, p in PRICES.items():
        repo.ensure_price_feed(PriceFeed(feed_id_for(SERVER, pair), SERVER, pair, NOW))
        for i, t in enumerate(times):
            price = jpy(i) if (pair == "USDJPY" and jpy) else p
            items.append(bar(pair, t, price))
    candles.append(items, [])
    return times


@pytest.fixture
def env():
    repo, candles, st = InMemoryRepository(), InMemoryCandleStore(), PointInTimeStore()
    repo.ensure_price_feed(PriceFeed(GOLD, SERVER, "XAUUSD", NOW))
    return repo, candles, st


def run(env, at=NOW, server=SERVER, feed=GOLD):
    repo, candles, st = env
    return MA.compute(repo=repo, candle_store=candles, record_store=st,
                      scope=Scope.of_feed("XAUUSD", Timeframe.M15, DataSource.MT5, feed),
                      mt5_server=server, as_of=at)


def load_all_rates(st, real_ch=None, nom_ch=None):
    load_rates(st, MA.REAL_10Y, rate_path(1.80, real_ch or alternating(40)))
    load_rates(st, MA.NOM_10Y, rate_path(4.10, nom_ch or alternating(40)))
    load_rates(st, MA.NOM_2Y, rate_path(3.60, alternating(40)))


# ------------------------------------------------------------------ H.15: giá trị tham chiếu tay

def test_rate_view_hand_reference():
    """Thay đổi ±2 đcb xen kẽ (số chẵn, trung bình 0) → độ lệch chuẩn đúng 2 đcb.
    Thay đổi cuối +2 → z1 = 2/2 = 1; tổng 5 thay đổi cuối = +2 → z5 = 2/(2·√5) = 0,4472."""
    st = PointInTimeStore()
    load_rates(st, MA.REAL_10Y, rate_path(1.80, alternating(40)[::-1]))
    v = MA.rate_view(st, MA.REAL_10Y, NOW)
    assert v["status"] == "OK" and v["date"] == "2026-11-11"
    assert v["change_1d_bp"] == 2.0 and v["change_5d_bp"] == 2.0
    assert v["z_1d"] == 1.0 and v["z_5d"] == round(2 / (2 * math.sqrt(5)), 3)
    assert v["direction"] == "FLAT" and v["history"] == 41


def test_rate_view_stale_missing_and_na_cells():
    st = PointInTimeStore()
    assert MA.rate_view(st, MA.REAL_10Y, NOW)["status"] == "MISSING"
    load_rates(st, MA.REAL_10Y, rate_path(1.80, alternating(30)), end=date(2026, 11, 2))
    assert MA.rate_view(st, MA.REAL_10Y, NOW)["status"] == "STALE"       # 10 ngày
    st.append(h15(MA.REAL_10Y, date(2026, 11, 11), None, status="NOT_AVAILABLE"))
    v = MA.rate_view(st, MA.REAL_10Y, NOW)                               # "n.a." không thành 0
    assert v["date"] == "2026-11-02" and v["status"] == "STALE"


# ------------------------------------------------------------------ luật bias

@pytest.mark.parametrize("dirs,want", [
    ({"a": "DOWN", "b": "DOWN"}, "SUPPORTIVE"), ({"a": "DOWN", "b": "FLAT"}, "SUPPORTIVE"),
    ({"a": "UP", "b": "UP"}, "HEADWIND"), ({"a": "UP", "b": None}, "HEADWIND"),
    ({"a": "UP", "b": "DOWN"}, "MIXED"), ({"a": "FLAT", "b": "FLAT"}, "NEUTRAL"),
    ({"a": None, "b": None}, "INSUFFICIENT_DATA"),
])
def test_bias_rule(dirs, want):
    assert MA.bias(dirs) == want


# ------------------------------------------------------------------ USD

def test_usd_series_matches_usd_index_and_hand_z(env):
    """USDJPY xen kẽ ×1,001 / ÷1,001 → lợi suất log của chỉ số = ±0,136·ln(1,001) (trung bình 0
    trên số chẵn bước) → độ lệch chuẩn đúng giá trị đó; 96 / 480 nến (chẵn) → thay đổi 0, z = 0."""
    repo, candles, _ = env
    n = MA.USD_HISTORY_BARS + MA.WEEK_BARS + 1
    load_usd(repo, candles, n, jpy=lambda i: 150.0 * (1.001 if i % 2 else 1.0))
    v = MA.usd_view(repo, candles, SERVER, NOW)
    cur = U.usd_index_for_server(repo, candles, SERVER, NOW)
    assert v["status"] == "OK" and v["value"] == cur.value
    assert v["series_last"] == pytest.approx(cur.value, abs=1e-4)
    assert v["change_1d_pct"] == 0.0 and v["z_1d"] == 0.0 and v["direction"] == "FLAT"


def test_usd_strong_rise_direction_up(env):
    repo, candles, _ = env
    n = MA.USD_HISTORY_BARS + MA.WEEK_BARS + 1
    load_usd(repo, candles, n,
             jpy=lambda i: 150.0 * (1.001 if i % 2 else 1.0) * (1 + 0.0004 * max(0, i - n + 480)))
    v = MA.usd_view(repo, candles, SERVER, NOW)
    assert v["direction"] == "UP" and v["z_5d"] >= 1 and v["change_5d_pct"] > 0


def test_usd_unavailable_keeps_running_with_cap(env):
    repo, candles, st = env
    load_all_rates(st)
    o = run(env)                                         # không có nến cặp tiền nào
    assert o.source_status is SourceStatus.HEALTHY
    assert "USD_INDEX_UNAVAILABLE" in o.quality_flags and o.confidence == 0.5
    assert o.features["bias_drivers"]["usd_index"] is None
    assert run(env, server=None).features["usd_index"]["reason"] == "NO_MT5_SERVER"


def test_usd_short_history_flagged(env):
    repo, candles, st = env
    load_all_rates(st)
    load_usd(repo, candles, 100)
    o = run(env)
    assert "OPTIONAL_INSUFFICIENT_HISTORY:usd_index" in o.quality_flags and o.confidence == 0.5


# ------------------------------------------------------------------ đầu ra + đầu vào xấu

def test_full_output_supportive_when_real_yield_falls(env):
    repo, candles, st = env
    load_all_rates(st, real_ch=alternating(36) + [-8, -8, -8, -8])
    load_usd(repo, candles, MA.USD_HISTORY_BARS + MA.WEEK_BARS + 1,
             jpy=lambda i: 150.0 * (1.001 if i % 2 else 1.0))
    o = run(env)
    f = o.features
    assert o.source_status is SourceStatus.HEALTHY and o.confidence == 1.0
    assert f["rates"]["real_yield_10y"]["direction"] == "DOWN"
    assert f["macro_bias"] == "SUPPORTIVE" and "REAL_YIELD_10Y_DOWN" in o.drivers
    assert f["fed_proxy"]["status"] in ("OK", "INSUFFICIENT_DATA")
    assert o.expires_at == NOW + MA.TTL
    assert o.output_id.startswith("macro:macro-1.0.0:MT5:")


def test_conflict_mixed_lowers_confidence(env):
    repo, candles, st = env
    load_all_rates(st, real_ch=alternating(36) + [-8, -8, -8, -8])
    n = MA.USD_HISTORY_BARS + MA.WEEK_BARS + 1
    load_usd(repo, candles, n,
             jpy=lambda i: 150.0 * (1.001 if i % 2 else 1.0) * (1 + 0.0004 * max(0, i - n + 480)))
    o = run(env)
    assert o.features["macro_bias"] == "MIXED"
    assert "MACRO_DRIVERS_CONFLICT" in o.drivers and o.confidence == 0.5


def test_stress_flag_on_extreme_daily_move(env):
    _, _, st = env
    load_all_rates(st, real_ch=alternating(39) + [40])
    o = run(env)
    assert "MACRO_STRESS" in o.risk_flags and "STRESS:real_yield_10y" in o.drivers


def test_real_yield_missing_blocks(env):
    _, _, st = env
    load_rates(st, MA.NOM_10Y, rate_path(4.10, alternating(40)))
    o = run(env)
    assert o.source_status is SourceStatus.MISSING
    assert "MISSING_INPUT:real_yield_10y" in o.drivers and set(o.features) == {"input"}


def test_real_yield_stale_blocks(env):
    _, _, st = env
    load_rates(st, MA.REAL_10Y, rate_path(1.80, alternating(30)), end=date(2026, 11, 2))
    o = run(env)
    assert o.source_status is SourceStatus.STALE and "STALE_INPUT:real_yield_10y" in o.drivers


def test_real_yield_short_history_invalid(env):
    _, _, st = env
    load_rates(st, MA.REAL_10Y, rate_path(1.80, alternating(4)))      # 5 quan sát < 6
    o = run(env)
    assert o.source_status is SourceStatus.INVALID
    assert "INSUFFICIENT_HISTORY:real_yield_10y" in o.drivers


def test_real_yield_week_of_history_levels_without_z(env):
    """Máy người dùng: H.15 chỉ hiện ~5 ngày, mới nạp từ 12/11 → vài tuần đầu < 21 quan sát:
    vẫn có mức + thay đổi, KHÔNG có z / hướng / bias (không đoán), trần confidence 0,5."""
    _, _, st = env
    load_rates(st, MA.REAL_10Y, rate_path(1.80, [-3, -3, -3, -3, -3, -3, -3]))
    o = run(env)
    r = o.features["rates"]["real_yield_10y"]
    assert o.source_status is SourceStatus.HEALTHY
    assert r["change_5d_bp"] == -15.0 and r["z_5d"] is None and r["direction"] is None
    assert o.features["macro_bias"] == "INSUFFICIENT_DATA" and not o.features["bias_complete"]
    assert "Z_HISTORY_SHORT:real_yield_10y" in o.quality_flags and o.confidence == 0.5


def test_revision_known_later_does_not_rewrite_past(env):
    """3-C06 + "revision không viết lại quyết định quá khứ"."""
    _, _, st = env
    load_all_rates(st)
    before = run(env)
    st.append(h15(MA.REAL_10Y, date(2026, 11, 11), "9.99", known=NOW + timedelta(hours=1),
                  rev=1))
    assert run(env) == before
    later = run(env, at=NOW + timedelta(hours=2))
    assert later.features["rates"]["real_yield_10y"]["value"] == "9.99"
    assert "MACRO_STRESS" in later.risk_flags


# ------------------------------------------------------------------ orchestrator

def test_router_macro_recompute():
    e = expired_event(ExpiredOutput("macro", "XAUUSD", "M15", "MT5", GOLD, "id", NOW))
    assert [r.job_type for r in routes_for(e)] == ["INVALIDATE_MARKETVIEW", "MACRO"]


def test_targets_and_handler_skip(env):
    repo, candles, st = env
    load_all_rates(st)
    other = feed_id_for("Other-Server", "XAUUSD")
    repo.ensure_price_feed(PriceFeed(other, "Other-Server", "XAUUSD", NOW))
    outs = InMemoryAnalystOutputStore()
    ma = MA.MacroAnalyst(repo=repo, candle_store=candles, record_store=st, out_store=outs,
                         market=MarketDataService(candles, source=DataSource.MT5),
                         active_feeds=lambda: [GOLD, other])
    times = load_usd(repo, candles, 10)
    pair_bar = bar("EURUSD", times[-1], 1.08)
    assert ma.targets(candle_event(pair_bar)) == [GOLD]                 # chỉ vàng cùng server
    upd = Event(EventType.MACRO_UPDATED, "fed_h15:x", "r0", occurred_at=NOW, known_at=NOW)
    assert ma.targets(upd) == [GOLD, other]
    h = MA.macro_handler(ma)
    assert h.run(candle_event(pair_bar), NOW + timedelta(seconds=10)) == \
        "macro:stored=1,skipped=0"
    assert h.run(candle_event(pair_bar), NOW + timedelta(seconds=11)) == \
        "macro:stored=0,skipped=1"
    assert ma.ensure_fresh(NOW + timedelta(seconds=12)) == 1           # chỉ nguồn còn thiếu
    assert ma.ensure_fresh(NOW + timedelta(seconds=13)) == 0


def test_api_macro_latest_own_account():
    from .auth_helpers import user_client
    outs = InMemoryAnalystOutputStore()
    candles = InMemoryCandleStore()
    st = PointInTimeStore()
    load_all_rates(st)
    c = user_client(InMemoryRepository(), candle_store=candles, analyst_store=outs,
                    data_source=DataSource.SAMPLE, run_sample_feed=False, run_analysts=False,
                    external_runner=None)
    url = "/api/accounts/default/analysts/macro/latest"
    assert c.get(url).json()["output"] is None
    market = MarketDataService(candles, source=DataSource.SAMPLE)
    ma = MA.MacroAnalyst(repo=None, candle_store=candles, record_store=st, out_store=outs,
                         market=market, active_feeds=lambda: [""])
    from gold_trading.common.time import utcnow
    now = utcnow()
    assert ma.run_at("", NOW, now) is True
    body = c.get(url).json()
    assert body["output"]["analyst_id"] == "macro"
    assert body["output"]["features"]["usd_index"]["reason"] == "NO_MT5_SERVER"
    assert c.get("/api/accounts/khac/analysts/macro/latest").status_code == 404
