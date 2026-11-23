"""GĐ6 bước 2 — cơ sở dữ liệu backtest riêng + nạp CSV (cả H4 / D1) + báo cáo dữ liệu."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import inspect

from gold_trading.backtest import cli
from gold_trading.backtest import data as BD
from gold_trading.backtest.db import BacktestDbError, init_db, resolve_url, same_database
from gold_trading.market.hours import is_open
from gold_trading.market.timeframes import Timeframe

ATH = ZoneInfo("Europe/Athens")
PG = "postgresql+psycopg://gold:secret@db:5432/gold_trading"


# ---------------------------------------------------------------------- DB riêng


@pytest.mark.parametrize("a,b,same", [
    (PG, "postgresql://other:pw2@db:5432/gold_trading", True),        # khác user / mật khẩu
    (PG, "postgresql+psycopg2://gold@DB/gold_trading", True),          # khác driver, cổng mặc định
    ("postgresql://u@localhost/x", "postgresql://u@127.0.0.1:5432/x", True),
    (PG, "postgresql+psycopg://gold:secret@db:5432/gold_backtest", False),   # khác tên DB
    (PG, "postgresql+psycopg://gold:secret@db2:5432/gold_trading", False),   # khác máy
    (PG, "postgresql+psycopg://gold:secret@db:5433/gold_trading", False),    # khác cổng
    ("sqlite:///a/b.db", "sqlite:///a/../a/b.db", True),
    ("sqlite:///a/b.db", "sqlite:///a/c.db", False),
    ("sqlite://", "sqlite://", False),                                      # bộ nhớ: không trùng
])
def test_same_database(a, b, same):
    assert same_database(a, b) is same


def test_resolve_url_requires_separate_db():
    with pytest.raises(BacktestDbError, match="Chưa đặt"):
        resolve_url({"DATABASE_URL": PG})
    with pytest.raises(BacktestDbError, match="CÙNG"):
        resolve_url({"DATABASE_URL": PG,
                     "GT_BACKTEST_DATABASE_URL": "postgresql://x:y@db/gold_trading"})
    ok = "postgresql+psycopg://gold:secret@db:5432/gold_backtest"
    assert resolve_url({"DATABASE_URL": PG, "GT_BACKTEST_DATABASE_URL": ok}) == ok
    assert resolve_url({"GT_BACKTEST_DATABASE_URL": ok}) == ok             # không có DB thật


def test_init_db_sqlite_and_refuses_live(tmp_path):
    url = f"sqlite:///{tmp_path / 'bt.db'}"
    assert init_db(url, env={}) == "SQLite: create_all"
    from sqlalchemy import create_engine
    names = set(inspect(create_engine(url)).get_table_names())
    assert {"candles", "backtest_registrations", "backtest_holdout_runs"} <= names
    with pytest.raises(BacktestDbError):
        init_db(url, env={"DATABASE_URL": url})


def test_init_db_postgres_never_runs_alembic_against_live():
    calls = []
    with pytest.raises(BacktestDbError):
        init_db(PG, env={"DATABASE_URL": PG}, run=lambda *a, **k: calls.append(a))
    assert calls == []


# ---------------------------------------------------------------------- CSV


def mt5_csv(start: datetime, days: int, tf: str = "M15", drop=(), spread=20,
            tz: ZoneInfo = ATH) -> str:
    """CSV kiểu MT5 (giờ server Athens). M1–H1: mỗi nến trong giờ mở cửa; H4 / D1: căn theo giờ
    server, chỉ ngày thứ Hai–thứ Sáu (giờ server)."""
    lines = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    tfo = Timeframe(tf)
    p = 2000.0
    if tfo.server_aligned:
        step = 4 if tf == "H4" else 24
        d0 = start.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        for k in range(days * 24 // step):
            loc = d0 + timedelta(hours=step * k)
            loc = loc.replace(tzinfo=None).replace(tzinfo=tz)       # giờ đồng hồ server
            if loc.weekday() > 4:
                continue
            lines.append(f"{loc:%Y.%m.%d}\t{loc:%H:%M:%S}\t{p}\t{p + 3}\t{p - 3}\t{p + 1}\t9\t0\t"
                         f"{spread}")
        return "\n".join(lines) + "\n"
    t = start
    while t < start + timedelta(days=days):
        if is_open(t) and is_open(t + tfo.delta - timedelta(seconds=1)) and t not in drop:
            loc = t.astimezone(tz)
            lines.append(f"{loc:%Y.%m.%d}\t{loc:%H:%M:%S}\t{p}\t{p + 1}\t{p - 1}\t{p + 0.5}\t9\t0\t"
                         f"{spread}")
        t += tfo.delta
    return "\n".join(lines) + "\n"


START = datetime(2025, 3, 2, 22, 0, tzinfo=UTC)       # tuần có Mỹ đổi giờ (09/03)


def test_parse_and_ingest_m15_and_report_gaps(tmp_path):
    # bỏ 12 nến trong giờ mở cửa (thứ Tư 00:00–02:45 UTC); 22:00 UTC mùa đông là giờ nghỉ
    drop = {START + timedelta(days=2, hours=h, minutes=15 * k) for h in (2, 3, 4) for k in range(4)}
    text = mt5_csv(START, 14, drop=drop)
    tf = Timeframe("M15")
    parsed = BD.parse(text, tf, "Europe/Athens")
    assert parsed.ok and not parsed.rejects
    url = f"sqlite:///{tmp_path / 'bt.db'}"
    init_db(url, env={})
    store = cli._store(url)
    res = BD.ingest(store, parsed, tf, symbol="XAUUSD", server_tz="Europe/Athens",
                    ingested_at=datetime(2026, 11, 23, tzinfo=UTC))
    assert res.accepted == len(parsed.bars) and res.quarantined == 0
    again = BD.ingest(store, parsed, tf, symbol="XAUUSD", server_tz="Europe/Athens",
                      ingested_at=datetime(2026, 11, 24, tzinfo=UTC))
    assert again.accepted == 0 and again.duplicates == len(parsed.bars)      # ghép file an toàn
    from gold_trading.contracts.candle import DataSource
    cs = list(store.latest_by_open_time("XAUUSD", tf, DataSource.CSV, parsed.bars[0].open_time,
                                        parsed.bars[-1].open_time).values())
    assert all(c.available_at == c.close_time for c in cs)                   # backfill
    rep = BD.report(cs, tf)
    assert rep.missing == 12 and len(rep.gaps) == 1 and rep.gaps[0].missing == 12
    assert rep.gaps[0].first == min(drop) and rep.unexpected == 0
    assert rep.spread_by_session["US"][0] == 20
    text_out = "\n".join(BD.render(rep))
    assert "thiếu 12 nến" in text_out


def test_wrong_timezone_rejected_and_not_ingested(tmp_path):
    text = mt5_csv(START, 14)
    parsed = BD.parse(text, Timeframe("M15"), "UTC")          # sai: file theo giờ Athens
    assert not parsed.ok and parsed.check.best_shift_hours != 0
    with pytest.raises(ValueError):
        BD.ingest(None, parsed, Timeframe("M15"), symbol="XAUUSD", server_tz="UTC",
                  ingested_at=datetime(2026, 11, 23, tzinfo=UTC))


@pytest.mark.parametrize("tf", ["H4", "D1"])
def test_h4_d1_server_aligned_ingest(tmp_path, tf):
    text = mt5_csv(START, 21, tf)
    parsed = BD.parse(text, Timeframe(tf), "Europe/Athens")
    assert parsed.ok and parsed.bars and not parsed.rejects
    url = f"sqlite:///{tmp_path / 'bt.db'}"
    init_db(url, env={})
    res = BD.ingest(cli._store(url), parsed, Timeframe(tf), symbol="XAUUSD",
                    server_tz="Europe/Athens", ingested_at=datetime(2026, 11, 23, tzinfo=UTC))
    assert res.accepted == len(parsed.bars) and res.quarantined == 0
    with pytest.raises(ValueError):
        BD.ingest(cli._store(url), parsed, Timeframe(tf), symbol="XAUUSD", server_tz=None,
                  ingested_at=datetime(2026, 11, 23, tzinfo=UTC))


# ---------------------------------------------------------------------- CLI


def test_cli_dry_run_needs_no_database(tmp_path, capsys):
    f = tmp_path / "m15.csv"
    f.write_text(mt5_csv(START, 7), encoding="utf-16")              # MT5 hay xuất UTF-16
    assert cli.main(["import", str(f), "--server-tz", "Europe/Athens", "--dry-run"], env={}) == 0
    assert "Đọc được" in capsys.readouterr().out


def test_cli_refuses_without_or_with_live_database(tmp_path, capsys):
    f = tmp_path / "m15.csv"
    f.write_text(mt5_csv(START, 7))
    assert cli.main(["import", str(f), "--server-tz", "Europe/Athens"], env={}) == 2
    live = f"sqlite:///{tmp_path / 'live.db'}"
    env = {"DATABASE_URL": live, "GT_BACKTEST_DATABASE_URL": live}
    assert cli.main(["import", str(f), "--server-tz", "Europe/Athens"], env=env) == 2
    assert cli.main(["init-db"], env=env) == 2
    assert "TỪ CHỐI" in capsys.readouterr().err
    assert not (tmp_path / "live.db").exists()                       # không chạm DB thật


def test_cli_import_and_report(tmp_path, capsys):
    f = tmp_path / "m15.csv"
    f.write_text(mt5_csv(START, 7))
    env = {"DATABASE_URL": f"sqlite:///{tmp_path / 'live.db'}",
           "GT_BACKTEST_DATABASE_URL": f"sqlite:///{tmp_path / 'bt.db'}"}
    assert cli.main(["init-db"], env=env) == 0
    assert cli.main(["import", str(f), "--server-tz", "Europe/Athens"], env=env) == 0
    assert cli.main(["data-report"], env=env) == 0
    out = capsys.readouterr().out
    assert "Kết quả (DB backtest): thêm" in out and "Khung M15:" in out and "thiếu 0" in out
    assert cli.main(["import", str(f), "--timeframe", "D1"], env=env) == 2   # thiếu múi giờ
