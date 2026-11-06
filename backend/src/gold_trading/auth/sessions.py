"""Phiên đăng nhập và giao dịch đăng nhập, lưu TRONG BỘ NHỚ (không ghi DB, không vào bản sao lưu).

Cookie chỉ chứa id ngẫu nhiên; bộ nhớ chỉ lưu băm SHA-256 của id. Backend khởi động lại → mọi
người đăng nhập lại (mặc định an toàn). Backend chạy một tiến trình.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta

LOGIN_TX_TTL = timedelta(minutes=10)
MAX_PENDING_LOGINS = 1000


def _h(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class Session:
    sub: str
    username: str
    email: str | None
    display_name: str | None
    roles: frozenset[str]
    created_at: datetime
    last_seen: datetime
    last_refresh: datetime
    refresh_token: str | None = field(repr=False)
    id_token: str | None = field(repr=False)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    @property
    def is_admin(self) -> bool:
        return "ADMIN" in self.roles


@dataclass(frozen=True)
class LoginTx:
    state_hash: str
    code_verifier: str = field(repr=False)
    nonce: str = field(repr=False)
    next_path: str
    created_at: datetime


class SessionStore:
    def __init__(self, *, max_age: timedelta, idle: timedelta) -> None:
        self.max_age = max_age
        self.idle = idle
        self._sessions: dict[str, Session] = {}
        self._logins: dict[str, LoginTx] = {}
        self._lock = threading.Lock()

    # --- Phiên ---

    def create(self, session: Session) -> str:
        raw = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[_h(raw)] = session
        return raw

    def get(self, raw: str | None, now: datetime) -> Session | None:
        """Phiên còn hiệu lực (và cập nhật thời điểm hoạt động), hoặc None."""
        if not raw:
            return None
        key = _h(raw)
        with self._lock:
            s = self._sessions.get(key)
            if s is None:
                return None
            if now - s.created_at > self.max_age or now - s.last_seen > self.idle:
                del self._sessions[key]
                return None
            s.last_seen = now
            return s

    def delete(self, raw: str | None) -> Session | None:
        if not raw:
            return None
        with self._lock:
            return self._sessions.pop(_h(raw), None)

    def delete_session(self, session: Session) -> None:
        with self._lock:
            for k, v in list(self._sessions.items()):
                if v is session:
                    del self._sessions[k]

    def delete_by_sub(self, sub: str) -> int:
        with self._lock:
            keys = [k for k, v in self._sessions.items() if v.sub == sub]
            for k in keys:
                del self._sessions[k]
            return len(keys)

    def purge(self, now: datetime) -> None:
        with self._lock:
            for k, s in list(self._sessions.items()):
                if now - s.created_at > self.max_age or now - s.last_seen > self.idle:
                    del self._sessions[k]
            for k, tx in list(self._logins.items()):
                if now - tx.created_at > LOGIN_TX_TTL:
                    del self._logins[k]

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    # --- Giao dịch đăng nhập (state → verifier, nonce, next), mỗi state dùng một lần ---

    def put_login(self, state: str, *, code_verifier: str, nonce: str, next_path: str,
                  now: datetime) -> None:
        self.purge(now)
        with self._lock:
            if len(self._logins) >= MAX_PENDING_LOGINS:
                # Chống bị làm đầy bộ nhớ: bỏ giao dịch cũ nhất.
                oldest = min(self._logins.values(), key=lambda t: t.created_at)
                del self._logins[oldest.state_hash]
            h = _h(state)
            self._logins[h] = LoginTx(h, code_verifier, nonce, next_path, now)

    def pop_login(self, state: str | None, now: datetime) -> LoginTx | None:
        if not state:
            return None
        with self._lock:
            tx = self._logins.pop(_h(state), None)
        if tx is None or now - tx.created_at > LOGIN_TX_TTL:
            return None
        return tx
