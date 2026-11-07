"""Repository cho trạng thái vận hành, phân theo tài khoản giao dịch (MT-01, MT-02).

Có bản bộ nhớ (test/dev) và bản SQL (Postgres; SQLite cho test). Hai bản phải hành xử giống nhau.

Ghi Safety dùng kiểm tra lạc quan (``expected_last``): chỉ ghi nếu sự kiện mới nhất trong DB đúng
là sự kiện mà người ghi đã thấy. Nhờ vậy lệnh HALT ghi thẳng vào DB từ CLI (OPS-15) không bao giờ
bị một tiến trình khác ghi đè bằng trạng thái cũ. Postgres còn khóa thêm theo tài khoản
(``pg_advisory_xact_lock``) để hai người ghi cùng lúc không lọt qua kiểm tra.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from sqlalchemy import (
    Engine,
    and_,
    create_engine,
    delete,
    event,
    func,
    insert,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError

from gold_trading.common.enums import SafetyState, TradingMode
from gold_trading.common.ids import new_id
from gold_trading.common.time import utcnow
from gold_trading.contracts.safety import SafetyTransition
from gold_trading.modes.manager import ModeChange
from gold_trading.storage.schema import (
    ACCOUNT_ROLES,
    DEFAULT_ACCOUNT_ID,
    MT5_LINK_HELD,
    MT5_LINK_STATUSES,
    TOKEN_REQUEST_EVENTS,
    account_members,
    audit_log,
    gateway_token_requests,
    gateway_tokens,
    metadata,
    mode_changes,
    mt5_links,
    safety_transitions,
    trading_accounts,
    users,
)

Role = Literal["OWNER", "OPERATOR", "VIEWER"]
ROLE_RANK: dict[str, int] = {"VIEWER": 1, "OPERATOR": 2, "OWNER": 3}
DEFAULT_ACCOUNT_NAME = "Tài khoản chính"


class StaleStateError(RuntimeError):
    """Trạng thái trong DB đã đổi (ví dụ HALT từ CLI) kể từ lần đọc trước: không ghi."""


class ConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuditEntry:
    at: datetime
    actor: str
    action: str
    outcome: str
    payload: dict[str, Any]
    detail: str | None = None
    account_id: str | None = None  # None = sự kiện hệ thống
    actor_sub: str | None = None


@dataclass(frozen=True)
class UserRecord:
    sub: str
    username: str
    email: str | None
    display_name: str | None
    # None = tài khoản do ADMIN tạo trên Dashboard (MT-20), người đó chưa đăng nhập lần nào
    first_login_at: datetime | None
    last_login_at: datetime | None
    # DEC-16: chỉ hai vai trò (ADMIN quản lý tài khoản, USER giao dịch) và hai trạng thái
    role: str = "USER"
    status: str = "ACTIVE"
    updated_at: datetime | None = None


@dataclass(frozen=True)
class TradingAccount:
    account_id: str
    name: str
    created_at: datetime
    created_by: str
    price_feed: bool


@dataclass(frozen=True)
class TokenRequestEvent:
    """DEC-17: sự kiện xin cấp token Gateway. Trạng thái hiện tại = sự kiện cuối của tài khoản."""

    account_id: str
    sub: str  # USER xin (chủ tài khoản)
    event: str  # REQUESTED | APPROVED | REJECTED | CANCELLED
    at: datetime
    actor: str  # người tạo sự kiện (USER xin, ADMIN cấp/từ chối, hệ thống)


@dataclass(frozen=True)
class Member:
    account_id: str
    sub: str
    role: str
    granted_at: datetime
    granted_by: str


@dataclass(frozen=True)
class Mt5Link:
    """MT-13: liên kết tài khoản giao dịch ↔ MT5 ``(login, server)`` do terminal báo."""

    link_id: str
    account_id: str
    mt5_login: int
    mt5_server: str
    mt5_company: str | None
    trade_mode: str  # DEMO | CONTEST | REAL
    gateway_id: str
    token_id: str | None  # None = token cũ GT_INGEST_TOKEN
    status: str
    created_at: datetime
    verified_at: datetime | None = None
    verified_by: str | None = None
    ended_at: datetime | None = None
    ended_by: str | None = None
    end_reason: str | None = None

    @property
    def held(self) -> bool:
        return self.status in MT5_LINK_HELD

    def same_identity(self, login: int, server: str, trade_mode: str) -> bool:
        return (self.mt5_login, self.mt5_server, self.trade_mode) == (login, server, trade_mode)


class Mt5LinkError(ConflictError):
    """``code``: NOT_FOUND | NOT_PENDING | IDENTITY_HELD (MT-C11) | ACCOUNT_HELD | NOT_OPEN."""

    def __init__(self, code: str, msg: str) -> None:
        super().__init__(msg)
        self.code = code


def _check_link(link: Mt5Link) -> None:
    if link.status not in MT5_LINK_STATUSES:
        raise ValueError(f"Trạng thái liên kết không hợp lệ: {link.status}")
    if link.trade_mode not in ("DEMO", "CONTEST", "REAL"):
        raise ValueError(f"Loại tài khoản MT5 không hợp lệ: {link.trade_mode}")
    if link.mt5_login <= 0 or not link.mt5_server:
        raise ValueError("Danh tính MT5 không hợp lệ")


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class Repository(Protocol):
    kind: str

    def healthy(self) -> bool: ...
    # Safety / Mode / audit theo tài khoản
    def safety_history(self, account_id: str, limit: int = 200) -> list[SafetyTransition]: ...
    def append_safety(
        self, account_id: str, t: SafetyTransition, *, expected_last: str | None | object = ...
    ) -> None: ...
    def last_mode(self, account_id: str) -> TradingMode | None: ...
    def append_mode(self, account_id: str, change: ModeChange) -> None: ...
    def append_audit(self, entry: AuditEntry) -> None: ...
    def audit(
        self, limit: int = 100, *, account_id: str | None = None, system: bool = False
    ) -> list[AuditEntry]: ...
    # Tài khoản giao dịch
    def ensure_default_account(self) -> None: ...
    def accounts(self) -> list[TradingAccount]: ...
    def account(self, account_id: str) -> TradingAccount | None: ...
    def create_account(self, acc: TradingAccount) -> None: ...
    # Người dùng + thành viên
    def upsert_user(self, sub: str, username: str, email: str | None,
                    display_name: str | None, at: datetime, role: str = "USER") -> None: ...
    def user(self, sub: str) -> UserRecord | None: ...
    def list_users(self) -> list[UserRecord]: ...
    def set_user_status(self, sub: str, status: str, at: datetime) -> bool: ...
    def find_user(self, username_or_email: str) -> UserRecord | None: ...
    def role(self, account_id: str, sub: str) -> str | None: ...
    def members(self, account_id: str) -> list[Member]: ...
    def memberships(self, sub: str) -> list[Member]: ...
    def set_member(self, m: Member) -> None: ...
    def remove_member(self, account_id: str, sub: str) -> bool: ...
    def provision_user(self, user: UserRecord, acc: TradingAccount | None, owner: Member,
                       token_raw: str | None, at: datetime) -> str | None:
        """MT-20/DEC-16: người dùng mới + tài khoản riêng (``acc``; None = nhận tài khoản có sẵn
        ``owner.account_id`` chưa có chủ) + quyền sở hữu, trong MỘT giao dịch. Token cũ của tài
        khoản luôn bị thu hồi. ``token_raw`` None (DEC-17: USER xin, ADMIN cấp sau) → không tạo
        token, trả None; có → tạo token, trả token_id."""
        ...
    def update_user_profile(self, sub: str, email: str, display_name: str,
                            at: datetime) -> bool: ...
    # Token Gateway
    def rotate_gateway_token(self, account_id: str, raw: str, by: str, at: datetime) -> str: ...
    def revoke_gateway_tokens(self, account_id: str, at: datetime) -> int: ...
    def account_for_token(self, raw: str) -> str | None: ...
    def gateway_token(self, raw: str) -> tuple[str, str] | None: ...
    def has_gateway_tokens(self, account_id: str) -> bool: ...
    def has_active_gateway_token(self, account_id: str) -> bool: ...
    # Xin cấp token (DEC-17)
    def add_token_request_event(self, e: TokenRequestEvent) -> None: ...
    def last_token_request(self, account_id: str) -> TokenRequestEvent | None: ...

    # --- Liên kết MT5 (MT-13) ---

    def mt5_links(self, account_id: str, limit: int = 50) -> list[Mt5Link]: ...
    def add_pending_link(self, link: Mt5Link) -> bool: ...
    def confirm_link(self, account_id: str, link_id: str, by: str, at: datetime) -> Mt5Link: ...
    def end_link(self, account_id: str, link_id: str, status: str, by: str, at: datetime,
                 reason: str) -> Mt5Link: ...
    def end_account_links(self, account_id: str, by: str, at: datetime, reason: str) -> int: ...


_UNSET: Any = object()


def _check_role(role: str) -> None:
    if role not in ACCOUNT_ROLES:
        raise ValueError(f"Vai trò không hợp lệ: {role}")


USER_ROLES = ("ADMIN", "USER")
USER_STATUSES = ("ACTIVE", "LOCKED", "DELETED")


def _check_token_event(e: TokenRequestEvent) -> None:
    if e.event not in TOKEN_REQUEST_EVENTS:
        raise ValueError(f"Sự kiện xin token không hợp lệ: {e.event}")


def _check_user(role: str, status: str) -> None:
    if role not in USER_ROLES:
        raise ValueError(f"Vai trò người dùng không hợp lệ: {role}")
    if status not in USER_STATUSES:
        raise ValueError(f"Trạng thái người dùng không hợp lệ: {status}")


class InMemoryRepository:
    kind = "memory"

    def __init__(self) -> None:
        self._safety: dict[str, list[SafetyTransition]] = {}
        self._modes: dict[str, list[ModeChange]] = {}
        self._audit: list[AuditEntry] = []
        self._accounts: dict[str, TradingAccount] = {}
        self._users: dict[str, UserRecord] = {}
        self._members: dict[tuple[str, str], Member] = {}
        self._tokens: list[dict[str, Any]] = []
        self._token_requests: list[TokenRequestEvent] = []
        self._links: list[Mt5Link] = []
        self._lock = threading.RLock()
        self.ensure_default_account()

    def healthy(self) -> bool:
        return True

    # --- Safety / Mode / audit ---

    def safety_history(self, account_id: str, limit: int = 200) -> list[SafetyTransition]:
        with self._lock:
            return list(self._safety.get(account_id, [])[-limit:])

    def append_safety(self, account_id: str, t: SafetyTransition, *,
                      expected_last: Any = _UNSET) -> None:
        with self._lock:
            self._require_account(account_id)
            hist = self._safety.setdefault(account_id, [])
            if expected_last is not _UNSET:
                current = hist[-1].transition_id if hist else None
                if current != expected_last:
                    raise StaleStateError(account_id)
            hist.append(t)

    def last_mode(self, account_id: str) -> TradingMode | None:
        with self._lock:
            m = self._modes.get(account_id)
            return TradingMode(m[-1].to_mode) if m else None

    def append_mode(self, account_id: str, change: ModeChange) -> None:
        with self._lock:
            self._require_account(account_id)
            self._modes.setdefault(account_id, []).append(change)

    def append_audit(self, entry: AuditEntry) -> None:
        with self._lock:
            self._audit.append(entry)

    def audit(self, limit: int = 100, *, account_id: str | None = None,
              system: bool = False) -> list[AuditEntry]:
        with self._lock:
            if system:
                rows = [e for e in self._audit if e.account_id is None]
            elif account_id is not None:
                rows = [e for e in self._audit if e.account_id == account_id]
            else:
                rows = list(self._audit)
            return list(reversed(rows[-limit:]))

    # --- Tài khoản ---

    def _require_account(self, account_id: str) -> None:
        if account_id not in self._accounts:
            raise KeyError(f"Không có tài khoản {account_id}")

    def ensure_default_account(self) -> None:
        with self._lock:
            if DEFAULT_ACCOUNT_ID not in self._accounts:
                self._accounts[DEFAULT_ACCOUNT_ID] = TradingAccount(
                    DEFAULT_ACCOUNT_ID, DEFAULT_ACCOUNT_NAME, utcnow(), "system", True
                )

    def accounts(self) -> list[TradingAccount]:
        with self._lock:
            return sorted(self._accounts.values(), key=lambda a: (a.created_at, a.account_id))

    def account(self, account_id: str) -> TradingAccount | None:
        return self._accounts.get(account_id)

    def create_account(self, acc: TradingAccount) -> None:
        with self._lock:
            if acc.account_id in self._accounts:
                raise ConflictError(f"Tài khoản {acc.account_id} đã tồn tại")
            self._accounts[acc.account_id] = acc

    # --- Người dùng + thành viên ---

    def upsert_user(self, sub, username, email, display_name, at, role="USER") -> None:
        _check_user(role, "ACTIVE")
        with self._lock:
            old = self._users.get(sub)
            first = (old.first_login_at if old else None) or at
            status = old.status if old else "ACTIVE"
            updated = (old.updated_at if old else None) if old and old.role == role else at
            self._users[sub] = UserRecord(sub, username, email, display_name, first, at,
                                          role, status, updated)

    def user(self, sub: str) -> UserRecord | None:
        return self._users.get(sub)

    def list_users(self) -> list[UserRecord]:
        with self._lock:
            return sorted(self._users.values(), key=lambda u: u.username.lower())

    def set_user_status(self, sub: str, status: str, at: datetime) -> bool:
        _check_user("USER", status)
        with self._lock:
            old = self._users.get(sub)
            if old is None:
                return False
            self._users[sub] = replace(old, status=status, updated_at=at)
            return True

    def find_user(self, username_or_email: str) -> UserRecord | None:
        q = username_or_email.strip().lower()
        with self._lock:
            for u in self._users.values():
                if u.username.lower() == q or (u.email and u.email.lower() == q):
                    return u
        return None

    def role(self, account_id: str, sub: str) -> str | None:
        m = self._members.get((account_id, sub))
        return m.role if m else None

    def members(self, account_id: str) -> list[Member]:
        with self._lock:
            return sorted(
                (m for (a, _), m in self._members.items() if a == account_id),
                key=lambda m: (-ROLE_RANK[m.role], m.granted_at),
            )

    def memberships(self, sub: str) -> list[Member]:
        with self._lock:
            return [m for (_, s), m in self._members.items() if s == sub]

    def set_member(self, m: Member) -> None:
        _check_role(m.role)
        with self._lock:
            self._require_account(m.account_id)
            if m.sub not in self._users:
                raise KeyError("Người dùng chưa đăng nhập lần nào")
            self._members[(m.account_id, m.sub)] = m

    def remove_member(self, account_id: str, sub: str) -> bool:
        with self._lock:
            return self._members.pop((account_id, sub), None) is not None

    def provision_user(self, user: UserRecord, acc: TradingAccount | None, owner: Member,
                       token_raw: str | None, at: datetime) -> str | None:
        _check_role(owner.role)
        _check_user(user.role, user.status)
        if owner.sub != user.sub or (acc is not None and owner.account_id != acc.account_id):
            raise ValueError("owner phải là người dùng mới của tài khoản mới")
        with self._lock:
            if acc is not None and acc.account_id in self._accounts:
                raise ConflictError(f"Tài khoản {acc.account_id} đã tồn tại")
            if acc is None and (
                owner.account_id not in self._accounts
                or any(a == owner.account_id and m.role == "OWNER"
                       for (a, _), m in self._members.items())
            ):
                raise ConflictError(f"Tài khoản {owner.account_id} không nhận chủ mới được")
            if user.sub in self._users:
                raise ConflictError("Người dùng đã tồn tại")
            self._users[user.sub] = user
            if acc is not None:
                self._accounts[acc.account_id] = acc
            self._members[(owner.account_id, user.sub)] = owner
            for t in self._tokens:
                if t["account_id"] == owner.account_id and t["revoked_at"] is None:
                    t["revoked_at"] = at
            if token_raw is None:
                return None
            token_id = new_id("gtk")
            self._tokens.append({
                "token_id": token_id, "account_id": owner.account_id,
                "token_sha256": token_hash(token_raw), "created_at": at,
                "created_by": owner.granted_by, "revoked_at": None,
            })
            return token_id

    def update_user_profile(self, sub: str, email: str, display_name: str,
                            at: datetime) -> bool:
        with self._lock:
            old = self._users.get(sub)
            if old is None:
                return False
            self._users[sub] = replace(old, email=email, display_name=display_name,
                                       updated_at=at)
            return True

    # --- Token Gateway ---

    def rotate_gateway_token(self, account_id: str, raw: str, by: str, at: datetime) -> str:
        with self._lock:
            self._require_account(account_id)
            for t in self._tokens:
                if t["account_id"] == account_id and t["revoked_at"] is None:
                    t["revoked_at"] = at
            token_id = new_id("gtk")
            self._tokens.append({
                "token_id": token_id, "account_id": account_id, "token_sha256": token_hash(raw),
                "created_at": at, "created_by": by, "revoked_at": None,
            })
            return token_id

    def account_for_token(self, raw: str) -> str | None:
        t = self.gateway_token(raw)
        return t[0] if t else None

    def gateway_token(self, raw: str) -> tuple[str, str] | None:
        """``(account_id, token_id)`` của token còn hiệu lực."""
        h = token_hash(raw)
        with self._lock:
            for t in self._tokens:
                if t["revoked_at"] is None and t["token_sha256"] == h:
                    return t["account_id"], t["token_id"]
        return None

    def has_gateway_tokens(self, account_id: str) -> bool:
        with self._lock:
            return any(t["account_id"] == account_id for t in self._tokens)

    def has_active_gateway_token(self, account_id: str) -> bool:
        with self._lock:
            return any(t["account_id"] == account_id and t["revoked_at"] is None
                       for t in self._tokens)

    def revoke_gateway_tokens(self, account_id: str, at: datetime) -> int:
        n = 0
        with self._lock:
            for t in self._tokens:
                if t["account_id"] == account_id and t["revoked_at"] is None:
                    t["revoked_at"] = at
                    n += 1
        return n

    # --- Xin cấp token (DEC-17) ---

    def add_token_request_event(self, e: TokenRequestEvent) -> None:
        _check_token_event(e)
        with self._lock:
            self._require_account(e.account_id)
            if e.sub not in self._users:
                raise KeyError("Không có người dùng")
            self._token_requests.append(e)

    def last_token_request(self, account_id: str) -> TokenRequestEvent | None:
        with self._lock:
            for e in reversed(self._token_requests):
                if e.account_id == account_id:
                    return e
        return None

    # --- Liên kết MT5 (MT-13) ---

    def mt5_links(self, account_id: str, limit: int = 50) -> list[Mt5Link]:
        with self._lock:
            return [x for x in self._links if x.account_id == account_id][-limit:]

    def _replace_link(self, new: Mt5Link) -> Mt5Link:
        for i, x in enumerate(self._links):
            if x.link_id == new.link_id:
                self._links[i] = new
                return new
        raise KeyError(new.link_id)

    def add_pending_link(self, link: Mt5Link) -> bool:
        _check_link(link)
        if link.status != "PENDING_CONFIRM":
            raise ValueError("Liên kết mới phải ở trạng thái PENDING_CONFIRM")
        with self._lock:
            self._require_account(link.account_id)
            mine = [x for x in self._links if x.account_id == link.account_id]
            if any(x.held for x in mine):
                return False  # đổi MT5 khi đang có liên kết: MT-14 xử lý, không tạo chờ mới
            for x in mine:
                if x.status == "PENDING_CONFIRM":
                    if x.same_identity(link.mt5_login, link.mt5_server, link.trade_mode):
                        return False
                    self._replace_link(replace(x, status="CANCELLED", ended_at=link.created_at,
                                               ended_by="gateway", end_reason="REPLACED"))
            self._links.append(link)
            return True

    def confirm_link(self, account_id: str, link_id: str, by: str, at: datetime) -> Mt5Link:
        with self._lock:
            x = next((x for x in self._links
                      if x.link_id == link_id and x.account_id == account_id), None)
            if x is None:
                raise Mt5LinkError("NOT_FOUND", "Không có liên kết này")
            if x.status != "PENDING_CONFIRM":
                raise Mt5LinkError("NOT_PENDING", "Liên kết không còn chờ xác nhận")
            if any(o.held and o.account_id == account_id for o in self._links):
                raise Mt5LinkError("ACCOUNT_HELD", "Tài khoản đã có liên kết MT5")
            if any(o.held and o.mt5_login == x.mt5_login
                   and o.mt5_server.lower() == x.mt5_server.lower() for o in self._links):
                raise Mt5LinkError("IDENTITY_HELD", "MT5 này đã liên kết ở tài khoản khác")
            return self._replace_link(replace(x, status="ACTIVE", verified_at=at, verified_by=by))

    def end_link(self, account_id: str, link_id: str, status: str, by: str, at: datetime,
                 reason: str) -> Mt5Link:
        if status not in ("REVOKED", "CANCELLED"):
            raise ValueError("Chỉ kết thúc liên kết bằng REVOKED/CANCELLED")
        with self._lock:
            x = next((x for x in self._links
                      if x.link_id == link_id and x.account_id == account_id), None)
            if x is None:
                raise Mt5LinkError("NOT_FOUND", "Không có liên kết này")
            if not (x.held or x.status == "PENDING_CONFIRM"):
                raise Mt5LinkError("NOT_OPEN", "Liên kết đã kết thúc")
            return self._replace_link(replace(x, status=status, ended_at=at, ended_by=by,
                                              end_reason=reason[:128]))

    def end_account_links(self, account_id: str, by: str, at: datetime, reason: str) -> int:
        n = 0
        with self._lock:
            for x in list(self._links):
                if x.account_id == account_id and (x.held or x.status == "PENDING_CONFIRM"):
                    self._replace_link(replace(
                        x, status="REVOKED" if x.held else "CANCELLED", ended_at=at, ended_by=by,
                        end_reason=reason[:128]))
                    n += 1
        return n


def _row(r) -> dict[str, Any]:
    """Bỏ cột seq; SQLite không lưu timezone nên gắn lại UTC (mọi thời gian lưu là UTC)."""
    out: dict[str, Any] = {}
    for k, v in r.items():
        if k == "seq":
            continue
        if isinstance(v, datetime) and v.tzinfo is None:
            v = v.replace(tzinfo=UTC)
        out[k] = v
    return out


def _lock_key(account_id: str) -> int:
    """Khóa advisory 64-bit có dấu, ổn định theo account_id."""
    return int.from_bytes(hashlib.sha256(b"safety:" + account_id.encode()).digest()[:8],
                          "big", signed=True)


class SqlRepository:
    kind = "postgres"

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        if engine.dialect.name != "postgresql":
            self.kind = engine.dialect.name
        if engine.dialect.name == "sqlite":
            # SQLite mặc định không kiểm khóa ngoại; bật để test giống Postgres.
            @event.listens_for(engine, "connect")
            def _fk_on(dbapi_conn, _):  # pragma: no cover - chỉ chạy với SQLite
                dbapi_conn.execute("PRAGMA foreign_keys=ON")

    @classmethod
    def from_url(cls, url: str) -> SqlRepository:
        return cls(create_engine(url, pool_pre_ping=True, future=True))

    def create_all(self) -> None:
        """Chỉ dùng cho test (SQLite). Môi trường thật dùng Alembic."""
        metadata.create_all(self.engine)
        self.ensure_default_account()

    def healthy(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    # --- Safety / Mode / audit ---

    def safety_history(self, account_id: str, limit: int = 200) -> list[SafetyTransition]:
        c = safety_transitions.c
        q = (
            select(safety_transitions)
            .where(c.account_id == account_id)
            .order_by(c.seq.desc())
            .limit(limit)
        )
        with self.engine.connect() as conn:
            rows = conn.execute(q).mappings().all()
        out = []
        for r in reversed(rows):
            d = _row(r)
            d.pop("account_id")
            out.append(SafetyTransition(**d))
        return out

    def _require_account(self, conn, account_id: str) -> None:
        if conn.execute(
            select(trading_accounts.c.account_id).where(
                trading_accounts.c.account_id == account_id
            )
        ).first() is None:
            raise KeyError(f"Không có tài khoản {account_id}")

    def append_safety(self, account_id: str, t: SafetyTransition, *,
                      expected_last: Any = _UNSET) -> None:
        c = safety_transitions.c
        with self.engine.begin() as conn:
            self._require_account(conn, account_id)
            if self.engine.dialect.name == "postgresql":
                conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _lock_key(account_id)})
            if expected_last is not _UNSET:
                current = conn.execute(
                    select(c.transition_id)
                    .where(c.account_id == account_id)
                    .order_by(c.seq.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if current != expected_last:
                    raise StaleStateError(account_id)
            conn.execute(insert(safety_transitions).values(account_id=account_id, **t.model_dump()))

    def last_mode(self, account_id: str) -> TradingMode | None:
        c = mode_changes.c
        q = select(c.to_mode).where(c.account_id == account_id).order_by(c.seq.desc()).limit(1)
        with self.engine.connect() as conn:
            value = conn.execute(q).scalar_one_or_none()
        return TradingMode(value) if value else None

    def append_mode(self, account_id: str, change: ModeChange) -> None:
        with self.engine.begin() as conn:
            self._require_account(conn, account_id)
            conn.execute(
                insert(mode_changes).values(
                    account_id=account_id,
                    from_mode=change.from_mode,
                    to_mode=change.to_mode,
                    actor=change.actor,
                    approver=change.approver,
                    at=utcnow(),
                )
            )

    def append_audit(self, entry: AuditEntry) -> None:
        with self.engine.begin() as conn:
            conn.execute(insert(audit_log).values(**entry.__dict__))

    def audit(self, limit: int = 100, *, account_id: str | None = None,
              system: bool = False) -> list[AuditEntry]:
        q = select(audit_log)
        if system:
            q = q.where(audit_log.c.account_id.is_(None))
        elif account_id is not None:
            q = q.where(audit_log.c.account_id == account_id)
        q = q.order_by(audit_log.c.seq.desc()).limit(limit)
        with self.engine.connect() as conn:
            rows = conn.execute(q).mappings().all()
        return [AuditEntry(**_row(r)) for r in rows]

    # --- Tài khoản ---

    def ensure_default_account(self) -> None:
        with self.engine.begin() as conn:
            exists = conn.execute(
                select(trading_accounts.c.account_id).where(
                    trading_accounts.c.account_id == DEFAULT_ACCOUNT_ID
                )
            ).first()
            if not exists:
                conn.execute(insert(trading_accounts).values(
                    account_id=DEFAULT_ACCOUNT_ID, name=DEFAULT_ACCOUNT_NAME,
                    created_at=utcnow(), created_by="system", price_feed=True,
                ))

    def accounts(self) -> list[TradingAccount]:
        c = trading_accounts.c
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(trading_accounts).order_by(c.created_at, c.account_id)
            ).mappings().all()
        return [TradingAccount(**_row(r)) for r in rows]

    def account(self, account_id: str) -> TradingAccount | None:
        with self.engine.connect() as conn:
            r = conn.execute(
                select(trading_accounts).where(trading_accounts.c.account_id == account_id)
            ).mappings().first()
        return TradingAccount(**_row(r)) if r else None

    def create_account(self, acc: TradingAccount) -> None:
        if self.account(acc.account_id) is not None:
            raise ConflictError(f"Tài khoản {acc.account_id} đã tồn tại")
        with self.engine.begin() as conn:
            conn.execute(insert(trading_accounts).values(**acc.__dict__))

    # --- Người dùng + thành viên ---

    def upsert_user(self, sub, username, email, display_name, at, role="USER") -> None:
        _check_user(role, "ACTIVE")
        with self.engine.begin() as conn:
            old = conn.execute(select(users.c.role).where(users.c.sub == sub)).first()
            if old:
                extra = {} if old.role == role else {"role": role, "updated_at": at}
                conn.execute(update(users).where(users.c.sub == sub).values(
                    username=username, email=email, display_name=display_name, last_login_at=at,
                    # Tạo từ Dashboard (MT-20): lần đăng nhập đầu tiên mới có first_login_at
                    first_login_at=func.coalesce(users.c.first_login_at, at), **extra,
                ))
            else:
                # Người mới: luôn ACTIVE; trạng thái chỉ đổi qua set_user_status (ADMIN).
                conn.execute(insert(users).values(
                    sub=sub, username=username, email=email, display_name=display_name,
                    first_login_at=at, last_login_at=at, role=role, status="ACTIVE",
                    updated_at=at,
                ))

    def list_users(self) -> list[UserRecord]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(users).order_by(func.lower(users.c.username))
                                ).mappings().all()
        return [UserRecord(**_row(r)) for r in rows]

    def set_user_status(self, sub: str, status: str, at: datetime) -> bool:
        _check_user("USER", status)
        with self.engine.begin() as conn:
            res = conn.execute(update(users).where(users.c.sub == sub)
                               .values(status=status, updated_at=at))
        return res.rowcount > 0

    def user(self, sub: str) -> UserRecord | None:
        with self.engine.connect() as conn:
            r = conn.execute(select(users).where(users.c.sub == sub)).mappings().first()
        return UserRecord(**_row(r)) if r else None

    def find_user(self, username_or_email: str) -> UserRecord | None:
        q = username_or_email.strip().lower()
        with self.engine.connect() as conn:
            r = conn.execute(
                select(users).where(
                    or_(func.lower(users.c.username) == q, func.lower(users.c.email) == q)
                ).limit(1)
            ).mappings().first()
        return UserRecord(**_row(r)) if r else None

    def role(self, account_id: str, sub: str) -> str | None:
        c = account_members.c
        with self.engine.connect() as conn:
            return conn.execute(
                select(c.role).where(and_(c.account_id == account_id, c.sub == sub))
            ).scalar_one_or_none()

    def members(self, account_id: str) -> list[Member]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(account_members).where(account_members.c.account_id == account_id)
            ).mappings().all()
        out = [Member(**_row(r)) for r in rows]
        return sorted(out, key=lambda m: (-ROLE_RANK[m.role], m.granted_at))

    def memberships(self, sub: str) -> list[Member]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(account_members).where(account_members.c.sub == sub)
            ).mappings().all()
        return [Member(**_row(r)) for r in rows]

    def set_member(self, m: Member) -> None:
        _check_role(m.role)
        if self.user(m.sub) is None:
            raise KeyError("Người dùng chưa đăng nhập lần nào")
        c = account_members.c
        with self.engine.begin() as conn:
            conn.execute(delete(account_members).where(
                and_(c.account_id == m.account_id, c.sub == m.sub)
            ))
            conn.execute(insert(account_members).values(**m.__dict__))

    def remove_member(self, account_id: str, sub: str) -> bool:
        c = account_members.c
        with self.engine.begin() as conn:
            res = conn.execute(delete(account_members).where(
                and_(c.account_id == account_id, c.sub == sub)
            ))
        return res.rowcount > 0

    def provision_user(self, user: UserRecord, acc: TradingAccount | None, owner: Member,
                       token_raw: str | None, at: datetime) -> str | None:
        _check_role(owner.role)
        _check_user(user.role, user.status)
        if owner.sub != user.sub or (acc is not None and owner.account_id != acc.account_id):
            raise ValueError("owner phải là người dùng mới của tài khoản mới")
        m, t = account_members.c, gateway_tokens.c
        token_id = new_id("gtk") if token_raw is not None else None
        try:
            with self.engine.begin() as conn:
                if acc is None:
                    # Nhận tài khoản có sẵn: phải tồn tại và CHƯA có chủ (kiểm trong cùng tx).
                    exists = conn.execute(select(trading_accounts.c.account_id).where(
                        trading_accounts.c.account_id == owner.account_id)).first()
                    has_owner = conn.execute(select(m.sub).where(and_(
                        m.account_id == owner.account_id, m.role == "OWNER")).limit(1)).first()
                    if exists is None or has_owner is not None:
                        raise ConflictError(
                            f"Tài khoản {owner.account_id} không nhận chủ mới được")
                conn.execute(insert(users).values(**user.__dict__))
                if acc is not None:
                    conn.execute(insert(trading_accounts).values(**acc.__dict__))
                conn.execute(insert(account_members).values(**owner.__dict__))
                conn.execute(
                    update(gateway_tokens)
                    .where(and_(t.account_id == owner.account_id, t.revoked_at.is_(None)))
                    .values(revoked_at=at)
                )
                if token_raw is not None:
                    conn.execute(insert(gateway_tokens).values(
                        token_id=token_id, account_id=owner.account_id,
                        token_sha256=token_hash(token_raw), created_at=at,
                        created_by=owner.granted_by, revoked_at=None,
                    ))
        except IntegrityError as e:
            raise ConflictError("Người dùng hoặc tài khoản đã tồn tại") from e
        return token_id

    def update_user_profile(self, sub: str, email: str, display_name: str,
                            at: datetime) -> bool:
        with self.engine.begin() as conn:
            res = conn.execute(update(users).where(users.c.sub == sub).values(
                email=email, display_name=display_name, updated_at=at))
        return res.rowcount > 0

    # --- Token Gateway ---

    def rotate_gateway_token(self, account_id: str, raw: str, by: str, at: datetime) -> str:
        c = gateway_tokens.c
        token_id = new_id("gtk")
        # Thu hồi token cũ và tạo token mới trong CÙNG transaction.
        with self.engine.begin() as conn:
            conn.execute(
                update(gateway_tokens)
                .where(and_(c.account_id == account_id, c.revoked_at.is_(None)))
                .values(revoked_at=at)
            )
            conn.execute(insert(gateway_tokens).values(
                token_id=token_id, account_id=account_id, token_sha256=token_hash(raw),
                created_at=at, created_by=by, revoked_at=None,
            ))
        return token_id

    def account_for_token(self, raw: str) -> str | None:
        t = self.gateway_token(raw)
        return t[0] if t else None

    def gateway_token(self, raw: str) -> tuple[str, str] | None:
        c = gateway_tokens.c
        with self.engine.connect() as conn:
            r = conn.execute(
                select(c.account_id, c.token_id).where(
                    and_(c.token_sha256 == token_hash(raw), c.revoked_at.is_(None))
                )
            ).first()
        return (r[0], r[1]) if r else None

    def has_gateway_tokens(self, account_id: str) -> bool:
        with self.engine.connect() as conn:
            return conn.execute(
                select(gateway_tokens.c.seq).where(gateway_tokens.c.account_id == account_id)
                .limit(1)
            ).first() is not None

    def has_active_gateway_token(self, account_id: str) -> bool:
        c = gateway_tokens.c
        with self.engine.connect() as conn:
            return conn.execute(
                select(c.seq).where(and_(c.account_id == account_id, c.revoked_at.is_(None)))
                .limit(1)
            ).first() is not None

    def revoke_gateway_tokens(self, account_id: str, at: datetime) -> int:
        c = gateway_tokens.c
        with self.engine.begin() as conn:
            res = conn.execute(
                update(gateway_tokens)
                .where(and_(c.account_id == account_id, c.revoked_at.is_(None)))
                .values(revoked_at=at)
            )
        return res.rowcount

    # --- Xin cấp token (DEC-17) ---

    def add_token_request_event(self, e: TokenRequestEvent) -> None:
        _check_token_event(e)
        with self.engine.begin() as conn:
            self._require_account(conn, e.account_id)
            conn.execute(insert(gateway_token_requests).values(**e.__dict__))

    def last_token_request(self, account_id: str) -> TokenRequestEvent | None:
        c = gateway_token_requests.c
        with self.engine.connect() as conn:
            r = conn.execute(
                select(c.account_id, c.sub, c.event, c.at, c.actor)
                .where(c.account_id == account_id).order_by(c.seq.desc()).limit(1)
            ).mappings().first()
        return TokenRequestEvent(**_row(r)) if r else None

    # --- Liên kết MT5 (MT-13) ---

    def mt5_links(self, account_id: str, limit: int = 50) -> list[Mt5Link]:
        c = mt5_links.c
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(mt5_links).where(c.account_id == account_id)
                .order_by(c.seq.desc()).limit(limit)
            ).mappings().all()
        return [Mt5Link(**_row(r)) for r in reversed(rows)]

    @staticmethod
    def _link(conn, account_id: str, link_id: str, *, lock: bool) -> Mt5Link | None:
        c = mt5_links.c
        q = select(mt5_links).where(and_(c.link_id == link_id, c.account_id == account_id))
        if lock and conn.dialect.name == "postgresql":
            q = q.with_for_update()
        r = conn.execute(q).mappings().first()
        return Mt5Link(**_row(r)) if r else None

    @staticmethod
    def _account_lock(conn, account_id: str) -> None:
        if conn.dialect.name == "postgresql":
            conn.execute(select(func.pg_advisory_xact_lock(_lock_key("mt5:" + account_id))))

    def add_pending_link(self, link: Mt5Link) -> bool:
        _check_link(link)
        if link.status != "PENDING_CONFIRM":
            raise ValueError("Liên kết mới phải ở trạng thái PENDING_CONFIRM")
        c = mt5_links.c
        try:
            with self.engine.begin() as conn:
                self._require_account(conn, link.account_id)
                self._account_lock(conn, link.account_id)
                open_rows = conn.execute(
                    select(mt5_links).where(and_(
                        c.account_id == link.account_id,
                        c.status.in_((*MT5_LINK_HELD, "PENDING_CONFIRM")),
                    ))
                ).mappings().all()
                links = [Mt5Link(**_row(r)) for r in open_rows]
                if any(x.held for x in links):
                    return False  # đổi MT5 khi đang có liên kết: MT-14 xử lý
                for x in links:
                    if x.same_identity(link.mt5_login, link.mt5_server, link.trade_mode):
                        return False
                    conn.execute(update(mt5_links).where(c.link_id == x.link_id).values(
                        status="CANCELLED", ended_at=link.created_at, ended_by="gateway",
                        end_reason="REPLACED"))
                conn.execute(insert(mt5_links).values(**link.__dict__))
        except IntegrityError:
            return False  # hai nhịp tim cùng lúc: dòng kia đã thắng
        return True

    def confirm_link(self, account_id: str, link_id: str, by: str, at: datetime) -> Mt5Link:
        c = mt5_links.c
        try:
            with self.engine.begin() as conn:
                self._account_lock(conn, account_id)
                x = self._link(conn, account_id, link_id, lock=True)
                if x is None:
                    raise Mt5LinkError("NOT_FOUND", "Không có liên kết này")
                if x.status != "PENDING_CONFIRM":
                    raise Mt5LinkError("NOT_PENDING", "Liên kết không còn chờ xác nhận")
                held = c.status.in_(MT5_LINK_HELD)
                if conn.execute(select(c.seq).where(and_(c.account_id == account_id, held))
                                .limit(1)).first():
                    raise Mt5LinkError("ACCOUNT_HELD", "Tài khoản đã có liên kết MT5")
                if conn.execute(select(c.seq).where(and_(
                        c.mt5_login == x.mt5_login,
                        func.lower(c.mt5_server) == x.mt5_server.lower(), held))
                        .limit(1)).first():
                    raise Mt5LinkError("IDENTITY_HELD", "MT5 này đã liên kết ở tài khoản khác")
                conn.execute(update(mt5_links).where(c.link_id == link_id).values(
                    status="ACTIVE", verified_at=at, verified_by=by))
        except IntegrityError as e:
            # Index duy nhất ở DB chặn hai tài khoản xác nhận cùng MT5 cùng lúc (MT-C11).
            raise Mt5LinkError("IDENTITY_HELD", "MT5 này đã liên kết ở tài khoản khác") from e
        return replace(x, status="ACTIVE", verified_at=at, verified_by=by)

    def end_link(self, account_id: str, link_id: str, status: str, by: str, at: datetime,
                 reason: str) -> Mt5Link:
        if status not in ("REVOKED", "CANCELLED"):
            raise ValueError("Chỉ kết thúc liên kết bằng REVOKED/CANCELLED")
        c = mt5_links.c
        with self.engine.begin() as conn:
            self._account_lock(conn, account_id)
            x = self._link(conn, account_id, link_id, lock=True)
            if x is None:
                raise Mt5LinkError("NOT_FOUND", "Không có liên kết này")
            if not (x.held or x.status == "PENDING_CONFIRM"):
                raise Mt5LinkError("NOT_OPEN", "Liên kết đã kết thúc")
            vals = {"status": status, "ended_at": at, "ended_by": by,
                    "end_reason": reason[:128]}
            conn.execute(update(mt5_links).where(c.link_id == link_id).values(**vals))
        return replace(x, **vals)

    def end_account_links(self, account_id: str, by: str, at: datetime, reason: str) -> int:
        c = mt5_links.c
        n = 0
        with self.engine.begin() as conn:
            self._account_lock(conn, account_id)
            base = {"ended_at": at, "ended_by": by, "end_reason": reason[:128]}
            n += conn.execute(update(mt5_links).where(and_(
                c.account_id == account_id, c.status.in_(MT5_LINK_HELD)))
                .values(status="REVOKED", **base)).rowcount
            n += conn.execute(update(mt5_links).where(and_(
                c.account_id == account_id, c.status == "PENDING_CONFIRM"))
                .values(status="CANCELLED", **base)).rowcount
        return n


def restore_safety_state(history: list[SafetyTransition]) -> tuple[SafetyState, str | None]:
    """Trạng thái khởi động từ lịch sử.

    - HALTED được giữ nguyên: restart không được tự gỡ dừng khẩn cấp.
    - ACTIVE -> PAUSED: sau restart phải kiểm tra lại rồi mới mở lệnh.
    Trả về (trạng thái, reason_code cần ghi nếu phải hạ trạng thái).
    """
    if not history:
        return SafetyState.PAUSED, None
    last = history[-1].to_state
    if last is SafetyState.ACTIVE:
        return SafetyState.ACTIVE, "STARTUP_REQUIRES_REVIEW"
    return last, None


def restore_mode(last: TradingMode | None, default: TradingMode) -> tuple[TradingMode, bool]:
    """Mode khởi động. LIVE không bao giờ được khôi phục tự động -> PAPER."""
    if last is None:
        return default, False
    last = TradingMode(last)  # chuẩn hóa: so sánh bằng `is` với chuỗi "LIVE" sẽ sai
    if last is TradingMode.LIVE:
        return TradingMode.PAPER, True
    return last, False


