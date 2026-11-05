from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.analysts.indicators import ema, rsi
from gold_trading.contracts.candle import DataSource
from gold_trading.ingestion.candles import CandleIngestor, RawBar
from gold_trading.ingestion.sources import csv_file, sample
from gold_trading.market.hours import MarketSession, session_at
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.candles import InMemoryCandleStore

TF = Timeframe.M15


# ---- Lịch thị trường (giờ New York, tự xử lý DST) ----


@pytest.mark.parametrize(
    ("utc", "expected"),
    [
        (datetime(2026, 1, 6, 14, 0, tzinfo=UTC), MarketSession.OPEN),
        (datetime(2026, 1, 6, 22, 30, tzinfo=UTC), MarketSession.DAILY_BREAK),  # 17:30 NY mùa đông
        (datetime(2026, 7, 7, 21, 30, tzinfo=UTC), MarketSession.DAILY_BREAK),  # 17:30 NY mùa hè
        (datetime(2026, 7, 7, 22, 30, tzinfo=UTC), MarketSession.OPEN),  # 18:30 NY mùa hè
        (datetime(2026, 1, 10, 12, 0, tzinfo=UTC), MarketSession.WEEKEND),  # thứ Bảy
        (datetime(2026, 1, 9, 22, 30, tzinfo=UTC), MarketSession.WEEKEND),  # thứ Sáu sau đóng cửa
        (datetime(2026, 1, 11, 22, 30, tzinfo=UTC), MarketSession.WEEKEND),  # CN trước 18:00 NY
        (datetime(2026, 1, 11, 23, 30, tzinfo=UTC), MarketSession.OPEN),  # CN sau 18:00 NY
    ],
)
def test_sessions(utc, expected):
    assert session_at(utc) is expected


# ---- Dữ liệu mẫu ----


def _gen(days=10, seed=1):
    end = datetime(2026, 1, 16, 12, 0, tzinfo=UTC)
    return list(
        sample.generate(
            start=end - timedelta(days=days), end=end, tf=TF, prev_close=2400.0, seed=seed
        )
    )


def test_sample_is_deterministic_and_valid():
    a, b = _gen(), _gen()
    assert a == b
    assert _gen(seed=2) != a
    for x in a:
        assert x.high >= max(x.open, x.close) and x.low <= min(x.open, x.close) > 0
        assert session_at(x.open_time) is MarketSession.OPEN


def test_sample_passes_ingestion_without_quarantine():
    store = InMemoryCandleStore()
    bars = _gen()
    r = CandleIngestor(store).ingest(
        bars,
        symbol="XAUUSD",
        timeframe=TF,
        source=DataSource.SAMPLE,
        ingested_at=datetime(2026, 1, 16, 12, 0, tzinfo=UTC),
        backfill=True,
    )
    assert r.quarantined == 0 and r.accepted == len(bars) > 500


# ---- CSV ----

MT5_CSV = (
    "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
    "2026.01.06\t16:00:00\t2400.10\t2402.00\t2399.50\t2401.20\t812\t0\t18\n"  # mùa đông GMT+2
    "2026.07.07\t16:00:00\t2400.10\t2402.00\t2399.50\t2401.20\t812\t0\t18\n"  # mùa hè GMT+3
    "2026.01.06\tbad\t1\t1\t1\t1\t0\t0\t0\n"
    "2026.01.06\t16:15:00\tx\t1\t1\t1\t0\t0\t0\n"
)


def test_mt5_csv_converts_server_time_to_utc():
    bars, rejects = csv_file.parse(MT5_CSV, server_tz="Europe/Athens")
    assert [b.open_time for b in bars] == [
        datetime(2026, 1, 6, 14, 0, tzinfo=UTC),
        datetime(2026, 7, 7, 13, 0, tzinfo=UTC),
    ]
    assert bars[0].tick_volume == 812 and bars[0].spread_points == 18
    assert [(r.line, r.reason) for r in rejects] == [(4, "BAD_TIME"), (5, "BAD_NUMBER")]


def test_mt5_csv_requires_server_timezone():
    with pytest.raises(csv_file.CsvFormatError, match="múi giờ"):
        csv_file.parse(MT5_CSV, server_tz=None)


def test_generic_csv_with_explicit_offset():
    text = "time,open,high,low,close,volume\n2026-01-06T16:00:00+02:00,1,2,0.5,1.5,10\n"
    bars, _ = csv_file.parse(text, server_tz=None)
    assert bars[0].open_time == datetime(2026, 1, 6, 14, 0, tzinfo=UTC)


def test_ambiguous_dst_hour_rejected_not_guessed():
    # 25/10/2026 03:30 giờ Athens xảy ra hai lần (lùi giờ)
    text = "time,open,high,low,close\n2026-10-25 03:30:00,1,2,0.5,1.5\n"
    bars, rejects = csv_file.parse(text, server_tz="Europe/Athens")
    assert bars == [] and rejects[0].reason == "AMBIGUOUS_LOCAL_TIME"


def test_missing_columns():
    with pytest.raises(csv_file.CsvFormatError, match="close"):
        csv_file.parse("time,open,high,low\n2026-01-06T16:00:00Z,1,2,0.5\n", server_tz=None)


# ---- Chỉ báo ----


def test_ema_seeded_with_sma():
    out = ema([1, 2, 3, 4, 5], 3)
    assert out[:2] == [None, None]
    assert out[2] == pytest.approx(2.0)  # SMA(1,2,3)
    assert out[3] == pytest.approx(3.0)  # 0.5*4 + 0.5*2
    assert out[4] == pytest.approx(4.0)


def test_rsi_reference_values():
    # Ví dụ kinh điển của StockCharts. Họ làm tròn lãi/lỗ trung bình (0.24/0.10) nên ra 70.53;
    # giá trị chính xác: lãi 3.34/14, lỗ 1.40/14 → RS = 2.3857 → RSI = 70.464.
    closes = [
        44.34,
        44.09,
        44.15,
        43.61,
        44.33,
        44.83,
        45.10,
        45.42,
        45.84,
        46.08,
        45.89,
        46.03,
        45.61,
        46.28,
        46.28,
    ]
    out = rsi(closes, 14)
    assert out[13] is None
    assert out[14] == pytest.approx(70.464, abs=0.001)
    assert rsi(list(range(20)), 14)[-1] == 100.0
    assert rsi(list(range(20, 0, -1)), 14)[-1] == pytest.approx(0.0)


def test_cli_import_csv_into_sqlite(tmp_path, monkeypatch, capsys):
    from gold_trading.ingestion import cli
    from gold_trading.storage.candles import SqlCandleStore
    from gold_trading.storage.repository import SqlRepository

    db = f"sqlite:///{tmp_path / 'x.db'}"
    SqlRepository.from_url(db).create_all()
    f = tmp_path / "x.csv"
    f.write_text(MT5_CSV)
    monkeypatch.setenv("DATABASE_URL", db)
    assert cli.main(["import-csv", str(f), "--server-tz", "Europe/Athens"]) == 0
    assert "thêm 2" in capsys.readouterr().out
    store = SqlCandleStore(SqlRepository.from_url(db).engine)
    st = store.stats("XAUUSD", TF, DataSource.CSV)
    assert st.count == 2 and st.quarantined == 2
    # Nạp lại cùng file: không nhân đôi
    assert cli.main(["import-csv", str(f), "--server-tz", "Europe/Athens"]) == 0
    assert "thêm 0, trùng 2" in capsys.readouterr().out


# ---- Độ mới dữ liệu ----


def _svc_with_last_bar(open_time):
    from gold_trading.market.service import MarketDataService

    store = InMemoryCandleStore()
    CandleIngestor(store).ingest(
        [RawBar(open_time, 1, 2, 0.5, 1.5)],
        symbol="XAUUSD",
        timeframe=TF,
        source=DataSource.SAMPLE,
        ingested_at=open_time + TF.delta,
        backfill=False,
    )
    return MarketDataService(store, source=DataSource.SAMPLE)


FRI_LAST = datetime(2026, 1, 9, 21, 45, tzinfo=UTC)  # nến 16:45–17:00 NY thứ Sáu


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 1, 10, 12, 0, tzinfo=UTC), "MARKET_CLOSED"),  # thứ Bảy, đủ nến
        (datetime(2026, 1, 11, 23, 1, tzinfo=UTC), "FRESH"),  # vừa mở cửa CN 18:01 NY
        (datetime(2026, 1, 11, 23, 16, tzinfo=UTC), "FRESH"),  # nến đầu tuần mới đóng 1 phút
        (datetime(2026, 1, 11, 23, 18, tzinfo=UTC), "STALE"),  # quá 2 phút vẫn chưa có
    ],
)
def test_freshness_around_weekend(now, expected):
    assert _svc_with_last_bar(FRI_LAST).summary(now).freshness == expected


def test_outage_before_weekend_is_not_hidden():
    thu = datetime(2026, 1, 8, 15, 0, tzinfo=UTC)
    sat = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
    assert _svc_with_last_bar(thu).summary(sat).freshness == "STALE"


def test_cli_rejects_h4():
    from gold_trading.ingestion import cli

    with pytest.raises(SystemExit):
        cli.main(["import-csv", "x.csv", "--timeframe", "H4"])


def _mt5_rows(start_utc, n, tz_name):
    """Sinh CSV kiểu MT5 với giờ server = giờ UTC đổi sang tz_name."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz_name)
    lines = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>"]
    bars = list(
        sample.generate(
            start=start_utc, end=start_utc + timedelta(days=30), tf=TF, prev_close=2400.0, seed=3
        )
    )[:n]
    for b in bars:
        local = b.open_time.astimezone(tz)
        lines.append(
            f"{local:%Y.%m.%d}\t{local:%H:%M:%S}\t{b.open}\t{b.high}\t{b.low}\t{b.close}\t1"
        )
    return "\n".join(lines) + "\n"


def test_session_check_accepts_correct_timezone_and_rejects_wrong_one():
    text = _mt5_rows(datetime(2026, 2, 2, tzinfo=UTC), 600, "Europe/Athens")
    good, _ = csv_file.parse(text, server_tz="Europe/Athens")
    assert csv_file.check_sessions(good, 15).ok
    wrong, _ = csv_file.parse(text, server_tz="UTC")  # khai báo sai: lệch 2 giờ
    chk = csv_file.check_sessions(wrong, 15)
    assert not chk.ok and chk.best_shift_hours == -2 and chk.best_outside_fraction <= 0.01


def test_cli_refuses_file_with_wrong_timezone(tmp_path, monkeypatch, capsys):
    from gold_trading.ingestion import cli

    f = tmp_path / "w.csv"
    f.write_text(_mt5_rows(datetime(2026, 2, 2, tzinfo=UTC), 600, "Europe/Athens"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'n.db'}")
    assert cli.main(["import-csv", str(f), "--server-tz", "UTC"]) == 3
    err = capsys.readouterr().err
    assert "TỪ CHỐI" in err and "-2 giờ" in err
