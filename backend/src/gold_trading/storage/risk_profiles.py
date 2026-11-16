"""Hồ sơ rủi ro có phiên bản (GĐ5 bước 3 — DB-07, RPF-01; DEC-09, KN-12, Q6).

Mỗi tài khoản một chuỗi phiên bản **chỉ thêm** (không sửa / xóa bản cũ). Mọi con số do **người
dùng** chọn (H1–H11); hệ thống chỉ kiểm hợp lệ cứng — rủi ro / lệnh **trong [0,25 %; 0,5 %]**
(DEC-09), không ai vượt được. Chỉ **chủ tài khoản** (USER đang ACTIVE, không phải ADMIN) được tạo
phiên bản mới; hiệu lực ngay (Q6 = B). Thiết kế: docs/thiet-ke/35-risk-engine.md mục 9.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from gold_trading.storage.schema import risk_profiles

# DEC-09 (luật cứng của người dùng): rủi ro thật / lệnh trong [0,25 %; 0,5 %].
RISK_PER_TRADE_MIN = Decimal("0.0025")
RISK_PER_TRADE_MAX = Decimal("0.005")

NEWS_POLICIES = ("CLOSE_ALL", "KEEP_SAFE_ONLY")
WEEKEND_POLICIES = ("CLOSE_ALL",)          # cho giữ cần cách tính gap — chưa có
CASH_FLOW_POLICIES = ("SEPARATE",)
PYRAMIDING_POLICIES = ("NONE", "ONLY_IF_ALL_SAFE", "ONLY_IF_ALL_IN_PROFIT")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DECIMAL_FIELDS = ("risk_per_trade", "min_reward_risk", "max_open_risk", "max_daily_loss",
                  "max_weekly_loss", "max_monthly_loss", "max_drawdown_halt",
                  "max_effective_leverage")


class ProfileError(ValueError):
    """Hồ sơ không hợp lệ (thông báo tiếng Việt để hiện cho người dùng)."""


class ProfilePermissionError(PermissionError):
    """Người tạo không phải chủ tài khoản đang hoạt động (Q6, DEC-16)."""


@dataclass(frozen=True)
class RiskProfileValues:
    """Các số người dùng chọn. Tỷ lệ là phần của equity (0,0025 = 0,25 %)."""

    risk_per_trade: Decimal
    min_reward_risk: Decimal
    max_open_risk: Decimal
    max_daily_loss: Decimal
    max_weekly_loss: Decimal
    max_monthly_loss: Decimal
    max_consecutive_losses: int
    day_reset_tz: str
    day_reset_time: str
    max_trades_per_day: int
    max_drawdown_halt: Decimal
    news_hold_policy: str
    weekend_policy: str
    weekend_close_before_min: int
    max_effective_leverage: Decimal
    cash_flow_policy: str
    pyramiding_policy: str
    notes: str = ""


@dataclass(frozen=True)
class RiskProfile:
    account_id: str
    version: int
    values: RiskProfileValues
    created_at: datetime
    created_by: str
    reason: str


def _utc(v: datetime) -> datetime:
    if v.tzinfo is None or v.utcoffset() is None:
        raise ProfileError("thời điểm phải có múi giờ (UTC)")
    return v.astimezone(UTC)


def _db(v: datetime) -> datetime:
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


def _in(name: str, v: Decimal, lo: Decimal, hi: Decimal, *, lo_open: bool = False) -> None:
    if (v <= lo if lo_open else v < lo) or v > hi:
        raise ProfileError(f"{name} = {v} ngoài khoảng cho phép")


def validate(v: RiskProfileValues) -> RiskProfileValues:
    """Kiểm hợp lệ cứng. Lỗi → ``ProfileError`` (không lưu được)."""
    for n in DECIMAL_FIELDS:
        x = getattr(v, n)
        if not isinstance(x, Decimal) or not x.is_finite():
            raise ProfileError(f"{n} phải là số thập phân hữu hạn (Decimal)")
        if x.as_tuple().exponent < -6:  # type: ignore[operator]
            raise ProfileError(f"{n} tối đa 6 chữ số thập phân")
    for n in ("max_consecutive_losses", "max_trades_per_day", "weekend_close_before_min"):
        if not isinstance(getattr(v, n), int) or isinstance(getattr(v, n), bool):
            raise ProfileError(f"{n} phải là số nguyên")
    r = v.risk_per_trade
    if not RISK_PER_TRADE_MIN <= r <= RISK_PER_TRADE_MAX:
        raise ProfileError("rủi ro / lệnh phải trong khoảng 0,25 %–0,5 % (DEC-09)")
    _in("R:R tối thiểu", v.min_reward_risk, Decimal(1), Decimal(10))
    _in("tổng rủi ro mở", v.max_open_risk, r, Decimal("0.05"))
    _in("lỗ ngày", v.max_daily_loss, r, Decimal("0.2"))
    if not v.max_daily_loss <= v.max_weekly_loss <= v.max_monthly_loss <= Decimal("0.2"):
        raise ProfileError("cần lỗ ngày ≤ lỗ tuần ≤ lỗ tháng ≤ 20 %")
    _in("dừng hẳn khi sụt", v.max_drawdown_halt, Decimal(0), Decimal("0.5"), lo_open=True)
    _in("đòn bẩy thực tế", v.max_effective_leverage, Decimal(0), Decimal(30), lo_open=True)
    if not 1 <= v.max_consecutive_losses <= 50:
        raise ProfileError("chuỗi thua phải từ 1 tới 50 lệnh")
    if not 1 <= v.max_trades_per_day <= 100:
        raise ProfileError("số lệnh / ngày phải từ 1 tới 100")
    if not 5 <= v.weekend_close_before_min <= 240:
        raise ProfileError("đóng trước cuối tuần phải từ 5 tới 240 phút")
    try:
        if not v.day_reset_tz:
            raise ZoneInfoNotFoundError(v.day_reset_tz)
        ZoneInfo(v.day_reset_tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise ProfileError(f"múi giờ không hợp lệ: {v.day_reset_tz!r}") from None
    if not _TIME_RE.match(v.day_reset_time):
        raise ProfileError("mốc ngày phải dạng HH:MM")
    for name, val, allowed in (("news_hold_policy", v.news_hold_policy, NEWS_POLICIES),
                               ("weekend_policy", v.weekend_policy, WEEKEND_POLICIES),
                               ("cash_flow_policy", v.cash_flow_policy, CASH_FLOW_POLICIES),
                               ("pyramiding_policy", v.pyramiding_policy, PYRAMIDING_POLICIES)):
        if val not in allowed:
            raise ProfileError(f"{name} = {val!r} không được hỗ trợ")
    if len(v.notes) > 1000:
        raise ProfileError("ghi chú tối đa 1000 ký tự")
    return v


def _check_meta(created_by: str, reason: str, at: datetime) -> datetime:
    if not created_by or len(created_by) > 128:
        raise ProfileError("cần người tạo")
    if not reason or len(reason) > 256:
        raise ProfileError("cần lý do (≤ 256 ký tự)")
    return _utc(at)


class RiskProfileStore(Protocol):
    def append(self, account_id: str, values: RiskProfileValues, *, created_by: str,
               reason: str, at: datetime) -> RiskProfile: ...
    def at(self, account_id: str, at: datetime) -> RiskProfile | None: ...
    def history(self, account_id: str) -> list[RiskProfile]: ...


class InMemoryRiskProfileStore:
    def __init__(self) -> None:
        self._rows: list[RiskProfile] = []
        self._lock = threading.Lock()

    def append(self, account_id, values, *, created_by, reason, at):
        validate(values)
        t = _check_meta(created_by, reason, at)
        with self._lock:
            mine = [p for p in self._rows if p.account_id == account_id]
            if mine and t < mine[-1].created_at:
                raise ProfileError("thời điểm lùi về trước phiên bản đã có")
            p = RiskProfile(account_id, len(mine) + 1, values, t, created_by, reason)
            self._rows.append(p)
            return p

    def at(self, account_id, at):
        at = _utc(at)
        with self._lock:
            rows = [p for p in self._rows if p.account_id == account_id and p.created_at <= at]
        return max(rows, key=lambda p: p.version) if rows else None

    def history(self, account_id):
        with self._lock:
            return [p for p in self._rows if p.account_id == account_id]


_VALUE_NAMES = tuple(f.name for f in fields(RiskProfileValues))


class SqlRiskProfileStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _row(m) -> RiskProfile:
        raw = {n: getattr(m, n) for n in _VALUE_NAMES}
        for n in DECIMAL_FIELDS:
            raw[n] = Decimal(str(raw[n])).normalize()
        return RiskProfile(m.account_id, int(m.version), RiskProfileValues(**raw),
                           _db(m.created_at), m.created_by, m.reason)

    def append(self, account_id, values, *, created_by, reason, at):
        validate(values)
        t = _check_meta(created_by, reason, at)
        c = risk_profiles.c
        for _ in range(3):      # hai lần tạo cùng lúc → trùng version → thử lại
            try:
                with self.engine.begin() as conn:
                    last = conn.execute(select(func.max(c.version), func.max(c.created_at))
                                        .where(c.account_id == account_id)).first()
                    if last[1] is not None and t < _db(last[1]):
                        raise ProfileError("thời điểm lùi về trước phiên bản đã có")
                    ver = (last[0] or 0) + 1
                    conn.execute(insert(risk_profiles).values(
                        account_id=account_id, version=ver, created_at=t,
                        created_by=created_by, reason=reason,
                        **{n: getattr(values, n) for n in _VALUE_NAMES}))
                return RiskProfile(account_id, ver, values, t, created_by, reason)
            except IntegrityError:
                with self.engine.connect() as conn:
                    taken = conn.execute(select(c.version).where(
                        c.account_id == account_id, c.version == ver)).first()
                if taken is None:
                    raise       # vi phạm CHECK (DEC-09 ở DB), không phải trùng phiên bản
        raise ProfileError("không ghi được phiên bản mới (tranh chấp), thử lại")

    def at(self, account_id, at):
        c = risk_profiles.c
        with self.engine.connect() as conn:
            m = conn.execute(select(risk_profiles).where(
                c.account_id == account_id, c.created_at <= _utc(at))
                .order_by(c.version.desc()).limit(1)).first()
        return self._row(m) if m is not None else None

    def history(self, account_id):
        c = risk_profiles.c
        with self.engine.connect() as conn:
            rows = conn.execute(select(risk_profiles).where(c.account_id == account_id)
                                .order_by(c.version)).all()
        return [self._row(m) for m in rows]


def create_profile(store: RiskProfileStore, repo, account_id: str, actor_sub: str,
                   values: RiskProfileValues, *, reason: str, at: datetime,
                   actor_is_admin: bool) -> RiskProfile:
    """Q6 = B: chỉ chủ tài khoản (USER, ACTIVE) tạo phiên bản mới; ADMIN không can dự.
    Đọc quyền từ DB mỗi lần (không cache)."""
    from gold_trading.accounts.access import decide, owns

    user = repo.user(actor_sub)
    status = user.status if user is not None else None
    is_admin = actor_is_admin or (user is not None and user.role == "ADMIN")
    if decide(is_admin=is_admin, owns=owns(repo, account_id, actor_sub), status=status) != "ok":
        raise ProfilePermissionError("chỉ chủ tài khoản đang hoạt động được đổi hồ sơ rủi ro")
    return store.append(account_id, values, created_by=actor_sub, reason=reason, at=at)


def with_changes(v: RiskProfileValues, **kw) -> RiskProfileValues:
    return replace(v, **kw)
