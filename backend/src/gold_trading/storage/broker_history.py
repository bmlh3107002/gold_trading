"""KN-05 (đánh giá độc lập; GW-09): lịch sử thông số broker + số liệu tài khoản — chỉ thêm.

Trước đây nhịp tim Gateway chỉ giữ trong bộ nhớ (``GatewayMonitor``) → không biết swap / đòn bẩy /
giá trị hợp đồng **tại một thời điểm trong quá khứ** (GĐ5 RSK-03/08/09, GĐ6 chi phí qua đêm, GĐ9
đối soát). Ở đây:

- ``broker_spec_history``: một dòng **mỗi khi thông số đổi** (so với dòng gần nhất cùng tài khoản +
  danh tính MT5 + mã broker). Đổi A → B → A ghi đủ ba dòng. ``observed_at`` = lúc backend nhận
  (đã biết từ lúc này — point-in-time).
- ``account_equity_hourly``: dòng **đầu tiên mỗi giờ UTC** (balance / equity / margin / đòn bẩy).

``None`` = Gateway không đọc được, **không phải 0**; lưu nguyên ``NULL``, không đoán.
Thiết kế: docs/thiet-ke/34-lich-su-thong-so-broker.md
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import and_, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from gold_trading.storage.schema import account_equity_hourly, broker_spec_history

SPEC_FIELDS = ("digits", "point", "contract_size", "volume_min", "volume_max", "volume_step",
               "currency_profit", "stops_level", "freeze_level", "swap_mode", "swap_long",
               "swap_short", "swap_rollover3days", "leverage", "account_currency")
EQUITY_FIELDS = ("currency", "balance", "equity", "margin", "margin_free", "margin_level",
                 "leverage")


def _utc(v: datetime) -> datetime:
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError("thời điểm phải có múi giờ (UTC)")
    return v.astimezone(UTC)


def _db(v: datetime) -> datetime:
    """Giá trị đọc từ DB: SQLite trả giờ không múi (đã ghi dạng UTC) → gắn UTC."""
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


def spec_hash(spec: Mapping[str, Any]) -> str:
    missing = set(SPEC_FIELDS) - set(spec)
    extra = set(spec) - set(SPEC_FIELDS)
    if missing or extra:
        raise ValueError(f"thông số sai trường: thiếu {sorted(missing)}, thừa {sorted(extra)}")
    canon = json.dumps({k: spec[k] for k in SPEC_FIELDS}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


@dataclass(frozen=True)
class SpecKey:
    account_id: str
    mt5_login: int
    mt5_server: str
    broker_symbol: str


@dataclass(frozen=True)
class SpecRow:
    key: SpecKey
    observed_at: datetime
    spec: dict[str, Any]
    spec_hash: str
    gateway_version: str


class BrokerHistoryStore(Protocol):
    def record_spec(self, key: SpecKey, spec: Mapping[str, Any], *, observed_at: datetime,
                    gateway_version: str) -> bool: ...
    def spec_at(self, account_id: str, broker_symbol: str, at: datetime) -> SpecRow | None: ...
    def specs(self, account_id: str) -> list[SpecRow]: ...
    def record_equity(self, account_id: str, mt5_login: int, mt5_server: str,
                      values: Mapping[str, Any], *, observed_at: datetime) -> bool: ...
    def equity_rows(self, account_id: str) -> list[dict[str, Any]]: ...


def _hour(t: datetime) -> datetime:
    return t.replace(minute=0, second=0, microsecond=0)


def _check_equity(values: Mapping[str, Any]) -> dict[str, Any]:
    if set(values) != set(EQUITY_FIELDS):
        raise ValueError(f"số liệu tài khoản sai trường: {sorted(values)}")
    return {k: values[k] for k in EQUITY_FIELDS}


class InMemoryBrokerHistoryStore:
    def __init__(self) -> None:
        self._specs: list[SpecRow] = []
        self._equity: dict[tuple[str, int, str, datetime], dict[str, Any]] = {}
        self._lock = threading.Lock()

    def record_spec(self, key, spec, *, observed_at, gateway_version):
        h, t = spec_hash(spec), _utc(observed_at)
        with self._lock:
            last = next((r for r in reversed(self._specs) if r.key == key), None)
            if last is not None and last.spec_hash == h:
                return False
            if last is not None and t < last.observed_at:
                raise ValueError("observed_at lùi về trước dòng đã ghi")
            self._specs.append(SpecRow(key, t, {k: spec[k] for k in SPEC_FIELDS}, h,
                                       gateway_version))
            return True

    def spec_at(self, account_id, broker_symbol, at):
        at = _utc(at)
        with self._lock:
            rows = [r for r in self._specs if r.key.account_id == account_id
                    and r.key.broker_symbol == broker_symbol and r.observed_at <= at]
        return rows[-1] if rows else None

    def specs(self, account_id):
        with self._lock:
            return [r for r in self._specs if r.key.account_id == account_id]

    def record_equity(self, account_id, mt5_login, mt5_server, values, *, observed_at):
        t = _utc(observed_at)
        k = (account_id, mt5_login, mt5_server, _hour(t))
        row = _check_equity(values)
        with self._lock:
            if k in self._equity:
                return False
            self._equity[k] = {"account_id": account_id, "mt5_login": mt5_login,
                               "mt5_server": mt5_server, "hour": k[3], "observed_at": t, **row}
            return True

    def equity_rows(self, account_id):
        with self._lock:
            return sorted((dict(v) for v in self._equity.values()
                           if v["account_id"] == account_id),
                          key=lambda r: (r["hour"], r["mt5_server"], r["mt5_login"]))


class SqlBrokerHistoryStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._lock = threading.Lock()   # một tiến trình backend: tránh hai nhịp tim ghi trùng

    @staticmethod
    def _row(m) -> SpecRow:
        key = SpecKey(m.account_id, int(m.mt5_login), m.mt5_server, m.broker_symbol)
        return SpecRow(key, _db(m.observed_at), {k: getattr(m, k) for k in SPEC_FIELDS},
                       m.spec_hash, m.gateway_version)

    def _last(self, conn, key: SpecKey):
        c = broker_spec_history.c
        return conn.execute(
            select(broker_spec_history).where(
                c.account_id == key.account_id, c.mt5_login == key.mt5_login,
                c.mt5_server == key.mt5_server, c.broker_symbol == key.broker_symbol)
            .order_by(c.observed_at.desc(), c.seq.desc()).limit(1)).first()

    def record_spec(self, key, spec, *, observed_at, gateway_version):
        h, t = spec_hash(spec), _utc(observed_at)
        with self._lock, self.engine.begin() as conn:
            last = self._last(conn, key)
            if last is not None and last.spec_hash == h:
                return False
            if last is not None and t < _db(last.observed_at):
                raise ValueError("observed_at lùi về trước dòng đã ghi")
            conn.execute(insert(broker_spec_history).values(
                account_id=key.account_id, mt5_login=key.mt5_login, mt5_server=key.mt5_server,
                broker_symbol=key.broker_symbol, observed_at=t, spec_hash=h,
                gateway_version=gateway_version, **{k: spec[k] for k in SPEC_FIELDS}))
            return True

    def spec_at(self, account_id, broker_symbol, at):
        c = broker_spec_history.c
        with self.engine.connect() as conn:
            m = conn.execute(select(broker_spec_history).where(
                c.account_id == account_id, c.broker_symbol == broker_symbol,
                c.observed_at <= _utc(at)).order_by(c.observed_at.desc(), c.seq.desc())
                .limit(1)).first()
        return self._row(m) if m is not None else None

    def specs(self, account_id):
        c = broker_spec_history.c
        with self.engine.connect() as conn:
            rows = conn.execute(select(broker_spec_history).where(c.account_id == account_id)
                                .order_by(c.observed_at, c.seq)).all()
        return [self._row(m) for m in rows]

    def record_equity(self, account_id, mt5_login, mt5_server, values, *, observed_at):
        t = _utc(observed_at)
        row = _check_equity(values)
        c = account_equity_hourly.c
        where = and_(c.account_id == account_id, c.mt5_login == mt5_login,
                     c.mt5_server == mt5_server, c.hour == _hour(t))
        with self.engine.begin() as conn:
            if conn.execute(select(c.hour).where(where)).first() is not None:
                return False
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(account_equity_hourly).values(
                    account_id=account_id, mt5_login=mt5_login, mt5_server=mt5_server,
                    hour=_hour(t), observed_at=t, **row))
            return True
        except IntegrityError:
            # Chỉ coi là "đã có" khi dòng của giờ đó thật sự tồn tại; lỗi khác (CHECK…) ném ra.
            with self.engine.connect() as conn:
                if conn.execute(select(c.hour).where(where)).first() is not None:
                    return False
            raise

    def equity_rows(self, account_id):
        c = account_equity_hourly.c
        with self.engine.connect() as conn:
            rows = conn.execute(select(account_equity_hourly).where(c.account_id == account_id)
                                .order_by(c.hour, c.mt5_server, c.mt5_login)).all()
        return [{**m._mapping, "hour": _db(m.hour), "observed_at": _db(m.observed_at)}
                for m in rows]
