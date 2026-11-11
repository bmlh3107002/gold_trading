"""MT-05 (phần lưu trữ) + DEC-14 + ING-15 (symbol): nguồn giá theo (server broker, symbol broker).

Không trộn giá giữa hai broker; cùng server + symbol dùng chung; symbol khóa vào liên kết; màn
hình thị trường chung chỉ đọc nguồn của tài khoản cấp giá; thiếu nguồn → không có dữ liệu.
Chạy với cả kho bộ nhớ và SQL (SQLite).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.analysts.runner import TechnicalRunner
from gold_trading.common.time import utcnow
from gold_trading.contracts.candle import DataSource
from gold_trading.market.feeds import feed_id_for
from gold_trading.market.service import MarketDataService
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.analyst_outputs import InMemoryAnalystOutputStore
from gold_trading.storage.candles import InMemoryCandleStore, SqlCandleStore
from gold_trading.storage.repository import InMemoryRepository, SqlRepository
from tests.auth_helpers import client, login_owner, make_app
from tests.mt5_helpers import BROKER_SYMBOL, FEED, IDENT_FIELDS, LOGIN, SERVER, link_active
from tests.test_ingest_api import TOKEN, bars, batch

CANDLES = "/api/ingest/mt5/candles"
TF = Timeframe.M15
TOK_B = "gtk_" + "b" * 40


def test_feed_id_reference_values():
    """So với giá trị tính tay: sha256("broker-demo\\0XAUUSD")[:24]."""
    want = "pf_" + hashlib.sha256(b"broker-demo\0XAUUSD").hexdigest()[:24]
    assert feed_id_for("Broker-Demo", "XAUUSD") == want
    assert feed_id_for("BROKER-DEMO", "XAUUSD") == want  # server không phân biệt hoa/thường
    assert feed_id_for("Broker-Demo", "xauusd") != want  # symbol broker giữ nguyên chữ
    assert feed_id_for("Broker-Live", "XAUUSD") != want
    assert feed_id_for("Broker-Demo", "XAUUSD.r") != want
    assert len(want) <= 64
    # Ký tự điều khiển (vd. NUL: "a\0b"+"c" và "a"+"b\0c" sẽ ra cùng mã) / khoảng trắng → từ chối
    for bad in (("", "XAUUSD"), ("S", ""), ("a", "b\0c"), ("a\0b", "c"), (" S", "X"),
                ("S", "X "), ("S\t", "X")):
        with pytest.raises(ValueError):
            feed_id_for(*bad)


@pytest.fixture(params=["memory", "sqlite"])
def kind(request):
    return request.param


class World:
    def __init__(self, kind, tmp_path):
        if kind == "memory":
            self.repo = InMemoryRepository()
            self.store = InMemoryCandleStore()
        else:
            self.repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'gt.db'}")
            self.repo.create_all()
            self.store = SqlCandleStore(self.repo.engine)
        self.app, self.kc = make_app(self.repo, candle_store=self.store,
                                     data_source=DataSource.MT5, run_analysts=False,
                                     run_sample_feed=False, ingest_token=TOKEN)
        self.a = login_owner(self.app, self.kc, self.repo, "alice")  # tài khoản "default"
        self.b = login_owner(self.app, self.kc, self.repo, "bob", "acc_b")
        self.repo.rotate_gateway_token("acc_b", TOK_B, "t", utcnow())
        self.gw = client(self.app)

    def post(self, body, tok=TOKEN, dry=False):
        return self.gw.post(CANDLES + ("?dry_run=true" if dry else ""), json=body,
                            headers={"Authorization": f"Bearer {tok}"})

    def count(self, feed):
        return self.store.stats("XAUUSD", TF, DataSource.MT5, feed=feed).count


@pytest.fixture
def w(kind, tmp_path):
    return World(kind, tmp_path)


def shifted(rows, delta):
    return [r | {"open": r["open"] + delta, "high": r["high"] + delta, "low": r["low"] + delta,
                 "close": r["close"] + delta} for r in rows]


def test_two_brokers_never_mixed(w):
    link_active(w.repo)  # default: Broker-Demo
    link_active(w.repo, "acc_b", login=777, server="Other-Live")
    base = bars(50)
    assert w.post(batch(base)).json()["accepted"] == 50
    other = batch(shifted(base, 5.0)) | {"mt5_login": 777, "mt5_server": "Other-Live"}
    r = w.post(other, tok=TOK_B)
    # Cùng open_time, khác giá: nguồn khác → nhận hết, KHÔNG thành revision của nguồn kia
    assert r.status_code == 200 and r.json()["accepted"] == 50 and r.json()["revised"] == 0
    fb = feed_id_for("Other-Live", BROKER_SYMBOL)
    assert w.count(FEED) == 50 and w.count(fb) == 50
    a = w.store.query("XAUUSD", TF, DataSource.MT5, as_of=datetime(2030, 1, 1, tzinfo=UTC),
                      feed=FEED)
    b = w.store.query("XAUUSD", TF, DataSource.MT5, as_of=datetime(2030, 1, 1, tzinfo=UTC),
                      feed=fb)
    assert all(x.close + 5.0 == y.close for x, y in zip(a, b, strict=True))
    assert {x.feed_id for x in a} == {FEED} and {y.feed_id for y in b} == {fb}
    # Nguồn "" (SAMPLE/CSV/không gắn broker) không thấy gì
    assert w.count("") == 0


def test_same_server_and_symbol_share_one_feed(w):
    link_active(w.repo)
    w.repo.end_account_links("default", "t", utcnow(), "test")  # nhường MT5 (MT-C11)
    # Hai MT5 KHÁC login, cùng broker server + symbol → cùng một nguồn giá
    link_active(w.repo, "default", login=111)
    link_active(w.repo, "acc_b", login=222)
    base = bars(30)
    assert w.post(batch(base) | {"mt5_login": 111}).json()["accepted"] == 30
    r = w.post(batch(base) | {"mt5_login": 222}, tok=TOK_B).json()
    assert r["accepted"] == 0 and r["duplicates"] == 30
    assert w.count(FEED) == 30


def test_broker_symbol_locked_on_first_write(w):
    link_active(w.repo)
    assert w.post(batch(bars(10))).status_code == 200
    link = w.repo.mt5_links("default")[-1]
    assert link.broker_symbol == BROKER_SYMBOL
    assert w.repo.price_feed(FEED).broker_symbol == BROKER_SYMBOL
    assert w.repo.price_feed(FEED).mt5_server == SERVER
    binds = [e for e in w.repo.audit(500, account_id="default") if e.action == "price_feed.bind"]
    assert len(binds) == 1 and binds[0].payload["feed_id"] == FEED
    # Đổi symbol broker (XAUUSD → XAUUSD.r): nguồn khác → từ chối, không ghi gì
    r = w.post(batch(bars(12)) | {"broker_symbol": "XAUUSD.r"})
    assert r.status_code == 409 and r.json()["detail"].startswith("MT5_LINK_SYMBOL")
    assert w.count(feed_id_for(SERVER, "XAUUSD.r")) == 0 and w.count(FEED) == 10
    # Gửi lại đúng symbol cũ → vẫn được; audit bind không lặp
    assert w.post(batch(bars(12))).status_code == 200
    assert len([e for e in w.repo.audit(500, account_id="default")
                if e.action == "price_feed.bind"]) == 1
    # Muốn dùng symbol mới: gỡ liên kết + liên kết lại → nguồn mới
    w.repo.end_account_links("default", "t", utcnow(), "test")
    link_active(w.repo)
    r = w.post(batch(bars(12)) | {"broker_symbol": "XAUUSD.r"})
    assert r.status_code == 200 and w.count(feed_id_for(SERVER, "XAUUSD.r")) == 12


def test_missing_broker_symbol_rejected(w):
    link_active(w.repo)
    body = batch(bars(5))
    body.pop("broker_symbol")
    r = w.post(body)
    assert r.status_code == 409 and r.json()["detail"].startswith("MT5_LINK_REQUIRED")
    assert "0.5.0" in r.json()["detail"]
    assert w.repo.mt5_links("default")[-1].broker_symbol is None  # không khóa gì
    assert w.post(batch(bars(5)) | {"broker_symbol": ""}).status_code == 422
    assert w.post(batch(bars(5)) | {"broker_symbol": "X" * 65}).status_code == 422
    for bad in ("XAU USD", "XAU\x00", " XAUUSD", "XAUÜSD"):
        assert w.post(batch(bars(5)) | {"broker_symbol": bad}).status_code == 422


def test_dry_run_dedupes_against_the_right_feed(w):
    link_active(w.repo)
    w.post(batch(bars(20)))
    r = w.post(batch(bars(20)), dry=True).json()
    assert r["duplicates"] == 20 and r["accepted"] == 0
    # Cùng nến nhưng của broker khác (chưa có dữ liệu) → chạy thử thấy là mới
    r = w.post(batch(bars(20)) | {"mt5_server": "Other-Live"}, dry=True).json()
    assert r["accepted"] == 20
    assert w.count(feed_id_for("Other-Live", BROKER_SYMBOL)) == 0
    # Tên server lạ trong chạy thử: không lỗi 500
    assert w.post(batch(bars(5)) | {"mt5_server": " Bad\tName"}, dry=True).status_code == 200


def test_quarantine_tagged_with_feed(w):
    link_active(w.repo)
    bad = bars(3)
    bad[1] = bad[1] | {"high": bad[1]["low"] - 1}
    r = w.post(batch(bad)).json()
    assert r["quarantined"] == 1
    q = w.store.quarantine(10)
    assert q[0].feed_id == FEED
    assert w.store.stats("XAUUSD", TF, DataSource.MT5, feed=FEED).quarantined == 1
    assert w.store.stats("XAUUSD", TF, DataSource.MT5, feed="").quarantined == 0


# ---------- MT-05 phần đọc: mỗi tài khoản đọc nguồn của mình ----------


def mk(c, acc, what="candles"):
    return c.get(f"/api/accounts/{acc}/market/{what}")


def test_each_account_reads_only_its_own_feed(w):
    link_active(w.repo, "acc_b", login=777, server="Other-Live")
    assert w.post(batch(bars(30)) | {"mt5_login": 777, "mt5_server": "Other-Live"},
                  tok=TOK_B).status_code == 200
    # alice chưa liên kết: không có dữ liệu, KHÔNG mượn nguồn của bob
    assert mk(w.a, "default").json()["candles"] == []
    assert mk(w.a, "default", "quality").json()["candle_count"] == 0
    assert mk(w.a, "default", "summary").json()["last_price"] is None
    assert len(mk(w.b, "acc_b").json()["candles"]) == 30
    link_active(w.repo)
    w.post(batch(shifted(bars(30), 100.0)))
    a = mk(w.a, "default").json()["candles"]
    b = mk(w.b, "acc_b").json()["candles"]
    assert len(a) == 30 and len(b) == 30
    assert a[-1]["close"] == b[-1]["close"] + 100.0
    assert mk(w.a, "default", "quality").json()["candle_count"] == 30
    assert mk(w.a, "default", "summary").json()["last_price"] == a[-1]["close"]


def test_no_global_mt5_price(w):
    """DEC-14: không có "nguồn giá chung" cho MT5 — màn hình không gắn tài khoản luôn rỗng."""
    link_active(w.repo)
    w.post(batch(bars(30)))
    assert w.a.get("/api/market/candles").json()["candles"] == []
    assert w.a.get("/api/market/quality").json()["candle_count"] == 0
    assert w.a.get("/api/analysts/technical/latest").json()["output"] is None


def test_account_market_endpoints_owner_only(w):
    link_active(w.repo)
    w.post(batch(bars(10)))
    admin = client(w.app)
    w.kc.login(admin, "root", admin=True)
    for path in ("market/candles", "market/summary", "market/quality",
                 "analysts/technical/latest"):
        url = f"/api/accounts/default/{path}"
        assert w.b.get(url).status_code == 404  # tài khoản người khác
        assert admin.get(url).status_code == 404  # ADMIN không vào tài khoản giao dịch
        assert client(w.app).get(url).status_code == 401
        assert w.a.get(url).status_code == 200
    w.repo.set_user_status(w.a.sub, "LOCKED", utcnow())
    assert w.a.get("/api/accounts/default/market/candles").status_code in (401, 403)


def test_mismatched_link_still_shows_its_old_feed(w):
    """MISMATCH chặn GHI; nến cũ của đúng nguồn vẫn xem được (độ mới sẽ báo cũ)."""
    link_active(w.repo)
    w.post(batch(bars(10)))
    w.post(batch(bars(10)) | {"mt5_login": 999})  # MT5 khác → MISMATCH
    assert w.repo.mt5_links("default")[-1].status == "MISMATCH"
    assert len(mk(w.a, "default").json()["candles"]) == 10


def test_market_linked_but_not_yet_written_has_no_data(w):
    link_active(w.repo)  # chưa có lô nến nào → chưa khóa symbol → chưa có nguồn
    assert mk(w.a, "default", "quality").json()["candle_count"] == 0


def test_runner_analyses_each_feed_separately():
    from gold_trading.analysts import technical
    from gold_trading.ingestion.candles import CandleIngestor
    from gold_trading.ingestion.sources import sample

    store = InMemoryCandleStore()
    end = datetime(2026, 1, 16, 12, 0, tzinfo=UTC)
    raw = list(sample.generate(start=datetime(2026, 1, 2, tzinfo=UTC), end=end,
                               tf=TF, prev_close=2400, seed=3))
    from gold_trading.ingestion.candles import RawBar

    ing = CandleIngestor(store)
    for feed, d in (("pf_a", 0.0), ("pf_b", 50.0)):
        ing.ingest([RawBar(b.open_time, b.open + d, b.high + d, b.low + d, b.close + d,
                           b.tick_volume, b.spread_points) for b in raw],
                   symbol="XAUUSD", timeframe=TF, source=DataSource.MT5,
                   ingested_at=end, backfill=True, feed=feed)
    market = MarketDataService(store, source=DataSource.MT5, feed_resolver=lambda: None)
    out = InMemoryAnalystOutputStore()
    feeds = {"v": ["pf_a", "pf_b"]}
    runner = TechnicalRunner(market, out, feeds=lambda: feeds["v"])
    assert runner.tick(raw[-1].open_time + TF.delta + timedelta(minutes=1)) is True
    la = out.latest(technical.ANALYST_ID, symbol="XAUUSD", tf=TF, source=DataSource.MT5,
                    feed="pf_a")
    lb = out.latest(technical.ANALYST_ID, symbol="XAUUSD", tf=TF, source=DataSource.MT5,
                    feed="pf_b")
    assert la is not None and lb is not None and la.output.output_id != lb.output.output_id
    assert out.latest(technical.ANALYST_ID, symbol="XAUUSD", tf=TF, source=DataSource.MT5,
                      feed="") is None
    # Một nguồn lỗi không chặn nguồn khác
    feeds["v"] = ["pf_bad", "pf_a"]
    orig = market.with_feed

    def boom(resolver):
        m = orig(resolver)
        if resolver and resolver() == "pf_bad":
            raise RuntimeError("hỏng")
        return m

    market.with_feed = boom
    runner.tick(end)  # không ném lỗi ra ngoài


def test_runner_skips_without_feed_and_stores_per_feed():
    store = InMemoryCandleStore()
    feed = {"v": None}
    market = MarketDataService(store, source=DataSource.MT5, feed_resolver=lambda: feed["v"])
    out = InMemoryAnalystOutputStore()
    runner = TechnicalRunner(market, out)
    assert runner.tick(datetime(2026, 1, 16, 12, 5, tzinfo=UTC)) is False
    assert market.candles(as_of=datetime(2030, 1, 1, tzinfo=UTC), limit=10) == []
    assert market.stats() is None and market.quarantine() == []
    feed["v"] = "pf_x"
    assert market.feed == "pf_x"
    # Kết quả analyst gắn feed: nguồn khác không đọc được
    from gold_trading.analysts import technical

    assert out.latest(technical.ANALYST_ID, symbol="XAUUSD", tf=TF, source=DataSource.MT5,
                      feed="pf_y") is None


def test_identity_fields_contain_broker_symbol():
    assert IDENT_FIELDS["broker_symbol"] == BROKER_SYMBOL and IDENT_FIELDS["mt5_login"] == LOGIN


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_identical_candles_on_two_feeds_each_get_analyst_output(kind, tmp_path):
    """Lỗi tìm được khi soát: hai broker có nến GIỐNG HỆT nhau → output_id trùng → nguồn thứ hai
    không bao giờ có kết quả analyst. Giờ duy nhất theo (feed, output_id)."""
    from gold_trading.analysts import technical
    from gold_trading.ingestion.candles import CandleIngestor, RawBar
    from gold_trading.ingestion.sources import sample
    from gold_trading.storage.analyst_outputs import SqlAnalystOutputStore

    if kind == "memory":
        store, out = InMemoryCandleStore(), InMemoryAnalystOutputStore()
    else:
        repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'a.db'}")
        repo.create_all()
        store, out = SqlCandleStore(repo.engine), SqlAnalystOutputStore(repo.engine)
    end = datetime(2026, 1, 16, 12, 0, tzinfo=UTC)
    raw = list(sample.generate(start=datetime(2026, 1, 2, tzinfo=UTC), end=end, tf=TF,
                               prev_close=2400, seed=3))
    ing = CandleIngestor(store)
    for feed in ("pf_a", "pf_b"):
        ing.ingest([RawBar(b.open_time, b.open, b.high, b.low, b.close, b.tick_volume,
                           b.spread_points) for b in raw], symbol="XAUUSD", timeframe=TF,
                   source=DataSource.MT5, ingested_at=end, backfill=True, feed=feed)
    market = MarketDataService(store, source=DataSource.MT5, feed_resolver=lambda: None)
    runner = TechnicalRunner(market, out, feeds=lambda: ["pf_a", "pf_b"])
    assert runner.tick(raw[-1].open_time + TF.delta + timedelta(minutes=1)) is True
    got = [out.latest(technical.ANALYST_ID, symbol="XAUUSD", tf=TF, source=DataSource.MT5,
                      feed=f) for f in ("pf_a", "pf_b")]
    assert all(g is not None for g in got)
    assert got[0].output.output_id == got[1].output.output_id  # cùng nội dung, mỗi nguồn một bản
    assert runner.tick(raw[-1].open_time + TF.delta + timedelta(minutes=1)) is False
