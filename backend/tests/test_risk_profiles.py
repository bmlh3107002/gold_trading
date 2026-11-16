"""GĐ5 bước 3 — hồ sơ rủi ro có phiên bản (DB-07, RPF-01; DEC-09, KN-12, Q6)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from gold_trading.storage.repository import (
    InMemoryRepository,
    Member,
    SqlRepository,
    TradingAccount,
)
from gold_trading.storage.risk_profiles import (
    InMemoryRiskProfileStore,
    ProfileError,
    ProfilePermissionError,
    RiskProfileValues,
    SqlRiskProfileStore,
    create_profile,
    validate,
)
from gold_trading.storage.schema import risk_profiles

T = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)
D = Decimal

# Hồ sơ v1 người dùng chốt 16/11 (H1–H11) — số thật của người dùng, dùng để kiểm hợp lệ.
USER_V1 = RiskProfileValues(
    risk_per_trade=D("0.0025"), min_reward_risk=D("1.5"), max_open_risk=D("0.005"),
    max_daily_loss=D("0.0075"), max_weekly_loss=D("0.015"), max_monthly_loss=D("0.03"),
    max_consecutive_losses=5, day_reset_tz="America/New_York", day_reset_time="17:00",
    max_trades_per_day=4, max_drawdown_halt=D("0.05"), news_hold_policy="KEEP_SAFE_ONLY",
    weekend_policy="CLOSE_ALL", weekend_close_before_min=30, max_effective_leverage=D(3),
    cash_flow_policy="SEPARATE", pyramiding_policy="ONLY_IF_ALL_IN_PROFIT",
    notes="H1–H11 chốt 16/11")


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryRiskProfileStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'p.db'}")
    repo.create_all()
    return SqlRiskProfileStore(repo.engine)


def test_user_v1_is_valid():
    assert validate(USER_V1) is USER_V1


@pytest.mark.parametrize("r,ok", [("0.0025", True), ("0.005", True), ("0.0035", True),
                                  ("0.002499", False), ("0.005001", False), ("0.01", False),
                                  ("0", False), ("-0.0025", False)])
def test_dec09_risk_per_trade_bounds(r, ok):
    v = replace(USER_V1, risk_per_trade=D(r), max_open_risk=D("0.01"), max_daily_loss=D("0.01"),
                max_weekly_loss=D("0.02"), max_monthly_loss=D("0.04"))
    if ok:
        validate(v)
    else:
        with pytest.raises(ProfileError):
            validate(v)


@pytest.mark.parametrize("kw", [
    dict(max_open_risk=D("0.002")),                       # heat < rủi ro / lệnh
    dict(max_open_risk=D("0.06")),
    dict(max_daily_loss=D("0.002")),                      # lỗ ngày < một lệnh
    dict(max_weekly_loss=D("0.005")),                     # tuần < ngày
    dict(max_monthly_loss=D("0.01")),                     # tháng < tuần
    dict(min_reward_risk=D("0.9")),
    dict(max_drawdown_halt=D(0)), dict(max_drawdown_halt=D("0.6")),
    dict(max_effective_leverage=D(0)), dict(max_effective_leverage=D(31)),
    dict(max_consecutive_losses=0), dict(max_trades_per_day=0),
    dict(weekend_close_before_min=4), dict(max_trades_per_day=True),
    dict(day_reset_tz="New_York"), dict(day_reset_tz=""), dict(day_reset_tz="../etc"),
    dict(day_reset_time="24:00"), dict(day_reset_time="5:00"),
    dict(news_hold_policy="KEEP"),                        # giữ bình thường: không hỗ trợ
    dict(weekend_policy="KEEP_SAFE_ONLY"),                # giữ qua cuối tuần: chưa có cách tính
    dict(pyramiding_policy="ALLOW"), dict(cash_flow_policy="NONE"),
    dict(risk_per_trade=0.0025),                          # float — không chấp nhận
    dict(risk_per_trade=D("NaN")), dict(min_reward_risk=D("1.1234567")),
    dict(notes="x" * 1001),
])
def test_invalid_profiles_rejected(kw):
    with pytest.raises(ProfileError):
        validate(replace(USER_V1, **kw))


def test_versions_point_in_time_and_round_trip(store):
    p1 = store.append("a1", USER_V1, created_by="sub-u", reason="H1–H11", at=T)
    v2 = replace(USER_V1, risk_per_trade=D("0.005"))
    p2 = store.append("a1", v2, created_by="sub-u", reason="nới", at=T + timedelta(days=1))
    assert (p1.version, p2.version) == (1, 2)
    assert store.at("a1", T - timedelta(seconds=1)) is None
    got = store.at("a1", T + timedelta(hours=1))
    assert got.version == 1 and got.values == USER_V1 and got.created_by == "sub-u"
    assert store.at("a1", T + timedelta(days=2)).values.risk_per_trade == D("0.005")
    assert store.at("a2", T + timedelta(days=2)) is None
    assert [p.version for p in store.history("a1")] == [1, 2]


def test_invalid_not_stored(store):
    with pytest.raises(ProfileError):
        store.append("a1", replace(USER_V1, risk_per_trade=D("0.006")), created_by="u",
                     reason="r", at=T)
    with pytest.raises(ProfileError):
        store.append("a1", USER_V1, created_by="", reason="r", at=T)
    with pytest.raises(ProfileError):
        store.append("a1", USER_V1, created_by="u", reason="", at=T)
    with pytest.raises(ProfileError):
        store.append("a1", USER_V1, created_by="u", reason="r", at=T.replace(tzinfo=None))
    assert store.history("a1") == []


def test_time_cannot_go_backwards(store):
    store.append("a1", USER_V1, created_by="u", reason="r", at=T)
    with pytest.raises(ProfileError):
        store.append("a1", USER_V1, created_by="u", reason="r", at=T - timedelta(seconds=1))


def test_db_check_enforces_dec09_even_bypassing_code(tmp_path):
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'c.db'}")
    repo.create_all()
    row = {f: getattr(USER_V1, f) for f in RiskProfileValues.__dataclass_fields__}
    with pytest.raises(IntegrityError), repo.engine.begin() as conn:
        conn.execute(insert(risk_profiles).values(
            account_id="a1", version=1, created_at=T, created_by="u", reason="r",
            **(row | {"risk_per_trade": D("0.01")})))


def test_new_version_keeps_old_one(tmp_path):
    # Kho chỉ thêm (trên Postgres trigger chặn UPDATE / DELETE — migration 0025, CI docker):
    # lưu bản mới không đổi bản cũ.
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'u.db'}")
    repo.create_all()
    s = SqlRiskProfileStore(repo.engine)
    s.append("a1", USER_V1, created_by="u", reason="r", at=T)
    s.append("a1", replace(USER_V1, max_trades_per_day=3), created_by="u", reason="r2",
             at=T + timedelta(minutes=1))
    assert s.history("a1")[0].values == USER_V1


def test_concurrent_appends_get_distinct_versions():
    s = InMemoryRiskProfileStore()
    with ThreadPoolExecutor(8) as pool:
        out = list(pool.map(lambda k: s.append("a1", USER_V1, created_by="u", reason=f"r{k}",
                                               at=T), range(16)))
    assert sorted(p.version for p in out) == list(range(1, 17))


# ---------------------------------------------------------------- Q6: ai được tạo

@pytest.fixture
def repo():
    r = InMemoryRepository()
    r.create_account(TradingAccount("a1", "A", T, "system", False))
    r.upsert_user("sub-u", "u", None, None, T)
    r.upsert_user("sub-other", "o", None, None, T)
    r.upsert_user("sub-admin", "adm", None, None, T, role="ADMIN")
    r.set_member(Member("a1", "sub-u", "OWNER", T, "system"))
    return r


def test_owner_creates_profile(repo):
    s = InMemoryRiskProfileStore()
    p = create_profile(s, repo, "a1", "sub-u", USER_V1, reason="H1–H11", at=T,
                       actor_is_admin=False)
    assert p.version == 1 and p.created_by == "sub-u"


@pytest.mark.parametrize("actor,is_admin", [("sub-other", False), ("sub-admin", False),
                                            ("sub-u", True), ("khong-co", False)])
def test_non_owner_or_admin_cannot_create(repo, actor, is_admin):
    s = InMemoryRiskProfileStore()
    with pytest.raises(ProfilePermissionError):
        create_profile(s, repo, "a1", actor, USER_V1, reason="r", at=T, actor_is_admin=is_admin)
    assert s.history("a1") == []


def test_admin_even_as_member_cannot_create(repo):
    repo.set_member(Member("a1", "sub-admin", "OWNER", T, "system"))
    with pytest.raises(ProfilePermissionError):
        create_profile(InMemoryRiskProfileStore(), repo, "a1", "sub-admin", USER_V1,
                       reason="r", at=T, actor_is_admin=False)


def test_locked_owner_cannot_create(repo):
    repo.set_user_status("sub-u", "LOCKED", T)
    with pytest.raises(ProfilePermissionError):
        create_profile(InMemoryRiskProfileStore(), repo, "a1", "sub-u", USER_V1, reason="r",
                       at=T, actor_is_admin=False)


def test_owner_cannot_exceed_dec09_either(repo):
    with pytest.raises(ProfileError):
        create_profile(InMemoryRiskProfileStore(), repo, "a1", "sub-u",
                       replace(USER_V1, risk_per_trade=D("0.0075")), reason="r", at=T,
                       actor_is_admin=False)
