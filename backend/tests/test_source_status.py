"""ING-30: trạng thái nguồn ngoài HEALTHY/STALE/MISSING/INVALID, TTL riêng từng nguồn.

Chạy cho cả nhật ký trong bộ nhớ và SQLite (cùng quy tắc). Case nền: 1C-C05, 1D-C05, 1E-C03,
1E-C05, 1F-C02 (phần trạng thái nguồn).
"""

import random
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from gold_trading.common.enums import SourceStatus
from gold_trading.ingestion.point_in_time import AppendCounts, PointInTimeStore
from gold_trading.ingestion.source_status import (
    CheckOutcome,
    SourceCheck,
    SourceCheckLog,
    SourceRegistry,
    SourceSpec,
    evaluate,
    source_health,
    summarize,
)
from gold_trading.storage.external_records import SqlExternalRecordStore
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.source_checks import SqlSourceCheckLog
from tests.factories import record

H, S, M, INV = (SourceStatus.HEALTHY, SourceStatus.STALE, SourceStatus.MISSING,
              SourceStatus.INVALID)
OK, ERR, BAD = CheckOutcome.OK, CheckOutcome.ERROR, CheckOutcome.INVALID
T0 = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
h = lambda n: timedelta(hours=n)  # noqa: E731

RSS = SourceSpec("fed_rss", "news", fetch_ttl=h(1))
COT = SourceSpec("cftc_cot", "positioning", fetch_ttl=h(26), data_ttl=timedelta(days=11))
CAL = SourceSpec("bls_calendar", "calendar", fetch_ttl=h(26))


@pytest.fixture(params=["memory", "sqlite"])
def env(request, tmp_path):
    """(nhật ký lần kiểm, store bản ghi) cùng một loại."""
    if request.param == "memory":
        return SourceCheckLog(), PointInTimeStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'x.db'}")
    repo.create_all()
    return SqlSourceCheckLog(repo.engine), SqlExternalRecordStore(repo.engine)


def chk(t, outcome=OK, code=None, source="fed_rss", **kw):
    return SourceCheck(source, t, outcome, code, **kw)


def status(env, spec, as_of, source=None):
    log, recs = env
    name = source or spec.name
    return evaluate(name, spec, log.summary(name, as_of), as_of,
                    recs.latest_event_time(name, as_of))


# --- cấu hình ---

@pytest.mark.parametrize("kw", [
    dict(name="Fed RSS"), dict(name=""), dict(name="a" * 65), dict(kind="price"),
    dict(fetch_ttl=timedelta(0)), dict(fetch_ttl=-h(1)), dict(fetch_ttl=timedelta(days=401)),
    dict(data_ttl=timedelta(0)),
])
def test_spec_rejects_bad_config(kw):
    base = dict(name="fred", kind="macro", fetch_ttl=h(1))
    with pytest.raises(ValueError):
        SourceSpec(**(base | kw))


def test_calendar_cannot_have_data_ttl():
    with pytest.raises(ValueError, match="calendar"):
        SourceSpec("bls_calendar", "calendar", fetch_ttl=h(1), data_ttl=h(1))


def test_registry_rejects_duplicate_names():
    with pytest.raises(ValueError, match="trùng"):
        SourceRegistry([RSS, SourceSpec("fed_rss", "news", fetch_ttl=h(2))])


# --- lần kiểm ---

@pytest.mark.parametrize("args", [
    (datetime(2026, 1, 5, 14, 0), OK, None),  # giờ không múi giờ
    (T0, OK, "TIMEOUT"),                       # OK không có mã lỗi
    (T0, ERR, None),                           # lỗi phải có mã
    (T0, ERR, "timeout"),
    # Thông điệp lỗi gốc có thể chứa URL kèm khóa API → chỉ nhận mã ngắn (ING-31 nền).
    (T0, ERR, "HTTP 401 https://api.stlouisfed.org/?api_key=abc123"),
    (T0, ERR, "X" * 65),
])
def test_check_rejects_bad_values(args):
    with pytest.raises(ValueError):
        SourceCheck("fred", *args)


def test_check_rejects_negative_counts_and_bad_source():
    with pytest.raises(ValueError):
        SourceCheck("fred", T0, OK, inserted=-1)
    with pytest.raises(ValueError):
        SourceCheck("FRED\x00", T0, OK)


def test_check_normalizes_to_utc():
    et = datetime(2026, 1, 5, 9, 0, tzinfo=ZoneInfo("America/New_York"))
    assert SourceCheck("fred", et, OK).checked_at == T0
    assert SourceCheck("fred", et, OK).checked_at.tzinfo is UTC


def test_from_counts():
    assert SourceCheck.from_counts("x", T0, AppendCounts()).outcome is OK  # không có gì mới
    c = SourceCheck.from_counts("x", T0, AppendCounts(invalid=3))
    assert (c.outcome, c.error_code, c.invalid) == (BAD, "ALL_RECORDS_REJECTED", 3)
    assert SourceCheck.from_counts("x", T0, AppendCounts(conflict=1)).outcome is BAD
    c = SourceCheck.from_counts("x", T0, AppendCounts(inserted=2, invalid=1, conflict=1))
    assert c.outcome is OK and (c.inserted, c.invalid, c.conflict) == (2, 1, 1)
    assert SourceCheck.from_counts("x", T0, AppendCounts(duplicate=5, invalid=1)).outcome is OK


# --- trạng thái ---

def test_unknown_and_disabled_sources_are_missing(env):
    log, recs = env
    log.record(chk(T0, source="ghost"))
    assert evaluate("ghost", None, log.summary("ghost", T0), T0, None).reason == "UNKNOWN_SOURCE"
    off = SourceSpec("fed_rss", "news", fetch_ttl=h(1), enabled=False)
    log.record(chk(T0))
    r = status(env, off, T0)
    assert (r.status, r.reason) == (M, "DISABLED")


def test_never_checked_is_missing(env):
    r = status(env, RSS, T0)
    assert (r.status, r.reason, r.last_check_at, r.last_ok_at) == (M, "NEVER_CHECKED", None, None)


def test_only_errors_is_missing(env):
    log, _ = env
    log.record(chk(T0, ERR, "TIMEOUT"))
    log.record(chk(T0 + h(0.5), ERR, "HTTP_503"))
    r = status(env, RSS, T0 + h(0.5))
    assert (r.status, r.reason, r.last_error_code, r.failures_since_ok) == \
        (M, "NEVER_OK", "HTTP_503", 2)


def test_fetch_ttl_boundary(env):
    log, _ = env
    log.record(chk(T0))
    assert status(env, RSS, T0).status is H
    assert status(env, RSS, T0 + h(1)).status is H  # đúng bằng TTL vẫn còn hạn
    r = status(env, RSS, T0 + h(1) + timedelta(seconds=1))
    assert (r.status, r.reason) == (S, "FETCH_TTL_EXPIRED")


def test_ttl_is_per_source(env):
    log, _ = env
    other = SourceSpec("treasury_rss", "news", fetch_ttl=h(6))
    log.record(chk(T0))
    log.record(chk(T0, source="treasury_rss"))
    at = T0 + h(3)
    assert status(env, RSS, at).status is S
    assert status(env, other, at).status is H


def test_transient_error_within_ttl_stays_healthy_then_stale(env):
    """1D-C05: nguồn chết / bị giới hạn tần suất → còn trong TTL vẫn HEALTHY (có cờ), quá TTL
    → STALE (không bao giờ coi số cũ là mới)."""
    log, _ = env
    log.record(chk(T0))
    log.record(chk(T0 + h(0.25), ERR, "RATE_LIMITED"))
    log.record(chk(T0 + h(0.5), ERR, "TIMEOUT"))
    r = status(env, RSS, T0 + h(0.5))
    assert r.status is H and "RECENT_FAILURES" in r.flags and r.failures_since_ok == 2
    assert r.last_error_code == "TIMEOUT"
    assert status(env, RSS, T0 + h(1.01)).status is S
    log.record(chk(T0 + h(2)))  # phục hồi
    r = status(env, RSS, T0 + h(2))
    assert r.status is H and r.failures_since_ok == 0 and "RECENT_FAILURES" not in r.flags


@pytest.mark.parametrize("code", ["AUTH_FAILED", "KEY_MISSING", "SOURCE_DISCONTINUED",
                                  "FORBIDDEN"])
def test_fatal_error_is_missing_immediately(env, code):
    """1E-C05 (khóa sai/hết hạn), 1E-C03 (series ngừng): MISSING ngay, không chờ hết TTL."""
    log, _ = env
    log.record(chk(T0))
    log.record(chk(T0 + h(0.1), ERR, code))
    r = status(env, RSS, T0 + h(0.1))
    assert (r.status, r.reason) == (M, code)
    # Lỗi tạm sau đó không che lỗi "chết" (khóa vẫn sai).
    log.record(chk(T0 + h(0.2), ERR, "TIMEOUT"))
    assert status(env, RSS, T0 + h(0.2)).reason == code
    # Trước lúc lỗi: quá khứ không bị viết lại.
    assert status(env, RSS, T0 + h(0.05)).status is H
    log.record(chk(T0 + h(0.3)))  # người dùng sửa khóa
    assert status(env, RSS, T0 + h(0.3)).status is H


def test_invalid_after_ok_is_invalid_until_clean_check(env):
    log, _ = env
    log.record(chk(T0))
    log.record(chk(T0 + h(0.1), BAD, "PARSE_ERROR"))
    log.record(chk(T0 + h(0.2), ERR, "TIMEOUT"))  # lỗi mạng sau đó không xóa INVALID
    r = status(env, RSS, T0 + h(0.2))
    assert (r.status, r.reason) == (INV, "PARSE_ERROR")
    log.record(chk(T0 + h(0.3)))
    assert status(env, RSS, T0 + h(0.3)).status is H


def test_fatal_takes_precedence_over_invalid(env):
    log, _ = env
    log.record(chk(T0))
    log.record(chk(T0 + h(0.1), ERR, "AUTH_FAILED"))
    log.record(chk(T0 + h(0.2), BAD, "SCHEMA_CHANGED"))
    assert status(env, RSS, T0 + h(0.2)).status is M


def test_partial_invalid_flags(env):
    log, _ = env
    log.record(chk(T0, inserted=3, invalid=1, conflict=2))
    r = status(env, RSS, T0)
    assert r.status is H and r.flags == {"PARTIAL_INVALID", "CONFLICT_SEEN"}


def test_future_checks_ignored_point_in_time(env):
    log, _ = env
    log.record(chk(T0))
    log.record(chk(T0 + h(5), ERR, "AUTH_FAILED"))  # ghi trước, xảy ra sau as_of
    r = status(env, RSS, T0 + h(0.5))
    assert r.status is H and r.last_check_at == T0 and r.last_error_code is None


def test_same_timestamp_uses_write_order(env):
    log, _ = env
    log.record(chk(T0))
    log.record(chk(T0, ERR, "AUTH_FAILED"))
    assert status(env, RSS, T0).status is M
    log2 = SourceCheckLog()
    log2.record(chk(T0, ERR, "AUTH_FAILED"))
    log2.record(chk(T0))
    assert evaluate("fed_rss", RSS, log2.summary("fed_rss", T0), T0, None).status is H


def test_dst_ttl_uses_real_elapsed_time(env):
    """TTL tính theo thời gian thật (UTC), không theo giờ đồng hồ treo tường. Mỹ đổi giờ
    08/03/2026: 12:00 ET thứ Bảy → 12:00 ET Chủ nhật chỉ là 23 giờ."""
    log, _ = env
    et = ZoneInfo("America/New_York")
    spec = SourceSpec("fed_rss", "news", fetch_ttl=h(23.5))
    log.record(chk(datetime(2026, 3, 7, 12, 0, tzinfo=et)))
    assert status(env, spec, datetime(2026, 3, 8, 12, 0, tzinfo=et)).status is H
    assert status(env, spec, datetime(2026, 3, 8, 12, 31, tzinfo=et)).status is S


def test_naive_as_of_rejected(env):
    log, _ = env
    with pytest.raises(ValueError):
        log.summary("fed_rss", datetime(2026, 1, 5))
    with pytest.raises(ValueError):
        evaluate("fed_rss", RSS, summarize([], T0), datetime(2026, 1, 5), None)


# --- data_ttl ---

def cot_record(rid, report_day, published, ingested=None, **kw):
    return record(rid, report_day, ingested or published, kind="positioning",
                  source="cftc_cot", available_at=published, logical_key=rid, **kw)


def test_data_ttl_no_data_is_missing(env):
    log, _ = env
    log.record(chk(T0, source="cftc_cot"))
    r = status(env, COT, T0)
    assert (r.status, r.reason) == (M, "NO_DATA")


def test_data_ttl_publication_delayed(env):
    """1F-C02: nguồn vẫn trả lời (OK hằng ngày) nhưng không có báo cáo mới (chính phủ đóng
    cửa) → STALE khi dữ kiện mới nhất cũ quá data_ttl, không coi số cũ là mới."""
    log, recs = env
    tue = datetime(2026, 1, 6, 0, 0, tzinfo=UTC)
    fri = datetime(2026, 1, 9, 20, 30, tzinfo=UTC)
    recs.append(cot_record("cot-0106", tue, fri))
    for d in range(0, 20):
        log.record(chk(fri + timedelta(days=d), source="cftc_cot"))
    r = status(env, COT, fri + timedelta(days=4))
    assert r.status is H and r.latest_event_at == tue
    r = status(env, COT, tue + timedelta(days=11, seconds=1))
    assert (r.status, r.reason) == (S, "DATA_TTL_EXPIRED")


def test_data_ttl_backfill_does_not_look_fresh(env):
    """Nạp bù hôm nay một báo cáo cũ: known_at = hôm nay nhưng event_time cũ → vẫn STALE."""
    log, recs = env
    now = datetime(2026, 2, 20, 12, 0, tzinfo=UTC)
    recs.append(cot_record("cot-old", datetime(2026, 1, 6, tzinfo=UTC),
                           datetime(2026, 1, 9, 20, 30, tzinfo=UTC), ingested=now))
    log.record(chk(now, source="cftc_cot"))
    assert status(env, COT, now).reason == "DATA_TTL_EXPIRED"


def test_data_ttl_ignores_unknown_and_future_records(env):
    log, recs = env
    tue = datetime(2026, 1, 6, tzinfo=UTC)
    fri = datetime(2026, 1, 9, 20, 30, tzinfo=UTC)
    # Đã nạp nhưng nguồn chưa công bố (available_at sau as_of) → chưa được tính.
    recs.append(cot_record("cot-0106", tue, fri, ingested=tue + h(1)))
    log.record(chk(tue + h(1), source="cftc_cot"))
    r = status(env, COT, tue + h(2))
    assert (r.status, r.reason, r.latest_event_at) == (M, "NO_DATA", None)
    # Lịch: sự kiện tương lai không phải "dữ liệu mới nhất".
    recs.append(record("cal-1", T0 + timedelta(days=30), T0, kind="calendar",
                       source="bls_calendar", logical_key="CPI:2026-02"))
    _, recs_ = env
    assert recs_.latest_event_time("bls_calendar", T0) is None


def test_source_health_lists_registry(env):
    log, recs = env
    reg = SourceRegistry([RSS, COT, CAL])
    log.record(chk(T0))
    out = {r.source: r for r in source_health(reg, log, recs, T0)}
    assert set(out) == {"fed_rss", "cftc_cot", "bls_calendar"}
    assert out["fed_rss"].status is H
    assert out["cftc_cot"].reason == "NEVER_CHECKED"
    assert source_health(reg, log, recs, T0, sources=["nope"])[0].reason == "UNKNOWN_SOURCE"


# --- tính lại quá khứ: bộ nhớ = SQL, thứ tự ghi không đổi kết quả ---

def _random_checks(seed):
    rnd = random.Random(seed)
    codes = ["TIMEOUT", "HTTP_503", "RATE_LIMITED", "AUTH_FAILED", "PARSE_ERROR"]
    out, t = [], T0
    for _ in range(80):
        t += timedelta(minutes=rnd.choice([0, 1, 7, 30, 90]))
        o = rnd.choice([OK, OK, OK, ERR, BAD])
        code = None if o is OK else rnd.choice(codes)
        out.append(chk(t, o, code, inserted=rnd.randint(0, 2), invalid=rnd.randint(0, 1)))
    return out


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_replay_same_status_every_as_of(tmp_path, seed):
    checks = _random_checks(seed)
    mem = SourceCheckLog()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'r.db'}")
    repo.create_all()
    sql = SqlSourceCheckLog(repo.engine)
    for c in checks:
        mem.record(c)
        sql.record(c)
    # Ghi lại theo thứ tự khác nhưng giữ thứ tự trong cùng mốc giờ → cùng kết quả.
    by_t: dict = {}
    for c in checks:
        by_t.setdefault(c.checked_at, []).append(c)
    shuffled = SourceCheckLog()
    keys = list(by_t)
    random.Random(seed).shuffle(keys)
    for k in keys:
        for c in by_t[k]:
            shuffled.record(c)
    end = checks[-1].checked_at + h(2)
    t = T0 - h(1)
    while t <= end:
        a, b, c = (x.summary("fed_rss", t) for x in (mem, sql, shuffled))
        assert a == b == c, t
        ea = evaluate("fed_rss", RSS, a, t, None)
        assert ea == evaluate("fed_rss", RSS, b, t, None)
        t += timedelta(minutes=13)
