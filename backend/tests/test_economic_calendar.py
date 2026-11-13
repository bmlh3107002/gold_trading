"""Bước 8g-2 — mức quan trọng có phiên bản (ING-20) + bảng lịch hợp nhất (1C-C07).

Lịch thật Fed / BEA (``tests/fixtures``) + lịch DOL theo quy tắc, ghi qua bộ nạp thật rồi đọc
lại tại ``as_of``. Case: cửa sổ quanh giờ đã xác nhận, cả ngày khi chưa chắc giờ / hai nguồn
lệch, ngày đổi giờ DST (23 / 25 giờ), sự kiện bị hủy / dời, sự kiện lạ → HIGH, không forecast →
"không đủ dữ liệu", point-in-time.
"""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from gold_trading.common.enums import SourceStatus
from gold_trading.contracts.records import NormalizedRecord
from gold_trading.ingestion import economic_calendar as C
from gold_trading.ingestion import event_importance as I
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.ingestion.source_status import SourceCheckLog
from gold_trading.ingestion.sources import bea as B
from gold_trading.ingestion.sources import dol as D
from gold_trading.ingestion.sources import fed_fomc as F
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.repository import SqlRepository

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
FED = {
    F.MEETINGS_PATH: (FIX / "fed" / "fomccalendars-2026-11-13.html").read_text(encoding="utf-8"),
    F.CALENDAR_INDEX_PATH: (FIX / "fed" / "calendar-2026-11-13.html").read_text(encoding="utf-8"),
    **{f"/newsevents/2026-{m}.htm": (FIX / "fed" / f"2026-{m}.html").read_text(encoding="utf-8")
       for m in ("october", "november", "december")},
}
BEA = {
    B.ICS_URL: (FIX / "bea" / "schedule-2026-11-13.ics").read_text(encoding="utf-8"),
    B.DATES_URL: (FIX / "bea" / "release_dates-2026-11-13.json").read_text(encoding="utf-8"),
}

# Ảnh chụp chính sách theo phiên bản: đổi bảng mức / cửa sổ mà không đổi POLICY_VERSION → đỏ.
POLICY_FINGERPRINTS = {
    "event-policy-2026.11.13":
        "5d4a3853ebd620eb7f5fbc65bab085e8eb83a02b3f1b203dec4f80cd8760fe87",
}


def utc(*a):
    return datetime(*a, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        st = PointInTimeStore()
    else:
        repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'c.db'}")
        repo.create_all()
        st = SqlExternalRecordStore(repo.engine)
    log = SourceCheckLog()
    F.run_once(store=st, log=log, get=lambda p: FED[p], now=NOW)
    B.run_schedule_once(store=st, log=log, get=lambda u, p=None: BEA[u], now=NOW)
    D.run_schedule_once(store=st, log=log, now=NOW)
    return st


def cal_record(key, at, payload, rev=0, ingested=NOW, source="fed_fomc"):
    return NormalizedRecord(
        record_id=f"{source}:{key}:r{rev}", source=source, kind="calendar", logical_key=key,
        revision=rev, event_time=at, ingested_at=ingested, source_status=SourceStatus.HEALTHY,
        payload_version="t", raw_ref="test", payload=payload)


def find(items, key):
    got = [i for i in items if i.logical_key == key]
    assert len(got) == 1, key
    return got[0]


# ------------------------------------------------------------------ ING-20: mức quan trọng

def test_importance_table():
    assert I.rate("FOMC_STATEMENT").importance is I.Importance.HIGH
    assert I.rate("FOMC_PRESS_CONFERENCE").importance is I.Importance.HIGH
    assert I.rate("FOMC_MINUTES").importance is I.Importance.MEDIUM
    assert I.rate("BEA_PIO").importance is I.Importance.HIGH
    assert I.rate("BEA_GDP", "ADVANCE").importance is I.Importance.HIGH
    assert I.rate("BEA_GDP", "SECOND").importance is I.Importance.MEDIUM
    assert I.rate("DOL_JOBLESS_CLAIMS").importance is I.Importance.MEDIUM
    for ev, var in (("CPI", None), (None, None), ("BEA_GDP", None), ("BEA_GDP", "INITIAL"),
                    ("BEA_GDP", "UPDATED"), ("fomc_statement", None)):
        r = I.rate(ev, var)
        assert (r.importance, r.known) == (I.Importance.HIGH, False), (ev, var)
    assert I.rate("FOMC_STATEMENT").policy_version == I.POLICY_VERSION


def test_policy_change_requires_new_version():
    snap = json.dumps(I.table_snapshot(), sort_keys=True, ensure_ascii=False)
    fp = hashlib.sha256(snap.encode()).hexdigest()
    assert I.POLICY_VERSION in POLICY_FINGERPRINTS, "đổi chính sách: thêm phiên bản mới"
    assert POLICY_FINGERPRINTS[I.POLICY_VERSION] == fp, \
        "bảng mức quan trọng / cửa sổ đổi mà POLICY_VERSION giữ nguyên"


def test_windows_are_sane():
    for imp, w in I.WINDOWS.items():
        assert timedelta(0) <= w.before <= timedelta(hours=1), imp
        assert timedelta(0) < w.after <= timedelta(hours=1), imp
    assert I.WINDOWS[I.Importance.HIGH].after >= I.WINDOWS[I.Importance.MEDIUM].after \
        >= I.WINDOWS[I.Importance.LOW].after


# ------------------------------------------------------------------ bảng hợp nhất, dữ liệu thật

def test_unified_calendar_from_real_sources(store):
    items = C.economic_calendar(store, NOW)
    assert {i.source for i in items} == set(C.CALENDAR_SOURCES)
    fomc = find(items, "FOMC_STATEMENT:2026-12-09")
    assert (fomc.release_at, fomc.importance, fomc.all_day) == (utc(2026, 12, 9, 19), "HIGH",
                                                                 False)
    assert (fomc.window_start, fomc.window_end) == (utc(2026, 12, 9, 18, 45),
                                                     utc(2026, 12, 9, 19, 15))
    gdp = find(items, "GDP:2026Q3:SECOND")
    assert (gdp.importance, gdp.variant) == ("MEDIUM", "SECOND")
    assert (gdp.window_start, gdp.window_end) == (utc(2026, 11, 25, 13, 25),
                                                   utc(2026, 11, 25, 13, 40))
    pio = [i for i in items if i.event == "BEA_PIO" and i.release_at == utc(2026, 11, 25, 13, 30)]
    assert len(pio) == 1 and pio[0].importance == "HIGH"
    assert (pio[0].window_start, pio[0].window_end) == (utc(2026, 11, 25, 13, 15),
                                                         utc(2026, 11, 25, 13, 45))
    claims = find(items, "CLAIMS:2026-11-19")
    assert (claims.importance, claims.window_start, claims.window_end) == (
        "MEDIUM", utc(2026, 11, 19, 13, 25), utc(2026, 11, 19, 13, 40))
    assert "TIME_BY_RULE" in claims.notes and not claims.time_confirmed and not claims.all_day
    # 1C-C07: không forecast → không đủ dữ liệu, nhưng vẫn có cửa sổ
    for i in items:
        assert i.forecast is None and i.forecast_status == "INSUFFICIENT_DATA"
        assert i.surprise_status == "INSUFFICIENT_DATA"
        assert i.window_start < i.window_end and i.policy_version == I.POLICY_VERSION


def test_holiday_week_and_unconfirmed_time_block_whole_new_york_day(store):
    items = C.economic_calendar(store, NOW, end=utc(2027, 3, 1))
    for key, day in (("CLAIMS:2026-11-26:WED", date(2026, 11, 25)),
                     ("CLAIMS:2026-11-26", date(2026, 11, 26)),
                     ("CLAIMS:2026-11-26:FRI", date(2026, 11, 27))):
        it = find(items, key)
        assert it.all_day and it.release_date_local == day
        # EST (UTC-5): 0:00 ET = 05:00 UTC, dài đúng 24 giờ
        assert it.window_start == datetime(day.year, day.month, day.day, 5, tzinfo=UTC)
        assert it.window_end - it.window_start == timedelta(hours=24)
    # Họp FOMC 2027 chưa có lịch tháng → chưa chắc giờ → cả ngày cuối họp
    jan = [i for i in items if i.event == "FOMC_STATEMENT" and i.release_at.year == 2027]
    assert jan and all(i.all_day and not i.time_confirmed for i in jan)
    assert all(i.window_end - i.window_start == timedelta(hours=24) for i in jan)


def test_dst_day_windows_23_and_25_hours():
    s, e = C._day_window(date(2027, 3, 14))  # Mỹ sang giờ hè
    assert e - s == timedelta(hours=23) and s == utc(2027, 3, 14, 5)
    s, e = C._day_window(date(2026, 11, 1))  # Mỹ về giờ chuẩn
    assert e - s == timedelta(hours=25) and s == utc(2026, 11, 1, 4)
    s, e = C._day_window(date(2026, 7, 2))
    assert (s, e - s) == (utc(2026, 7, 2, 4), timedelta(hours=24))


def test_distrusted_time_widens_to_whole_day():
    st = PointInTimeStore()
    at = utc(2026, 12, 2, 19)
    st.append(cal_record("FOMC_MINUTES:2026-12-02", at, {
        "event": "FOMC_MINUTES", "time_confirmed": True, "all_day": False, "status": "SCHEDULED",
        "flags": ["CALENDAR_SOURCES_DISAGREE"], "tz": "America/New_York"}))
    it = C.economic_calendar(st, NOW)[0]
    assert it.all_day and not it.time_confirmed and "TIME_DISTRUSTED_WHOLE_DAY" in it.notes
    assert (it.window_start, it.window_end) == (utc(2026, 12, 2, 5), utc(2026, 12, 3, 5))


def test_unknown_event_is_high_with_note():
    st = PointInTimeStore()
    st.append(cal_record("X:1", utc(2026, 11, 20, 15), {
        "event": "SOMETHING_NEW", "time_confirmed": True, "status": "SCHEDULED", "flags": []}))
    st.append(cal_record("X:2", utc(2026, 11, 21, 15), {"time_confirmed": True}))
    a, b = C.economic_calendar(st, NOW)
    for it in (a, b):
        assert it.importance == "HIGH" and "IMPORTANCE_UNKNOWN_EVENT" in it.notes
    assert b.event == "UNKNOWN" and b.status == "SCHEDULED"
    assert (a.window_start, a.window_end) == (utc(2026, 11, 20, 14, 45), utc(2026, 11, 20, 15, 15))


def test_removed_and_moved_events_point_in_time():
    st = PointInTimeStore()
    base = {"event": "FOMC_STATEMENT", "time_confirmed": True, "all_day": False,
            "status": "SCHEDULED", "flags": []}
    t1, t2 = utc(2026, 12, 9, 19), utc(2026, 12, 16, 19)
    st.append(cal_record("FOMC_STATEMENT:A", t1, base))
    st.append(cal_record("FOMC_STATEMENT:A", t2, base, rev=1, ingested=NOW + timedelta(hours=1)))
    st.append(cal_record("FOMC_STATEMENT:B", t1, base, source="fed_fomc"))
    st.append(cal_record("FOMC_STATEMENT:B", t1, {**base, "status": "REMOVED"}, rev=1,
                         ingested=NOW + timedelta(hours=1)))
    before = C.economic_calendar(st, NOW)
    assert [(i.logical_key, i.release_at) for i in before] == [
        ("FOMC_STATEMENT:A", t1), ("FOMC_STATEMENT:B", t1)]
    after = C.economic_calendar(st, NOW + timedelta(hours=1))
    assert [(i.logical_key, i.release_at) for i in after] == [("FOMC_STATEMENT:A", t2)]
    # Đã dời: cửa sổ ngày cũ không còn (lỗi lọc trước khi chọn revision đã sửa ở 8g-2)
    assert C.active_windows(st, t1, ) == []
    assert C.active_windows(st, NOW + timedelta(hours=1)) == []
    rem = C.economic_calendar(st, NOW + timedelta(hours=1), include_removed=True)
    gone = find(rem, "FOMC_STATEMENT:B")
    assert gone.status == "REMOVED" and gone.window_start is None
    assert not gone.window_contains(t1)


def dol_value(week, released, series="ICSA", value="220000", rev=0):
    return NormalizedRecord(
        record_id=f"dol_claims:{series}:{week}:r{rev}", source="dol_claims", kind="macro",
        logical_key=f"{series}:{week}", revision=rev, event_time=utc(2026, 11, 15, 5),
        ingested_at=released + timedelta(seconds=40), available_at=released,
        source_status=SourceStatus.HEALTHY, payload_version="t", raw_ref="t",
        payload={"series": series, "week_ending": week, "value": value})


def test_active_windows(store):
    # Số tuần đến 14/11 đã nhận lúc 13:30:40 → cửa sổ không bị kéo dài
    store.append(dol_value("2026-11-14", utc(2026, 11, 19, 13, 30)))
    at = utc(2026, 11, 19, 13, 31)
    assert [i.logical_key for i in C.active_windows(store, at)] == ["CLAIMS:2026-11-19"]
    assert C.active_windows(store, utc(2026, 11, 19, 13, 40)) == []  # biên phải mở
    assert [i.logical_key for i in C.active_windows(store, utc(2026, 11, 19, 13, 25))] == \
        ["CLAIMS:2026-11-19"]  # biên trái đóng
    # Ngày Lễ Tạ ơn: sự kiện cả ngày phủ cả lúc nửa đêm giờ New York
    assert [i.logical_key for i in C.active_windows(store, utc(2026, 11, 26, 5))] == \
        ["CLAIMS:2026-11-26"]


def test_point_in_time_and_input_checks(store):
    assert C.economic_calendar(store, NOW - timedelta(seconds=1)) == []  # chưa nạp
    with pytest.raises(ValueError):
        C.economic_calendar(store, datetime(2026, 11, 13, 12))
    # Khoảng thời gian hẹp: chỉ sự kiện có cửa sổ giao khoảng đó
    got = C.economic_calendar(store, NOW, start=utc(2026, 11, 25, 13, 40),
                              end=utc(2026, 11, 25, 13, 41))
    assert {i.event for i in got} == {"BEA_PIO", "DOL_JOBLESS_CLAIMS"}


def test_cli_lich(store, capsys):
    from gold_trading.ingestion import cli
    assert cli._lich(14, store=store, now=NOW) == 0
    out = capsys.readouterr().out
    assert "2026-11-19 20:30 (NY 08:30)" in out and "DOL_JOBLESS_CLAIMS" in out
    assert "TIME_BY_RULE" in out and "2026-11-26 cả ngày (New York)" in out
    assert "GDP:2026Q3:SECOND" in out and "không đủ dữ liệu" in out
    assert "số: NOT_DUE" in out
    # Có nhật ký lần kiểm: in trạng thái nguồn (chưa kiểm = không khỏe)
    assert cli._lich(14, store=store, now=NOW, check_log=SourceCheckLog()) == 0
    out = capsys.readouterr().out
    assert "fed_fomc KHÔNG KHỎE" in out and "SCHEDULE_SOURCE_UNHEALTHY" in out
    assert cli._lich(0, store=store, now=NOW) == 2
    assert cli._lich(5, env={}) == 2
    assert cli._lich(3, store=PointInTimeStore(), now=NOW) == 0
    assert "chưa có sự kiện" in capsys.readouterr().out


# ------------------------------------------------------------------ 8g-3: 1C-C05 số actual

def dol_item(store, at, key="CLAIMS:2026-11-19", **kw):
    return find(C.economic_calendar(store, at, start=at - timedelta(days=2), **kw), key)


def test_actual_status_flow_and_window_extension(store):
    rel = utc(2026, 11, 19, 13, 30)
    it = dol_item(store, rel - timedelta(minutes=10))
    assert it.actual_status == "NOT_DUE" and it.window_end == rel + timedelta(minutes=10)
    it = dol_item(store, rel + timedelta(minutes=5))
    assert it.actual_status == "AWAITING" and it.window_end == rel + timedelta(minutes=10)
    it = dol_item(store, rel + timedelta(minutes=8))  # sắp hết cửa sổ mà chưa có số → kéo dài
    assert it.window_end == rel + timedelta(minutes=13)
    assert "WINDOW_EXTENDED_ACTUAL_UNKNOWN" in it.notes
    at = rel + timedelta(minutes=20)  # quá 15 phút chưa có số → chưa biết
    it = dol_item(store, at)
    assert it.actual_status == "UNKNOWN_LATE" and "ACTUAL_UNKNOWN" in it.notes
    assert [i.logical_key for i in C.active_windows(store, at)] == ["CLAIMS:2026-11-19"]
    # Nguồn số không khỏe → chưa biết ngay, kể cả trong 15 phút đầu
    it = dol_item(store, rel + timedelta(minutes=1), health={"dol_claims": False})
    assert it.actual_status == "UNKNOWN_SOURCE_DOWN"
    # Số tới muộn lúc 14:00 (biết lúc 14:00:40): trước đó vẫn chặn, sau đó hết
    store.append(dol_value("2026-11-14", utc(2026, 11, 19, 14, 0)))
    assert dol_item(store, utc(2026, 11, 19, 13, 59)).actual_status == "UNKNOWN_LATE"
    it = dol_item(store, utc(2026, 11, 19, 14, 1))
    assert it.actual_status == "RECEIVED" and "ACTUAL_LATE" in it.notes
    assert it.window_end == utc(2026, 11, 19, 14, 0, 40)
    assert it.actuals == (("ICSA", "220000"),)
    assert C.active_windows(store, utc(2026, 11, 19, 14, 1)) == []


def test_unknown_actual_window_capped_at_end_of_new_york_day(store):
    last = utc(2026, 11, 20, 4, 58)  # 23:58 ET ngày 19/11
    it = dol_item(store, last)
    assert it.actual_status == "UNKNOWN_LATE" and it.window_end == utc(2026, 11, 20, 5)
    assert it.window_contains(last)
    it = dol_item(store, utc(2026, 11, 20, 5))
    assert "ACTUAL_MISSING_END_OF_DAY" in it.notes and not it.window_contains(
        utc(2026, 11, 20, 5))


def test_holiday_week_later_days_released_when_number_already_out(store):
    # Lễ Tạ ơn: số tuần đến 21/11 ra thứ Tư 25/11 8:30 ET
    store.append(dol_value("2026-11-21", utc(2026, 11, 25, 13, 30)))
    at = utc(2026, 11, 26, 15)
    items = C.economic_calendar(store, at, start=utc(2026, 11, 25), end=utc(2026, 11, 28))
    keys = [i.logical_key for i in items if i.event == "DOL_JOBLESS_CLAIMS"]
    assert keys == ["CLAIMS:2026-11-26:WED"]  # thứ Năm, thứ Sáu không còn phải chặn
    assert items[0].actual_status == "RECEIVED" and items[0].all_day
    assert C.active_windows(store, at) == []
    # Point-in-time: thứ Tư lúc 8:00 ET chưa có số → cả thứ Năm, thứ Sáu vẫn chờ
    before = C.economic_calendar(store, utc(2026, 11, 25, 13), start=utc(2026, 11, 25),
                                 end=utc(2026, 11, 28))
    assert {i.logical_key for i in before if i.event == "DOL_JOBLESS_CLAIMS"} == {
        "CLAIMS:2026-11-26:WED", "CLAIMS:2026-11-26", "CLAIMS:2026-11-26:FRI"}


def test_bea_actuals_matched_per_release(store):
    rel = utc(2026, 11, 25, 13, 30)
    store.append(NormalizedRecord(
        record_id="bea_nipa:A191RL:2026Q3:r1", source="bea_nipa", kind="macro",
        logical_key="A191RL:2026Q3", revision=1, event_time=utc(2026, 10, 1),
        ingested_at=rel + timedelta(seconds=80), available_at=rel,
        source_status=SourceStatus.HEALTHY, payload_version="t", raw_ref="t",
        payload={"series": "A191RL", "value": "3.6", "release_ref": "GDP:2026Q3:SECOND"}))
    at = rel + timedelta(minutes=12)
    items = C.economic_calendar(store, at, start=rel - timedelta(hours=1))
    gdp = find(items, "GDP:2026Q3:SECOND")
    assert gdp.actual_status == "RECEIVED" and gdp.actuals == (("A191RL", "3.6"),)
    assert gdp.window_end == rel + timedelta(minutes=10)
    pio = [i for i in items if i.event == "BEA_PIO" and i.release_at == rel][0]
    assert pio.actual_status == "AWAITING"  # cùng giờ nhưng chưa có số PCE
    # thứ Tư tuần lễ: DOL cũng đang chặn cả ngày
    assert [i.event for i in C.active_windows(store, at)] == ["DOL_JOBLESS_CLAIMS", "BEA_PIO"]


def test_schedule_source_unhealthy_distrusts_future_times(store):
    items = C.economic_calendar(store, NOW, health={"fed_fomc": False})
    dec = find(items, "FOMC_STATEMENT:2026-12-09")
    assert dec.all_day and "SCHEDULE_SOURCE_UNHEALTHY" in dec.notes
    assert (dec.window_start, dec.window_end) == (utc(2026, 12, 9, 5), utc(2026, 12, 10, 5))
    assert dec.actual_status == "NOT_APPLICABLE"
    ok = find(C.economic_calendar(store, NOW, health={"fed_fomc": True}),
              "FOMC_STATEMENT:2026-12-09")
    assert not ok.all_day


def test_health_map_from_check_log():
    st, log = PointInTimeStore(), SourceCheckLog()
    F.run_once(store=st, log=log, get=lambda p: FED[p], now=NOW)
    h = C.health_map(log, st, NOW)
    assert h["fed_fomc"] is True
    assert h["bea_nipa"] is False and h["dol_claims"] is False  # chưa kiểm lần nào
    assert C.health_map(log, st, NOW + timedelta(hours=27))["fed_fomc"] is False  # STALE


# ------------------------------------------------------------------ 8g-3: ING-19 / 1C-C08

def test_revision_classify():
    from decimal import Decimal

    from gold_trading.ingestion import revisions as V
    assert V.classify("ICSA", "220000", "232000") == ("LARGE_REVISION", Decimal("12000"))
    assert V.classify("ICSA", "220000", "210000") == ("LARGE_REVISION", Decimal("-10000"))
    assert V.classify("ICSA", "220000", "223000")[0] == "SMALL_REVISION"
    assert V.classify("A191RL", "3.4", "2.4")[0] == "LARGE_REVISION"   # đúng bằng ngưỡng
    assert V.classify("A191RL", "3.4", "2.5")[0] == "SMALL_REVISION"
    assert V.classify("DPCERG", "132.257", "135.0")[0] == "NO_THRESHOLD"
    for a, b in ((None, "1"), ("(NA)", "1"), ("1", None), ("x", "1"), ("1", "NaN")):
        assert V.classify("A191RL", a, b) == ("NOT_COMPARABLE", None)  # không coi trống là 0


def test_revisions_view_point_in_time(store):
    from gold_trading.ingestion import revisions as V
    pdf = (FIX / "dol" / "ui-data-2026-11-12.pdf").read_bytes()
    D.run_values_once(store=store, log=SourceCheckLog(), get=lambda u: pdf, now=NOW)
    first = store.as_of(NOW, source="dol_claims", logical_key="ICSA:2026-11-07")[0]
    nxt = utc(2026, 11, 19, 13, 30)
    big = str(int(first.payload["value"]) + 12000)
    store.append(NormalizedRecord(
        record_id="dol_claims:ICSA:2026-11-07:r1", source="dol_claims", kind="macro",
        logical_key="ICSA:2026-11-07", revision=1, event_time=first.event_time,
        ingested_at=nxt + timedelta(seconds=30), available_at=nxt,
        source_status=SourceStatus.HEALTHY, payload_version="t", raw_ref="t",
        payload={**first.payload, "value": big}))
    assert V.revisions(store, nxt) == []  # chưa biết bản sửa
    got = V.revisions(store, nxt + timedelta(minutes=1))
    assert len(got) == 1
    r = got[0]
    assert (r.series, r.revision, r.previous_value, r.value, r.delta, r.flag) == (
        "ICSA", 1, first.payload["value"], big, "12000", "LARGE_REVISION")
    assert r.policy_version == V.REVISION_POLICY_VERSION and r.threshold == "10000"
    assert V.revisions(store, nxt + timedelta(days=61)) == []  # ngoài khoảng since
    with pytest.raises(ValueError):
        V.revisions(store, datetime(2026, 11, 20))


def test_late_known_number_never_extends_window_past_new_york_day(store):
    """Lỗi tìm được khi soát: số tuần lễ nạp muộn 1 ngày làm cửa sổ cả ngày kéo sang hôm sau."""
    # Số tuần đến 21/11 DOL phát hành thứ Tư 25/11 8:30 ET nhưng hệ thống chỉ biết lúc 2:00 ET
    # thứ Sáu 27/11 (backend tắt hai ngày)
    known = utc(2026, 11, 27, 7)
    store.append(NormalizedRecord(
        record_id="dol_claims:ICSA:2026-11-21:r0", source="dol_claims", kind="macro",
        logical_key="ICSA:2026-11-21", revision=0, event_time=utc(2026, 11, 22, 5),
        ingested_at=known, available_at=utc(2026, 11, 25, 13, 30),
        source_status=SourceStatus.HEALTHY, payload_version="t", raw_ref="t",
        payload={"series": "ICSA", "week_ending": "2026-11-21", "value": "1"}))
    at = known + timedelta(minutes=1)
    items = {i.logical_key: i for i in C.economic_calendar(
        store, at, start=utc(2026, 11, 24), end=utc(2026, 11, 29))
        if i.event == "DOL_JOBLESS_CLAIMS"}
    wed, thu, fri = (items["CLAIMS:2026-11-26:WED"], items["CLAIMS:2026-11-26"],
                     items["CLAIMS:2026-11-26:FRI"])
    assert wed.window_end == utc(2026, 11, 26, 5) and "ACTUAL_LATE" in wed.notes
    assert thu.window_end == utc(2026, 11, 27, 5)  # không kéo qua hết ngày
    assert fri.window_start == utc(2026, 11, 27, 5) and fri.window_end == known
    assert "RELEASED_EARLIER_IN_WEEK" in fri.notes
    assert C.active_windows(store, at) == []
    assert [i.logical_key for i in C.active_windows(store, known - timedelta(minutes=1))] == \
        ["CLAIMS:2026-11-26:FRI"]  # trước lúc biết số: vẫn chặn
