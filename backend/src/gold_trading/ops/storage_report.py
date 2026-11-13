"""Báo cáo dung lượng + ước tính tăng trưởng từng bảng (GĐ1 bước 10f — ING-33). Chỉ ĐỌC.

Số đo trên DB thật (máy người dùng) thay vì đoán: số dòng, dung lượng (hypertable TimescaleDB
tính cả chunk), số dòng mới 1 ngày / 7 ngày gần nhất → byte/dòng × dòng/ngày → ước tính 1 năm.
Bảng có hạn giữ (``quote_seconds``, ``GT_QUOTE_RETENTION_DAYS``): trần ``hạn giữ × dòng/ngày``.

Thiết kế + chính sách giữ dữ liệu: ``docs/thiet-ke/23-giu-du-lieu.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, text

# Bảng → cột thời điểm hệ thống nhận / tạo dòng (đo tốc độ tăng).
TABLES: dict[str, str] = {
    "candles": "ingested_at",
    "quote_seconds": "ingested_at",
    "candle_quarantine": "received_at",
    "analyst_outputs": "computed_at",
    "external_records": "ingested_at",
    "external_quarantine": "received_at",
    "external_source_checks": "checked_at",
    "audit_log": "at",
}


@dataclass(frozen=True)
class TableUsage:
    table: str
    rows: int
    bytes: int | None              # None: không đo được (SQLite)
    rows_1d: int
    rows_7d: int
    span_days: float               # khoảng thời gian có dữ liệu (dòng cũ nhất → as_of)
    retention_days: int | None = None

    @property
    def rows_per_day(self) -> float | None:
        """7 ngày nếu dữ liệu đã đủ 7 ngày, không thì 1 ngày; chưa đủ 1 ngày → không ước tính."""
        if self.span_days >= 7:
            return self.rows_7d / 7
        if self.span_days >= 1:
            return float(self.rows_1d)
        return None

    @property
    def bytes_per_row(self) -> float | None:
        return self.bytes / self.rows if self.bytes is not None and self.rows > 0 else None

    def projected_bytes(self, days: int = 365) -> float | None:
        """Ước tính dung lượng sau ``days`` ngày nữa (bảng có hạn giữ: trần theo hạn giữ)."""
        rpd, bpr = self.rows_per_day, self.bytes_per_row
        if rpd is None or bpr is None:
            return None
        if self.retention_days is not None:
            return rpd * min(days, self.retention_days) * bpr
        return (self.rows + rpd * days) * bpr


def _is_hypertable(conn, table: str) -> bool:
    has_ts = conn.execute(text(
        "select 1 from pg_extension where extname = 'timescaledb'")).first() is not None
    if not has_ts:
        return False
    return conn.execute(text(
        "select 1 from timescaledb_information.hypertables where hypertable_name = :t"),
        {"t": table}).first() is not None


def _size(conn, table: str) -> int | None:
    if conn.dialect.name != "postgresql":
        return None
    if _is_hypertable(conn, table):
        return int(conn.execute(text("select hypertable_size(:t)"), {"t": table}).scalar() or 0)
    return int(conn.execute(text("select pg_total_relation_size(:t)"), {"t": table}).scalar() or 0)


def _aware(v):
    if v is None:
        return None
    if isinstance(v, str):  # SQLite trả chuỗi
        v = datetime.fromisoformat(v)
    return v if v.tzinfo else v.replace(tzinfo=UTC)


def report(engine: Engine, as_of: datetime, *,
           quote_retention_days: int | None = 30) -> tuple[list[TableUsage], int | None]:
    """``(từng bảng, dung lượng cả DB)``. Bảng chưa có (migration cũ) → bỏ qua."""
    out: list[TableUsage] = []
    with engine.connect() as conn:
        for table, col in TABLES.items():
            try:
                row = conn.execute(text(
                    f"select count(*), min({col}), "                       # noqa: S608
                    f"sum(case when {col} > :d1 and {col} <= :t then 1 else 0 end), "
                    f"sum(case when {col} > :d7 and {col} <= :t then 1 else 0 end) "
                    f"from {table}"),
                    {"t": as_of, "d1": as_of - timedelta(days=1),
                     "d7": as_of - timedelta(days=7)}).one()
            except Exception:  # bảng chưa tồn tại
                conn.rollback()
                continue
            n, first, r1, r7 = row
            first = _aware(first)
            span = max(0.0, (as_of - first).total_seconds() / 86400) if first else 0.0
            out.append(TableUsage(
                table, int(n), _size(conn, table), int(r1 or 0), int(r7 or 0), span,
                quote_retention_days if table == "quote_seconds" else None))
        db = None
        if conn.dialect.name == "postgresql":
            db = int(conn.execute(text("select pg_database_size(current_database())")).scalar())
    return out, db


def human(n: float | None) -> str:
    if n is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:,.1f} GB"
