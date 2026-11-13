"""ING-09 (bước 8b): lịch FOMC từ trang chính thức của Fed — trang thật lưu ngày 2026-11-13.

Case: 1C-C02 (hủy/hoãn), 1C-C03 (đổi giờ), 1C-C04 (DST Mỹ), trang hỏng, lỗi mạng, nạp lại.
"""

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from gold_trading.common.enums import SourceStatus
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.ingestion.source_status import (
    CheckOutcome,
    SourceCheckLog,
    SourceRegistry,
    evaluate,
)
from gold_trading.ingestion.source_terms import SourceTerms, TermsStatus
from gold_trading.ingestion.sources import fed_fomc as F
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.source_checks import SqlSourceCheckLog

FIX = Path(__file__).parent / "fixtures" / "fed"
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
MEETINGS = (FIX / "fomccalendars-2026-11-13.html").read_text(encoding="utf-8")
INDEX = (FIX / "calendar-2026-11-13.html").read_text(encoding="utf-8")


def month(name: str) -> str:
    return (FIX / f"2026-{name}.html").read_text(encoding="utf-8")


def pages(**over) -> dict[str, str]:
    p = {F.MEETINGS_PATH: MEETINGS, F.CALENDAR_INDEX_PATH: INDEX,
         "/newsevents/2026-october.htm": month("october"),
         "/newsevents/2026-november.htm": month("november"),
         "/newsevents/2026-december.htm": month("december")}
    p.update(over)
    return p


def getter(p: dict[str, str]):
    def get(path):
        if path not in p:
            raise AssertionError(f"tải trang không mong đợi: {path}")
        v = p[path]
        if isinstance(v, Exception):
            raise v
        return v
    return get


@pytest.fixture(params=["memory", "sqlite"])
def env(request, tmp_path):
    if request.param == "memory":
        return PointInTimeStore(), SourceCheckLog()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'f.db'}")
    repo.create_all()
    return SqlExternalRecordStore(repo.engine), SqlSourceCheckLog(repo.engine)


def utc(*a):
    return datetime(*a, tzinfo=UTC)


# --- trang lịch họp ---

def test_parse_meetings_real_page():
    ms = F.parse_meetings(MEETINGS)
    y2026 = [(m.start.isoformat(), m.end.isoformat(), m.sep) for m in ms if m.end.year == 2026]
    assert y2026 == [
        ("2026-01-27", "2026-01-28", False), ("2026-03-17", "2026-03-18", True),
        ("2026-04-28", "2026-04-29", False), ("2026-06-16", "2026-06-17", True),
        ("2026-07-28", "2026-07-29", False), ("2026-09-15", "2026-09-16", True),
        ("2026-10-27", "2026-10-28", False), ("2026-12-08", "2026-12-09", True),
    ]
    # Họp vắt qua hai tháng; bỏ phiếu bằng văn bản; họp chiến lược (ghi chú riêng).
    by_start = {m.start: m for m in ms}
    assert by_start[date(2024, 4, 30)].end == date(2024, 5, 1)
    assert by_start[date(2023, 1, 31)].end == date(2023, 2, 1)
    assert by_start[date(2025, 8, 22)].note == "notation vote"
    assert by_start[date(2027, 10, 26)].note == "Monetary Policy Strategy Meeting"
    assert len([m for m in ms if m.end.year == 2027]) == 8


@pytest.mark.parametrize("broken", [
    "<html>trang bảo trì</html>",
    MEETINGS.replace(">27-28</div>", ">27–28 TBD</div>", 1),
    MEETINGS.replace("<strong>January</strong>", "<strong>Janvier</strong>", 1),
    MEETINGS.replace(">17-18*</div>", ">17-31*</div>", 1),  # họp 15 ngày
    MEETINGS.replace(">27-28</div>", ">30-31</div>", 1).replace(">27-28</div>", ">30-31</div>"),
])
def test_parse_meetings_rejects_unknown_format(broken):
    with pytest.raises(F.FomcParseError):
        F.parse_meetings(broken)


# --- lịch tháng (giờ công bố) ---

def test_month_calendar_times_and_dst():
    mo, rel = F.parse_month_calendar(month("december"))
    assert mo == date(2026, 12, 1)
    got = {(r.kind, r.at.astimezone(UTC), r.meeting_end) for r in rel}
    assert got == {
        ("FOMC_MINUTES", utc(2026, 12, 30, 19, 0), date(2026, 12, 9)),
        ("FOMC_PRESS_CONFERENCE", utc(2026, 12, 9, 19, 30), None),
        ("FOMC_STATEMENT", utc(2026, 12, 9, 19, 0), date(2026, 12, 9)),
    }
    # 1C-C04: tháng 6 giờ mùa hè (UTC-4): 2:00 p.m. ET = 18:00 UTC.
    _, rel = F.parse_month_calendar(month("june"))
    st = [r for r in rel if r.kind == "FOMC_STATEMENT"][0]
    assert st.at.astimezone(UTC) == utc(2026, 6, 17, 18, 0)
    # Tháng 11: biên bản họp 27-28/10.
    _, rel = F.parse_month_calendar(month("november"))
    assert [(r.kind, r.meeting_end) for r in rel] == [("FOMC_MINUTES", date(2026, 10, 28))]


def test_minutes_in_january_refer_to_previous_december():
    page = month("december").replace("December 2026</h4>", "January 2027</h4>")
    _, rel = F.parse_month_calendar(page.split("FOMC Press Conference")[0])
    minutes = [r for r in rel if r.kind == "FOMC_MINUTES"][0]
    assert minutes.at.date() == date(2027, 1, 30) and minutes.meeting_end == date(2026, 12, 9)


@pytest.mark.parametrize("old,new", [
    ("<p>2:00 p.m.</p>", "<p>2 pm</p>"),
    ("<p>2:00 p.m.</p>", "<p>14:00 p.m.</p>"),
    ("<p>30</p>", "<p>TBD</p>"),
    ("<p>30</p>", "<p>31 32</p>"),
    ("<p>FOMC Minutes</p>", "<p>FOMC Something New</p>"),
    ("Meeting of December 8-9", "Meeting (date to come)"),
])
def test_month_calendar_rejects_unknown_format(old, new):
    with pytest.raises(F.FomcParseError):
        F.parse_month_calendar(month("december").replace(old, new, 1))


def test_month_links_from_index_not_constructed():
    links = F.month_links(INDEX)
    assert "/newsevents/2026-04.htm" in links and "/newsevents/2026-august.htm" in links
    assert F.link_month("/newsevents/2026-04.htm") == date(2026, 4, 1)
    assert F.link_month("/newsevents/2026-august.htm") == date(2026, 8, 1)
    assert F.link_month("/newsevents/2026-foo.htm") is None


# --- ghép sự kiện ---

def events_at(now=NOW, **over):
    ms, rel, cov = F.collect(getter(pages(**over)), now)
    return {e.logical_key: e for e in F.build_events(ms, rel, cov, now)}


def test_build_events_confirmed_and_unconfirmed():
    ev = events_at()
    dec = ev["FOMC_STATEMENT:2026-12-09"]
    assert dec.event_time == utc(2026, 12, 9, 19, 0)
    assert dec.payload["time_confirmed"] is True
    assert dec.payload["sep"] is True and dec.payload["tentative"] is False
    assert ev["FOMC_PRESS_CONFERENCE:2026-12-09"].event_time == utc(2026, 12, 9, 19, 30)
    assert ev["FOMC_MINUTES:2026-11-18"].payload["meeting_end"] == "2026-10-28"
    # 2027 chưa có lịch tháng → KHÔNG đoán 2 giờ chiều: cả ngày, 00:00 giờ miền Đông.
    jan = ev["FOMC_STATEMENT:2027-01-27"]
    assert jan.payload["time_confirmed"] is False and jan.payload["all_day"] is True
    assert jan.event_time == utc(2027, 1, 27, 5, 0)
    assert jan.payload["tentative"] is True  # họp 12/2026 chưa diễn ra
    assert ev["FOMC_STATEMENT:2027-10-27"].payload["note"] == "Monetary Policy Strategy Meeting"
    # Cuộc họp đã qua lâu không đưa vào; họp 28/10 (đã qua > 7 ngày) cũng không.
    assert "FOMC_STATEMENT:2026-10-28" not in ev
    assert all(e.event_time.tzinfo is not None for e in ev.values())


def test_sources_disagree_is_flagged_not_trusted():
    # Lịch tháng ghi tuyên bố ngày 10 (họp 9-10) trong khi trang lịch họp ghi 8-9.
    bad = re.sub(r"(<p>FOMC Meeting</p>.*?December&nbsp;)8 - 9(.*?<p>)9(</p>)",
                 r"\g<1>9 - 10\g<2>10\g<3>", month("december"), count=1, flags=re.S)
    assert bad != month("december")
    ev = events_at(**{"/newsevents/2026-december.htm": bad})
    dec = ev["FOMC_STATEMENT:2026-12-09"]
    assert dec.payload["time_confirmed"] is False and "CALENDAR_SOURCES_DISAGREE" in \
        dec.payload["flags"]
    extra = ev["FOMC_STATEMENT:2026-12-10"]
    assert "CALENDAR_SOURCES_DISAGREE" in extra.payload["flags"]


# --- chạy một lần: ghi, nạp lại, đổi giờ, hủy, lỗi ---

def registry():
    return SourceRegistry([F.fomc_spec()])


def stmt(store, key, at):
    return [r for r in store.as_of(at, source=F.SOURCE, logical_key=key)]


def test_run_once_idempotent(env):
    store, log = env
    c1 = F.run_once(store=store, log=log, get=getter(pages()), now=NOW)
    assert c1.outcome is CheckOutcome.OK and c1.inserted > 5
    n = len(store.as_of(NOW, source=F.SOURCE))
    c2 = F.run_once(store=store, log=log, get=getter(pages()), now=NOW + timedelta(hours=1))
    assert c2.outcome is CheckOutcome.OK and c2.inserted == 0
    assert len(store.as_of(NOW + timedelta(hours=2), source=F.SOURCE)) == n
    assert all(r.revision == 0 for r in store.as_of(NOW + timedelta(hours=2), source=F.SOURCE))


def test_time_change_is_new_revision(env):
    """1C-C03: Fed đổi giờ công bố → revision mới; trước lúc biết vẫn thấy giờ cũ."""
    store, log = env
    F.run_once(store=store, log=log, get=getter(pages()), now=NOW)
    t2 = NOW + timedelta(days=1)
    moved = month("december").replace(
        "<p>2:00 p.m.</p>\n                                </div>\n"
        "                                <div class=\"col-xs-7\">    \n"
        "                                    <p>FOMC Meeting</p>",
        "<p>2:15 p.m.</p>\n                                </div>\n"
        "                                <div class=\"col-xs-7\">    \n"
        "                                    <p>FOMC Meeting</p>")
    assert moved != month("december")
    F.run_once(store=store, log=log, get=getter(pages(**{
        "/newsevents/2026-december.htm": moved})), now=t2)
    key = "FOMC_STATEMENT:2026-12-09"
    assert stmt(store, key, NOW + timedelta(hours=1))[0].event_time == utc(2026, 12, 9, 19, 0)
    after = stmt(store, key, t2)[0]
    assert after.event_time == utc(2026, 12, 9, 19, 15) and after.revision == 1


def _drop_meeting(page: str, label: str, dates: str) -> str:
    i = page.index(f"<strong>{label}</strong>", page.index("2027 FOMC Meetings"))
    j = page.index(f">{dates}</div>", i)
    k = page.index("fomc-meeting__month", j)
    row_start = page.rindex('<div class="', 0, page.rindex("fomc-meeting", 0, i))
    return page[:row_start] + page[page.rindex('<div class="', 0, k):]


def test_cancelled_meeting_marked_removed(env):
    """1C-C02: cuộc họp tương lai biến mất khỏi trang → revision REMOVED, không xóa."""
    store, log = env
    F.run_once(store=store, log=log, get=getter(pages()), now=NOW)
    t2 = NOW + timedelta(days=1)
    page = _drop_meeting(MEETINGS, "March", "16-17")
    assert len(F.parse_meetings(page)) == len(F.parse_meetings(MEETINGS)) - 1
    c = F.run_once(store=store, log=log, get=getter(pages(**{F.MEETINGS_PATH: page})), now=t2)
    assert c.outcome is CheckOutcome.OK
    r = stmt(store, "FOMC_STATEMENT:2027-03-17", t2)[0]
    assert r.payload["status"] == "REMOVED" and r.revision == 1
    assert stmt(store, "FOMC_STATEMENT:2027-03-17", NOW)[0].payload["status"] == "SCHEDULED"


def test_many_removals_treated_as_broken_page(env):
    store, log = env
    F.run_once(store=store, log=log, get=getter(pages()), now=NOW)
    n = len(store.as_of(NOW, source=F.SOURCE))
    page = MEETINGS
    for label, d in (("March", "16-17"), ("April", "27-28"), ("June", "8-9")):
        page = _drop_meeting(page, label, d)
    t2 = NOW + timedelta(days=1)
    c = F.run_once(store=store, log=log, get=getter(pages(**{F.MEETINGS_PATH: page})), now=t2)
    assert (c.outcome, c.error_code) == (CheckOutcome.INVALID, "TOO_MANY_REMOVALS")
    assert len(store.as_of(t2, source=F.SOURCE)) == n
    assert all(r.payload["status"] == "SCHEDULED" for r in store.as_of(t2, source=F.SOURCE))


@pytest.mark.parametrize("over,outcome,code", [
    ({F.MEETINGS_PATH: F.FetchError("HTTP_503")}, CheckOutcome.ERROR, "HTTP_503"),
    ({"/newsevents/2026-december.htm": F.FetchError("TIMEOUT")}, CheckOutcome.ERROR, "TIMEOUT"),
    ({F.MEETINGS_PATH: "<html>bảo trì</html>"}, CheckOutcome.INVALID, "PARSE_ERROR"),
    ({F.CALENDAR_INDEX_PATH: "<html></html>"}, CheckOutcome.INVALID, "PARSE_ERROR"),
    # Trang tháng 12 bị trả nhầm nội dung tháng 6.
    ({"/newsevents/2026-december.htm": month("june")}, CheckOutcome.INVALID, "PARSE_ERROR"),
])
def test_failures_write_nothing(env, over, outcome, code):
    store, log = env
    c = F.run_once(store=store, log=log, get=getter(pages(**over)), now=NOW)
    assert (c.outcome, c.error_code) == (outcome, code)
    assert store.as_of(NOW + timedelta(days=1), source=F.SOURCE) == []


def test_status_after_failures(env):
    """ING-30: lỗi mạng sau lần OK → HEALTHY trong 26 giờ rồi STALE; trang hỏng → INVALID."""
    store, log = env
    spec = F.fomc_spec()
    F.run_once(store=store, log=log, get=getter(pages()), now=NOW)
    t = NOW + timedelta(hours=6)
    F.run_once(store=store, log=log, get=getter(pages(**{
        F.MEETINGS_PATH: F.FetchError("HTTP_503")})), now=t)

    def st(at):
        return evaluate(F.SOURCE, spec, log.summary(F.SOURCE, at), at, None).status
    assert st(t) is SourceStatus.HEALTHY
    assert st(NOW + timedelta(hours=26, seconds=1)) is SourceStatus.STALE
    t3 = NOW + timedelta(hours=7)
    F.run_once(store=store, log=log, get=getter(pages(**{F.MEETINGS_PATH: "<p>x</p>"})), now=t3)
    assert st(t3) is SourceStatus.INVALID


def test_requires_verified_terms(env):
    store, log = env
    blocked = {"fed": SourceTerms("fed", TermsStatus.NEEDS_REVIEW, date(2026, 11, 13), "#")}
    with pytest.raises(ValueError, match="ING-32"):
        SourceRegistry([F.fomc_spec()], terms=blocked)
    assert registry().get(F.SOURCE) is not None


# --- tải qua HTTP ---

def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_http_getter_ok_and_errors():
    get = F.http_getter(client(lambda req: httpx.Response(200, text="ok")))
    assert get(F.MEETINGS_PATH) == "ok"
    with pytest.raises(F.FetchError) as e:
        F.http_getter(client(lambda req: httpx.Response(503)))(F.MEETINGS_PATH)
    assert e.value.code == "HTTP_503"
    with pytest.raises(F.FetchError) as e:
        F.http_getter(client(lambda req: httpx.Response(200, content=b"x" * (6 * 1024 * 1024))))(
            F.MEETINGS_PATH)
    assert e.value.code == "RESPONSE_TOO_LARGE"

    def timeout(req):
        raise httpx.ReadTimeout("chậm", request=req)
    with pytest.raises(F.FetchError) as e:
        F.http_getter(client(timeout))(F.MEETINGS_PATH)
    assert e.value.code == "TIMEOUT"

    def redirect(req):
        if req.url.host == "www.federalreserve.gov":
            return httpx.Response(302, headers={"location": "https://evil.example/x"})
        return httpx.Response(200, text="giả")
    with pytest.raises(F.FetchError) as e:
        F.http_getter(client(redirect))(F.MEETINGS_PATH)
    assert e.value.code == "UNEXPECTED_REDIRECT"
    with pytest.raises(F.FetchError):
        get("https://evil.example/x")


def test_cli_fomc_dry_run(monkeypatch, capsys):
    from gold_trading.ingestion import cli

    monkeypatch.setattr(cli, "utcnow", lambda: NOW)
    monkeypatch.setattr(F, "http_getter", lambda client: getter(pages()))
    assert cli.main(["fomc", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "2026-12-09 19:00 UTC  FOMC_STATEMENT" in out
    assert "2027-01-27 (chưa có giờ)  FOMC_STATEMENT  [dự kiến]" in out
    monkeypatch.setattr(F, "http_getter", lambda client: getter(
        pages(**{F.MEETINGS_PATH: F.FetchError("HTTP_503")})))
    assert cli.main(["fomc", "--dry-run"]) == 1
