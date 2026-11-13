"""Bước 9e — COT vàng của CFTC (ING-12, 1F-C01..C03).

Khối GOLD Code-088691 thật (chốt 03/11/2026) — ``tests/fixtures/cftc/`` (in ra từ máy người dùng,
public domain, CFTC). Số tham chiếu đọc tay trên báo cáo + đẳng thức cộng của CFTC.
"""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from gold_trading.common.enums import SourceStatus
from gold_trading.ingestion import cli
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.ingestion.source_status import CheckOutcome, SourceCheckLog, evaluate
from gold_trading.ingestion.sources import cftc_cot as C
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.source_checks import SqlSourceCheckLog

PAGE = (Path(__file__).parent / "fixtures" / "cftc" / "deacmxsf-2026-11-03-gold.txt").read_text(
    encoding="utf-8")
REL = datetime(2026, 11, 6, 20, 30, tzinfo=UTC)   # 15:30 ET thứ Sáu 06/11 (EST)
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def utc(*a):
    return datetime(*a, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def env(request, tmp_path):
    if request.param == "memory":
        return PointInTimeStore(), SourceCheckLog()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'c.db'}")
    repo.create_all()
    return SqlExternalRecordStore(repo.engine), SqlSourceCheckLog(repo.engine)


def run(env, page=PAGE, now=NOW):
    store, log = env
    return C.run_once(store=store, log=log, get=lambda: page, now=now)


def gold(page=PAGE):
    """Khối GOLD (để sửa từng phần trong test hỏng)."""
    i = page.index("GOLD - COMMODITY EXCHANGE INC.    ")
    j = page.index("MICRO GOLD")
    return i, j


def sub_gold(old, new, page=PAGE):
    i, j = gold(page)
    blk = page[i:j]
    assert old in blk, old
    return page[:i] + blk.replace(old, new, 1) + page[j:]


# ------------------------------------------------------------------ đọc

def test_parse_real_report_hand_values():
    r = C.parse(PAGE)
    assert r.as_of == date(2026, 11, 3) and r.change_from == date(2026, 10, 27)
    assert (r.open_interest, r.oi_change) == (399169, 2359)
    assert r.positions == {"noncomm_long": 220530, "noncomm_short": 40982,
                           "noncomm_spreads": 68289, "comm_long": 64326, "comm_short": 269228,
                           "total_long": 353145, "total_short": 378499, "nonrept_long": 46024,
                           "nonrept_short": 20670}
    assert r.changes["comm_short"] == -10505 and r.changes["noncomm_long"] == -3194
    assert r.percents["noncomm_long"] == "55.2" and r.total_traders == 282
    assert r.traders["total_short"] == 153 and r.flags == ()
    # Không lấy nhầm MICRO GOLD (OI 111,271)
    assert r.open_interest != 111271


def test_html_wrapper_and_crlf():
    html_page = "<html><body><pre>" + PAGE.replace("\n", "\r\n").replace(
        "COMMITMENTS", "COMMITMENTS") + "</pre></body></html>"
    assert C.parse(html_page).open_interest == 399169


@pytest.mark.parametrize("old,new,why", [
    ("Code-088691", "Code-088699", "đổi mã hợp đồng (1F-C03)"),
    ("(CONTRACTS OF 100 TROY OUNCES)", "(CONTRACTS OF 50 TROY OUNCES)", "đổi đơn vị (1F-C03)"),
    (" 220,530   40,982", " 220,531   40,982", "tổng long không khớp"),
    ("  269,228  353,145", "  269,229  353,145", "tổng short không khớp"),
    ("   46,024   20,670", "   46,025   20,670", "không khớp OI"),
    ("  -3,194    3,709", "  -3,195    3,709", "thay đổi không khớp"),
    ("(CHANGE IN OPEN INTEREST:      2,359)", "(CHANGE IN OPEN INTEREST:      2,360)",
     "thay đổi OI không khớp"),
    ("    55.2     10.3", "    45.2     10.3", "% lệch số"),
    ("    55.2     10.3", "    55,2     10.3", "% sai định dạng"),
    ("AS OF 11/03/26", "AS OF 11/31/26", "ngày không tồn tại"),
    ("AS OF 11/03/26", "AS OF 2026-11-03", "định dạng ngày lạ"),
    (" 220,530   40,982   68,289", " 220,530   40,982", "thiếu cột"),
    ("OPEN INTEREST:      399,169", "OPEN INTEREST:      N/A", "OI không phải số"),
    ("NUMBER OF TRADERS IN EACH CATEGORY (TOTAL TRADERS:      282)",
     "NUMBER OF TRADERS", "thiếu tổng trader"),
])
def test_broken_reports_rejected(old, new, why):
    with pytest.raises(C.CotParseError):
        C.parse(sub_gold(old, new))


def test_missing_or_duplicate_gold_block():
    with pytest.raises(C.CotParseError, match="một khối GOLD"):
        C.parse(PAGE.replace("GOLD - COMMODITY EXCHANGE INC.    ",
                             "GOLDX - COMMODITY EXCHANGE INC."))
    i, j = gold()
    with pytest.raises(C.CotParseError, match="một khối GOLD"):
        C.parse(PAGE + "\n" + PAGE[i:j])
    with pytest.raises(C.CotParseError):
        C.parse("<html>Service unavailable</html>")


def test_flags_not_tuesday_and_change_base():
    p = sub_gold("AS OF 11/03/26", "AS OF 11/02/26")
    p = sub_gold("CHANGES FROM 10/27/26", "CHANGES FROM 10/26/26", p)
    assert C.parse(p).flags == ("AS_OF_NOT_TUESDAY",)
    p = sub_gold("CHANGES FROM 10/27/26", "CHANGES FROM 10/20/26")
    assert C.parse(p).flags == ("CHANGE_BASE_NOT_PRIOR_WEEK",)


# ------------------------------------------------------------------ lịch công bố (1F-C01)

def test_release_schedule_2026():
    assert len(C.RELEASES) == 52
    assert C.release_for(date(2026, 11, 3)) == date(2026, 11, 6)
    assert C.release_for(date(2026, 11, 10)) == date(2026, 11, 16)    # dời: Veterans Day
    assert C.release_for(date(2026, 11, 24)) == date(2026, 11, 30)    # dời: Lễ Tạ ơn
    assert C.release_for(date(2026, 12, 22)) == date(2026, 12, 28)    # dời: Giáng sinh
    assert C.release_for(date(2025, 12, 30)) == date(2026, 1, 5)
    assert C.release_for(date(2026, 12, 29)) is None                  # 2027 chưa có lịch
    assert date(2026, 11, 16) in C.DELAYED and date(2026, 11, 20) not in C.DELAYED
    assert all(d.weekday() == 4 or d in C.DELAYED for d in C.RELEASES)  # thứ Sáu trừ ngày dời
    # 15:30 New York: mùa hè UTC-4, mùa đông UTC-5
    assert C.release_at(date(2026, 7, 14)) == utc(2026, 7, 17, 19, 30)
    assert C.release_at(date(2026, 11, 3)) == REL


# ------------------------------------------------------------------ ghi + point-in-time

def test_first_load_point_in_time(env):
    store, log = env
    c = run(env)
    assert (c.outcome, c.inserted) == (CheckOutcome.OK, 1)
    r = store.as_of(NOW, source=C.SOURCE)[0]
    assert r.logical_key == "GOLD_088691:2026-11-03" and r.kind == "positioning"
    assert r.event_time == utc(2026, 11, 4, 5) and r.available_at == REL
    assert r.payload["noncomm_net"] == 220530 - 40982
    assert r.payload["release_at"] == REL.isoformat() and r.payload["flags"] == []
    # Ngày chốt ≠ ngày công bố: trước 15:30 thứ Sáu không thấy (kể cả khi nạp sớm)
    st2, log2 = PointInTimeStore(), SourceCheckLog()
    C.run_once(store=st2, log=log2, get=lambda: PAGE, now=utc(2026, 11, 5, 12))
    assert st2.as_of(REL - timedelta(seconds=1), source=C.SOURCE) == []
    assert len(st2.as_of(REL, source=C.SOURCE)) == 1


def test_outside_schedule_not_guessed(env):
    store, _ = env
    p = PAGE.replace("AS OF 11/03/26", "AS OF 12/29/26").replace(
        "CHANGES FROM 10/27/26", "CHANGES FROM 12/22/26")
    now = utc(2027, 1, 5, 12)
    run(env, page=p, now=now)
    r = store.as_of(now, source=C.SOURCE)[0]
    assert r.available_at is None and r.known_at == now
    assert "RELEASE_SCHEDULE_UNKNOWN" in r.payload["flags"]


def test_reload_revision_and_old_report(env):
    store, _ = env
    run(env)
    assert run(env, now=NOW + timedelta(hours=7)).inserted == 0   # nạp lại → không thêm
    # CFTC sửa báo cáo (số thương mại short + tổng + nhỏ lẻ đổi cho khớp)
    fixed = sub_gold("  269,228  353,145  378,499   46,024   20,670",
                     "  269,200  353,145  378,471   46,024   20,698")
    later = NOW + timedelta(days=1)
    assert run(env, page=fixed, now=later).inserted == 1
    hist = store.history(C.SOURCE, "GOLD_088691:2026-11-03", later)
    assert [h.revision for h in hist] == [0, 1]
    assert store.as_of(NOW + timedelta(hours=1), source=C.SOURCE)[0].payload["positions"][
        "comm_short"] == 269228  # quá khứ giữ nguyên
    # Báo cáo tuần mới rồi trang lại trả báo cáo cũ (bộ đệm) → không ghi
    newer = PAGE.replace("AS OF 11/03/26", "AS OF 11/10/26").replace(
        "CHANGES FROM 10/27/26", "CHANGES FROM 11/03/26")
    t2 = utc(2026, 11, 16, 21)
    assert run(env, page=newer, now=t2).inserted == 1
    st_before = len(store.history(C.SOURCE, "GOLD_088691:2026-11-03", t2))
    assert run(env, page=fixed, now=t2 + timedelta(hours=7)).inserted == 0
    assert len(store.history(C.SOURCE, "GOLD_088691:2026-11-03", t2 + timedelta(hours=8))) \
        == st_before


@pytest.mark.parametrize("page", ["<html>bảo trì</html>",
                                  PAGE.replace("AS OF 11/03/26", "AS OF 11/24/26").replace(
                                      "CHANGES FROM 10/27/26", "CHANGES FROM 11/17/26")])
def test_invalid_or_future_report_writes_nothing(env, page):
    store, log = env
    c = run(env, page=page)
    assert (c.outcome, c.error_code) == (CheckOutcome.INVALID, "PARSE_ERROR")
    assert store.as_of(NOW + timedelta(days=30), source=C.SOURCE) == []


def test_status_ttl_delay_1f_c02(env):
    store, log = env

    def st(at):
        return evaluate(C.SOURCE, C.spec(), log.summary(C.SOURCE, at), at,
                        store.latest_event_time(C.SOURCE, at))
    def boom():
        raise C.FetchError("FORBIDDEN")
    C.run_once(store=store, log=log, get=boom, now=NOW - timedelta(hours=1))
    run(env)
    assert st(NOW).status is SourceStatus.HEALTHY
    # CFTC trễ (chính phủ đóng cửa): trang vẫn trả báo cáo 03/11 → quá 14 ngày → STALE
    for d in range(1, 13):
        run(env, now=NOW + timedelta(days=d))
    h = st(NOW + timedelta(days=12))
    assert (h.status, h.reason) == (SourceStatus.STALE, "DATA_TTL_EXPIRED")
    assert st(NOW + timedelta(days=1)).status is SourceStatus.HEALTHY


def test_due_policy():
    from gold_trading.ingestion.source_status import CheckSummary, SourceCheck
    s = lambda last, ok: CheckSummary(last, ok, 0, None, None, None)  # noqa: E731
    assert C.due(NOW, s(None, None)) == "REFRESH"
    t = NOW - timedelta(hours=5)
    assert C.due(NOW, s(SourceCheck(C.SOURCE, t, CheckOutcome.OK), t)) is None
    t = NOW - timedelta(hours=6)
    assert C.due(NOW, s(SourceCheck(C.SOURCE, t, CheckOutcome.OK), t)) == "REFRESH"
    e = SourceCheck(C.SOURCE, NOW - timedelta(minutes=10), CheckOutcome.ERROR, "FORBIDDEN")
    assert C.due(NOW, s(e, t)) is None


# ------------------------------------------------------------------ HTTP + CLI

def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("resp,code", [
    (httpx.Response(403), "FORBIDDEN"), (httpx.Response(404), "NOT_FOUND"),
    (httpx.Response(200, content=b"x" * (C.MAX_BYTES + 1)), "RESPONSE_TOO_LARGE"),
])
def test_http_errors(resp, code):
    with pytest.raises(C.FetchError) as e:
        C.http_getter(_client(lambda r: resp))()
    assert e.value.code == code


def test_http_redirect_other_host_and_ok():
    def h(req):
        if req.url.host == "www.cftc.gov":
            return httpx.Response(301, headers={"location": "https://evil.example/x"})
        return httpx.Response(200, text=PAGE)
    with pytest.raises(C.FetchError) as e:
        C.http_getter(_client(h))()
    assert e.value.code == "UNEXPECTED_REDIRECT"
    assert C.http_getter(_client(lambda r: httpx.Response(200, text=PAGE)))() == PAGE


def test_cli_dry_run(capsys):
    rc = cli._cot(True, client_factory=lambda: _client(lambda r: httpx.Response(200, text=PAGE)))
    out = capsys.readouterr().out
    assert rc == 0 and "chốt 2026-11-03" in out and "ròng +179,548" in out
    assert "Commodity Futures Trading Commission" in out
    rc = cli._cot(True, client_factory=lambda: _client(lambda r: httpx.Response(403)))
    assert rc == 1 and "FORBIDDEN" in capsys.readouterr().out
