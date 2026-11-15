"""GĐ3 bước 7c — báo cáo ngưỡng R3 / R5 trên dữ liệu thật (TEC-05). Chỉ đọc."""

from datetime import UTC, datetime, timedelta

from gold_trading.contracts.candle import Candle, DataSource
from gold_trading.ingestion import cli
from gold_trading.market.feeds import feed_id_for
from gold_trading.market.quality import assess_window
from gold_trading.market.timeframes import Timeframe
from gold_trading.ops import quality_report as QR
from gold_trading.storage.candles import SqlCandleStore
from gold_trading.storage.repository import PriceFeed, SqlRepository

M = timedelta(minutes=15)
T0 = datetime(2026, 1, 5, 1, 0, tzinfo=UTC)
FEED = feed_id_for("MetaQuotes-Demo", "XAUUSD")


def series(n=400, spike_at=None, release_at=None, wide_at=None, source=DataSource.CSV, feed=""):
    out = []
    for i in range(n):
        t = T0 + M * i
        o = 2400.0 + (i % 5) * 0.5
        rng = 2.0
        if i in (spike_at, release_at):
            rng = 40.0                                     # 20 × trung vị biên độ (2)
        sp = 60 if i == wide_at else 20
        out.append(Candle(symbol="XAUUSD", timeframe=Timeframe.M15, source=source, feed_id=feed,
                          open_time=t, close_time=t + M, open=o, high=o + rng / 2,
                          low=o - rng / 2, close=o, spread_points=sp, ingested_at=t + M,
                          available_at=t + M))
    return out


def test_ratios_match_quality_gate_and_flags_events():
    rows = series(spike_at=350, release_at=380, wide_at=390)
    rel = rows[380].open_time
    rep = QR.analyze(rows, [(rel - M, rel + 2 * M)])
    kinds = {(e.open_time, e.kind) for e in rep.r3}
    assert (rows[350].open_time, "RANGE") in kinds and (rows[380].open_time, "RANGE") in kinds
    by = {e.open_time: e for e in rep.r3}
    assert by[rows[380].open_time].in_release_window is True      # trùng giờ công bố
    assert by[rows[350].open_time].in_release_window is False     # không trùng → kiểm biểu đồ
    assert rep.r5 == []                                            # 60/20 = đúng 3×: không vượt
    # Cùng cửa sổ như cổng chất lượng Technical: nến 350 cũng là spike ở đó
    assert rows[350].open_time in assess_window(rows[51:351], Timeframe.M15).spikes


def test_wide_spread_strictly_above_threshold():
    rows = series(wide_at=390)
    rows[390] = Candle(**{**rows[390].model_dump(), "spread_points": 61})
    rep = QR.analyze(rows)
    assert [round(e.ratio, 2) for e in rep.r5] == [3.05]


def test_no_lookahead_and_since_window():
    rows = series(n=400, spike_at=399)
    a = QR.analyze(rows[:399])
    b = QR.analyze(rows)
    assert a.range_ratios == b.range_ratios[:len(a.range_ratios)]  # nến cũ không đổi khi thêm mới
    s = QR.analyze(rows, since=rows[300].open_time)
    assert s.bars == 100 and s.first == rows[300].open_time


def test_percentiles_and_render():
    assert QR.pct([1, 2, 3, 4, 5], 0.5) == 3 and QR.pct([], 0.5) is None
    rep = QR.analyze(series(spike_at=350), [])
    text = "\n".join(QR.render(rep, "srv / XAUUSD"))
    assert "R3 biên độ / trung vị" in text and "KHÔNG trùng giờ công bố" in text
    assert "vượt 8×" in text


def test_cli_read_only(tmp_path, capsys):
    url = f"sqlite:///{tmp_path / 'q.db'}"
    repo = SqlRepository.from_url(url)
    repo.create_all()
    repo.ensure_price_feed(PriceFeed(FEED, "MetaQuotes-Demo", "XAUUSD", T0))
    cs = SqlCandleStore(repo.engine)
    cs.append(series(spike_at=350, source=DataSource.MT5, feed=FEED), [])
    now = T0 + M * 401
    assert cli._nguong(3, env={"DATABASE_URL": url}, now=now) == 0
    out = capsys.readouterr().out
    assert "MetaQuotes-Demo / XAUUSD" in out and "Chỉ đọc" in out
    assert len(cs.query("XAUUSD", Timeframe.M15, DataSource.MT5, as_of=now, end=now,
                        limit=1000, feed=FEED)) == 400               # không ghi gì


def test_cli_no_gold_feed(tmp_path, capsys):
    url = f"sqlite:///{tmp_path / 'e.db'}"
    SqlRepository.from_url(url).create_all()
    assert cli._nguong(3, env={"DATABASE_URL": url}) == 1
