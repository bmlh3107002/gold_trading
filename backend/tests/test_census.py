"""Bước 8d — Census: lịch (ING-09) + số actual doanh số bán lẻ (ING-17), revision (ING-19).

Dữ liệu: hai trang lịch + lịch bán lẻ tải nguyên văn 2026-11-13; phản hồi API dựng theo dạng chuẩn
của Census với số thật (xem ``tests/fixtures/census/README.md``).
Case: 1C-C01, 1C-C02, 1C-C03, 1C-C04, 1C-C06, 1C-C08, trang hỏng, lỗi mạng, khóa sai/thiếu.
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
from gold_trading.ingestion.sources import census as C
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.schema import external_records
from gold_trading.storage.source_checks import SqlSourceCheckLog

FIX = Path(__file__).parent / "fixtures" / "census"
LV2027 = (FIX / "calendar-listview-2027.html").read_text(encoding="utf-8")
LV2026 = (FIX / "calendar-listview-2026.html").read_text(encoding="utf-8")
RETAIL = (FIX / "retail-release-schedule.html").read_text(encoding="utf-8")
API = {y: (FIX / f"marts-{y}.json").read_text(encoding="utf-8") for y in ("2025", "2026")}
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
KEY_VALUE = "0123456789abcdef0123456789abcdef01234567"
KEY = KeyLookup("census", ApiKey("census", KEY_VALUE), None)
U_LV = C.BASE + C.LISTVIEW_PATH
U_LV26 = C.BASE + C.LISTVIEW_YEAR_PATH.format(year=2026)
U_RET = C.BASE + C.RETAIL_SCHEDULE_PATH


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def getter(over=None, api=None, calls=None):
    pages = {U_LV: LV2027, U_LV26: LV2026, U_RET: RETAIL, **(over or {})}
    api = {**API, **(api or {})}

    def get(url, params=None):
        if calls is not None:
            calls.append((url, dict(params or {})))
        if url == C.API_URL:
            assert params["key"] == KEY_VALUE
            v = api.get(params["time"], "")
        else:
            v = pages[url]
        if isinstance(v, Exception):
            raise v
        return v
    return get


@pytest.fixture(params=["memory", "sqlite"])
def env(request, tmp_path):
    if request.param == "memory":
        return PointInTimeStore(), SourceCheckLog()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'c.db'}")
    repo.create_all()
    return SqlExternalRecordStore(repo.engine), SqlSourceCheckLog(repo.engine)


def schedule(now=NOW, **over):
    listed, retail = C.collect_schedule(getter(over), now)
    return {e.logical_key: e for e in C.build_schedule(listed, retail, now)}


def lv_replace(old, new, page=LV2026, code="A202611170830"):
    """Sửa đúng dòng doanh số bán lẻ có mã ẩn ``code`` (trang có nhiều chỉ số cùng ngày)."""
    rows = page.split('<tr height="20">')
    hits = [i for i, r in enumerate(rows) if code in r and "Retail and Food Services" in r]
    assert len(hits) == 1 and old in rows[hits[0]], old
    rows[hits[0]] = rows[hits[0]].replace(old, new)
    return '<tr height="20">'.join(rows)


# ------------------------------------------------------------------ lịch

def test_real_schedule():
    ev = schedule()
    nxt = ev["RETAIL:2026-10"]
    assert nxt.event_time == utc(2026, 11, 17, 13, 30)  # 8:30 ET mùa đông
    assert nxt.payload["time_confirmed"] and nxt.payload["release_local"] == "08:30"
    assert ev["RETAIL:2027-05"].event_time == utc(2027, 6, 16, 12, 30)  # 8:30 ET mùa hè (1C-C04)
    assert len(ev) == 14 and all(e.payload["flags"] == [] for e in ev.values())


def test_listview_year_and_rows():
    y, rows = C.parse_listview(LV2026)
    assert y == 2026 and len(rows) == 13
    assert rows[0].period == date(2025, 11, 1)
    y, rows = C.parse_listview(LV2027)
    assert y == 2027 and len(rows) == 12


def test_retail_schedule_skips_tba():
    r = C.parse_retail_schedule(RETAIL)
    assert r[date(2026, 10, 1)] == date(2026, 11, 17)
    assert date(2027, 12, 1) not in r  # "To be announced"
    assert len(r) == 15


def test_january_fetches_current_year_page_only_once():
    # Đầu năm 2027: trang mặc định đã là 2027 → không tải trang năm riêng.
    calls = []
    g = getter(calls=calls)
    C.collect_schedule(g, utc(2027, 1, 5))
    assert [u for u, _ in calls] == [U_LV, U_RET]


@pytest.mark.parametrize("broken", [
    "<html>bảo trì</html>",
    LV2026.replace("US Census Bureau: 2026 Economic Indicator", "Lịch", 1),
    lv_replace("8:30 AM", "10:00 AM"),                         # giờ chữ lệch mã ẩn
    lv_replace("November 17, 2026", "November 31, 2026"),
    lv_replace("A202610<", "A202611<"),                       # kỳ chữ lệch mã ẩn
    LV2026.replace("Advance Monthly Sales for Retail and Food Services", "Retail sales"),
])
def test_broken_listview_rejected(broken):
    with pytest.raises(C.CensusParseError):
        C.parse_listview(broken)


@pytest.mark.parametrize("broken", [
    "<html/>",
    RETAIL.replace("Release Date at 8:30 am</strong></td>",
                   "Release Date at 10:00 am</strong></td>", 1),
    RETAIL.replace("November 17, 2026", "17/11/2026", 1),
    RETAIL.replace("<td style=\"text-align:center\">October 2026</td>",
                   "<td style=\"text-align:center\">Octobre 2026</td>", 1),
])
def test_broken_retail_schedule_rejected(broken):
    assert broken != RETAIL
    with pytest.raises(C.CensusParseError):
        C.parse_retail_schedule(broken)


def test_sources_disagree_flags_all_day():
    # 1C-C06: lịch bán lẻ dời sang 18/11 mà lịch chung vẫn 17/11 → cả hai ngày đều chặn cả ngày.
    ret = RETAIL.replace("November 17, 2026", "November 18, 2026", 1)
    ev = schedule(**{U_RET: ret})
    e = ev["RETAIL:2026-10"]
    assert e.payload["flags"] == ["CALENDAR_SOURCES_DISAGREE"]
    assert e.payload["all_day"] and e.event_time == utc(2026, 11, 17, 5, 0)
    assert all(not x.payload["flags"] for k, x in ev.items() if k != "RETAIL:2026-10")


def test_period_only_in_retail_schedule_added():
    ret = RETAIL.replace("To be announced at a later date", "January 14, 2028", 1)
    ev = schedule(**{U_RET: ret})
    e = ev["RETAIL:2027-12"]
    assert e.payload["all_day"] and e.payload["flags"] == ["CALENDAR_SOURCES_DISAGREE"]


def test_no_future_release_rejected():
    listed, retail = C.collect_schedule(getter(), NOW)
    with pytest.raises(C.CensusParseError):
        C.build_schedule(listed, retail, utc(2028, 2, 1))


def run_sched(store, log, now=NOW, **over):
    return C.run_schedule_once(store=store, log=log, get=getter(over), now=now)


def test_run_schedule_reload_and_reschedule(env):
    store, log = env
    assert run_sched(store, log).inserted == 14
    assert run_sched(store, log, now=NOW + timedelta(hours=2)).inserted == 0
    # 1C-C03: Census dời công bố tháng 11 sang 17/12 (cả hai trang) → revision, quá khứ giữ cũ.
    later = NOW + timedelta(days=1)
    lv = LV2026.replace("December 16, 2026", "December 17, 2026").replace(
        "A202612160830", "A202612170830")
    ret = RETAIL.replace("December 16, 2026", "December 17, 2026", 1)
    assert run_sched(store, log, now=later, **{U_LV26: lv, U_RET: ret}).inserted == 1
    new = store.as_of(later, source=C.SCHEDULE_SOURCE, logical_key="RETAIL:2026-11")[0]
    old = store.as_of(NOW, source=C.SCHEDULE_SOURCE, logical_key="RETAIL:2026-11")[0]
    assert (new.revision, new.event_time) == (1, utc(2026, 12, 17, 13, 30))
    assert (old.revision, old.event_time) == (0, utc(2026, 12, 16, 13, 30))


def test_release_removed_from_both_pages(env):
    # 1C-C02: Census bỏ một lần công bố (vd. chính phủ đóng cửa) → REMOVED.
    store, log = env
    run_sched(store, log)
    later = NOW + timedelta(days=1)
    rows = LV2026.split("<tr height=\"20\">")
    rows = [r for r in rows if not ("A202612160830" in r and "Retail and Food" in r)]
    lv = "<tr height=\"20\">".join(rows)
    ret = RETAIL.replace("December 16, 2026", "To be announced at a later date", 1)
    c = run_sched(store, log, now=later, **{U_LV26: lv, U_RET: ret})
    assert c.outcome is CheckOutcome.OK
    r = store.as_of(later, source=C.SCHEDULE_SOURCE, logical_key="RETAIL:2026-11")[0]
    assert r.payload["status"] == "REMOVED"


@pytest.mark.parametrize("over,outcome,code", [
    ({U_LV: C.FetchError("HTTP_503")}, CheckOutcome.ERROR, "HTTP_503"),
    ({U_RET: C.FetchError("TIMEOUT")}, CheckOutcome.ERROR, "TIMEOUT"),
    ({U_LV: "<html/>"}, CheckOutcome.INVALID, "PARSE_ERROR"),
    ({U_LV26: LV2027}, CheckOutcome.INVALID, "PARSE_ERROR"),  # trang năm 2026 trả nhầm 2027
])
def test_schedule_errors_write_nothing(env, over, outcome, code):
    store, log = env
    c = run_sched(store, log, **over)
    assert (c.outcome, c.error_code) == (outcome, code)
    assert store.as_of(NOW, source=C.SCHEDULE_SOURCE) == []


def test_terms_required():
    t = {"census": SourceTerms("census", TermsStatus.NEEDS_REVIEW, date(2026, 11, 13), "#c")}
    with pytest.raises(ValueError):
        SourceRegistry([C.schedule_spec()], terms=t)
    SourceRegistry([C.schedule_spec(), C.values_spec()])


# ------------------------------------------------------------------ số actual

def all_obs():
    obs = C.parse_api(API["2025"]) + C.parse_api(API["2026"])
    C.check_consistency(obs)
    return {o.key: o for o in obs}


def test_parse_real_values_and_filters():
    o = all_obs()
    # Số tham chiếu: bảng Census (marts_current.xlsx) công bố 15/10/2026.
    assert o["44X72:SM:2026-09"].value == "745021"
    assert o["44X72:MPCSM:2026-09"].value == "0.8"
    assert o["44Y72:SM:2026-09"].value == "605188"
    assert o["44W72:SM:2026-09"].value == "537167"
    assert o["44X72:MPCSM:2025-10"].value == "0.0"
    # Dòng sai số, dòng chưa điều chỉnh mùa vụ (999999), ngành 441 bị bỏ.
    assert o["44X72:SM:2025-01"].value == "687058"
    assert len(o) == 6 * 21 and not any(k.startswith("441:") for k in o)
    assert o["44X72:SM:2026-09"].period_end == utc(2026, 10, 1, 4, 0)


def test_hand_check_percent():
    # Tay: 745 021 / 739 322 − 1 = 0,771 % → Census ghi 0.8.
    o = all_obs()
    calc = int(o["44X72:SM:2026-09"].value) / int(o["44X72:SM:2026-08"].value) - 1
    assert round(calc * 100, 1) == float(o["44X72:MPCSM:2026-09"].value)


def _api(year, fn):
    rows = json.loads(API[year])
    fn(rows)
    return json.dumps(rows)


def _set(cat, dt, period, value):
    def fn(rows):
        for r in rows[1:]:
            if (r[4], r[1], r[6], r[3], r[5]) == (cat, dt, period, "no", "yes"):
                r[0] = value
    return fn


def test_inconsistent_percent_rejected():
    # % công bố lệch % tự tính > 0,1 → nghi mã sai / dữ liệu hỏng.
    bad = _api("2026", _set("44X72", "MPCSM", "2026-09", "1.5"))
    with pytest.raises(C.CensusParseError):
        C.check_consistency(C.parse_api(API["2025"]) + C.parse_api(bad))


@pytest.mark.parametrize("fn", [
    lambda rows: rows.__setitem__(0, [c for c in rows[0] if c != "error_data"]),
    lambda rows: rows.append(["1", "SM"]),
    lambda rows: rows[1].__setitem__(0, "12,34"),
    lambda rows: rows[1].__setitem__(6, "2026-13"),
    lambda rows: rows[1].__setitem__(5, "maybe"),
    lambda rows: rows[1].__setitem__(0, 745021),
    lambda rows: rows.append([*rows[1][:0], "1", *rows[1][1:]]),  # cùng kỳ hai giá trị
])
def test_bad_api_rows_rejected(fn):
    with pytest.raises(C.CensusParseError):
        C.parse_api(_api("2026", fn))


@pytest.mark.parametrize("text", ["<html>", "{}", "[]", "[[]]"])
def test_bad_api_body_rejected(text):
    with pytest.raises(C.CensusParseError):
        C.parse_api(text)


def test_empty_year_204_and_missing_series():
    assert C.parse_api("") == []
    only = _api("2026", lambda rows: rows.__setitem__(slice(1, None),
                                                       [r for r in rows[1:] if r[4] != "44W72"]))
    with pytest.raises(C.CensusParseError, match="thiếu series"):
        C.check_consistency(C.parse_api(only))


def run_vals(store, log, now=NOW, key=KEY, **api):
    return C.run_values_once(store=store, log=log, get=getter(api=api), key_lookup=key, now=now)


def test_initial_then_unchanged_then_revision(env):
    store, log = env
    run_sched(store, log)
    c = run_vals(store, log)
    assert c.outcome is CheckOutcome.OK and c.inserted == 126
    r = store.as_of(NOW, source=C.VALUES_SOURCE, logical_key="44X72:SM:2026-09")[0]
    assert r.payload["flags"] == ["INITIAL_LOAD"] and r.payload["unit"] == "USD_MILLIONS"
    assert run_vals(store, log, now=NOW + timedelta(hours=1)).inserted == 0
    # 17/11 8:30 ET: Census công bố tháng 10 + sửa tháng 9 (số thật giả định cho test).
    at = utc(2026, 11, 17, 13, 32)

    def release(rows):
        _set("44X72", "SM", "2026-09", "746500")(rows)
        _set("44X72", "MPCSM", "2026-09", "1.0")(rows)
        rows.append(["752000", "SM", "0", "no", "44X72", "yes", "2026-10", "1"])
        rows.append(["0.7", "MPCSM", "0", "no", "44X72", "yes", "2026-10", "1"])
    c = run_vals(store, log, now=at, **{"2026": _api("2026", release)})
    assert c.outcome is CheckOutcome.OK and c.inserted == 4
    oct_ = store.as_of(at, source=C.VALUES_SOURCE, logical_key="44X72:SM:2026-10")[0]
    assert oct_.payload["release_ref"] == "RETAIL:2026-10"
    assert oct_.payload["latency_seconds"] == 120 and oct_.payload["flags"] == []
    sep = store.as_of(at, source=C.VALUES_SOURCE, logical_key="44X72:SM:2026-09")[0]
    assert (sep.revision, sep.payload["value"]) == (1, "746500")
    old = store.as_of(at - timedelta(seconds=1), source=C.VALUES_SOURCE,
                      logical_key="44X72:SM:2026-09")[0]
    assert (old.revision, old.payload["value"]) == (0, "745021")


def test_not_available_is_not_zero(env):
    store, log = env
    run_vals(store, log, **{"2026": _api("2026", _set("44W72", "SM", "2026-09", "(S)"))})
    r = store.as_of(NOW, source=C.VALUES_SOURCE, logical_key="44W72:SM:2026-09")[0]
    assert r.payload["value"] is None and r.payload["value_status"] == "NOT_AVAILABLE"
    z = store.as_of(NOW, source=C.VALUES_SOURCE, logical_key="44X72:MPCSM:2025-10")[0]
    assert z.payload["value"] == "0.0" and z.payload["value_status"] == "AVAILABLE"


@pytest.mark.parametrize("lookup,code", [
    (KeyLookup("census", None, "KEY_MISSING"), "KEY_MISSING"),
    (KeyLookup("census", None, "KEY_INVALID"), "KEY_INVALID"),
])
def test_missing_key_never_calls(env, lookup, code):
    store, log = env
    calls = []
    c = C.run_values_once(store=store, log=log, get=getter(calls=calls), key_lookup=lookup,
                          now=NOW)
    assert (c.outcome, c.error_code) == (CheckOutcome.ERROR, code) and calls == []


@pytest.mark.parametrize("api,outcome,code", [
    ({"2026": C.FetchError("AUTH_FAILED")}, CheckOutcome.ERROR, "AUTH_FAILED"),
    ({"2025": "<html>"}, CheckOutcome.INVALID, "PARSE_ERROR"),
])
def test_value_errors_write_nothing(env, api, outcome, code):
    store, log = env
    c = run_vals(store, log, **api)
    assert (c.outcome, c.error_code) == (outcome, code)
    assert store.as_of(NOW, source=C.VALUES_SOURCE) == []
    if code == "AUTH_FAILED":
        h = evaluate(C.VALUES_SOURCE, C.values_spec(), log.summary(C.VALUES_SOURCE, NOW), NOW,
                     None)
        assert (h.status, h.reason) == (SourceStatus.MISSING, "AUTH_FAILED")


def test_new_year_with_no_current_data(env):
    # Tháng 1/2027: năm 2027 chưa có số → 204 (rỗng), vẫn OK với số năm 2026.
    store, log = env
    c = C.run_values_once(store=store, log=log, key_lookup=KEY, now=utc(2027, 1, 5),
                          get=getter(api={"2027": "", "2026": API["2026"]}))
    assert c.outcome is CheckOutcome.OK and c.inserted == 6 * 9


def test_key_never_stored(tmp_path):
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'k.db'}")
    repo.create_all()
    store, log = SqlExternalRecordStore(repo.engine), SqlSourceCheckLog(repo.engine)
    c = C.run_values_once(store=store, log=log, get=getter(), key_lookup=KEY, now=NOW)
    assert c.outcome is CheckOutcome.OK
    with repo.engine.connect() as conn:
        rows = conn.execute(select(external_records)).mappings().all()
    assert rows and not any(KEY_VALUE in json.dumps(dict(r), default=str) for r in rows)


def test_stale_when_census_late(env):
    store, log = env
    run_vals(store, log)
    at = utc(2026, 11, 25, 12, 0)  # số mới nhất tháng 9 (hết kỳ 01/10) → 55 ngày + vài giờ
    run_vals(store, log, now=at)
    h = evaluate(C.VALUES_SOURCE, C.values_spec(), log.summary(C.VALUES_SOURCE, at), at,
                 store.latest_event_time(C.VALUES_SOURCE, at))
    assert (h.status, h.reason) == (SourceStatus.STALE, "DATA_TTL_EXPIRED")


def test_values_due(env):
    store, log = env
    assert C.values_due(NOW, store, None) == "RECONCILE"
    run_sched(store, log)
    rel = utc(2026, 11, 17, 13, 30)
    ok = rel - timedelta(days=1)
    assert C.values_due(rel - timedelta(minutes=1), store, ok) is None
    assert C.values_due(rel + timedelta(minutes=5), store, ok) == "RELEASE_WINDOW"
    assert C.values_due(rel + timedelta(minutes=91), store, ok) is None


# ------------------------------------------------------------------ HTTP

def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("resp,code", [
    (httpx.Response(302, headers={"location": "https://api.census.gov/data/invalid_key.html"}),
     "AUTH_FAILED"),
    (httpx.Response(302, headers={"location": "https://api.census.gov/data/missing_key.html"}),
     "KEY_MISSING"),
    (httpx.Response(302, headers={"location": "https://evil.example/"}), "UNEXPECTED_REDIRECT"),
    (httpx.Response(429), "RATE_LIMITED"),
    (httpx.Response(500), "HTTP_500"),
    (httpx.Response(200, content=b"x" * (C.MAX_BYTES + 1)), "RESPONSE_TOO_LARGE"),
])
def test_http_errors(resp, code):
    get = C.http_getter(_client(lambda req: resp))
    with pytest.raises(C.FetchError) as e:
        get(C.API_URL, {"key": KEY_VALUE})
    assert e.value.code == code and KEY_VALUE not in repr(e.value)


def test_http_204_and_bad_url():
    get = C.http_getter(_client(lambda req: httpx.Response(204)))
    assert get(C.API_URL, {"key": KEY_VALUE}) == ""
    with pytest.raises(C.FetchError, match="BAD_URL"):
        get("https://census.gov.evil.example/x")


def test_cli_dry_run(capsys):
    def h(req):
        u = str(req.url).split("?")[0]
        if u == C.API_URL:
            return httpx.Response(200, text=API.get(req.url.params["time"], "")) \
                if req.url.params["time"] in API else httpx.Response(204)
        pages = {U_LV: LV2027, U_LV26: LV2026, U_RET: RETAIL}
        return httpx.Response(200, text=pages[u]) if u in pages else httpx.Response(404)
    fac = lambda: _client(h)  # noqa: E731
    rc = cli._census(True, env={"GT_CENSUS_API_KEY": KEY_VALUE}, client_factory=fac)
    out = capsys.readouterr().out
    assert rc == 0 and "RETAIL:2026-10" in out and "44X72:SM 2026-09: 745021" in out
    assert "not endorsed or certified by the Census Bureau" in out and KEY_VALUE not in out
    rc = cli._census(True, env={}, client_factory=fac)
    assert rc == 1 and "KEY_MISSING" in capsys.readouterr().out
