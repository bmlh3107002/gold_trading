"""Bước 8f — DOL: lịch theo quy tắc + số trợ cấp thất nghiệp tuần (ING-09, ING-17, ING-19).

Bản tin PDF thật ``tests/fixtures/dol/ui-data-2026-11-12.pdf`` (www.dol.gov/ui/data.pdf, public
domain, U.S. Department of Labor). Case: 1C-C02/C03 (tuần lễ), 1C-C04 (DST), 1C-C08 (sửa số),
PDF hỏng / số không khớp / giờ lạ, lỗi mạng, bản tin cũ.
"""

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from gold_trading.common.enums import SourceStatus
from gold_trading.ingestion import cli
from gold_trading.ingestion.point_in_time import PointInTimeStore
from gold_trading.ingestion.source_status import (
    CheckOutcome,
    SourceCheckLog,
    SourceRegistry,
    evaluate,
)
from gold_trading.ingestion.sources import dol as D
from gold_trading.market.federal_holidays import federal_holidays, holidays_between
from gold_trading.market.holidays import US_HOLIDAYS
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.source_checks import SqlSourceCheckLog

FIX = Path(__file__).parent / "fixtures" / "dol"
PDF = (FIX / "ui-data-2026-11-12.pdf").read_bytes()
TEXT = D.pdf_text(PDF)
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def utc(*a):
    return datetime(*a, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def env(request, tmp_path):
    if request.param == "memory":
        return PointInTimeStore(), SourceCheckLog()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'd.db'}")
    repo.create_all()
    return SqlExternalRecordStore(repo.engine), SqlSourceCheckLog(repo.engine)


# ------------------------------------------------------------------ ngày lễ liên bang

def test_federal_holidays_2026_2027():
    # Theo 5 U.S.C. 6103 + nghỉ bù (thứ Bảy → thứ Sáu, Chủ nhật → thứ Hai).
    assert list(federal_holidays(2026)) == [
        date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 5, 25),
        date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7), date(2026, 10, 12),
        date(2026, 11, 11), date(2026, 11, 26), date(2026, 12, 25)]
    h27 = federal_holidays(2027)
    assert date(2027, 11, 11) in h27 and date(2027, 11, 11).weekday() == 3  # Veterans thứ Năm
    assert date(2027, 12, 24) in h27 and date(2027, 12, 31) in h27  # 25/12 + 01/01/2028 thứ Bảy
    assert date(2022, 1, 1) not in federal_holidays(2022)  # nghỉ bù sang 31/12/2021
    assert date(2021, 12, 31) in federal_holidays(2021)
    assert date(2021, 1, 20) in federal_holidays(2021)      # Nhậm chức
    assert date(2025, 1, 20) in federal_holidays(2025)      # trùng MLK 2025
    assert date(2020, 6, 19) not in federal_holidays(2020)  # Juneteenth từ 2021


def test_federal_holidays_cross_check_market_table():
    # Mọi ngày nghỉ trọn/ngừng sớm của thị trường do ngày lễ liên bang phải có trong bảng liên bang.
    market_only = ("Good Friday", "Day after Thanksgiving", "Christmas Eve")
    for y in (2024, 2025, 2026, 2027):
        fed = federal_holidays(y)
        for h in US_HOLIDAYS.holidays:
            if h.day.year == y and not any(n in h.name for n in market_only):
                assert h.day in fed, (h.day, h.name)


def test_federal_holiday_range():
    assert list(holidays_between(date(2026, 12, 28), date(2027, 1, 1))) == [date(2027, 1, 1)]
    with pytest.raises(ValueError):
        federal_holidays(1800)


# ------------------------------------------------------------------ lịch theo quy tắc

def by_key(now=NOW):
    return {e.logical_key: e for e in D.build_schedule(now)}


def test_rule_schedule_normal_and_holiday_weeks():
    ev = by_key()
    n = ev["CLAIMS:2026-11-19"]
    assert n.event_time == utc(2026, 11, 19, 13, 30)  # 8:30 ET mùa đông
    assert n.payload["basis"] == "RULE" and not n.payload["time_confirmed"]
    assert not n.payload["all_day"] and n.payload["week_ending"] == "2026-11-14"
    # Lễ Tạ ơn (thứ Năm 26/11): không đoán ngày mới, chặn cả ngày thứ Tư–Sáu.
    for k, d in (("CLAIMS:2026-11-26:WED", 25), ("CLAIMS:2026-11-26", 26),
                 ("CLAIMS:2026-11-26:FRI", 27)):
        e = ev[k]
        assert e.payload["all_day"] and e.payload["flags"] == ["HOLIDAY_WEEK"]
        assert e.event_time == utc(2026, 11, d, 5, 0)
        assert e.payload["holidays"] == ["2026-11-26 Thanksgiving Day"]
    # Tuần có ngày lễ thứ Hai cũng chặn rộng (hướng an toàn).
    ev2 = by_key(utc(2027, 1, 10))
    assert ev2["CLAIMS:2027-01-21"].payload["holidays"] == [
        "2027-01-18 Birthday of Martin Luther King, Jr."]


def test_rule_schedule_dst():
    # 1C-C04: tháng 6 giờ mùa hè → 8:30 ET = 12:30 UTC.
    ev = by_key(utc(2027, 6, 1))
    assert ev["CLAIMS:2027-06-10"].event_time == utc(2027, 6, 10, 12, 30)
    # Mỹ đổi giờ Chủ nhật 14/03/2027 (Chủ nhật thứ hai của tháng 3): 11/3 còn giờ đông, 18/3 hè.
    ev = by_key(utc(2027, 3, 1))
    assert ev["CLAIMS:2027-03-11"].event_time == utc(2027, 3, 11, 13, 30)
    assert ev["CLAIMS:2027-03-18"].event_time == utc(2027, 3, 18, 12, 30)


def test_rule_schedule_horizon_and_keep():
    ev = D.build_schedule(NOW)
    assert max(e.event_time for e in ev) <= NOW + timedelta(weeks=D.HORIZON_WEEKS, days=2)
    assert min(e.event_time for e in ev) >= NOW - timedelta(days=8)


def test_run_schedule_idempotent(env):
    store, log = env
    c = D.run_schedule_once(store=store, log=log, now=NOW)
    assert c.outcome is CheckOutcome.OK and c.inserted > 0
    assert D.run_schedule_once(store=store, log=log, now=NOW + timedelta(hours=1)).inserted == 0


# ------------------------------------------------------------------ bản tin PDF

def test_parse_real_release():
    rel = D.parse_release(TEXT)
    assert rel.released_at == datetime(2026, 11, 12, 8, 30, tzinfo=D.ET)
    v = {k: x[1] for k, x in rel.values.items()}
    # Số trong bản tin 12/11/2026 (kiểm tay: 191.000 + 9.000 = 200.000; 1.717.000 − 20.000).
    assert v == {"ICSA:2026-11-07": 200000, "ICSA:2026-10-31": 191000,
                 "IC4WSA:2026-11-07": 195250, "IC4WSA:2026-10-31": 195250,
                 "CCSA:2026-10-31": 1697000, "CCSA:2026-10-24": 1717000}


def mutate(old, new, count=1):
    t = re.sub(r"\s+", " ", TEXT)
    assert old in t, old
    return t.replace(old, new, count)


@pytest.mark.parametrize("bad", [
    mutate("initial claims was 200,000", "initial claims was 201,000"),        # ± không khớp
    mutate("revised up by 2,000 from 189,000", "revised up by 3,000 from 189,000"),
    mutate("an increase of 9,000", "a decrease of 9,000"),
    mutate("Thursday, November 12, 2026", "Friday, November 12, 2026"),       # thứ sai
    mutate("Thursday, November 12, 2026", "Thursday, November 31, 2026"),
    mutate("EMBARGOED UNTIL", "EMBARGO"),
    mutate("In the week ending November 7", "In the week ending November 8"),  # không phải thứ Bảy
    mutate("In the week ending November 7", "For the week ending November 7"),
    mutate("insured unemployment during the week ending October 31",
           "insured unemployment during the week ending October 24"),
    mutate("initial claims was 200,000", "initial claims was 200.000"),
    "",
])
def test_bad_release_rejected(bad):
    with pytest.raises(D.DolParseError):
        D.parse_release(bad)


def test_unrevised_and_unchanged_forms():
    t = mutate("The previous week's level was revised up by 2,000 from 189,000 to 191,000.",
               "The previous week's level was unrevised at 191,000.")
    assert D.parse_release(t).values["ICSA:2026-10-31"][1] == 191000


def test_not_a_pdf():
    with pytest.raises(D.DolParseError):
        D.pdf_text(b"%PDF-1.7 broken")


def run_vals(store, log, now=NOW, pdf=PDF):
    def get(url):
        assert url == D.PDF_URL
        if isinstance(pdf, Exception):
            raise pdf
        return pdf
    return D.run_values_once(store=store, log=log, get=get, now=now)


def test_values_on_schedule_with_latency(env):
    store, log = env
    D.run_schedule_once(store=store, log=log, now=utc(2026, 11, 10))
    c = run_vals(store, log, now=utc(2026, 11, 12, 13, 31))
    assert c.outcome is CheckOutcome.OK and c.inserted == 6
    r = store.as_of(utc(2026, 11, 12, 13, 31), source=D.VALUES_SOURCE,
                    logical_key="ICSA:2026-11-07")[0]
    assert r.payload["value"] == "200000" and r.payload["flags"] == []  # tuần Veterans: khớp
    assert r.payload["latency_seconds"] == 60
    assert r.available_at == utc(2026, 11, 12, 13, 30)
    assert r.event_time == utc(2026, 11, 8, 5, 0)
    # Trước giờ phát hành: point-in-time không thấy.
    assert store.as_of(utc(2026, 11, 12, 13, 29), source=D.VALUES_SOURCE) == []


def test_off_schedule_flagged(env):
    # Chưa có lịch (hoặc giờ phát hành lệch lịch) → cờ cảnh báo.
    store, log = env
    run_vals(store, log)
    r = store.as_of(NOW, source=D.VALUES_SOURCE, logical_key="ICSA:2026-11-07")[0]
    assert r.payload["flags"] == ["RELEASE_OFF_SCHEDULE"]


def test_revision_next_week_and_old_release_ignored(env):
    # Tuần sau DOL sửa số tuần 7/11 → revision 1; tải lại bản tin cũ không viết lại.
    store, log = env
    run_vals(store, log)
    nxt = mutate("8:30 A.M. (Eastern) Thursday, November 12, 2026",
                 "8:30 A.M. (Eastern) Thursday, November 19, 2026")
    nxt = nxt.replace("week ending November 7, the advance figure for seasonally adjusted initial "
                      "claims was 200,000, an increase of 9,000 from the previous week's revised "
                      "level. The previous week's level was revised up by 2,000 from 189,000 to "
                      "191,000.",
                      "week ending November 14, the advance figure for seasonally adjusted "
                      "initial claims was 205,000, an increase of 3,000 from the previous week's "
                      "revised level. The previous week's level was revised up by 2,000 from "
                      "200,000 to 202,000.")
    nxt = nxt.replace("week ending October 31 was 1,697,000", "week ending November 7 was "
                      "1,697,000")
    rel = D.parse_release(nxt)
    at = utc(2026, 11, 19, 13, 35)
    D.sync_values(store, rel, at)
    r = store.as_of(at, source=D.VALUES_SOURCE, logical_key="ICSA:2026-11-07")[0]
    assert (r.revision, r.payload["value"]) == (1, "202000")
    old = store.as_of(at - timedelta(minutes=10), source=D.VALUES_SOURCE,
                      logical_key="ICSA:2026-11-07")[0]
    assert old.payload["value"] == "200000"
    # Bản tin cũ (12/11) tải lại sau → không ghi đè số đã sửa.
    counts = D.sync_values(store, D.parse_release(TEXT), at + timedelta(hours=1))
    assert counts.inserted == 0
    r = store.as_of(at + timedelta(hours=1), source=D.VALUES_SOURCE,
                    logical_key="ICSA:2026-11-07")[0]
    assert r.payload["value"] == "202000"


def test_future_dated_release_rejected(env):
    store, log = env
    c = run_vals(store, log, now=utc(2026, 11, 12, 13, 0))  # trước 8:30 ET
    assert (c.outcome, c.error_code) == (CheckOutcome.INVALID, "PARSE_ERROR")


@pytest.mark.parametrize("pdf,outcome,code", [
    (D.FetchError("HTTP_503"), CheckOutcome.ERROR, "HTTP_503"),
    (D.FetchError("FORBIDDEN"), CheckOutcome.ERROR, "FORBIDDEN"),
    (b"%PDF-1.4 rong", CheckOutcome.INVALID, "PARSE_ERROR"),
])
def test_value_errors(env, pdf, outcome, code):
    store, log = env
    c = run_vals(store, log, pdf=pdf)
    assert (c.outcome, c.error_code) == (outcome, code)
    assert store.as_of(NOW, source=D.VALUES_SOURCE) == []


def test_stale_and_due(env):
    store, log = env
    run_vals(store, log)
    at = utc(2026, 11, 25, 12, 0)  # tuần mới nhất 7/11 → quá 16 ngày
    run_vals(store, log, now=at)
    h = evaluate(D.VALUES_SOURCE, D.values_spec(), log.summary(D.VALUES_SOURCE, at), at,
                 store.latest_event_time(D.VALUES_SOURCE, at))
    assert (h.status, h.reason) == (SourceStatus.STALE, "DATA_TTL_EXPIRED")
    D.run_schedule_once(store=store, log=log, now=NOW)
    rel = utc(2026, 11, 19, 13, 30)
    assert D.values_due(rel + timedelta(minutes=5), store, rel - timedelta(days=1)) == \
        "RELEASE_WINDOW"
    assert D.values_due(rel + timedelta(minutes=95), store, rel - timedelta(days=1)) is None
    # Tuần lễ: cả ngày thứ Tư–Sáu trong giờ hành chính.
    assert D.values_due(utc(2026, 11, 25, 14, 0), store, rel) == "RELEASE_DAY"
    assert D.values_due(utc(2026, 11, 25, 3, 0), store, rel) is None


def test_terms_verified():
    SourceRegistry([D.schedule_spec(), D.values_spec()])


# ------------------------------------------------------------------ HTTP + CLI

def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("resp,code", [
    (httpx.Response(403), "FORBIDDEN"),
    (httpx.Response(200, content=b"<html>"), "NOT_PDF"),
    (httpx.Response(302, headers={"location": "https://evil.example/x.pdf"}),
     "UNEXPECTED_REDIRECT"),
    (httpx.Response(200, content=b"%PDF" + b"x" * D.MAX_BYTES), "RESPONSE_TOO_LARGE"),
])
def test_http_errors(resp, code):
    def h(req):
        if req.url.host == "evil.example":
            return httpx.Response(200, content=b"%PDF")
        return resp
    with pytest.raises(D.FetchError) as e:
        D.http_getter(_client(h))(D.PDF_URL)
    assert e.value.code == code
    with pytest.raises(D.FetchError, match="BAD_URL"):
        D.http_getter(_client(h))("https://dol.gov.evil.example/ui/data.pdf")


def test_cli_dry_run(capsys):
    fac = lambda: _client(lambda req: httpx.Response(200, content=PDF))  # noqa: E731
    rc = cli._dol(True, env={}, client_factory=fac)
    out = capsys.readouterr().out
    assert rc == 0 and "ICSA tuần đến 2026-11-07: 200000" in out
    assert "U.S. Department of Labor" in out
