"""Lịch doanh số bán lẻ Census chép tay (DEC-01 / ING-09; người dùng chốt 2026-11-17).

Bảng chép tay được đối chiếu với **hai trang Census thật** (``tests/fixtures/census``, tải nguyên
văn 2026-11-13; trang tải lại 2026-11-17 cho cùng lịch) qua bộ đọc đã có test của ``census.py``.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gold_trading.ingestion import economic_calendar as C
from gold_trading.ingestion import event_importance as I
from gold_trading.ingestion import external_runner as R
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.ingestion.source_status import CheckOutcome, SourceCheckLog
from gold_trading.ingestion.sources import census as CEN
from gold_trading.ingestion.sources import census_manual as M
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.source_checks import SqlSourceCheckLog

FIX = Path(__file__).parent / "fixtures" / "census"
T = datetime(2026, 11, 17, 7, 0, tzinfo=UTC)         # sáng 17/11 giờ VN, trước 08:30 ET


def utc(*a):
    return datetime(*a, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def env(request, tmp_path):
    if request.param == "memory":
        return PointInTimeStore(), SourceCheckLog()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'c.db'}")
    repo.create_all()
    return SqlExternalRecordStore(repo.engine), SqlSourceCheckLog(repo.engine)


def test_table_matches_both_official_census_pages():
    read = lambda f: (FIX / f).read_text(encoding="utf-8")       # noqa: E731
    _, a = CEN.parse_listview(read("calendar-listview-2027.html"))
    _, b = CEN.parse_listview(read("calendar-listview-2026.html"))
    listview = {f"{x.period:%Y-%m}": x.at for x in a + b}
    retail = {f"{p:%Y-%m}": d for p, d in CEN.parse_retail_schedule(
        read("retail-release-schedule.html")).items()}
    table = M.schedule_table()
    assert len(table) == 15
    for period, d in table:
        at = listview[period]
        assert at.date() == d and at.strftime("%H:%M") == "08:30", period
        assert retail[period] == d, period          # trang bán lẻ riêng cũng khớp
        assert M.release_at(d) == at.astimezone(UTC)


def test_dst_hand_checked():
    ev = {e.logical_key: e.event_time for e in M.build_schedule(utc(2026, 11, 1))}
    assert ev["RETAIL:2026-10"] == utc(2026, 11, 17, 13, 30)    # EST: 08:30 ET = 13:30 UTC
    assert ev["RETAIL:2027-02"] == utc(2027, 3, 16, 12, 30)     # sau đổi giờ 14/3/2027 → EDT
    assert ev["RETAIL:2027-09"] == utc(2027, 10, 15, 12, 30)    # còn EDT
    assert ev["RETAIL:2027-10"] == utc(2027, 11, 16, 13, 30)    # sau 7/11/2027 → EST


def test_payload_same_shape_as_census_source():
    e = next(e for e in M.build_schedule(T) if e.logical_key == "RETAIL:2026-11")
    p = e.payload
    assert (p["event"], p["time_confirmed"], p["all_day"], p["release_local"], p["status"]) == (
        CEN.EVENT, True, False, "08:30", "SCHEDULED")
    assert p["schedule_version"] == M.SCHEDULE_VERSION and p["includes"] == ["RETAIL_SALES"]


@pytest.mark.parametrize("rows,msg", [
    ((("2026-09", "2026-10-15"), ("2026-11", "2026-12-16")), "liên tiếp"),
    ((("2026-09", "2026-10-15"), ("2026-10", "2026-10-15")), "không tăng"),
    ((("2026-09", "2026-10-17"),), "lạ"),                          # thứ Bảy
    ((("2026-09", "2026-09-30"),), "lạ"),                          # chưa hết tháng số liệu
    ((("2026-09", "2027-10-15"),), "lạ"),                          # gõ nhầm năm
])
def test_table_validation(monkeypatch, rows, msg):
    monkeypatch.setattr(M, "_TABLE", rows)
    with pytest.raises(M.ScheduleError, match=msg):
        M.schedule_table()


def test_window_blocks_entries_around_release(env):
    store, log = env
    chk = M.run_schedule_once(store=store, log=log, now=T)
    assert chk.outcome is CheckOutcome.OK and chk.inserted > 0
    health = C.health_map(log, store, T)
    assert health[M.SCHEDULE_SOURCE] is True
    item = next(i for i in C.economic_calendar(store, T, health=health)
                if i.logical_key == "RETAIL:2026-10")
    # HIGH: 15 phút trước / sau 13:30 UTC; không có số actual → không kéo dài cửa sổ
    assert (item.importance, item.importance_known) == ("HIGH", True)
    assert (item.window_start, item.window_end) == (utc(2026, 11, 17, 13, 15),
                                                    utc(2026, 11, 17, 13, 45))
    assert item.actual_status == "NOT_APPLICABLE" and not item.all_day


def test_expiring_table_is_invalid_and_calendar_distrusts(env):
    store, log = env
    late = utc(2027, 11, 1)      # lần cuối 15/12/2027 còn 44 ngày < 45
    assert M.run_schedule_once(store=store, log=log, now=late - timedelta(days=30)).outcome \
        is CheckOutcome.OK
    chk = M.run_schedule_once(store=store, log=log, now=late)
    assert (chk.outcome, chk.error_code) == (CheckOutcome.INVALID, "SCHEDULE_TABLE_EXPIRING")
    health = C.health_map(log, store, late)
    assert health[M.SCHEDULE_SOURCE] is False
    item = next(i for i in C.economic_calendar(store, late, health=health)
                if i.logical_key == "RETAIL:2027-10")
    assert item.all_day and "SCHEDULE_SOURCE_UNHEALTHY" in item.notes    # chặn cả ngày


def test_idempotent_and_cutoff(env):
    store, log = env
    a = M.run_schedule_once(store=store, log=log, now=T)
    b = M.run_schedule_once(store=store, log=log, now=T + timedelta(hours=20))
    assert a.inserted > 0 and (b.inserted, b.duplicate) == (0, 0)
    keys = {r.logical_key for r in store.as_of(T, source=M.SCHEDULE_SOURCE, kind="calendar")}
    assert "RETAIL:2026-09" not in keys       # 15/10 cũ hơn 7 ngày → không ghi
    assert {"RETAIL:2026-10", "RETAIL:2027-11"} <= keys


def test_wired_into_runner_calendar_and_policy():
    assert "census_retail" in R.DEFAULT_SOURCES and R.parse_sources("census_retail")
    assert M.SCHEDULE_SOURCE in C.CALENDAR_SOURCES   # Risk Q1 + Event analyst kiểm sức khỏe nguồn
    r = I.rate(CEN.EVENT)
    assert r.known and r.importance is I.Importance.HIGH
