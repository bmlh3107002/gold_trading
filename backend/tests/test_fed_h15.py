"""Bước 9b — lãi suất H.15 của Fed (ING-11, ING-25, ING-26; 1E-C01..C04).

Trang thật ``tests/fixtures/fed/h15-2026-11-12.html`` (www.federalreserve.gov/releases/h15/,
public domain, Federal Reserve Board; lợi suất trái phiếu do U.S. Treasury tính). Số tham chiếu
đối chiếu với file CSV "Treasury Constant Maturities" của Fed tải riêng cùng ngày (2Y 10/11 = 4.73,
10Y = 4.98) và đọc tay bảng trên trang.
"""

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from gold_trading.common.enums import SourceStatus
from gold_trading.ingestion import cli
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.ingestion.source_status import CheckOutcome, SourceCheckLog, evaluate
from gold_trading.ingestion.sources import fed_h15 as H
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.source_checks import SqlSourceCheckLog

PAGE = (Path(__file__).parent / "fixtures" / "fed" / "h15-2026-11-12.html").read_text(
    encoding="utf-8")
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def utc(*a):
    return datetime(*a, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def env(request, tmp_path):
    if request.param == "memory":
        return PointInTimeStore(), SourceCheckLog()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'h.db'}")
    repo.create_all()
    return SqlExternalRecordStore(repo.engine), SqlSourceCheckLog(repo.engine)


def run(env, page=PAGE, now=NOW):
    store, log = env
    return H.run_once(store=store, log=log, get=lambda: page, now=now)


def vals(store, series, at=NOW):
    return {r.payload["date"]: (r.payload["value"], r.payload["value_status"])
            for r in store.as_of(at, source=H.SOURCE) if r.payload["series"] == series}


def cell(page, series_row_text, col, new):
    """Sửa một ô của trang (dòng có nhãn ``series_row_text`` trong nhóm đúng, cột ``col``)."""
    i = page.index(series_row_text)
    j = page.index(f'col{col}" nowrap="nowrap">', i)
    k = page.index("</td>", j)
    start = j + len(f'col{col}" nowrap="nowrap">')
    return page[:start] + new + page[k:]


TWO_YEAR = 'class="stub in4">2-year</th>'


# ------------------------------------------------------------------ đọc trang thật

def test_parse_real_page_reference_values():
    rel = H.parse_release(PAGE)
    assert rel.release_date == date(2026, 11, 12)
    got = {(o.series, o.day.isoformat()): (o.value, o.status) for o in rel.observations}
    assert got[("UST_CMT_2Y", "2026-11-10")] == ("4.73", "AVAILABLE")
    assert got[("UST_CMT_10Y", "2026-11-10")] == ("4.98", "AVAILABLE")
    assert got[("UST_TIPS_10Y", "2026-11-10")] == ("2.78", "AVAILABLE")
    assert got[("EFFR", "2026-11-10")] == ("3.88", "AVAILABLE")
    assert got[("UST_CMT_2Y", "2026-11-05")] == ("4.46", "AVAILABLE")
    # 11/11 Veterans Day: thị trường trái phiếu đóng (*) → không có số, không nội suy (1E-C02)
    assert got[("UST_CMT_10Y", "2026-11-11")] == (None, "MARKET_CLOSED")
    assert got[("UST_TIPS_10Y", "2026-11-11")] == (None, "MARKET_CLOSED")
    assert got[("EFFR", "2026-11-11")] == ("3.88", "AVAILABLE")  # EFFR vẫn có
    assert len(rel.observations) == 20
    # Không lấy nhầm dòng 10-year danh nghĩa cho TIPS và ngược lại
    assert got[("UST_TIPS_10Y", "2026-11-05")] == ("2.60", "AVAILABLE")
    assert got[("UST_CMT_10Y", "2026-11-05")] == ("4.84", "AVAILABLE")


def test_na_and_blank_cells():
    p = cell(PAGE, TWO_YEAR, 2, "&nbsp;n.a.&nbsp;")
    p = cell(p, TWO_YEAR, 3, "&nbsp;&nbsp;")  # trống ở ngày thường → chưa công bố, không ghi
    got = {(o.series, o.day.isoformat()): (o.value, o.status)
           for o in H.parse_release(p).observations}
    assert got[("UST_CMT_2Y", "2026-11-06")] == (None, "NOT_AVAILABLE")
    assert ("UST_CMT_2Y", "2026-11-09") not in got


@pytest.mark.parametrize("mutate,why", [
    (lambda p: p.replace("Release date: November 12, 2026", "Release date: Nov 12, 2026"),
     "ngày phát hành lạ"),
    (lambda p: p.replace('id="h15table"', 'id="other"'), "không có bảng"),
    (lambda p: p.replace(">Inflation indexed <", ">Inflation-protected <"),
     "đổi tên nhóm (1E-C03)"),
    (lambda p: p.replace("Federal funds (effective)", "Federal funds rate"), "đổi tên dòng"),
    (lambda p: cell(p, TWO_YEAR, 4, "&nbsp;473&nbsp;"), "đổi đơn vị: 473 (1E-C04)"),
    (lambda p: cell(p, TWO_YEAR, 4, "&nbsp;47.30&nbsp;"), "ngoài khoảng -5..25 (1E-C04)"),
    (lambda p: cell(p, TWO_YEAR, 4, "&nbsp;4.7&nbsp;"), "sai số chữ số"),
    (lambda p: cell(p, TWO_YEAR, 4, "&nbsp;4,73&nbsp;"), "dấu phẩy"),
    (lambda p: p.replace("2026<br>Nov<br>9", "2026<br>Nov<br>12"), "ngày cột = ngày phát hành"),
    (lambda p: p.replace("2026<br>Nov<br>9", "2026<br>Nov<br>5"), "cột trùng ngày"),
    (lambda p: p.replace("2026<br>Nov<br>9", "2026<br>Noc<br>9"), "tháng lạ"),
    (lambda p: p.replace("2026<br>Nov<br>9", "2026<br>Nov<br>31"), "ngày không tồn tại"),
    (lambda p: p.replace('id="col3"', 'id="col7"'), "cột sai thứ tự"),
    (lambda p: re.sub(r'(?s)(class="stub in4">2-year</th>.*?)<td class="data"[^>]*>.*?</td>',
                      r"\1", p, count=1), "thiếu ô"),
])
def test_broken_pages_rejected(mutate, why):
    p = mutate(PAGE)
    assert p != PAGE, why
    with pytest.raises(H.H15ParseError):
        H.parse_release(p)


def test_duplicate_row_rejected():
    i = PAGE.index('<th nowrap="nowrap" id="id9588fd0"')
    row_start = PAGE.rindex("<tr>", 0, i)
    row_end = PAGE.index("</tr>", i) + len("</tr>")
    dup = PAGE[:row_end] + PAGE[row_start:row_end].replace('id="id9588fd0"', 'id="idX"') + \
        PAGE[row_end:]
    with pytest.raises(H.H15ParseError, match="hai lần"):
        H.parse_release(dup)


# ------------------------------------------------------------------ ghi + point-in-time

def test_first_load_and_point_in_time(env):
    store, log = env
    c = run(env)
    assert (c.outcome, c.inserted) == (CheckOutcome.OK, 20)
    assert vals(store, "UST_CMT_2Y")["2026-11-10"] == ("4.73", "AVAILABLE")
    r = store.as_of(NOW, source=H.SOURCE, logical_key="UST_CMT_2Y:2026-11-10")[0]
    # Hết ngày 10/11 giờ New York; trang không ghi giờ phát hành → biết từ lúc tải (1E-C01)
    assert r.event_time == utc(2026, 11, 11, 5) and r.available_at is None
    assert r.known_at == NOW
    assert store.as_of(NOW - timedelta(seconds=1), source=H.SOURCE) == []
    closed = store.as_of(NOW, source=H.SOURCE, logical_key="UST_CMT_10Y:2026-11-11")[0]
    assert closed.payload["value"] is None and "MARKET_CLOSED" in closed.quality_flags
    assert r.payload["source_note"].startswith("U.S. Treasury")
    eff = store.as_of(NOW, source=H.SOURCE, logical_key="EFFR:2026-11-10")[0]
    assert eff.payload["source_note"] == H.BOARD


def test_reload_idempotent_and_revision_keeps_past(env):
    store, log = env
    run(env)
    c = run(env, now=NOW + timedelta(hours=5))
    assert (c.inserted, c.outcome) == (0, CheckOutcome.OK)
    # Fed sửa số 2 năm ngày 10/11 trong lần phát hành sau
    later = NOW + timedelta(days=1)
    p = cell(PAGE, TWO_YEAR, 4, "&nbsp;4.74&nbsp;").replace(
        "Release date: November 12, 2026", "Release date: November 13, 2026")
    c = run(env, page=p, now=later)
    assert c.inserted == 1
    assert vals(store, "UST_CMT_2Y", later)["2026-11-10"] == ("4.74", "AVAILABLE")
    assert vals(store, "UST_CMT_2Y", NOW)["2026-11-10"] == ("4.73", "AVAILABLE")  # quá khứ giữ
    hist = store.history(H.SOURCE, "UST_CMT_2Y:2026-11-10", later)
    assert [h.revision for h in hist] == [0, 1]
    # Bản phát hành cũ (12/11) tải lại sau → không viết đè số mới
    c = run(env, now=later + timedelta(hours=5))
    assert c.inserted == 0
    assert vals(store, "UST_CMT_2Y", later + timedelta(hours=5))["2026-11-10"][0] == "4.74"


def test_closed_day_later_filled_is_revision(env):
    store, _ = env
    run(env)
    p = cell(PAGE, TWO_YEAR, 5, "&nbsp;4.70&nbsp;").replace(
        "Release date: November 12, 2026", "Release date: November 13, 2026")
    run(env, page=p, now=NOW + timedelta(days=1))
    assert vals(store, "UST_CMT_2Y", NOW + timedelta(days=1))["2026-11-11"] == ("4.70",
                                                                                "AVAILABLE")


@pytest.mark.parametrize("page,code", [
    ("<html>bảo trì</html>", "PARSE_ERROR"),
    (PAGE.replace("Release date: November 12, 2026", "Release date: November 14, 2026"),
     "PARSE_ERROR"),  # ngày phát hành ở tương lai so với lúc tải
])
def test_invalid_pages_write_nothing(env, page, code):
    store, log = env
    c = run(env, page=page)
    assert (c.outcome, c.error_code) == (CheckOutcome.INVALID, code)
    assert store.as_of(NOW, source=H.SOURCE) == []
    h = evaluate(H.SOURCE, H.spec(), log.summary(H.SOURCE, NOW), NOW,
                 store.latest_event_time(H.SOURCE, NOW))
    assert h.status is SourceStatus.INVALID


def test_fetch_error_and_status_ttl(env):
    store, log = env

    def boom():
        raise H.FetchError("HTTP_503")
    c = H.run_once(store=store, log=log, get=boom, now=NOW)
    assert (c.outcome, c.error_code) == (CheckOutcome.ERROR, "HTTP_503")
    run(env)
    st = lambda at: evaluate(H.SOURCE, H.spec(), log.summary(H.SOURCE, at), at,  # noqa: E731
                             store.latest_event_time(H.SOURCE, at))
    assert st(NOW).status is SourceStatus.HEALTHY
    assert (st(NOW + timedelta(hours=31)).reason) == "FETCH_TTL_EXPIRED"
    # Vẫn tải được nhưng Fed không có số mới quá 7 ngày → STALE (dữ liệu cũ, 1F-C02 cùng kiểu)
    for k in range(1, 9):
        run(env, now=NOW + timedelta(days=k))
    assert st(NOW + timedelta(days=8)).reason == "DATA_TTL_EXPIRED"


def test_due_policy():
    from gold_trading.ingestion.source_status import CheckSummary, SourceCheck
    s = lambda last, ok: CheckSummary(last, ok, 0, None, None, None)  # noqa: E731
    ok_c = lambda t: SourceCheck(H.SOURCE, t, CheckOutcome.OK)  # noqa: E731
    err = lambda t: SourceCheck(H.SOURCE, t, CheckOutcome.ERROR, "TIMEOUT")  # noqa: E731
    assert H.due(NOW, s(None, None)) == "REFRESH"
    t = NOW - timedelta(hours=3)
    assert H.due(NOW, s(ok_c(t), t)) is None
    t = NOW - timedelta(hours=4)
    assert H.due(NOW, s(ok_c(t), t)) == "REFRESH"
    assert H.due(NOW, s(err(NOW - timedelta(minutes=10)), t)) is None
    assert H.due(NOW, s(err(NOW - timedelta(minutes=30)), t)) == "RETRY"


def test_terms_verified_provider():
    from gold_trading.ingestion.source_status import SourceRegistry
    SourceRegistry([H.spec()])  # fed VERIFIED → bật được


# ------------------------------------------------------------------ HTTP + CLI

def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("resp,code", [
    (httpx.Response(503), "HTTP_503"),
    (httpx.Response(403), "FORBIDDEN"),
    (httpx.Response(200, content=b"x" * (H.MAX_BYTES + 1)), "RESPONSE_TOO_LARGE"),
])
def test_http_errors(resp, code):
    get = H.http_getter(_client(lambda req: resp))
    with pytest.raises(H.FetchError) as e:
        get()
    assert e.value.code == code


def test_http_redirect_to_other_host():
    def h(req):
        if req.url.host == "www.federalreserve.gov":
            return httpx.Response(302, headers={"location": "https://evil.example/x"})
        return httpx.Response(200, text=PAGE)
    with pytest.raises(H.FetchError) as e:
        H.http_getter(_client(h))()
    assert e.value.code == "UNEXPECTED_REDIRECT"


def test_http_timeout_and_ok():
    def to(req):
        raise httpx.ReadTimeout("x", request=req)
    with pytest.raises(H.FetchError) as e:
        H.http_getter(_client(to))()
    assert e.value.code == "TIMEOUT"
    seen = []

    def ok(req):
        seen.append(str(req.url))
        return httpx.Response(200, text=PAGE)
    assert H.http_getter(_client(ok))() == PAGE and seen == [H.URL]


def test_cli_dry_run(capsys):
    rc = cli._h15(True, client_factory=lambda: _client(lambda r: httpx.Response(200, text=PAGE)))
    out = capsys.readouterr().out
    assert rc == 0  # trang mẫu phát hành 12/11/2026, trước giờ chạy test
    assert "UST_CMT_2Y" in out and "4.73" in out and "U.S. Treasury" in out
    rc = cli._h15(True, client_factory=lambda: _client(lambda r: httpx.Response(503)))
    assert rc == 1 and "HTTP_503" in capsys.readouterr().out


# ------------------------------------------------------------------ 9c: proxy kỳ vọng Fed (ING-27)

def _rec(series, day, value, status="AVAILABLE", rev=0, ingested=NOW):
    from gold_trading.contracts.records import NormalizedRecord
    return NormalizedRecord(
        record_id=f"fed_h15:{series}:{day}:r{rev}", source="fed_h15", kind="macro",
        logical_key=f"{series}:{day}", revision=rev,
        event_time=H._event_time(date.fromisoformat(day)), ingested_at=ingested,
        source_status=SourceStatus.HEALTHY, payload_version="t", raw_ref="t",
        payload={"series": series, "date": day, "value": value, "value_status": status})


def test_proxy_on_real_page_hand_computed(env):
    from gold_trading.ingestion.macro_view import fed_expectation_proxy
    store, _ = env
    run(env)
    px = fed_expectation_proxy(store, NOW)
    # 11/11: EFFR có số nhưng thị trường trái phiếu đóng → lùi về 10/11 (không trộn ngày)
    assert px.status == "OK" and px.observation_date == date(2026, 11, 10)
    assert (px.two_year, px.effr) == ("4.73", "3.88")
    assert (px.spread_pp, px.spread_bp, px.lean) == ("0.85", 85, "LEANS_HOLD_OR_HIKE")
    assert "không phải xác suất" in px.label


def test_proxy_signs_and_flat(env):
    from gold_trading.ingestion.macro_view import fed_expectation_proxy
    store, _ = env
    run(env, page=cell(PAGE, TWO_YEAR, 4, "&nbsp;3.50&nbsp;"))
    px = fed_expectation_proxy(store, NOW)
    assert (px.spread_pp, px.spread_bp, px.lean) == ("-0.38", -38, "LEANS_CUT")
    st2 = PointInTimeStore()
    st2.extend([_rec("UST_CMT_2Y", "2026-11-10", "3.88"), _rec("EFFR", "2026-11-10", "3.88")])
    px = fed_expectation_proxy(st2, NOW)
    assert (px.spread_bp, px.lean) == (0, "FLAT")


def test_proxy_insufficient_data_never_mixes_days():
    from gold_trading.ingestion.macro_view import fed_expectation_proxy
    st = PointInTimeStore()
    assert fed_expectation_proxy(st, NOW).reason == "NO_COMMON_DAY"
    st.extend([_rec("UST_CMT_2Y", "2026-11-10", "4.73"), _rec("EFFR", "2026-11-09", "3.88"),
               _rec("EFFR", "2026-11-10", None, "NOT_AVAILABLE")])
    px = fed_expectation_proxy(st, NOW)
    assert (px.status, px.reason, px.spread_bp) == ("INSUFFICIENT_DATA", "NO_COMMON_DAY", None)
    st.append(_rec("UST_CMT_2Y", "2026-11-09", "4.56"))
    assert fed_expectation_proxy(st, NOW).observation_date == date(2026, 11, 9)


def test_proxy_stale_and_point_in_time(env):
    from gold_trading.ingestion.macro_view import fed_expectation_proxy
    store, _ = env
    run(env)
    late = NOW + timedelta(days=8)  # số mới nhất 10/11 → quá 7 ngày
    px = fed_expectation_proxy(store, late)
    assert (px.status, px.reason, px.observation_date) == ("INSUFFICIENT_DATA", "STALE",
                                                            date(2026, 11, 10))
    assert fed_expectation_proxy(store, NOW - timedelta(seconds=1)).reason == "NO_COMMON_DAY"
    # Fed sửa số 2 năm 10/11 → 4.74 (biết sau 1 ngày): trước đó vẫn 85, sau đó 86
    later = NOW + timedelta(days=1)
    p = cell(PAGE, TWO_YEAR, 4, "&nbsp;4.74&nbsp;").replace(
        "Release date: November 12, 2026", "Release date: November 13, 2026")
    run(env, page=p, now=later)
    assert fed_expectation_proxy(store, NOW + timedelta(hours=1)).spread_bp == 85
    assert fed_expectation_proxy(store, later).spread_bp == 86
    with pytest.raises(ValueError):
        fed_expectation_proxy(store, datetime(2026, 11, 13))


def test_cli_prints_proxy(capsys):
    cli._h15(True, client_factory=lambda: _client(lambda r: httpx.Response(200, text=PAGE)))
    out = capsys.readouterr().out
    # Giờ thật > 7 ngày sau 10/11/2026 thì proxy báo không đủ dữ liệu (đúng: số cũ)
    assert "+85 điểm cơ bản → LEANS_HOLD_OR_HIKE" in out or "không đủ dữ liệu (STALE)" in out
