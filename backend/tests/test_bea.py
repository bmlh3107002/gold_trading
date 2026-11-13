"""Bước 8c — BEA: lịch công bố (ING-09) + số actual GDP, PCE (ING-17), revision (ING-19).

Dữ liệu: file lịch ICS + JSON thật tải 2026-11-13; phản hồi API NIPA dựng theo hướng dẫn API của
BEA với số thật từ file công khai NipaData (xem ``tests/fixtures/bea/README.md``).
Case: 1C-C01 (chưa có số ≠ 0), 1C-C02 (hủy), 1C-C03 (đổi giờ), 1C-C04 (DST), 1C-C06 (hai nguồn
lệch), 1C-C08 (sửa số), trang hỏng, lỗi mạng, khóa thiếu / sai, khóa không bao giờ bị lưu.
"""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from gold_trading.common.enums import SourceStatus
from gold_trading.ingestion import cli
from gold_trading.ingestion.api_keys import ApiKey, KeyLookup
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.ingestion.source_status import (
    CheckOutcome,
    SourceCheckLog,
    SourceRegistry,
    evaluate,
)
from gold_trading.ingestion.source_terms import SourceTerms, TermsStatus
from gold_trading.ingestion.sources import bea as B
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.schema import external_records
from gold_trading.storage.source_checks import SqlSourceCheckLog

FIX = Path(__file__).parent / "fixtures" / "bea"
ICS = (FIX / "schedule-2026-11-13.ics").read_text(encoding="utf-8")
DATES = (FIX / "release_dates-2026-11-13.json").read_text(encoding="utf-8")
NIPA = {t: (FIX / f"nipa-{t}-2026-11-13.json").read_text(encoding="utf-8") for t in B.TABLES}
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
KEY_VALUE = "ABCDEF12-3456-7890-ABCD-EF1234567890"
KEY = KeyLookup("bea", ApiKey("bea", KEY_VALUE), None)


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def getter(ics=ICS, dates=DATES, nipa=None, calls=None):
    nipa = {**NIPA, **(nipa or {})}

    def get(url, params=None):
        if calls is not None:
            calls.append((url, dict(params or {})))
        if url == B.ICS_URL:
            v = ics
        elif url == B.DATES_URL:
            v = dates
        elif url == B.API_URL:
            assert params["UserID"] == KEY_VALUE
            v = nipa[params["TableName"]]
        else:
            raise AssertionError(url)
        if isinstance(v, Exception):
            raise v
        return v
    return get


@pytest.fixture(params=["memory", "sqlite"])
def env(request, tmp_path):
    if request.param == "memory":
        return PointInTimeStore(), SourceCheckLog()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'b.db'}")
    repo.create_all()
    return SqlExternalRecordStore(repo.engine), SqlSourceCheckLog(repo.engine)


def schedule(now=NOW, ics=ICS, dates=DATES):
    return B.build_schedule(B.parse_ics(ics), B.parse_release_dates(dates), now)


def by_key(events):
    return {e.logical_key: e for e in events}


def set_event(summary_part: str, new_line: str, extra: str = "", ics=ICS) -> str:
    """Đổi dòng DTSTART (và thêm dòng ``extra``) của đúng một sự kiện có tiêu đề chứa
    ``summary_part`` (tiêu đề đã nối dòng gập)."""
    text = ics.replace("\r\n", "\n")
    blocks = text.split("BEGIN:VEVENT\n")
    hits = [i for i, b in enumerate(blocks) if summary_part in b.replace("\n ", "")]
    assert len(hits) == 1, hits
    lines = blocks[hits[0]].split("\n")
    lines = [new_line if ln.startswith("DTSTART") else ln for ln in lines]
    if extra:
        lines.insert(1, extra)
    blocks[hits[0]] = "\n".join(lines)
    return "BEGIN:VEVENT\n".join(blocks)


# ------------------------------------------------------------------ lịch: đọc file thật

def test_real_schedule_upcoming_gdp_pce():
    ev = by_key(schedule())
    gdp = ev["GDP:2026Q3:SECOND"]
    assert gdp.event_time == utc(2026, 11, 25, 13, 30)  # 8:30 sáng giờ miền Đông (EST)
    assert gdp.payload["time_confirmed"] and not gdp.payload["all_day"]
    assert gdp.payload["release_local"] == "08:30" and gdp.payload["flags"] == []
    assert gdp.payload["includes"] == ["REAL_GDP"]
    pio = ev["PIO:2026-10"]
    assert pio.event_time == utc(2026, 11, 25, 13, 30)
    assert "PCE_PRICE_INDEX" in pio.payload["includes"]
    # Đúng 2 năm tới: mỗi tháng một PIO, mỗi quý ba ước tính GDP; không cờ lệch nào.
    assert len(ev) == 28
    assert all(e.payload["flags"] == [] for e in ev.values())
    assert {k for k in ev if k.startswith("GDP:2027Q1")} == {
        "GDP:2027Q1:ADVANCE", "GDP:2027Q1:SECOND", "GDP:2027Q1:THIRD"}


def test_dst_conversion_from_utc_file():
    # 1C-C04: file ghi giờ UTC; mùa hè 12:30 UTC và mùa đông 13:30 UTC đều là 8:30 ET.
    ev = by_key(schedule(now=utc(2027, 3, 1)))
    assert ev["GDP:2027Q1:ADVANCE"].event_time == utc(2027, 4, 29, 12, 30)
    assert ev["GDP:2026Q4:THIRD"].event_time == utc(2027, 3, 31, 12, 30)
    assert ev["PIO:2027-01"].event_time == utc(2027, 2, 25, 13, 30)
    assert {e.payload["release_local"] for e in ev.values()} == {"08:30"}


def test_old_title_formats_and_combined_month():
    # Thời kỳ chính phủ đóng cửa 2025: "Initial/Updated Estimate", PIO gộp hai tháng.
    ev = by_key(schedule(now=utc(2025, 12, 1)))
    assert ev["GDP:2025Q3:INITIAL"].event_time == utc(2025, 12, 23, 13, 30)
    assert ev["GDP:2025Q3:UPDATED"].event_time == utc(2026, 1, 22, 13, 30)
    assert ev["PIO:2025-10..2025-11"].event_time == utc(2026, 1, 22, 15, 0)  # 10:00 ET
    assert ev["PIO:2025-09"].event_time == utc(2025, 12, 5, 15, 0)


@pytest.mark.parametrize("title,expect", [
    ("GDP (Second Estimate) and Corporate Profits, 3rd Quarter 2026", "GDP:2026Q3:SECOND"),
    ("GDP (Advance Estimate), 4th Quarter and Year 2026", "GDP:2026Q4:ADVANCE"),
    ("Gross Domestic Product, 1st Quarter 2025 (Third Estimate), GDP by Industry, and Corporate "
     "Profits (Revised)", "GDP:2025Q1:THIRD"),
    ("Personal Income and Outlays, July 2026 ", "PIO:2026-07"),
    ("Personal Income and Outlays, October and November 2025", "PIO:2025-10..2025-11"),
    ("GDP by County and Personal Income by County, 2025", None),
    ("Gross Domestic Product by State and Personal Income by State, 3rd quarter 2025", None),
    ("Gross Domestic Product for Puerto Rico, 2024", None),
    ("U.S. International Trade in Goods and Services, October 2026", None),
    ("Real Personal Consumption Expenditures by State and Real Personal Income by State, 2025",
     None),
])
def test_classify_titles(title, expect):
    r = B.classify(title)
    assert (r.logical_key if r else None) == expect


@pytest.mark.parametrize("title", [
    "GDP (Fourth Estimate), 3rd Quarter 2026",           # ước tính lạ
    "GDP (Advance Estimate), Third Quarter 2026",        # quý viết kiểu khác
    "GDP (Advance Estimate), 1st Quarter 2026 and 2nd Quarter 2026",
    "Personal Income and Outlays, Octobre 2026",
    "Personal Income and Outlays, 2026",
    "Personal Income and Outlays, November and October 2026",
    "Personal Income and Outlays, December 2025 and January 2026",
])
def test_classify_rejects_lookalike_titles(title):
    with pytest.raises(B.BeaParseError):
        B.classify(title)


def test_old_unparseable_titles_outside_window_are_ignored():
    # Tiêu đề cũ (trước cửa sổ) có định dạng lạ không làm hỏng lần tải hiện tại.
    old = ("BEGIN:VEVENT\nSUMMARY:GDP (Weird), Q 2020\nDTSTART:20200101T133000Z\nEND:VEVENT\n")
    ics = ICS.replace("BEGIN:VEVENT", old + "BEGIN:VEVENT", 1)
    assert len(schedule(ics=ics)) == 28


# ------------------------------------------------------------------ lịch: file hỏng

@pytest.mark.parametrize("broken", [
    "<html>bảo trì</html>",
    "",
    ICS.replace("END:VCALENDAR", ""),
    ICS.replace("END:VEVENT", "", 1),                                     # VEVENT không đóng
    ICS.replace("DTSTART;VALUE=DATE-TIME:20250107T133000Z", "", 1),       # thiếu DTSTART
    ICS.replace("DTSTART:20261125T133000Z", "DTSTART:20261125T083000", 1),  # giờ trôi
    ICS.replace("DTSTART:20261125T133000Z", "DTSTART:20261325T133000Z", 1),  # tháng 13
    ICS.replace("DTSTART:20261125T133000Z",
                "DTSTART;TZID=Europe/London:20261125T133000", 1),          # múi giờ lạ
    "BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n",                     # không sự kiện
])
def test_broken_ics_rejected(broken):
    with pytest.raises(B.BeaParseError):
        schedule(ics=broken)


def test_lookalike_title_in_window_rejects_whole_fetch():
    ics = ICS.replace("GDP (Second Estimate) and Corporate Profits\\, 3rd Quarter 2026",
                      "GDP (Second Estimate) and Corporate Profits\\, Q3 2026")
    with pytest.raises(B.BeaParseError):
        schedule(ics=ics)


@pytest.mark.parametrize("broken", [
    "not json", "[]", json.dumps({"Gross Domestic Product": {"release_dates": []}}),
    DATES.replace("2026-11-25T13:30:00+00:00", "2026-11-25T13:30:00", 1),  # giờ không múi
    DATES.replace("2026-11-25T13:30:00+00:00", "25/11/2026", 1),
])
def test_broken_release_dates_rejected(broken):
    with pytest.raises(B.BeaParseError):
        B.parse_release_dates(broken)


def test_no_future_release_rejected():
    with pytest.raises(B.BeaParseError):
        schedule(now=utc(2028, 6, 1))


# ------------------------------------------------------------------ lịch: hai nguồn lệch

def test_ics_time_differs_from_json_flagged_and_all_day():
    # 1C-C06: lịch ICS dời PIO tháng 10 sang 10:00 ET mà file JSON vẫn 8:30 → không tin giờ.
    ics = set_event("Personal Income and Outlays\\, October 2026", "DTSTART:20261125T150000Z")
    ev = by_key(schedule(ics=ics))
    moved = [e for e in ev.values() if e.payload["flags"]]
    assert [e.logical_key for e in moved] == ["PIO:2026-10"]
    m = moved[0]
    assert m.payload["flags"] == ["CALENDAR_SOURCES_DISAGREE"]
    assert not m.payload["time_confirmed"] and m.payload["all_day"]
    assert m.event_time == utc(2026, 11, 25, 5, 0)  # 00:00 ET → chặn cả ngày


def test_json_only_date_added_as_all_day_event():
    d = json.loads(DATES)
    d["Gross Domestic Product"]["release_dates"].append("2026-12-02T13:30:00+00:00")
    ev = by_key(schedule(dates=json.dumps(d)))
    x = ev["GDP:UNMATCHED:2026-12-02"]
    assert x.payload["all_day"] and x.payload["flags"] == ["CALENDAR_SOURCES_DISAGREE"]
    assert x.event_time == utc(2026, 12, 2, 5, 0)
    assert len(ev) == 29


def test_ics_event_missing_from_json_flagged():
    d = json.loads(DATES)
    d["Personal Income and Outlays"]["release_dates"].remove("2026-12-23T13:30:00+00:00")
    ev = by_key(schedule(dates=json.dumps(d)))
    assert ev["PIO:2026-11"].payload["flags"] == ["CALENDAR_SOURCES_DISAGREE"]
    assert ev["GDP:2026Q3:THIRD"].payload["flags"] == []  # nhóm GDP không bị ảnh hưởng


def test_date_only_event_is_all_day():
    ics = set_event("Personal Income and Outlays\\, November 2026",
                    "DTSTART;VALUE=DATE:20261223")
    ev = by_key(schedule(ics=ics))
    assert ev["PIO:2026-11"].payload["all_day"] and not ev["PIO:2026-11"].payload["time_confirmed"]
    assert ev["PIO:2026-11"].event_time == utc(2026, 12, 23, 5, 0)


# ------------------------------------------------------------------ lịch: chạy + revision

def run_sched(store, log, now=NOW, **kw):
    return B.run_schedule_once(store=store, log=log, get=getter(**kw), now=now)


def test_run_schedule_and_reload_idempotent(env):
    store, log = env
    c = run_sched(store, log)
    assert c.outcome is CheckOutcome.OK and c.inserted == 28
    c2 = run_sched(store, log, now=NOW + timedelta(hours=1))
    assert c2.outcome is CheckOutcome.OK and c2.inserted == 0
    h = evaluate(B.SCHEDULE_SOURCE, B.schedule_spec(), log.summary(B.SCHEDULE_SOURCE, NOW),
                 NOW, store.latest_event_time(B.SCHEDULE_SOURCE, NOW))
    assert h.status is SourceStatus.HEALTHY


def test_reschedule_creates_revision_past_view_kept(env):
    # 1C-C03: BEA dời ngày công bố (cả hai file) → revision mới, quá khứ vẫn thấy giờ cũ.
    store, log = env
    run_sched(store, log)
    later = NOW + timedelta(days=2)
    ics = set_event("Personal Income and Outlays\\, November 2026", "DTSTART:20261222T133000Z")
    d = json.loads(DATES)
    d["Personal Income and Outlays"]["release_dates"] = [
        "2026-12-22T13:30:00+00:00" if x == "2026-12-23T13:30:00+00:00" else x
        for x in d["Personal Income and Outlays"]["release_dates"]]
    assert run_sched(store, log, now=later, ics=ics, dates=json.dumps(d)).inserted == 1
    new = store.as_of(later, source=B.SCHEDULE_SOURCE, logical_key="PIO:2026-11")[0]
    old = store.as_of(NOW, source=B.SCHEDULE_SOURCE, logical_key="PIO:2026-11")[0]
    assert (new.revision, new.event_time) == (1, utc(2026, 12, 22, 13, 30))
    assert (old.revision, old.event_time) == (0, utc(2026, 12, 23, 13, 30))


def test_cancelled_release_becomes_removed(env):
    # 1C-C02: BEA hủy / hoãn không hẹn (STATUS:CANCELLED hoặc mất khỏi lịch) → REMOVED, không xóa.
    store, log = env
    run_sched(store, log)
    later = NOW + timedelta(days=1)
    ics = set_event("Personal Income and Outlays\\, November 2026",
                    "DTSTART:20261223T133000Z", extra="STATUS:CANCELLED")
    d = json.loads(DATES)
    d["Personal Income and Outlays"]["release_dates"].remove("2026-12-23T13:30:00+00:00")
    c = run_sched(store, log, now=later, ics=ics, dates=json.dumps(d))
    assert c.outcome is CheckOutcome.OK
    gone = [r for r in store.as_of(later, source=B.SCHEDULE_SOURCE)
            if r.payload["status"] == "REMOVED"]
    assert [r.logical_key for r in gone] == ["PIO:2026-11"]
    # Lần công bố GDP cùng ngày không bị ảnh hưởng.
    assert store.as_of(later, source=B.SCHEDULE_SOURCE, logical_key="GDP:2026Q3:THIRD"
                       )[0].payload["status"] == "SCHEDULED"


def test_many_removed_at_once_writes_nothing(env):
    store, log = env
    run_sched(store, log)
    norm = ICS
    for part in ("Personal Income and Outlays\\, November 2026",
                 "Personal Income and Outlays\\, December 2026",
                 "GDP (Advance Estimate)\\, 4th Quarter and Year 2026"):
        start = [ln for ln in norm.replace("\r\n", "\n").split("BEGIN:VEVENT\n")
                 if part in ln.replace("\n ", "")][0].split("DTSTART")[1].split("\n")[0]
        norm = set_event(part, "DTSTART" + start, extra="STATUS:CANCELLED", ics=norm)
    later = NOW + timedelta(days=1)
    c = run_sched(store, log, now=later, ics=norm)
    assert (c.outcome, c.error_code) == (CheckOutcome.INVALID, "TOO_MANY_REMOVALS")
    assert all(r.payload["status"] == "SCHEDULED"
               for r in store.as_of(later, source=B.SCHEDULE_SOURCE))


@pytest.mark.parametrize("kw,outcome,code", [
    ({"ics": B.FetchError("HTTP_503")}, CheckOutcome.ERROR, "HTTP_503"),
    ({"dates": B.FetchError("TIMEOUT")}, CheckOutcome.ERROR, "TIMEOUT"),
    ({"ics": "<html/>"}, CheckOutcome.INVALID, "PARSE_ERROR"),
    ({"dates": "{}"}, CheckOutcome.INVALID, "PARSE_ERROR"),
])
def test_schedule_errors_write_nothing(env, kw, outcome, code):
    store, log = env
    c = run_sched(store, log, **kw)
    assert (c.outcome, c.error_code) == (outcome, code)
    assert store.as_of(NOW, source=B.SCHEDULE_SOURCE) == []
    assert log.summary(B.SCHEDULE_SOURCE, NOW).last_check == c


def test_schedule_stale_after_26_hours(env):
    store, log = env
    run_sched(store, log)
    later = NOW + timedelta(hours=26, minutes=1)
    h = evaluate(B.SCHEDULE_SOURCE, B.schedule_spec(), log.summary(B.SCHEDULE_SOURCE, later),
                 later, None)
    assert (h.status, h.reason) == (SourceStatus.STALE, "FETCH_TTL_EXPIRED")


def test_terms_must_be_verified():
    t = {"bea": SourceTerms("bea", TermsStatus.NEEDS_REVIEW, date(2026, 11, 13), "#bea")}
    with pytest.raises(ValueError):
        SourceRegistry([B.schedule_spec()], terms=t)
    with pytest.raises(ValueError, match="chưa được bật"):
        B.run_schedule_once(store=PointInTimeStore(), log=SourceCheckLog(), get=getter(),
                            now=NOW, registry=SourceRegistry([]))
    SourceRegistry([B.schedule_spec(), B.values_spec()])  # điều khoản thật: VERIFIED


# ------------------------------------------------------------------ số actual: đọc

def test_parse_real_values_match_published_numbers():
    # Số tham chiếu: file công khai NipaData của BEA (sau lần công bố 29/10/2026).
    obs = {(o.series, o.period): o for t in B.TABLES
           for o in B.parse_table(t, json.loads(NIPA[t]))}
    assert obs[("A191RL", "2026Q3")].value == "3.4"   # GDP thực quý 3/2026, ước tính lần đầu
    assert obs[("A191RL", "2025Q4")].value == "0.2"
    assert obs[("DPCERGM", "2026-09")].value == "0.5"
    assert obs[("DPCERGM", "2026-06")].value == "-0.1"
    assert obs[("DPCCRGM", "2026-09")].value == "0.3"
    assert obs[("DPCERG", "2026-09")].value == "132.257"
    assert obs[("DPCCRG", "2025-09")].value == "126.940"
    # Dòng không cấu hình (DPCERL, DGDSRGM...) bị bỏ qua.
    assert {s for s, _ in obs} == {"A191RL", "DPCERGM", "DPCCRGM", "DPCERG", "DPCCRG"}
    # Cuối kỳ = 00:00 giờ miền Đông của ngày đầu kỳ sau.
    assert obs[("A191RL", "2026Q3")].period_end == utc(2026, 10, 1, 4, 0)
    assert obs[("DPCERGM", "2025-12")].period_end == utc(2026, 1, 1, 5, 0)


def test_hand_check_yoy_from_levels():
    # Kiểm tay: chỉ số mức khớp % tháng BEA công bố (132.257 / 131.611 - 1 = 0.49 % → "0.5").
    obs = {(o.series, o.period): o for o in B.parse_table("T20804", json.loads(NIPA["T20804"]))}
    a, b = float(obs[("DPCERG", "2026-09")].value), float(obs[("DPCERG", "2026-08")].value)
    assert round((a / b - 1) * 100, 1) == 0.5


@pytest.mark.parametrize("raw,expect", [
    ("3.4", "3.4"), ("-0.1", "-0.1"), ("0.0", "0.0"), ("0", "0"), ("23,770.5", "23770.5"),
    ("1,234,567", "1234567"), (" 2.5 ", "2.5"),
    ("(NA)", None), ("---", None), ("(D)", None),
])
def test_parse_value(raw, expect):
    assert B.parse_value(raw) == expect


@pytest.mark.parametrize("raw", ["", "abc", "1.2.3", "1,23", "NaN", "Infinity", "1e5", "--1",
                                 3.4, None, "12,34.5"])
def test_parse_value_rejects(raw):
    with pytest.raises(B.BeaParseError):
        B.parse_value(raw)


def _body(table, mutate):
    b = json.loads(NIPA[table])
    mutate(b["BEAAPI"]["Results"]["Data"])
    return b


@pytest.mark.parametrize("mutate", [
    lambda d: d.__setitem__(slice(None), [r for r in d if r["SeriesCode"] != "DPCCRGM"]),
    lambda d: [r.__setitem__("LineNumber", "26") for r in d if r["SeriesCode"] == "DPCCRGM"],
    lambda d: d.append({**d[0], "DataValue": "9.9"}),               # cùng kỳ hai giá trị
    lambda d: d[0].__setitem__("TimePeriod", "2026M13"),
    lambda d: d[0].__setitem__("TimePeriod", "2026Q3"),
    lambda d: d[0].__setitem__("DataValue", "n/a?"),
    lambda d: d.append("không phải dict"),
])
def test_parse_table_rejects_unexpected(mutate):
    with pytest.raises(B.BeaParseError):
        B.parse_table("T20807", _body("T20807", mutate))


def test_parse_table_rejects_missing_data():
    with pytest.raises(B.BeaParseError):
        B.parse_table("T10101", {"BEAAPI": {"Results": {}}})
    with pytest.raises(B.BeaParseError):
        B.parse_table("T10101", [])


@pytest.mark.parametrize("body,code", [
    ({"BEAAPI": {"Results": {"Error": {"APIErrorCode": "1",
                                       "APIErrorDescription": "Invalid API UserId."}}}},
     "AUTH_FAILED"),
    ({"BEAAPI": {"Results": {"Error": {"APIErrorCode": "7"}}}}, "RATE_LIMITED"),
    ({"BEAAPI": {"Error": {"APIErrorCode": "40"}}}, "BEA_API_ERROR_40"),
    ({"BEAAPI": {"Results": {"Error": {"APIErrorCode": "x; drop"}}}}, "BEA_API_ERROR"),
    ({"BEAAPI": {"Results": {"Data": []}}}, None),
])
def test_api_error_codes(body, code):
    assert B.api_error_code(body) == code


# ------------------------------------------------------------------ số actual: chạy

def run_vals(store, log, now=NOW, key=KEY, **kw):
    return B.run_values_once(store=store, log=log, get=getter(**kw), key_lookup=key, now=now)


def test_initial_load_then_unchanged(env):
    store, log = env
    c = run_vals(store, log)
    # 7 quý GDP (2025Q1..2026Q3) + 4 series tháng × 21 tháng (2025-01..2026-09).
    assert c.outcome is CheckOutcome.OK and c.inserted == 7 + 4 * 21
    recs = store.as_of(NOW, source=B.VALUES_SOURCE)
    assert all(r.kind == "macro" and "INITIAL_LOAD" in r.payload["flags"] for r in recs)
    gdp = store.as_of(NOW, source=B.VALUES_SOURCE, logical_key="A191RL:2026Q3")[0]
    assert gdp.payload["value"] == "3.4" and gdp.payload["value_status"] == "AVAILABLE"
    assert gdp.payload["release_ref"] is None and gdp.available_at is None
    c2 = run_vals(store, log, now=NOW + timedelta(hours=1))
    assert c2.outcome is CheckOutcome.OK and c2.inserted == 0


def _gdp_second_estimate(value):
    def mutate(d):
        for r in d:
            if r["SeriesCode"] == "A191RL" and r["TimePeriod"] == "2026Q3":
                r["DataValue"] = value
    return json.dumps(_body("T10101", mutate))


def test_revision_on_release_measures_latency(env):
    # ING-17 + ING-19 + 1C-C08: ngày 25/11 BEA công bố ước tính lần 2 → revision 1, gắn lần
    # công bố + đo độ trễ; xem lại quá khứ vẫn thấy số cũ.
    store, log = env
    run_sched(store, log)
    run_vals(store, log)
    at = utc(2026, 11, 25, 13, 31, 20)
    c = run_vals(store, log, now=at, nipa={"T10101": _gdp_second_estimate("4.1")})
    assert c.inserted == 1
    new = store.as_of(at, source=B.VALUES_SOURCE, logical_key="A191RL:2026Q3")[0]
    assert (new.revision, new.payload["value"]) == (1, "4.1")
    assert new.payload["release_ref"] == "GDP:2026Q3:SECOND"
    assert new.payload["latency_seconds"] == 80
    assert new.available_at == utc(2026, 11, 25, 13, 30) and new.payload["flags"] == []
    before = store.as_of(at - timedelta(seconds=1), source=B.VALUES_SOURCE,
                         logical_key="A191RL:2026Q3")[0]
    assert (before.revision, before.payload["value"]) == (0, "3.4")
    assert [r.revision for r in store.history(B.VALUES_SOURCE, "A191RL:2026Q3", at)] == [0, 1]


def test_change_outside_schedule_flagged(env):
    store, log = env
    run_sched(store, log)
    run_vals(store, log)
    at = utc(2026, 11, 18, 14, 0)  # không có lần công bố GDP nào trong 3 ngày qua
    run_vals(store, log, now=at, nipa={"T10101": _gdp_second_estimate("3.5")})
    r = store.as_of(at, source=B.VALUES_SOURCE, logical_key="A191RL:2026Q3")[0]
    assert r.payload["flags"] == ["UNSCHEDULED_CHANGE"] and r.payload["release_ref"] is None


def test_not_available_is_not_zero(env):
    # 1C-C01: "(NA)" → không có số (None), khác hẳn số 0.
    store, log = env

    def mutate(d):
        for r in d:
            if r["SeriesCode"] == "DPCERGM" and r["TimePeriod"] == "2026M09":
                r["DataValue"] = "(NA)"
            if r["SeriesCode"] == "DPCCRGM" and r["TimePeriod"] == "2026M09":
                r["DataValue"] = "0.0"
    run_vals(store, log, nipa={"T20807": json.dumps(_body("T20807", mutate))})
    na = store.as_of(NOW, source=B.VALUES_SOURCE, logical_key="DPCERGM:2026-09")[0]
    zero = store.as_of(NOW, source=B.VALUES_SOURCE, logical_key="DPCCRGM:2026-09")[0]
    assert na.payload["value"] is None and na.payload["value_status"] == "NOT_AVAILABLE"
    assert "VALUE_NOT_AVAILABLE" in na.payload["flags"]
    assert zero.payload["value"] == "0.0" and zero.payload["value_status"] == "AVAILABLE"
    # Lần sau BEA có số → revision mới.
    run_vals(store, log, now=NOW + timedelta(days=1))
    r = store.as_of(NOW + timedelta(days=1), source=B.VALUES_SOURCE,
                    logical_key="DPCERGM:2026-09")[0]
    assert (r.revision, r.payload["value"]) == (1, "0.5")


@pytest.mark.parametrize("lookup,code", [
    (KeyLookup("bea", None, "KEY_MISSING"), "KEY_MISSING"),
    (KeyLookup("bea", None, "KEY_INVALID"), "KEY_INVALID"),
])
def test_missing_or_bad_key_never_calls_bea(env, lookup, code):
    store, log = env
    calls = []
    c = B.run_values_once(store=store, log=log, get=getter(calls=calls), key_lookup=lookup,
                          now=NOW)
    assert (c.outcome, c.error_code) == (CheckOutcome.ERROR, code) and calls == []
    h = evaluate(B.VALUES_SOURCE, B.values_spec(), log.summary(B.VALUES_SOURCE, NOW), NOW, None)
    assert (h.status, h.reason) == (SourceStatus.MISSING, code)


def test_rejected_key_makes_source_missing(env):
    store, log = env
    run_vals(store, log)
    bad = json.dumps({"BEAAPI": {"Request": {"RequestParam": [
        {"ParameterName": "USERID", "ParameterValue": KEY_VALUE}]},
        "Results": {"Error": {"APIErrorCode": "1",
                              "APIErrorDescription": "Invalid API UserId."}}}})
    at = NOW + timedelta(hours=1)
    c = run_vals(store, log, now=at, nipa={"T10101": bad})
    assert (c.outcome, c.error_code) == (CheckOutcome.ERROR, "AUTH_FAILED")
    h = evaluate(B.VALUES_SOURCE, B.values_spec(), log.summary(B.VALUES_SOURCE, at), at,
                 store.latest_event_time(B.VALUES_SOURCE, at))
    assert (h.status, h.reason) == (SourceStatus.MISSING, "AUTH_FAILED")


@pytest.mark.parametrize("nipa,outcome,code", [
    ({"T20804": B.FetchError("RATE_LIMITED")}, CheckOutcome.ERROR, "RATE_LIMITED"),
    ({"T20807": "<html>"}, CheckOutcome.INVALID, "PARSE_ERROR"),
    ({"T10101": json.dumps({"BEAAPI": {"Results": {}}})}, CheckOutcome.INVALID, "PARSE_ERROR"),
])
def test_value_errors_write_nothing(env, nipa, outcome, code):
    store, log = env
    c = run_vals(store, log, nipa=nipa)
    assert (c.outcome, c.error_code) == (outcome, code)
    assert store.as_of(NOW, source=B.VALUES_SOURCE) == []


def test_key_never_stored(tmp_path):
    # Phản hồi BEA chép lại khóa trong Request → không được nằm trong payload / raw / raw_ref.
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'k.db'}")
    repo.create_all()
    store, log = SqlExternalRecordStore(repo.engine), SqlSourceCheckLog(repo.engine)
    nipa = {t: v.replace("Your-36Character-Key", KEY_VALUE) for t, v in NIPA.items()}
    assert all(KEY_VALUE in v for v in nipa.values())
    calls = []
    c = B.run_values_once(store=store, log=log, get=getter(nipa=nipa, calls=calls),
                          key_lookup=KEY, now=NOW)
    assert c.outcome is CheckOutcome.OK and len(calls) == 3
    with repo.engine.connect() as conn:
        rows = conn.execute(select(external_records)).mappings().all()
    assert rows and not any(KEY_VALUE in json.dumps(dict(r), default=str) for r in rows)


def test_values_go_stale_when_bea_late(env):
    store, log = env
    run_vals(store, log)
    # Số mới nhất: tháng 9/2026 (hết kỳ 01/10 04:00 UTC) → quá 62 ngày (02/12) mà chưa có số mới.
    at = utc(2026, 12, 2, 5, 0)
    run_vals(store, log, now=at)
    h = evaluate(B.VALUES_SOURCE, B.values_spec(), log.summary(B.VALUES_SOURCE, at), at,
                 store.latest_event_time(B.VALUES_SOURCE, at))
    assert (h.status, h.reason) == (SourceStatus.STALE, "DATA_TTL_EXPIRED")


def test_values_due_policy(env):
    store, log = env
    assert B.values_due(NOW, store, None) == "RECONCILE"
    run_sched(store, log)
    assert B.values_due(NOW, store, NOW - timedelta(days=1)) is None
    assert B.values_due(NOW, store, NOW - timedelta(days=7, minutes=1)) == "RECONCILE"
    rel = utc(2026, 11, 25, 13, 30)
    ok = rel - timedelta(days=1)
    assert B.values_due(rel - timedelta(minutes=1), store, ok) is None
    assert B.values_due(rel, store, ok) == "RELEASE_WINDOW"
    assert B.values_due(rel + timedelta(minutes=89), store, ok) == "RELEASE_WINDOW"
    assert B.values_due(rel + timedelta(minutes=91), store, ok) is None


# ------------------------------------------------------------------ HTTP

def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_http_getter_ok_and_params_not_in_errors():
    seen = []

    def h(req):
        seen.append(req.url)
        return httpx.Response(200, text="ok")
    get = B.http_getter(_client(h))
    assert get(B.API_URL, {"UserID": KEY_VALUE, "TableName": "T10101"}) == "ok"
    assert seen[0].params["UserID"] == KEY_VALUE and seen[0].host == "apps.bea.gov"


@pytest.mark.parametrize("handler,code", [
    (lambda r: httpx.Response(429, headers={"retry-after": "59"}), "RATE_LIMITED"),
    (lambda r: httpx.Response(503), "HTTP_503"),
    (lambda r: httpx.Response(401), "AUTH_FAILED"),
    (lambda r: httpx.Response(200, content=b"x" * (B.MAX_BYTES + 1)), "RESPONSE_TOO_LARGE"),
    (lambda r: httpx.Response(302, headers={"location": "https://evil.example/x"}),
     "UNEXPECTED_REDIRECT"),
])
def test_http_getter_errors(handler, code):
    def h(req):
        if req.url.host == "evil.example":
            return httpx.Response(200, text="x")
        return handler(req)
    with pytest.raises(B.FetchError) as e:
        B.http_getter(_client(h))(B.API_URL, {"UserID": KEY_VALUE})
    assert e.value.code == code and KEY_VALUE not in str(e.value)


def test_http_getter_timeout_and_bad_url():
    def h(req):
        raise httpx.ReadTimeout("hết giờ " + str(req.url))
    get = B.http_getter(_client(h))
    with pytest.raises(B.FetchError) as e:
        get(B.API_URL, {"UserID": KEY_VALUE})
    assert e.value.code == "TIMEOUT" and KEY_VALUE not in repr(e.value)
    with pytest.raises(B.FetchError, match="BAD_URL"):
        get("https://example.com/api", None)
    with pytest.raises(B.FetchError, match="BAD_URL"):
        get("http://apps.bea.gov/api/data", None)


# ------------------------------------------------------------------ CLI

def _mock_factory():
    def h(req):
        u = str(req.url).split("?")[0]
        if u == B.ICS_URL:
            return httpx.Response(200, text=ICS)
        if u == B.DATES_URL:
            return httpx.Response(200, text=DATES)
        if u == B.API_URL:
            return httpx.Response(200, text=NIPA[req.url.params["TableName"]])
        return httpx.Response(404)
    return lambda: _client(h)


def test_cli_dry_run_with_and_without_key(capsys):
    rc = cli._bea(True, env={"GT_BEA_API_KEY": KEY_VALUE}, client_factory=_mock_factory())
    out = capsys.readouterr().out
    assert rc == 0
    assert "GDP:2026Q3:SECOND" in out and "A191RL 2026Q3: 3.4" in out
    assert "not endorsed or certified by BEA" in out and KEY_VALUE not in out
    rc = cli._bea(True, env={}, client_factory=_mock_factory())
    out = capsys.readouterr().out
    assert rc == 1 and "KEY_MISSING" in out and "GDP:2026Q3:SECOND" in out
