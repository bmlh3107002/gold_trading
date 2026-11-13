"""Bước 10f — ING-33: báo cáo dung lượng + ước tính 1 năm (chỉ đọc)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from gold_trading.ingestion import cli
from gold_trading.ingestion.source_status import CheckOutcome, SourceCheck
from gold_trading.ops.storage_report import TableUsage, human, report
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.source_checks import SqlSourceCheckLog

NOW = datetime(2026, 11, 13, 12, tzinfo=UTC)


def test_rates_and_projection():
    u = TableUsage("x", rows=1000, bytes=100_000, rows_1d=50, rows_7d=280, span_days=10)
    assert u.rows_per_day == 40 and u.bytes_per_row == 100
    assert u.projected_bytes(365) == (1000 + 40 * 365) * 100
    short = TableUsage("x", rows=60, bytes=6000, rows_1d=60, rows_7d=60, span_days=2)
    assert short.rows_per_day == 60                 # chưa đủ 7 ngày → dùng 1 ngày
    new = TableUsage("x", rows=5, bytes=500, rows_1d=5, rows_7d=5, span_days=0.2)
    assert new.rows_per_day is None and new.projected_bytes() is None   # không đoán
    q = TableUsage("quote_seconds", rows=1000, bytes=50_000, rows_1d=100, rows_7d=700,
                   span_days=8, retention_days=30)
    assert q.projected_bytes(365) == 100 * 30 * 50     # trần theo hạn giữ, không cộng dồn
    assert TableUsage("x", 0, 8192, 0, 0, 0).bytes_per_row is None
    assert TableUsage("x", 10, None, 10, 10, 9).projected_bytes() is None   # SQLite


@pytest.mark.parametrize("n,s", [(None, "—"), (0, "0 B"), (1023, "1,023 B"), (1024, "1.0 KB"),
                                 (5 * 1024**2, "5.0 MB"), (3 * 1024**4, "3,072.0 GB")])
def test_human(n, s):
    assert human(n) == s


def test_report_sqlite_counts_windows(tmp_path):
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'r.db'}")
    repo.create_all()
    log = SqlSourceCheckLog(repo.engine)
    for h in (1, 30, 24 * 8, -1):       # 1 giờ, 30 giờ, 8 ngày trước; 1 bản sau as_of
        log.record(SourceCheck("s", NOW - timedelta(hours=h), CheckOutcome.OK))
    rows, db = report(repo.engine, NOW)
    u = {r.table: r for r in rows}["external_source_checks"]
    assert (u.rows, u.rows_1d, u.rows_7d) == (4, 1, 2)
    assert u.span_days == pytest.approx(8.0)
    assert u.bytes is None and db is None
    assert u.rows_per_day == pytest.approx(2 / 7)
    assert {r.table for r in rows} >= {"candles", "quote_seconds", "external_records"}


def test_report_skips_missing_table(tmp_path):
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'r.db'}")
    repo.create_all()
    with repo.engine.begin() as c:
        c.execute(text("drop table audit_log"))
    rows, _ = report(repo.engine, NOW)
    assert "audit_log" not in {r.table for r in rows} and len(rows) == 7


def test_report_is_read_only(tmp_path):
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'r.db'}")
    repo.create_all()
    p = tmp_path / "r.db"
    before = p.read_bytes()
    report(repo.engine, NOW)
    assert p.read_bytes() == before


def test_cli(tmp_path, capsys):
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'r.db'}")
    repo.create_all()
    assert cli._dung_luong(env={"GT_QUOTE_RETENTION_DAYS": "14"}, engine=repo.engine,
                           now=NOW) == 0
    out = capsys.readouterr().out
    assert "quote_seconds" in out and "(giữ 14 ngày)" in out and "Dung lượng cả DB: —" in out
    assert cli._dung_luong(env={}) == 2
