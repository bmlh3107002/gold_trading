"""ING-35 (KN-03): thống kê spread theo phút, giữ vĩnh viễn — tính tay + trường hợp xấu."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, IntegrityError

from gold_trading.market import quote_minutes as QM
from gold_trading.market.quotes import CALENDAR_CLOSED, WIDE_SPREAD, QuoteIngestor, QuoteSecond
from gold_trading.storage.quotes import (
    InMemoryQuoteMinuteStore,
    InMemoryQuoteStore,
    SqlQuoteMinuteStore,
    SqlQuoteStore,
)
from gold_trading.storage.repository import SqlRepository

M0 = datetime(2026, 1, 14, 10, 0, tzinfo=UTC)   # thứ Tư
F, G = "pf_a", "pf_b"


def s(t, *, bid=2400.10, ask=2400.30, low=None, high=None, sp=None, smax=None, ticks=2,
      flags=(), feed=F, at=None):
    sp = round((ask - bid) / 0.01) if sp is None else sp
    at = at or t + timedelta(seconds=1)
    lo = bid if low is None else low
    hi = ask if high is None else high
    return QuoteSecond(feed, t, bid, ask, lo, hi,
                       sp, sp if smax is None else smax, ticks, tuple(flags), at, at)


@pytest.fixture(params=["memory", "sqlite"])
def stores(request, tmp_path):
    if request.param == "memory":
        return InMemoryQuoteStore(), InMemoryQuoteMinuteStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'qm.db'}")
    repo.create_all()
    return SqlQuoteStore(repo.engine), SqlQuoteMinuteStore(repo.engine)


# ---------------------------------------------------------------- công thức (tính tay)

def test_aggregate_hand_computed():
    secs = [
        s(M0 + timedelta(seconds=0), bid=2400.00, ask=2400.20, sp=20, smax=25, ticks=3),
        s(M0 + timedelta(seconds=1), bid=2400.50, ask=2400.80, low=2399.90, sp=30, smax=40,
          ticks=1, flags=(WIDE_SPREAD,)),
        s(M0 + timedelta(seconds=7), bid=2400.40, ask=2400.60, high=2400.95, sp=20, smax=22,
          ticks=4),
        s(M0 + timedelta(seconds=59), bid=2400.30, ask=2400.40, sp=10, smax=10, ticks=2,
          flags=(CALENDAR_CLOSED,)),
    ]
    m = QM.aggregate(F, M0, list(reversed(secs)))      # thứ tự đầu vào không quan trọng
    assert (m.seconds, m.ticks) == (4, 10)
    assert (m.bid_open, m.bid_close, m.ask_close) == (2400.00, 2400.30, 2400.40)
    assert (m.bid_low, m.ask_high) == (2399.90, 2400.95)
    assert m.spread_min == 10
    assert m.spread_median == 20.0                       # trung vị (10, 20, 20, 30)
    assert m.spread_p95 == 40                            # hạng gần nhất ceil(0,95·4)=4 → 40
    assert m.spread_max == 40
    assert (m.seconds_wide, m.seconds_closed) == (1, 1)


def test_percentile_nearest_rank_reference():
    assert QM.p_nearest_rank([15, 20, 35, 40, 50], 0.95) == 50
    assert QM.p_nearest_rank(list(range(1, 21)), 0.95) == 19   # ceil(19) = 19
    assert QM.p_nearest_rank([7], 0.95) == 7
    with pytest.raises(ValueError):
        QM.p_nearest_rank([], 0.95)


def test_max_never_below_end_of_second_spread():
    # Gateway làm tròn: spread lớn nhất khai 24 nhưng spread cuối giây 25 (ING-08 cho lệch 1)
    m = QM.aggregate(F, M0, [s(M0, sp=25, smax=24)])
    assert m.spread_max == 25 and m.spread_p95 == 25 and m.spread_median == 25.0


def test_empty_minute_is_error_and_wrong_minute_rejected():
    with pytest.raises(ValueError):
        QM.aggregate(F, M0, [])
    with pytest.raises(ValueError):
        QM.aggregate(F, M0, [s(M0 + timedelta(minutes=1))])
    with pytest.raises(ValueError):
        QM.aggregate(F, M0, [s(M0, feed=G)])


# ---------------------------------------------------------------- bộ chạy + kho

def fill(qs, start, n, **kw):
    qs.append([s(start + timedelta(seconds=i), **kw) for i in range(n)])


def test_runner_aggregates_settled_minutes_only(stores):
    qs, ms = stores
    fill(qs, M0, 180)                                    # 3 phút trọn
    r = QM.QuoteMinuteRunner(qs, ms, retention=timedelta(days=30))
    now = M0 + timedelta(minutes=2) + QM.SETTLE          # phút 10:02 chưa lắng
    assert r.run_once(now) == 2
    rows = ms.query(F, M0 - timedelta(hours=1), M0 + timedelta(hours=1), as_of=now)
    assert [x.t for x in rows] == [M0, M0 + timedelta(minutes=1)]
    assert all(x.seconds == 60 and x.revision == 0 and x.available_at == now for x in rows)
    assert r.watermark == M0 + timedelta(minutes=2)
    assert r.run_once(now + timedelta(minutes=1)) == 1   # 10:02 lắng; hai phút cũ không ghi lại
    assert r.run_once(now + timedelta(minutes=2)) == 0   # idempotent


def test_gap_minute_has_no_row_not_zero(stores):
    qs, ms = stores
    fill(qs, M0, 30)
    fill(qs, M0 + timedelta(minutes=2), 30)              # phút 10:01 không có giây nào
    r = QM.QuoteMinuteRunner(qs, ms, retention=timedelta(days=30))
    now = M0 + timedelta(minutes=3) + QM.SETTLE
    r.run_once(now)
    got = ms.query(F, M0, M0 + timedelta(minutes=5), as_of=now)
    assert [x.t for x in got] == [M0, M0 + timedelta(minutes=2)]


def test_late_second_creates_revision_point_in_time(stores):
    qs, ms = stores
    fill(qs, M0, 30)
    r = QM.QuoteMinuteRunner(qs, ms, retention=timedelta(days=30))
    t1 = M0 + timedelta(minutes=1) + QM.SETTLE
    r.run_once(t1)
    late_at = t1 + timedelta(minutes=3)
    qs.append([s(M0 + timedelta(seconds=45), sp=90, smax=95, at=late_at)])   # tới muộn
    t2 = t1 + timedelta(minutes=5)
    assert r.run_once(t2) == 1
    before = ms.query(F, M0, M0 + MINUTE, as_of=t1 + timedelta(minutes=1))
    after = ms.query(F, M0, M0 + MINUTE, as_of=t2)
    assert before[0].revision == 0 and before[0].seconds == 30 and before[0].spread_max == 20
    assert after[0].revision == 1 and after[0].seconds == 31 and after[0].spread_max == 95
    assert after[0].available_at == t2


def test_fewer_seconds_after_purge_never_overwrites(stores):
    qs, ms = stores
    fill(qs, M0, 60)
    r = QM.QuoteMinuteRunner(qs, ms, retention=timedelta(days=30))
    t1 = M0 + timedelta(minutes=1) + QM.SETTLE
    r.run_once(t1)
    qs.purge_before(M0 + timedelta(seconds=40))          # xóa 40 giây đầu của phút
    assert r.run_once(t1 + timedelta(minutes=5)) == 0
    got = ms.query(F, M0, M0 + MINUTE, as_of=t1 + timedelta(hours=1))
    assert got[0].seconds == 60 and got[0].revision == 0


def test_feeds_kept_separate(stores):
    qs, ms = stores
    fill(qs, M0, 10, sp=20)
    fill(qs, M0, 10, sp=50, ask=2400.60, feed=G)
    r = QM.QuoteMinuteRunner(qs, ms, retention=timedelta(days=30))
    now = M0 + timedelta(minutes=1) + QM.SETTLE
    r.run_once(now)
    a = ms.query(F, M0, M0 + MINUTE, as_of=now)[0]
    b = ms.query(G, M0, M0 + MINUTE, as_of=now)[0]
    assert (a.feed_id, a.spread_max) == (F, 20) and (b.feed_id, b.spread_max) == (G, 50)


def test_first_run_backfills_retained_seconds_in_chunks(stores):
    qs, ms = stores
    now = M0 + timedelta(days=2)
    for d in range(3):                                   # 2 ngày trước, hôm qua, hôm nay
        fill(qs, M0 + timedelta(days=d) - timedelta(hours=5), 5)
    r = QM.QuoteMinuteRunner(qs, ms, retention=timedelta(days=30))
    assert r.run_once(now) == 3
    # Giây nằm ngoài hạn giữ (đang bị xóa dở) không được gộp ở lần đầu
    qs2, ms2 = InMemoryQuoteStore(), InMemoryQuoteMinuteStore()
    fill(qs2, now - timedelta(days=1) + timedelta(minutes=30), 5)   # trong 2 giờ cũ nhất
    r2 = QM.QuoteMinuteRunner(qs2, ms2, retention=timedelta(days=1))
    assert r2.run_once(now) == 0


MINUTE = QM.MINUTE


# ---------------------------------------------------------------- xóa giây có chốt chặn

class Cal:
    def is_open(self, t):
        return True


def test_purge_waits_for_minute_aggregation():
    qs, ms = InMemoryQuoteStore(), InMemoryQuoteMinuteStore()
    now = M0 + timedelta(days=40)
    old = M0 + timedelta(days=5)                          # quá hạn giữ 30 ngày
    fill(qs, old, 3)
    r = QM.QuoteMinuteRunner(qs, ms, retention=timedelta(days=30))
    g = QuoteIngestor(qs, Cal(), retention=timedelta(days=30), purge_guard=r.purge_guard)
    g._maybe_purge(now)                                  # bộ tổng hợp chưa chạy → không xóa
    assert len(qs.window(F, old, old + MINUTE)) == 3
    r.watermark = old                                    # mới tổng hợp tới trước phút đó
    g._next_purge = None
    g._maybe_purge(now)
    assert len(qs.window(F, old, old + MINUTE)) == 3
    r.watermark = now - QM.SETTLE                        # đã tổng hợp xong
    g._next_purge = None
    g._maybe_purge(now)
    assert qs.window(F, old, old + MINUTE) == []


def test_ingestor_without_guard_purges_as_before():
    qs = InMemoryQuoteStore()
    fill(qs, M0, 3)
    g = QuoteIngestor(qs, Cal(), retention=timedelta(days=1))
    g._maybe_purge(M0 + timedelta(days=3))
    assert qs.window(F, M0, M0 + MINUTE) == []


# ---------------------------------------------------------------- DB: chỉ-thêm + CHECK

def test_sqlite_check_rejects_impossible_row(tmp_path):
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'c.db'}")
    repo.create_all()
    ms = SqlQuoteMinuteStore(repo.engine)
    good = QM.aggregate(F, M0, [s(M0)])
    bad = QM.QuoteMinute(**{**good.__dict__, "seconds": 61, "computed_at": M0,
                            "available_at": M0})
    with pytest.raises((IntegrityError, DatabaseError)):
        ms.append([bad])


def test_migration_is_append_only_plain_table():
    src = (Path(__file__).parents[1] / "migrations" / "versions" / "0021_quote_minutes.py"
           ).read_text(encoding="utf-8")
    assert "quote_minutes" in src and "forbid_mutation" in src
    assert "create_hypertable" not in src and 'down_revision = "0020"' in src


def test_summary(tmp_path):
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 's.db'}")
    repo.create_all()
    qs, ms = SqlQuoteStore(repo.engine), SqlQuoteMinuteStore(repo.engine)
    fill(qs, M0, 120)
    QM.QuoteMinuteRunner(qs, ms, retention=timedelta(days=30)).run_once(
        M0 + timedelta(minutes=2) + QM.SETTLE)
    assert ms.summary() == [(F, 2, M0, M0 + MINUTE)]
    with repo.engine.connect() as c:
        assert c.execute(text("select count(*) from quote_minutes")).scalar() == 2


def test_cli_spread_phut_read_only(tmp_path, capsys):
    from gold_trading.ingestion.cli import _spread_phut
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'cli.db'}")
    repo.create_all()
    assert _spread_phut(engine=repo.engine) == 0
    assert "Chưa có dòng" in capsys.readouterr().out
    qs, ms = SqlQuoteStore(repo.engine), SqlQuoteMinuteStore(repo.engine)
    fill(qs, M0, 60)
    QM.QuoteMinuteRunner(qs, ms, retention=timedelta(days=30)).run_once(
        M0 + timedelta(minutes=1) + QM.SETTLE)
    assert _spread_phut(engine=repo.engine) == 0
    out = capsys.readouterr().out
    assert F in out and "2026-01-14 10:00" in out
    assert _spread_phut(env={}) == 2
