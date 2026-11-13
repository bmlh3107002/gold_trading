"""Store point-in-time dùng chung cho nguồn KHÔNG phải nến (ING-13, DB-08).

Bản trong bộ nhớ ở đây (test/dev, cũng là bản tham chiếu); bản SQL ở
``gold_trading.storage.external_records``, cùng interface và cùng quy tắc:

- Chỉ thêm mới. Định danh bản ghi ``(source, logical_key, revision)``.
- Gửi lại y hệt (cùng nội dung, khác ``ingested_at``) → ``DUPLICATE``, giữ bản đầu (idempotent:
  nạp lại → cùng kết quả).
- Cùng định danh mà khác nội dung, hoặc trùng ``record_id`` của bản ghi khác → ``CONFLICT``,
  KHÔNG ghi đè, đưa vào cách ly (nguồn sửa số phải thành revision mới).
- Không hợp lệ (kind lạ, số NaN/vô cực, quá dài, không phải JSON) → ``INVALID``, cách ly.
- Đọc tại ``as_of``: chỉ bản ghi có ``known_at <= as_of``; mỗi dữ kiện lấy revision lớn nhất
  trong số đã biết. Revision đến sau không viết lại quá khứ.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from gold_trading.contracts.records import EXTERNAL_KINDS, NormalizedRecord

MAX_SOURCE_LEN = 64
MAX_KEY_LEN = 256
MAX_RECORD_ID_LEN = 256
MAX_RAW_REF_LEN = 1024
MAX_JSON_BYTES = 256 * 1024  # payload hoặc raw sau khi tuần tự hóa
# Lý do coi là CONFLICT (dữ kiện đã có, nội dung khác); lý do khác là INVALID.
CONFLICT_REASONS = frozenset({"REVISION_CONFLICT", "RECORD_ID_CONFLICT", "KIND_CHANGED"})


class DuplicateRecordError(ValueError):
    """Giữ cho tương thích; store không còn ném lỗi này (dùng ``AppendOutcome.CONFLICT``)."""


class AppendOutcome(StrEnum):
    INSERTED = "INSERTED"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"
    INVALID = "INVALID"


@dataclass(frozen=True)
class AppendResult:
    outcome: AppendOutcome
    reason: str | None = None


@dataclass
class AppendCounts:
    inserted: int = 0
    duplicate: int = 0
    conflict: int = 0
    invalid: int = 0
    reasons: list[str] = field(default_factory=list)

    def add(self, r: AppendResult) -> None:
        setattr(self, r.outcome.value.lower(), getattr(self, r.outcome.value.lower()) + 1)
        if r.reason:
            self.reasons.append(r.reason)


@dataclass(frozen=True)
class QuarantineEntry:
    received_at: datetime
    source: str
    kind: str
    reason: str
    raw: Any


def _check_finite(v: Any) -> bool:
    if isinstance(v, float):
        return math.isfinite(v)
    if isinstance(v, dict):
        return all(_check_finite(x) for x in v.values())
    if isinstance(v, list | tuple):
        return all(_check_finite(x) for x in v)
    return True


def canonical_json(v: Any) -> str:
    """JSON chuẩn (khóa sắp xếp, không NaN) — dùng cho fingerprint và kiểm cỡ."""
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def fingerprint(r: NormalizedRecord) -> str:
    """Băm NỘI DUNG dữ kiện. Không gồm ingested_at / raw_ref / cờ / trạng thái nguồn:
    nạp lại cùng số liệu lúc khác vẫn ra cùng fingerprint."""
    body = {
        "kind": r.kind,
        "event_time": r.event_time.isoformat(),
        "available_at": r.available_at.isoformat() if r.available_at else None,
        "payload_version": r.payload_version,
        "payload": r.payload,
    }
    return hashlib.sha256(canonical_json(body).encode()).hexdigest()


def _has_nul(s: str) -> bool:
    # Postgres không lưu được ký tự NUL trong text/JSONB (JSON hóa thành "\u0000").
    return "\x00" in s or "\\u0000" in s


def validate(r: NormalizedRecord, raw: Any = None) -> str | None:
    """Lý do cách ly, hoặc None nếu hợp lệ."""
    if any(_has_nul(v) for v in (r.record_id, r.source, r.kind, r.logical_key, r.raw_ref,
                                 r.payload_version, *r.quality_flags)):
        return "FIELD_NUL_CHAR"
    if r.kind not in EXTERNAL_KINDS:
        return "KIND_INVALID"
    if not r.source or len(r.source) > MAX_SOURCE_LEN:
        return "SOURCE_INVALID"
    if len(r.logical_key) > MAX_KEY_LEN or len(r.record_id) > MAX_RECORD_ID_LEN \
            or len(r.raw_ref) > MAX_RAW_REF_LEN or len(r.payload_version) > 32:
        return "FIELD_TOO_LONG"
    for name, v in (("PAYLOAD", r.payload), ("RAW", raw)):
        if not _check_finite(v):
            return f"{name}_NON_FINITE"
        try:
            size = len(canonical_json(v).encode())
        except (TypeError, ValueError):
            return f"{name}_NOT_JSON"
        if size > MAX_JSON_BYTES:
            return f"{name}_TOO_LARGE"
        if _has_nul(canonical_json(v)):
            return f"{name}_NUL_CHAR"
    return None


def safe_raw(raw: Any) -> Any:
    """Bản raw lưu được vào cột JSON của bảng cách ly (không bao giờ làm hỏng việc cách ly)."""
    try:
        s = canonical_json(raw)
    except (TypeError, ValueError):
        s = None
    if s is not None and len(s.encode()) <= MAX_JSON_BYTES and not _has_nul(s):
        return raw
    text = repr(raw)  # repr thoát NUL thành "\x00"
    return {"repr_truncated": text[:4096], "original_len": len(text)}


def clean_label(s: str, n: int) -> str:
    """Nguồn/kind ghi vào bảng cách ly: bỏ NUL, cắt độ dài (không làm hỏng việc cách ly)."""
    return s.replace("\x00", "?")[:n]


def quarantine_raw(r: NormalizedRecord, raw: Any) -> Any:
    """Nội dung lưu vào cách ly: bản ghi + raw, không bao giờ ném lỗi (kể cả payload hỏng)."""
    try:
        rec: Any = r.model_dump(mode="json")
    except Exception:  # payload không tuần tự hóa được
        rec = r.model_dump(mode="json", exclude={"payload"}) | {"payload": safe_raw(r.payload)}
    return safe_raw({"record": rec, "raw": safe_raw(raw)})


def pick_latest(records: Iterable[NormalizedRecord], as_of: datetime) -> list[NormalizedRecord]:
    """Mỗi (source, logical_key): revision lớn nhất trong số bản ghi đã biết tại ``as_of``."""
    best: dict[tuple[str, str], NormalizedRecord] = {}
    for r in records:
        if r.known_at > as_of:
            continue
        k = (r.source, r.logical_key)
        if k not in best or r.revision > best[k].revision:
            best[k] = r
    return sorted(best.values(), key=lambda r: (r.event_time, r.source, r.logical_key))


class PointInTimeStore:
    """Bản trong bộ nhớ. An toàn luồng."""

    def __init__(self) -> None:
        self._by_identity: dict[tuple[str, str, int], tuple[NormalizedRecord, str]] = {}
        self._ids: set[str] = set()
        self._kind_of: dict[tuple[str, str], str] = {}
        self.quarantine: list[QuarantineEntry] = []
        self._lock = threading.Lock()

    def append(self, record: NormalizedRecord, raw: Any = None, *,
               received_at: datetime | None = None) -> AppendResult:
        reason = validate(record, raw)
        with self._lock:
            if reason is None:
                fp = fingerprint(record)
                ident = (record.source, record.logical_key, record.revision)
                existing = self._by_identity.get(ident)
                if existing is not None:
                    old, old_fp = existing
                    if old_fp == fp and old.record_id == record.record_id:
                        return AppendResult(AppendOutcome.DUPLICATE)
                    reason = "REVISION_CONFLICT"
                elif record.record_id in self._ids:
                    reason = "RECORD_ID_CONFLICT"
                elif self._kind_of.get(ident[:2], record.kind) != record.kind:
                    reason = "KIND_CHANGED"
                else:
                    self._by_identity[ident] = (record, fp)
                    self._ids.add(record.record_id)
                    self._kind_of[ident[:2]] = record.kind
                    return AppendResult(AppendOutcome.INSERTED)
            self.quarantine.append(QuarantineEntry(
                received_at or record.ingested_at, clean_label(record.source, MAX_SOURCE_LEN),
                clean_label(record.kind, 16), reason, quarantine_raw(record, raw)))
        outcome = AppendOutcome.CONFLICT if reason in CONFLICT_REASONS else AppendOutcome.INVALID
        return AppendResult(outcome, reason)

    def extend(self, records: Iterable[NormalizedRecord]) -> AppendCounts:
        counts = AppendCounts()
        for r in records:
            counts.add(self.append(r))
        return counts

    def as_of(self, as_of: datetime, *, source: str | None = None, kind: str | None = None,
              logical_key: str | None = None, event_from: datetime | None = None,
              event_to: datetime | None = None) -> list[NormalizedRecord]:
        """Bản mới nhất (đã biết tại ``as_of``) của mỗi dữ kiện khớp bộ lọc.

        ``event_from <= event_time < event_to`` nếu có.
        """
        with self._lock:
            rows = [r for r, _ in self._by_identity.values()
                    if (source is None or r.source == source)
                    and (kind is None or r.kind == kind)
                    and (logical_key is None or r.logical_key == logical_key)
                    and (event_from is None or r.event_time >= event_from)
                    and (event_to is None or r.event_time < event_to)]
        return pick_latest(rows, as_of)

    def latest_event_time(self, source: str, as_of: datetime) -> datetime | None:
        """``event_time`` lớn nhất (không quá ``as_of``) trong các bản ghi đã biết tại ``as_of``
        — đo độ cũ dữ liệu cho ``data_ttl`` (ING-30). Nạp bù số cũ không làm nguồn "mới"."""
        with self._lock:
            times = [r.event_time for r, _ in self._by_identity.values()
                     if r.source == source and r.known_at <= as_of and r.event_time <= as_of]
        return max(times, default=None)

    def history(self, source: str, logical_key: str, as_of: datetime) -> list[NormalizedRecord]:
        """Mọi revision đã biết tại ``as_of`` của một dữ kiện, theo revision tăng dần (ING-19)."""
        with self._lock:
            rows = [r for (s, k, _), (r, _) in self._by_identity.items()
                    if s == source and k == logical_key and r.known_at <= as_of]
        return sorted(rows, key=lambda r: r.revision)
