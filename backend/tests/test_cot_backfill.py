"""Nạp bù lịch sử COT từ file năm CFTC (GĐ3 bước 5 — Positioning).

File thật chưa đọc được từ máy chủ đám mây (403) → file dựng theo định dạng legacy "annual.txt"
(tiêu đề theo tên, có khoảng trắng thừa như file CFTC), tuần 03/11/2026 lấy đúng số của báo cáo
thật GĐ1 → kiểm cổng đối chiếu. Đọc file thật: chạy ``cot-bu --dry-run`` trên máy người dùng.
"""

import io
import zipfile
from datetime import UTC, date, datetime, timedelta

import pytest

from gold_trading.analysts import positioning as P
from gold_trading.ingestion import cli
from gold_trading.ingestion.source_status import SourceCheckLog
from gold_trading.ingestion.sources import cftc_cot as C
from gold_trading.ingestion.sources import cot_backfill as CB
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.repository import SqlRepository

from .test_cftc_cot import PAGE

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
REAL = C.parse(PAGE)
HEAD = ["Market and Exchange Names", "As of Date in Form YYMMDD", "As of Date in Form YYYY-MM-DD",
        "CFTC Contract Market Code", "CFTC Market Code in Initials", "Open Interest (All)",
        "Noncommercial Positions-Long (All)", "Noncommercial Positions-Short (All)",
        "Noncommercial Positions-Spreading (All)", "Commercial Positions-Long (All)",
        "Commercial Positions-Short (All)", " Total Reportable Positions-Long (All)",
        "Total Reportable Positions-Short (All)", "Nonreportable Positions-Long (All)",
        "Nonreportable Positions-Short (All)", "Change in Open Interest (All)",
        "Change in Noncommercial-Long (All)", "Change in Noncommercial-Short (All)",
        "Change in Noncommercial-Spreading (All)", "Change in Commercial-Long (All)",
        "Change in Commercial-Short (All)", "Change in Total Reportable-Long (All)",
        "Change in Total Reportable-Short (All)", "Change in Nonreportable-Long (All)",
        "Change in Nonreportable-Short (All)"]
ORDER = ("noncomm_long", "noncomm_short", "noncomm_spreads", "comm_long", "comm_short",
         "total_long", "total_short", "nonrept_long", "nonrept_short")


def week(d: date, nl: int, ns: int, sp: int = 68289, cl: int = 64326, cs: int = 269228,
         nrl: int = 46024, code="088691", name="GOLD - COMMODITY EXCHANGE INC."):
    tl, ts = nl + sp + cl, ns + sp + cs
    oi = max(tl + nrl, ts + 20_000)
    nrl, nrs = oi - tl, oi - ts
    pos = [nl, ns, sp, cl, cs, tl, ts, nrl, nrs]
    chg = [0] * 10
    return [name, d.strftime("%y%m%d"), d.isoformat(), f" {code}", "CMX", str(oi),
            *map(str, pos), *map(str, chg)]


def real_row():
    p = REAL.positions
    ch = REAL.changes
    return ["GOLD - COMMODITY EXCHANGE INC.", "261103", "2026-11-03", "088691", "CMX",
            str(REAL.open_interest), *(str(p[k]) for k in ORDER), str(REAL.oi_change),
            *(str(ch[k]) for k in ORDER)]


def annual(n_weeks=60, *, extra=(), tweak_real=None):
    rows = [HEAD]
    d0 = date(2026, 11, 3)
    for i in range(n_weeks, 0, -1):
        rows.append(week(d0 - timedelta(weeks=i), 150_000 + 2_000 * (i % 7), 40_000))
    r = real_row()
    if tweak_real:
        r = tweak_real(r)
    rows.append(r)
    rows.append(week(d0, 1, 1, code="088695", name="MICRO GOLD - COMMODITY EXCHANGE INC."))
    rows += list(extra)
    buf = io.StringIO()
    import csv
    csv.writer(buf).writerows(rows)
    return buf.getvalue()


def as_zip(text: str) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("annual.txt", text)
    return b.getvalue()


@pytest.fixture
def db(tmp_path):
    url = f"sqlite:///{tmp_path / 'c.db'}"
    repo = SqlRepository.from_url(url)
    repo.create_all()
    st = SqlExternalRecordStore(repo.engine)
    C.run_once(store=st, log=SourceCheckLog(), get=lambda: PAGE,
               now=datetime(2026, 11, 13, 12, tzinfo=UTC))
    return url, st


# ------------------------------------------------------------------ đọc

def test_parse_by_header_name_gold_only():
    reps = CB.parse_annual(annual(5))
    assert [r.as_of for r in reps][-1] == date(2026, 11, 3) and len(reps) == 6
    last = reps[-1]
    assert last.open_interest == REAL.open_interest and last.positions == REAL.positions
    assert last.changes == REAL.changes                   # MICRO GOLD 088695 bị bỏ


def test_missing_column_lists_seen_headers():
    with pytest.raises(CB.CotBackfillError, match="thiếu cột.*cột thấy được"):
        CB.parse_annual(annual(2).replace("Open Interest (All)", "Open Int (All)", 1))


def test_identity_broken_rejected():
    def bad(r):
        r[6] = str(int(r[6]) + 1)          # long không thương mại lệch tổng
        return r
    with pytest.raises(CB.CotBackfillError, match="tổng long"):
        CB.parse_annual(annual(2, tweak_real=bad))


def test_duplicate_date_and_bad_number_rejected():
    with pytest.raises(CB.CotBackfillError, match="hai lần"):
        CB.parse_annual(annual(2, extra=[real_row()]))
    with pytest.raises(CB.CotBackfillError, match="số không hợp lệ"):
        CB.parse_annual(annual(2, tweak_real=lambda r: r[:5] + ["n/a"] + r[6:]))


def test_zip_must_have_one_txt():
    assert CB.read_zip(as_zip("a")) == "a"
    with pytest.raises(CB.CotBackfillError):
        CB.read_zip(b"not a zip")


# ------------------------------------------------------------------ cổng đối chiếu + ghi

def test_cross_check_and_backfill_then_analyst_has_extremes(db):
    url, st = db
    reps = CB.parse_annual(annual(60))
    assert CB.cross_check(st, reps, NOW) == (1, [])
    c = CB.backfill(st, reps, NOW)
    assert c.added == 60 and c.same == 1 and c.conflict == []
    again = CB.backfill(st, reps, NOW)
    assert again.added == 0 and again.same == 61
    o = P.compute(st, NOW + timedelta(minutes=1))
    assert o.features["history_weeks"] == 61 and o.features["crowding"] != "INSUFFICIENT_DATA"
    old = st.as_of(NOW, source=C.SOURCE, logical_key="GOLD_088691:2026-09-01")[0]
    assert old.payload["report_source"] == "CFTC_HISTORY_ANNUAL" and old.revision == 0
    assert st.as_of(NOW - timedelta(seconds=1), source=C.SOURCE,
                    logical_key="GOLD_088691:2026-09-01") == []   # chưa nạp → chưa biết


def test_cli_dry_run_then_write(db, tmp_path, capsys):
    url, st = db
    f = tmp_path / "deacot2026.zip"
    f.write_bytes(as_zip(annual(60)))
    env = {"DATABASE_URL": url}
    assert cli._cot_backfill(True, 4, [f], env=env, now=NOW) == 0
    out = capsys.readouterr().out
    assert "1 tuần trùng, 0 tuần lệch" in out and "CHẠY THỬ" in out
    assert len(st.as_of(NOW, source=C.SOURCE)) == 1                 # chưa ghi
    assert cli._cot_backfill(False, 4, [f], env=env, now=NOW) == 0
    assert len(st.as_of(NOW, source=C.SOURCE)) == 61


def test_cli_mismatch_with_stored_report_writes_nothing(db, tmp_path, capsys):
    """Ánh xạ cột sai (vd. đổi chỗ long / short) → lệch báo cáo đã lưu → dừng, không ghi."""
    url, st = db

    def swap(r):
        r[6], r[7] = r[7], r[6]
        r[11], r[12] = r[12], r[11]
        r[13], r[14] = r[14], r[13]
        r[16], r[17] = r[17], r[16]
        r[21], r[22] = r[22], r[21]
        r[23], r[24] = r[24], r[23]
        return r
    f = tmp_path / "a.txt"
    f.write_text(annual(10, tweak_real=swap))
    rc = cli._cot_backfill(False, 4, [f], env={"DATABASE_URL": url}, now=NOW)
    err = capsys.readouterr().err
    assert rc == 1 and ("DỪNG" in err or "Không nạp" in err)
    assert len(st.as_of(NOW, source=C.SOURCE)) == 1


def test_cli_no_overlap_writes_nothing(tmp_path, capsys):
    url = f"sqlite:///{tmp_path / 'e.db'}"
    SqlRepository.from_url(url).create_all()
    f = tmp_path / "a.txt"
    f.write_text(annual(10))
    assert cli._cot_backfill(False, 4, [f], env={"DATABASE_URL": url}, now=NOW) == 1
    assert "DỪNG" in capsys.readouterr().err
