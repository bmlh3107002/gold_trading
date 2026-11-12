"""ING-08 + 1A-C13/C14/C15: giá sống bid/ask/spread gom theo giây, point-in-time.

Chạy với kho bộ nhớ và SQL (SQLite)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.common.time import utcnow
from gold_trading.contracts.candle import DataSource
from gold_trading.market.feeds import feed_id_for
from gold_trading.market.quotes import (
    BASELINE_MIN,
    CALENDAR_CLOSED,
    CLOSED_MISMATCH_MIN,
    SPREAD_UNRATED,
    WIDE_SPREAD,
    QuoteIn,
    QuoteIngestor,
    check_quote,
    spread_points,
)
from gold_trading.storage.quotes import InMemoryQuoteStore, SqlQuoteStore
from gold_trading.storage.repository import InMemoryRepository, SqlRepository
from tests.auth_helpers import user_client
from tests.mt5_helpers import FEED, IDENT_FIELDS, link_active

NOW = datetime(2026, 1, 14, 10, 0, 0, tzinfo=UTC)  # thứ Tư, thị trường mở
POINT = 0.01
F = "pf_test"


class Cal:
    def __init__(self, closed=()):
        self.closed = set(closed)

    def is_open(self, t):
        return t not in self.closed


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryQuoteStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'q.db'}")
    repo.create_all()
    return SqlQuoteStore(repo.engine)


def q(t, bid=2400.10, ask=2400.30, *, low=None, high=None, smax=None, ticks=3):
    sp = spread_points(bid, ask, POINT)
    return QuoteIn(t, bid, ask, bid if low is None else low, ask if high is None else high,
                   sp if smax is None else smax, ticks)


def sec(i, base=NOW):
    return base - timedelta(seconds=i)


def ing(store, cal=None, **kw):
    return QuoteIngestor(store, cal or Cal(), **kw)


# ---------- giá trị tham chiếu ----------


def test_spread_points_reference_values():
    # (2400.35 − 2400.10) / 0.01 = 25 point; làm tròn, không cắt (float 24.99999…)
    assert spread_points(2400.10, 2400.35, 0.01) == 25
    assert spread_points(1.08501, 1.08513, 0.00001) == 12
    assert spread_points(2400.0, 2400.0, 0.01) == 0


# ---------- lưu + khử trùng ----------


def test_store_and_idempotent(store):
    g = ing(store)
    items = [q(sec(i)) for i in range(5, 0, -1)]
    r = g.ingest(items, feed=F, point=POINT, now=NOW)
    assert (r.received, r.accepted, r.duplicates, r.dropped) == (5, 5, 0, {})
    r2 = g.ingest(items, feed=F, point=POINT, now=NOW + timedelta(seconds=1))
    assert (r2.accepted, r2.duplicates, r2.conflicts) == (0, 5, 0)
    last = store.latest(F, NOW + timedelta(seconds=5))
    assert last.t == sec(1) and last.spread_points == 20 and last.available_at == NOW


def test_conflicting_resend_keeps_first(store):
    g = ing(store)
    g.ingest([q(sec(1))], feed=F, point=POINT, now=NOW)
    r = g.ingest([q(sec(1), bid=2401.0, ask=2401.2)], feed=F, point=POINT, now=NOW)
    assert (r.accepted, r.duplicates, r.conflicts) == (0, 1, 1)
    assert store.latest(F, NOW).bid == 2400.10  # không ghi đè


def test_feeds_never_mix(store):
    g = ing(store)
    g.ingest([q(sec(1))], feed="pf_a", point=POINT, now=NOW)
    g.ingest([q(sec(1), bid=2500.0, ask=2500.3)], feed="pf_b", point=POINT, now=NOW)
    assert store.latest("pf_a", NOW).bid == 2400.10
    assert store.latest("pf_b", NOW).bid == 2500.0
    assert store.latest("pf_c", NOW) is None


# ---------- 1A-C13: bản ghi lỗi ----------


@pytest.mark.parametrize(
    "bad, reason",
    [
        (q(sec(1), bid=2400.5, ask=2400.3), "CROSSED"),  # bid > ask
        (q(sec(1), bid=0.0, ask=2400.3), "NON_POSITIVE"),
        (q(sec(1), bid=-1.0, ask=2400.3), "NON_POSITIVE"),
        (q(sec(1), low=2400.2), "INCONSISTENT"),  # bid thấp nhất > bid cuối
        (q(sec(1), high=2400.2), "INCONSISTENT"),  # ask cao nhất < ask cuối
        (q(sec(1), smax=10), "INCONSISTENT"),  # spread lớn nhất < spread cuối (20)
        (q(sec(1), smax=-1), "INCONSISTENT"),
        (q(sec(1), ticks=0), "INCONSISTENT"),
        (q(NOW - timedelta(milliseconds=500)), "NOT_WHOLE_SECOND"),
        (q(NOW + timedelta(seconds=3)), "FUTURE"),
        (q(NOW - timedelta(days=31)), "TOO_OLD"),
    ],
)
def test_bad_records_dropped_and_counted_others_kept(store, bad, reason):
    r = ing(store).ingest([q(sec(3)), bad, q(sec(2))], feed=F, point=POINT, now=NOW)
    assert r.dropped == {reason: 1}
    assert r.accepted == 2
    assert [x.t for x in store.window(F, sec(10), NOW)] == [sec(3), sec(2)]


def test_naive_time_rejected():
    assert check_quote(q(datetime(2026, 1, 14, 10)), POINT, NOW, NOW - timedelta(days=1)) \
        == "NOT_WHOLE_SECOND"


def test_spread_rounding_tolerance_one_point():
    # bid/ask cho spread 20.4 → 20; khai spread lớn nhất 19 vẫn chấp nhận (lệch làm tròn 1 point)
    assert check_quote(q(sec(1), smax=19), POINT, NOW, sec(100)) is None
    assert check_quote(q(sec(1), smax=18), POINT, NOW, sec(100)) == "INCONSISTENT"


def test_exactly_now_plus_tolerance_accepted():
    assert check_quote(q(NOW + timedelta(seconds=2)), POINT, NOW, sec(100)) is None


def test_duplicate_second_in_batch_keeps_first(store):
    r = ing(store).ingest([q(sec(1)), q(sec(1), bid=2401.0, ask=2401.2)], feed=F, point=POINT,
                          now=NOW)
    assert r.dropped == {"DUPLICATE_IN_BATCH": 1} and r.accepted == 1
    assert store.latest(F, NOW).bid == 2400.10


def test_out_of_order_and_late_arrival_keep_history_order_point_in_time(store):
    g = ing(store)
    g.ingest([q(sec(1)), q(sec(5)), q(sec(3))], feed=F, point=POINT, now=NOW)
    assert [x.t for x in store.window(F, sec(10), NOW)] == [sec(5), sec(3), sec(1)]
    late = NOW + timedelta(seconds=30)
    g.ingest([q(sec(4), bid=2399.0, ask=2399.2)], feed=F, point=POINT, now=late)
    rows = store.window(F, sec(10), NOW)
    assert [x.t for x in rows] == [sec(5), sec(4), sec(3), sec(1)]
    assert rows[1].available_at == late  # biết lúc nào thì ghi lúc đó
    # point-in-time: tại NOW chưa thấy giây đến muộn; "mới nhất" vẫn là giây gần nhất
    assert store.latest(F, NOW).t == sec(1)


def test_bad_point_rejected(store):
    for p in (0.0, -0.01, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            ing(store).ingest([q(sec(1))], feed=F, point=p, now=NOW)


# ---------- 1A-C14: spread giãn ----------


def baseline(store, g, n=BASELINE_MIN, spread=20, start=200):
    items = [q(sec(start - i), bid=2400.0, ask=2400.0 + spread * POINT) for i in range(n)]
    g.ingest(items, feed=F, point=POINT, now=NOW)


def test_not_enough_baseline_is_unrated_not_normal(store):
    g = ing(store)
    baseline(store, g, n=BASELINE_MIN - 1)
    g.ingest([q(sec(1), bid=2400.0, ask=2401.0)], feed=F, point=POINT, now=NOW)
    row = store.latest(F, NOW)
    assert SPREAD_UNRATED in row.flags and WIDE_SPREAD not in row.flags


def test_wide_spread_flag_boundary_and_real_value_kept(store):
    g = ing(store)
    baseline(store, g)  # trung vị 20 point → ngưỡng 3 × 20 = 60
    r = g.ingest([q(sec(2), bid=2400.0, ask=2400.60),  # 60: không giãn (phải > 60)
                  q(sec(1), bid=2400.0, ask=2400.61)], feed=F, point=POINT, now=NOW)
    assert r.wide_spread == 1
    rows = {x.t: x for x in store.window(F, sec(3), NOW)}
    assert rows[sec(2)].flags == ()
    assert WIDE_SPREAD in rows[sec(1)].flags and rows[sec(1)].spread_points == 61


def test_wide_spread_uses_max_within_second(store):
    g = ing(store)
    baseline(store, g)
    g.ingest([q(sec(1), bid=2400.0, ask=2400.2, smax=80)], feed=F, point=POINT, now=NOW)
    assert WIDE_SPREAD in store.latest(F, NOW).flags


def test_baseline_only_last_hour_and_ignores_closed_seconds(store):
    closed = {sec(150 - i) for i in range(BASELINE_MIN)}
    g = ing(store, Cal(closed))
    # 60 giây "đóng cửa" spread 2 point: không được dùng làm chuẩn
    g.ingest([q(t, bid=2400.0, ask=2400.02) for t in sorted(closed)], feed=F, point=POINT,
             now=NOW)
    # 60 giây cũ hơn 1 giờ: ngoài cửa sổ
    g.ingest([q(sec(4000 + i), bid=2400.0, ask=2400.02) for i in range(BASELINE_MIN)], feed=F,
             point=POINT, now=NOW)
    g.ingest([q(sec(1), bid=2400.0, ask=2400.2)], feed=F, point=POINT, now=NOW)
    assert SPREAD_UNRATED in store.latest(F, NOW).flags


# ---------- 1A-C15: giá khi lịch nói đóng cửa ----------


def test_closed_calendar_flag_and_mismatch_threshold(store):
    closed = {sec(i) for i in range(1, 200)}
    g = ing(store, Cal(closed))
    r = g.ingest([q(sec(i)) for i in range(CLOSED_MISMATCH_MIN - 1, 0, -1)], feed=F, point=POINT,
                 now=NOW)
    assert r.calendar_closed == CLOSED_MISMATCH_MIN - 1 and not r.calendar_mismatch
    assert CALENDAR_CLOSED in store.latest(F, NOW).flags  # vẫn lưu, kèm cờ
    r = g.ingest([q(sec(CLOSED_MISMATCH_MIN))], feed=F, point=POINT, now=NOW)
    assert r.calendar_mismatch


def test_closed_seconds_outside_10_minutes_do_not_count(store):
    closed = {sec(i) for i in range(1, 2000)}
    g = ing(store, Cal(closed))
    g.ingest([q(sec(700 + i)) for i in range(CLOSED_MISMATCH_MIN)], feed=F, point=POINT,
             now=NOW)
    r = g.ingest([q(sec(1))], feed=F, point=POINT, now=NOW)
    assert not r.calendar_mismatch


# ---------- giữ dữ liệu ----------


def test_retention_purge_throttled(store):
    g = ing(store, retention=timedelta(days=1), purge_every=timedelta(hours=1))
    g.ingest([q(sec(10))], feed=F, point=POINT, now=NOW)  # lần xóa đầu: lúc NOW
    from gold_trading.market.quotes import QuoteSecond

    stale = QuoteSecond(F, NOW - timedelta(days=2), 2400.0, 2400.2, 2400.0, 2400.2, 20, 20, 1,
                        (), NOW, NOW)
    store.append([stale])
    g.ingest([], feed=F, point=POINT, now=NOW + timedelta(minutes=30))  # chưa tới lượt xóa
    assert store.window(F, NOW - timedelta(days=3), NOW)[0].t == stale.t
    g.ingest([], feed=F, point=POINT, now=NOW + timedelta(hours=1))
    rows = store.window(F, NOW - timedelta(days=3), NOW + timedelta(hours=2))
    assert [x.t for x in rows] == [sec(10)]  # chỉ xóa dòng quá 1 ngày


def test_retention_env(monkeypatch):
    from gold_trading.api.app import quote_retention_days

    monkeypatch.delenv("GT_QUOTE_RETENTION_DAYS", raising=False)
    assert quote_retention_days() == 30
    monkeypatch.setenv("GT_QUOTE_RETENTION_DAYS", "7")
    assert quote_retention_days() == 7
    for bad in ("0", "400", "abc"):
        monkeypatch.setenv("GT_QUOTE_RETENTION_DAYS", bad)
        with pytest.raises(ValueError):
            quote_retention_days()


# ---------- API ----------

TOKEN = "t" * 32
URL = "/api/ingest/mt5/quotes"


def api(linked=True, **kw):
    repo = InMemoryRepository()
    if linked:
        link_active(repo)
    store = InMemoryQuoteStore()
    c = user_client(repo, data_source=DataSource.MT5, run_sample_feed=False, run_analysts=False,
                    ingest_token=TOKEN, quote_store=store, **kw)
    return c, store, repo


def body(seconds, **over):
    b = {"symbol": "XAUUSD", "gateway_id": "win-1", "point": POINT, "seconds": seconds,
         **IDENT_FIELDS}
    b.update(over)
    return b


def wire(t, bid=2400.10, ask=2400.30, **kw):
    return {"t": t.isoformat(), "bid": bid, "ask": ask, "bid_low": kw.get("low", bid),
            "ask_high": kw.get("high", ask), "spread_max_points": kw.get("smax", 20),
            "ticks": kw.get("ticks", 2)}


def now_s():
    return utcnow().replace(microsecond=0)


def post(c, b, token=TOKEN):
    return c.post(URL, json=b, headers={"Authorization": f"Bearer {token}"})


def test_api_stores_in_linked_feed():
    c, store, _ = api()
    t = now_s() - timedelta(seconds=2)
    r = post(c, body([wire(t), wire(t - timedelta(seconds=1)),
                      wire(t, bid=2400.5, ask=2400.7)]))
    assert r.status_code == 200, r.text
    j = r.json()
    assert (j["accepted"], j["dropped"]) == (2, {"DUPLICATE_IN_BATCH": 1})
    assert store.latest(FEED, utcnow()).t == t


def test_api_requires_token_and_active_link():
    c, _, _ = api(linked=False)
    t = now_s() - timedelta(seconds=1)
    assert post(c, body([wire(t)]), token="x" * 32).status_code == 401
    r = post(c, body([wire(t)]))
    assert r.status_code == 409 and r.json()["detail"].startswith("MT5_LINK_REQUIRED")


def test_api_other_mt5_is_mismatch_and_not_stored():
    c, store, repo = api()
    t = now_s() - timedelta(seconds=1)
    r = post(c, body([wire(t)], mt5_login=999))
    assert r.status_code == 409 and r.json()["detail"].startswith("MT5_LINK_MISMATCH")
    assert store.latest(FEED, utcnow()) is None
    assert [x.status for x in repo.mt5_links("default") if x.status == "MISMATCH"]


def test_api_symbol_locked_to_link():
    c, store, _ = api()
    t = now_s() - timedelta(seconds=1)
    assert post(c, body([wire(t)])).status_code == 200
    r = post(c, body([wire(t)], broker_symbol="XAUUSD.r"))
    assert r.status_code == 409 and r.json()["detail"].startswith("MT5_LINK_SYMBOL")
    assert store.latest(feed_id_for("Broker-Demo", "XAUUSD.r"), utcnow()) is None


@pytest.mark.parametrize("over", [{"symbol": "EURUSD"}, {"point": 0}, {"point": -0.01},
                                  {"mt5_account_type": "X"}, {"broker_symbol": "XAU USD"}])
def test_api_validation(over):
    c, _, _ = api()
    assert post(c, body([wire(now_s() - timedelta(seconds=1))], **over)).status_code == 422


def test_api_empty_batch_ok():
    c, _, _ = api()
    r = post(c, body([]))
    assert r.status_code == 200 and r.json()["received"] == 0


def test_api_batch_size_limit_and_missing_identity():
    c, _, _ = api()
    t0 = now_s() - timedelta(seconds=700)
    many = [wire(t0 + timedelta(seconds=i)) for i in range(601)]
    assert post(c, body(many)).status_code == 422
    b = body([wire(now_s())])
    del b["mt5_login"]
    assert post(c, b).status_code == 422


def test_api_validation_error_does_not_echo_values():
    c, _, _ = api()
    r = post(c, body([wire(now_s())], point="bí-mật"))
    assert r.status_code == 422 and "bí-mật" not in r.text


# ---------- DSH-07: đọc giá sống theo tài khoản ----------

from gold_trading.api.market import QUOTE_STALE_AFTER, live_quote  # noqa: E402
from gold_trading.market.quotes import QuoteSecond  # noqa: E402

QURL = "/api/accounts/default/market/quote"


def row(t, avail=None, flags=()):
    return QuoteSecond(F, t, 2400.1, 2400.3, 2400.0, 2400.4, 20, 40, 3, tuple(flags), t,
                       avail or t)


def test_live_quote_states_reference():
    st = InMemoryQuoteStore()
    assert live_quote(None, st, Cal(), NOW).state == "NO_FEED"
    assert live_quote(F, st, Cal(), NOW).state == "NO_DATA"
    st.append([row(NOW - QUOTE_STALE_AFTER)])
    q = live_quote(F, st, Cal(), NOW)
    assert (q.state, q.age_seconds, q.bid, q.ask, q.spread_points, q.spread_max_points) == \
        ("LIVE", 15.0, 2400.1, 2400.3, 20, 40)
    later = NOW + timedelta(seconds=1)
    assert live_quote(F, st, Cal(), later).state == "STALE"  # thị trường mở mà giá cũ > 15 s
    assert live_quote(F, st, Cal({later}), later).state == "CLOSED"  # lịch đóng cửa
    assert live_quote(F, st, Cal({later}), later).market_open is False


def test_live_quote_point_in_time_and_flags():
    st = InMemoryQuoteStore()
    st.append([row(NOW - timedelta(seconds=5), flags=(WIDE_SPREAD,)),
               row(NOW - timedelta(seconds=1), avail=NOW + timedelta(seconds=3))])
    q = live_quote(F, st, Cal(), NOW)
    assert q.t == NOW - timedelta(seconds=5) and q.flags == [WIDE_SPREAD]  # chưa "biết" giây sau


def test_api_quote_flow_owner_only():
    c, store, repo = api()
    assert c.get(QURL).json()["state"] == "NO_FEED"  # liên kết chưa ghi lô đầu (chưa khóa symbol)
    t = now_s() - timedelta(seconds=1)
    assert post(c, body([wire(t, bid=2400.10, ask=2400.35, smax=30)])).status_code == 200
    j = c.get(QURL).json()
    assert j["state"] == "LIVE" and j["bid"] == 2400.10 and j["ask"] == 2400.35
    assert j["spread_points"] == 25 and j["spread_max_points"] == 30
    assert SPREAD_UNRATED in j["flags"]
    # người khác / ADMIN không xem được
    from tests.auth_helpers import client as http_client
    from tests.auth_helpers import login_owner

    other = login_owner(c.app, c.kc, repo, "bob", "acc_other")
    assert other.get(QURL).status_code == 404
    assert other.get("/api/accounts/acc_other/market/quote").json()["state"] == "NO_FEED"
    adm = http_client(c.app)
    c.kc.login(adm, "admin", admin=True)
    assert adm.get(QURL).status_code == 404
    assert http_client(c.app).get(QURL).status_code == 401


def test_api_quote_sample_source_has_no_live_quote():
    repo = InMemoryRepository()
    link_active(repo)
    c = user_client(repo, data_source=DataSource.SAMPLE, run_sample_feed=False,
                    run_analysts=False, ingest_token=TOKEN)
    assert c.get(QURL).json()["state"] == "NO_FEED"  # không bịa bid/ask từ nến mẫu
