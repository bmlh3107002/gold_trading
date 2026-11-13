"""Bước 8e — BLS: lịch chép tay + số CPI / NFP / PPI qua API v2 (ING-09, ING-17, ING-19).

Dữ liệu thật: ``tests/fixtures/bls/timeseries-2026-11-13.json`` (máy người dùng gọi API có khóa,
2026-11-13 sau 13:30 UTC — PPI tháng 10 đã công bố). Lịch: 3 bảng người dùng chép từ trình duyệt.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from gold_trading.ingestion import cli
from gold_trading.ingestion import economic_calendar as C
from gold_trading.ingestion.api_keys import KeyLookup, load_api_key
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.ingestion.source_status import CheckOutcome, SourceCheckLog
from gold_trading.ingestion.sources import bls as L
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.source_checks import SqlSourceCheckLog

RAW = (Path(__file__).parent / "fixtures" / "bls" / "timeseries-2026-11-13.json").read_text(
    encoding="utf-8")
KEY = "0123456789abcdef0123456789abcdef"
T = datetime(2026, 11, 13, 14, 0, tzinfo=UTC)          # 30 phút sau PPI 08:30 ET (13:30 UTC)


def utc(*a):
    return datetime(*a, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def env(request, tmp_path):
    if request.param == "memory":
        return PointInTimeStore(), SourceCheckLog()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'b.db'}")
    repo.create_all()
    return SqlExternalRecordStore(repo.engine), SqlSourceCheckLog(repo.engine)


def key():
    return load_api_key("bls", {"GT_BLS_API_KEY": KEY})


def body(mut=None):
    j = json.loads(RAW)
    if mut:
        mut(j)
    return json.dumps(j)


def series(j, code):
    return next(s for s in j["Results"]["series"] if s["seriesID"] == code)


def run(env_, now=T, text=RAW, k=None):
    store, log = env_
    L.run_schedule_once(store=store, log=log, now=now)
    calls = []

    def post(b):
        calls.append(b)
        return text
    chk = L.run_values_once(store=store, log=log, post=post, key_lookup=k or key(), now=now)
    return chk, calls


# ------------------------------------------------------------------ lịch

def test_schedule_table_hand_checked():
    t = L.schedule_table()
    assert len(t) == 42 and {k for k, _, _ in t} == {"CPI", "EMPSIT", "PPI"}
    ev = {e.logical_key: e.event_time for e in L.build_schedule(utc(2026, 11, 1))}
    # giờ chuẩn (EST, UTC−5): 08:30 ET = 13:30 UTC
    assert ev["CPI:2026-11"] == utc(2026, 12, 10, 13, 30)
    assert ev["EMPSIT:2026-11"] == utc(2026, 12, 4, 13, 30)
    assert ev["PPI:2026-10"] == utc(2026, 11, 13, 13, 30)
    # CPI 10/3/2027: trước ngày đổi giờ 14/3/2027 → vẫn EST
    assert ev["CPI:2027-02"] == utc(2027, 3, 10, 13, 30)
    # giờ mùa hè (EDT, UTC−4): 08:30 ET = 12:30 UTC
    assert ev["CPI:2027-03"] == utc(2027, 4, 13, 12, 30)
    # NFP 5/11/2027: trước ngày hết giờ mùa hè 7/11/2027 → EDT
    assert ev["EMPSIT:2027-10"] == utc(2027, 11, 5, 12, 30)


def test_schedule_payload():
    e = next(e for e in L.build_schedule(T) if e.logical_key == "CPI:2026-11")
    p = e.payload
    assert (p["event"], p["time_confirmed"], p["all_day"], p["release_local"], p["status"]) == (
        "BLS_CPI", True, False, "08:30", "SCHEDULED")
    assert p["schedule_version"] == L.SCHEDULE_VERSION and p["period"] == "2026-11"


@pytest.mark.parametrize("kind,rows,msg", [
    ("CPI", (("2026-10", "2026-11-10"), ("2026-12", "2026-12-10")), "liên tiếp"),
    ("CPI", (("2026-10", "2026-11-10"), ("2026-11", "2026-11-10")), "không tăng"),
    ("CPI", (("2026-10", "2026-11-14"),), "lạ"),                     # thứ Bảy
    ("CPI", (("2026-10", "2026-10-15"),), "lạ"),                     # trước khi hết tháng
])
def test_schedule_table_validation(monkeypatch, kind, rows, msg):
    monkeypatch.setitem(L._TABLE, kind, rows)
    with pytest.raises(L.BlsParseError, match=msg):
        L.schedule_table()


def test_schedule_expiring_is_invalid_and_calendar_distrusts(env):
    store, log = env
    late = utc(2027, 11, 1)      # CPI cuối 10/12/2027 còn 39 ngày < 45
    chk = L.run_schedule_once(store=store, log=log, now=late - timedelta(days=30))
    assert chk.outcome is CheckOutcome.OK
    chk = L.run_schedule_once(store=store, log=log, now=late)
    assert (chk.outcome, chk.error_code) == (CheckOutcome.INVALID, "SCHEDULE_TABLE_EXPIRING")
    health = C.health_map(log, store, late)
    assert health["bls_schedule"] is False
    items = [i for i in C.economic_calendar(store, late, health=health)
             if i.source == "bls_schedule" and i.event == "BLS_EMPSIT"]
    nfp = next(i for i in items if i.logical_key == "EMPSIT:2027-10")
    assert nfp.all_day and "SCHEDULE_SOURCE_UNHEALTHY" in nfp.notes   # chặn cả ngày


def test_schedule_idempotent_and_cutoff(env):
    store, log = env
    a = L.run_schedule_once(store=store, log=log, now=T)
    b = L.run_schedule_once(store=store, log=log, now=T + timedelta(hours=20))
    assert a.inserted > 0 and (b.inserted, b.duplicate) == (0, 0)
    keys = {r.logical_key for r in store.as_of(T, source="bls_schedule", kind="calendar")}
    assert "EMPSIT:2026-10" not in keys       # 6/11 cũ hơn 7 ngày → không ghi
    assert {"CPI:2026-10", "PPI:2026-10", "CPI:2027-11"} <= keys


# ------------------------------------------------------------------ đọc phản hồi API

def test_parse_real_response_hand_checked():
    obs = {(o.series, o.period): o for o in L.parse_response(RAW)}
    assert len(obs) == 70
    cpi = obs[("CUSR0000SA0", "2026-10")]
    assert (cpi.value, cpi.footnotes, cpi.period_end) == ("337.476", (), utc(2026, 11, 1, 4))
    nfp = obs[("CES0000000001", "2026-10")]
    assert (nfp.value, nfp.footnotes) == ("159293", ("P",))
    assert obs[("CES0000000001", "2026-03")].value == "158650"       # chỗ ghép hai đoạn dán
    assert obs[("LNS14000000", "2026-01")].footnotes == ("12",)
    assert obs[("WPSFD4", "2026-10")].value == "160.254"
    # tháng 7 năm sau → cuối kỳ 0:00 ET 1/8 = 04:00 UTC (EDT)
    assert obs[("CUSR0000SA0", "2026-07")].period_end == utc(2026, 8, 1, 4)


def _set(code, period, field, value):
    def m(j):
        for d in series(j, code)["data"]:
            if d["period"] == period:
                d[field] = value
    return m


@pytest.mark.parametrize("mut,err", [
    (_set("CUSR0000SA0", "M10", "value", "3374.76"), "ngoài khoảng"),     # lệch dấu thập phân
    (_set("CES0000000001", "M10", "value", "159.293"), "ngoài khoảng"),   # đổi đơn vị
    (_set("LNS14000000", "M10", "value", "41"), "ngoài khoảng"),
    (_set("CUSR0000SA0", "M10", "value", "1,234"), "lạ"),
    (_set("CUSR0000SA0", "M10", "period", "M14"), "kỳ lạ"),
    (_set("CUSR0000SA0", "M09", "period", "M10"), "trùng"),
    (lambda j: j["Results"]["series"].pop(), "thiếu series"),
    (lambda j: series(j, "WPSFD4").update(seriesID="XYZ"), "series lạ"),
    (lambda j: j["Results"]["series"].append(series(j, "WPSFD4")), "series trùng"),
    (lambda j: j.pop("Results"), "Results"),
])
def test_parse_rejects(mut, err):
    with pytest.raises(L.BlsParseError, match=err):
        L.parse_response(body(mut))


def test_parse_not_json_and_annual_and_dash():
    with pytest.raises(L.BlsParseError):
        L.parse_response("<html>Access Denied</html>")

    def m(j):
        s = series(j, "CUSR0000SA0")["data"]
        s.append({"year": "2026", "period": "M13", "value": "999999", "footnotes": [{}]})
        s[0]["value"] = "-"
    obs = {(o.series, o.period): o for o in L.parse_response(body(m))}
    assert obs[("CUSR0000SA0", "2026-10")].value is None and len(obs) == 70


@pytest.mark.parametrize("status,msg,code", [
    ("REQUEST_NOT_PROCESSED", ["The key provided by the User is invalid."], "AUTH_FAILED"),
    ("REQUEST_NOT_PROCESSED", ["Your registration key has expired."], "AUTH_FAILED"),
    ("REQUEST_NOT_PROCESSED", ["You have reached the daily threshold for this key."],
     "RATE_LIMITED"),
    ("REQUEST_FAILED", ["Something else"], "API_NOT_PROCESSED"),
])
def test_api_error_codes(status, msg, code):
    with pytest.raises(L.FetchError) as e:
        L.parse_response(json.dumps({"status": status, "message": msg, "Results": {}}))
    assert e.value.code == code


# ------------------------------------------------------------------ ghi + point-in-time

def test_values_first_load_and_release_link(env):
    chk, calls = run(env)
    assert chk.outcome is CheckOutcome.OK and chk.inserted == 70
    assert calls[0]["registrationkey"] == KEY and calls[0]["startyear"] == "2025"
    store, _ = env
    v = {r.logical_key: r for r in store.as_of(T, source="bls_values")}
    ppi = v["WPSFD4:2026-10"]
    assert ppi.payload["release_ref"] == "PPI:2026-10"
    assert ppi.available_at == utc(2026, 11, 13, 13, 30)
    assert ppi.payload["latency_seconds"] == 1800 and "PRELIMINARY" in ppi.quality_flags
    cpi = v["CUSR0000SA0:2026-10"]                       # 10/11 13:30 → quá 3 ngày + 30 phút
    assert cpi.payload["release_ref"] is None and "INITIAL_LOAD" in cpi.quality_flags
    # nạp lúc 12/11 (trong 3 ngày) thì gắn được
    st2 = (PointInTimeStore(), SourceCheckLog())


    def no_ppi_oct(j):  # 12/11: PPI tháng 10 chưa công bố (13/11) → bỏ khỏi phản hồi
        s_ = series(j, "WPSFD4")
        s_["data"] = [d for d in s_["data"] if d["period"] != "M10"]
    run(st2, now=utc(2026, 11, 12, 12), text=body(no_ppi_oct))
    c2 = st2[0].as_of(utc(2026, 11, 12, 12), source="bls_values",
                      logical_key="CUSR0000SA0:2026-10")[0]
    assert (c2.payload["release_ref"], c2.available_at) == ("CPI:2026-10",
                                                            utc(2026, 11, 10, 13, 30))
    nfp = v["CES0000000001:2026-10"]
    assert nfp.payload["release_ref"] is None and "INITIAL_LOAD" in nfp.quality_flags  # 6/11
    assert nfp.available_at is None and nfp.known_at == T


def test_values_resync_and_revisions(env):
    run(env)
    chk, _ = run(env, now=T + timedelta(days=1))
    assert (chk.inserted, chk.duplicate) == (0, 0)
    # BLS sửa NFP tháng 9 và bỏ "sơ bộ" tháng 8 PPI → 2 revision; giá trị khác giữ nguyên
    t2 = T + timedelta(days=2)
    text = body(lambda j: (_set("CES0000000001", "M09", "value", "159101")(j),
                           _set("WPSFD4", "M08", "footnotes", [{}])(j)))
    chk, _ = run(env, now=t2, text=text)
    assert chk.inserted == 2
    store, _ = env
    h = store.history("bls_values", "CES0000000001:2026-09", t2)
    assert [r.payload["value"] for r in h] == ["159128", "159101"]
    assert "UNSCHEDULED_CHANGE" in h[1].quality_flags            # ngoài lần công bố
    assert store.as_of(t2 - timedelta(seconds=1), source="bls_values",
                       logical_key="CES0000000001:2026-09")[0].payload["value"] == "159128"
    p = store.history("bls_values", "WPSFD4:2026-08", t2)
    assert [("PRELIMINARY" in r.quality_flags) for r in p] == [True, False]


def test_new_release_captured_with_latency(env):
    """Giả lập NFP 4/12/2026 13:30 UTC: số tháng 11 vào lúc 13:31 → gắn lần công bố, trễ 60 s."""
    run(env)
    rel = utc(2026, 12, 4, 13, 30)
    store, log = env

    def add(j):
        d = series(j, "CES0000000001")["data"]
        d.insert(0, {"year": "2026", "period": "M11", "value": "159400",
                     "footnotes": [{"code": "P", "text": "preliminary"}]})
    ok = rel - timedelta(days=1)
    assert L.values_due(rel - timedelta(seconds=1), store, ok) is None
    assert L.values_due(rel, store, ok) == "RELEASE_WINDOW"
    chk, _ = run(env, now=rel + timedelta(seconds=60), text=body(add))
    assert chk.inserted == 1
    r = store.as_of(rel + timedelta(minutes=2), source="bls_values",
                    logical_key="CES0000000001:2026-11")[0]
    assert (r.payload["release_ref"], r.available_at, r.payload["latency_seconds"]) == (
        "EMPSIT:2026-11", rel, 60)
    assert L.values_due(rel + timedelta(minutes=2), store, rel) is None   # đã có số → thôi gọi
    # bảng lịch hợp nhất: NFP 4/12 → RECEIVED, cửa sổ 13:15–13:45 HIGH
    it = next(i for i in C.economic_calendar(store, rel + timedelta(minutes=2),
                                             start=rel - timedelta(hours=1))
              if i.logical_key == "EMPSIT:2026-11")
    assert (it.importance, it.window_start, it.window_end, it.actual_status) == (
        "HIGH", rel - timedelta(minutes=15), rel + timedelta(minutes=15), "RECEIVED")
    assert ("CES0000000001", "159400") in it.actuals


def test_release_late_api_keeps_window_open(env):
    """API chưa cập nhật lúc công bố → không ghi gì, vẫn gọi lại; cửa sổ kéo dài (1C-C05)."""
    run(env)
    store, _ = env
    rel = utc(2026, 12, 10, 13, 30)                       # CPI tháng 11
    chk, _ = run(env, now=rel + timedelta(minutes=1))    # API trả số cũ
    assert chk.inserted == 0
    assert L.values_due(rel + timedelta(minutes=2), store, rel) == "RELEASE_WINDOW"
    now = rel + timedelta(minutes=20)
    it = next(i for i in C.economic_calendar(store, now, start=rel - timedelta(hours=1))
              if i.logical_key == "CPI:2026-11")
    assert it.actual_status == "UNKNOWN_LATE" and it.window_end >= now
    assert L.values_due(rel + timedelta(minutes=91), store, rel) is None


def test_values_due_reconcile_rules(env):
    store, _ = env
    assert L.values_due(T, store, None) == "RECONCILE"
    assert L.values_due(T, store, T - timedelta(days=6)) is None
    assert L.values_due(T, store, T - timedelta(days=8)) == "RECONCILE"


def test_future_period_rejected(env):
    def add(j):
        series(j, "CUSR0000SA0")["data"].insert(0, {
            "year": "2026", "period": "M11", "value": "338.0", "footnotes": [{}]})
    chk, _ = run(env, text=body(add))       # 13/11: tháng 11 chưa kết thúc
    assert (chk.outcome, chk.error_code) == (CheckOutcome.INVALID, "PARSE_ERROR")


def test_missing_key_never_calls(env):
    chk, calls = run(env, k=KeyLookup("bls", None, "KEY_MISSING"))
    assert (chk.outcome, chk.error_code, calls) == (CheckOutcome.ERROR, "KEY_MISSING", [])


def test_http_poster_key_in_body_only():
    seen = []

    def h(req):
        seen.append(req)
        return httpx.Response(200, text=RAW)
    post = L.http_poster(httpx.Client(transport=httpx.MockTransport(h)))
    assert post({"registrationkey": KEY}) == RAW
    assert KEY not in str(seen[0].url) and seen[0].method == "POST"
    for status, code in ((401, "AUTH_FAILED"), (403, "FORBIDDEN"), (429, "RATE_LIMITED"),
                         (503, "HTTP_503"), (302, "HTTP_UNEXPECTED")):
        p = L.http_poster(httpx.Client(transport=httpx.MockTransport(
            lambda r, s=status: httpx.Response(s, headers={"location": "https://evil.x/"}))))
        with pytest.raises(L.FetchError) as e:
            p({})
        assert e.value.code == code


def test_cli_dry_run(capsys):
    def client():
        return httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, text=RAW)))
    rc = cli._bls(True, env={"GT_BLS_API_KEY": KEY}, client_factory=client, now=T)
    out = capsys.readouterr().out
    assert rc == 0 and "Lịch BLS" in out and "Số BLS: OK" in out
    assert "10/12/2026 20:30 giờ VN  Consumer Price Index — 2026-11" in out
    assert "04/12/2026 20:30 giờ VN  The Employment Situation — 2026-11" in out
    assert "CES0000000001    2026-10: 159293 (sơ bộ)" in out
    assert "BLS.gov cannot vouch" in out and KEY not in out
    assert cli._bls(True, env={}, client_factory=client, now=T) == 1   # thiếu khóa
