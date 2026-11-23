"""Dữ liệu giá lịch sử cho backtest (GĐ6 bước 2 — BT-01 phần dữ liệu, 6-C03; thiết kế 39 mục 4).

- Nạp file CSV xuất từ MT5 vào **cơ sở dữ liệu backtest riêng** qua đúng cửa nạp ``CandleIngestor``
  (nguồn ``CSV``, ``backfill`` → ``available_at = close_time``). Nhận M1–H1 **và H4 / D1** (căn theo
  giờ server broker — bắt buộc ``server_tz``). Không sửa lệnh ``import-csv`` của GĐ1.
- Kiểm múi giờ R1 như GĐ1; với H4 / D1 (nến dài, vắt qua giờ nghỉ hằng ngày) chỉ xét **giờ mở
  nến** có nằm trong giờ mở cửa tuần hay không.
- Báo cáo dữ liệu (chỉ đọc): khoảng thời gian, số nến, **chỗ hở trong giờ mở cửa** gom theo ngày
  giao dịch New York (theo lịch thị trường đầy đủ — năm chưa có trong bảng ngày lễ thì ngày lễ hiện
  thành chỗ hở → dùng để đối chiếu khi thêm ngày lễ), nến bị cách ly, cờ chất lượng, spread theo
  phiên. Thiếu → ghi ra, không bịa.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from gold_trading.backtest import stats as S
from gold_trading.backtest.metrics import session_of
from gold_trading.contracts.candle import Candle, DataSource
from gold_trading.ingestion.candles import CandleIngestor, IngestResult, RawBar
from gold_trading.ingestion.sources import csv_file
from gold_trading.market.hours import REFERENCE, MarketCalendar
from gold_trading.market.quality import expected_open_times
from gold_trading.market.timeframes import Timeframe
from gold_trading.risk.periods import Periods

NY_DAY = Periods.of("America/New_York", "17:00")
TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")


def read_text(raw: bytes) -> str:
    """MT5 xuất UTF-8 (có BOM) hoặc UTF-16."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("utf-16")


@dataclass
class Parsed:
    bars: list[RawBar]
    rejects: list
    check: csv_file.SessionCheck

    @property
    def ok(self) -> bool:
        return self.check.ok


def parse(text: str, tf: Timeframe, server_tz: str | None) -> Parsed:
    bars, rejects = csv_file.parse(text, server_tz=server_tz)
    # H4 / D1 vắt qua giờ nghỉ hằng ngày → chỉ xét giờ mở nến (1 phút) cho R1.
    minutes = 1 if tf.server_aligned else int(tf.delta.total_seconds() // 60)
    return Parsed(bars, rejects, csv_file.check_sessions(bars, minutes))


def ingest(store, parsed: Parsed, tf: Timeframe, *, symbol: str, server_tz: str | None,
           ingested_at: datetime, calendar: MarketCalendar = REFERENCE) -> IngestResult:
    if not parsed.ok:
        raise ValueError("file bị từ chối (R1 — nhiều khả năng sai múi giờ server)")
    if tf.server_aligned and not server_tz:
        raise ValueError(f"khung {tf} cần múi giờ server broker")
    return CandleIngestor(store, calendar).ingest(
        parsed.bars, symbol=symbol, timeframe=tf, source=DataSource.CSV,
        ingested_at=ingested_at, backfill=True,
        rejected=[(r.reason, r.raw | {"line": r.line}) for r in parsed.rejects],
        server_tz=ZoneInfo(server_tz) if server_tz else None)


# ---------------------------------------------------------------------- báo cáo dữ liệu


@dataclass
class Gap:
    trade_date: date
    missing: int
    first: datetime
    last: datetime


@dataclass
class DataReport:
    timeframe: str
    count: int
    first: datetime | None
    last: datetime | None
    expected: int
    gaps: list[Gap] = field(default_factory=list)
    flags: dict[str, int] = field(default_factory=dict)
    quarantined: int = 0
    spread_by_session: dict[str, tuple[float | None, float | None, int]] = field(
        default_factory=dict)                     # phiên → (trung vị, p95, số nến)
    unexpected: int = 0                           # nến nằm ngoài giờ mở cửa theo lịch

    @property
    def missing(self) -> int:
        return sum(g.missing for g in self.gaps)


def report(candles: list[Candle], tf: Timeframe, calendar: MarketCalendar = REFERENCE,
           quarantined: int = 0) -> DataReport:
    """Chỉ đọc. Chỗ hở = nến lẽ ra có (theo ``calendar``) mà không có, gom theo ngày giao dịch NY.
    H4 / D1: không tính chỗ hở (độ dài nến phụ thuộc giờ server) — chỉ đếm."""
    cs = sorted(candles, key=lambda c: c.open_time)
    if not cs:
        return DataReport(tf.value, 0, None, None, 0, quarantined=quarantined)
    have = {c.open_time for c in cs}
    rep = DataReport(tf.value, len(cs), cs[0].open_time, cs[-1].open_time, 0,
                     quarantined=quarantined)
    rep.flags = dict(Counter(f.value for c in cs for f in c.flags))
    if not tf.server_aligned:
        exp = expected_open_times(cs[0].open_time, cs[-1].open_time, tf, calendar)
        rep.expected = len(exp)
        expset = set(exp)
        rep.unexpected = sum(1 for t in have if t not in expset)
        by_day: dict[date, list[datetime]] = defaultdict(list)
        for t in exp:
            if t not in have:
                by_day[NY_DAY.trade_date(t)].append(t)
        rep.gaps = [Gap(d, len(v), v[0], v[-1]) for d, v in sorted(by_day.items())]
    sp: dict[str, list[float]] = defaultdict(list)
    for c in cs:
        if c.spread_points is not None:
            sp[session_of(c.open_time)].append(float(c.spread_points))
    rep.spread_by_session = {k: (S.percentile(v, 0.5), S.percentile(v, 0.95), len(v))
                             for k, v in sorted(sp.items())}
    return rep


def render(rep: DataReport, max_gaps: int = 60) -> list[str]:
    out = [f"Khung {rep.timeframe}: {rep.count} nến"
           + (f", {rep.first.isoformat()} → {rep.last.isoformat()}" if rep.first else "")]
    if rep.expected:
        cov = rep.count / rep.expected if rep.expected else 0
        out.append(f"  Lẽ ra có {rep.expected} nến trong giờ mở cửa; thiếu {rep.missing} "
                   f"(phủ {cov:.2%}); nến ngoài giờ theo lịch: {rep.unexpected}")
        full = [g for g in rep.gaps if g.missing >= 40]
        out.append(f"  Ngày thiếu ≥ 40 nến (nghi ngày lễ / mất dữ liệu): {len(full)}")
        for g in rep.gaps[:max_gaps]:
            out.append(f"    {g.trade_date.isoformat()} ({g.trade_date:%a}): thiếu {g.missing} "
                       f"nến, {g.first:%H:%M}–{(g.last + timedelta(minutes=14)):%H:%M} UTC")
        if len(rep.gaps) > max_gaps:
            out.append(f"    … còn {len(rep.gaps) - max_gaps} ngày nữa")
    out.append(f"  Cách ly: {rep.quarantined}; cờ: {rep.flags or 'không'}")
    for k, (med, p95, n) in rep.spread_by_session.items():
        out.append(f"  Spread {k}: trung vị {med:g}, p95 {p95:g} point ({n} nến)")
    return out
