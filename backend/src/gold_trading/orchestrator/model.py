"""Mô hình sự kiện + job của Event Orchestrator (GĐ2 bước 1 — ORC-03, ORC-06, ORC-08).

Thiết kế: ``docs/thiet-ke/25-event-orchestrator.md``. Bản trong bộ nhớ ở đây (test / tham chiếu);
bản SQL ở ``gold_trading.storage.orchestrator`` — cùng interface, cùng bộ test.
"""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from gold_trading.ingestion.point_in_time import canonical_json

MAX_SUBJECT = 256
MAX_VERSION = 64
MAX_PAYLOAD = 16 * 1024
ERROR_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class EventType(StrEnum):
    CANDLE_CLOSED = "CANDLE_CLOSED"
    CALENDAR_UPDATED = "CALENDAR_UPDATED"
    ACTUAL_RELEASED = "ACTUAL_RELEASED"
    MACRO_UPDATED = "MACRO_UPDATED"
    POSITIONING_UPDATED = "POSITIONING_UPDATED"
    NEWS_PUBLISHED = "NEWS_PUBLISHED"
    OUTPUT_EXPIRED = "OUTPUT_EXPIRED"      # kết quả analyst hết hạn mà chưa có kết quả mới (ORC-07)


class JobState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"            # lần thử lỗi, còn được thử lại
    DEAD = "DEAD"                # dead-letter: hết lượt / lỗi không thử lại
    NO_HANDLER = "NO_HANDLER"    # loại job chưa có bộ xử lý (analyst GĐ3) — không giả kết quả
    SUPERSEDED = "SUPERSEDED"    # debounce: có sự kiện mới hơn cùng chủ thể


TERMINAL = frozenset({JobState.SUCCEEDED, JobState.DEAD, JobState.NO_HANDLER,
                      JobState.SUPERSEDED})


def _utc(name: str, v: datetime | None) -> datetime | None:
    if v is None:
        return None
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError(f"{name} phải có múi giờ (UTC)")
    return v.astimezone(UTC)


def event_id_for(event_type: str, subject: str, version: str) -> str:
    return hashlib.sha256(f"{event_type}|{subject}|{version}".encode()).hexdigest()[:40]


@dataclass(frozen=True)
class Event:
    event_type: EventType
    subject: str
    event_version: str
    occurred_at: datetime
    known_at: datetime
    payload: dict = field(default_factory=dict)
    correlation_id: str | None = None   # None → chính event_id (sự kiện gốc)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_type", EventType(self.event_type))
        object.__setattr__(self, "occurred_at", _utc("occurred_at", self.occurred_at))
        object.__setattr__(self, "known_at", _utc("known_at", self.known_at))
        if not self.subject or len(self.subject) > MAX_SUBJECT or "\x00" in self.subject:
            raise ValueError("subject không hợp lệ")
        if not self.event_version or len(self.event_version) > MAX_VERSION:
            raise ValueError("event_version không hợp lệ")
        if len(canonical_json(self.payload).encode()) > MAX_PAYLOAD:
            raise ValueError("payload sự kiện quá lớn (chỉ chứa tham chiếu)")
        if self.correlation_id is None:
            object.__setattr__(self, "correlation_id", self.event_id)

    @property
    def event_id(self) -> str:
        return event_id_for(self.event_type.value, self.subject, self.event_version)

    def order_key(self) -> tuple:
        """Thứ tự nhân quả toàn phần, ổn định khi replay (2-C02)."""
        return (self.known_at, self.event_type.value, self.subject, self.event_version)


def job_key_for(event: Event, job_type: str, analyzer_version: str) -> str:
    """ORC-03: eventType + subject + eventVersion + analyzerVersion (+ loại job)."""
    return (f"{event.event_type.value}|{event.subject}|{event.event_version}|"
            f"{job_type}@{analyzer_version}")


@dataclass(frozen=True)
class Job:
    job_key: str
    event_id: str
    job_type: str
    analyzer_version: str
    correlation_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", _utc("created_at", self.created_at))
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,47}", self.job_type):
            raise ValueError(f"job_type không hợp lệ: {self.job_type!r}")
        if len(self.job_key) > 512 or len(self.analyzer_version) > 32:
            raise ValueError("job_key / analyzer_version quá dài")


@dataclass(frozen=True)
class Attempt:
    job_key: str
    state: JobState
    attempt: int
    at: datetime
    deadline_at: datetime | None = None
    error_code: str | None = None
    output_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", JobState(self.state))
        object.__setattr__(self, "at", _utc("at", self.at))
        object.__setattr__(self, "deadline_at", _utc("deadline_at", self.deadline_at))
        if self.attempt < 0:
            raise ValueError("attempt < 0")
        if self.error_code is not None and not ERROR_CODE_RE.match(self.error_code):
            # Chỉ mã ngắn — không bao giờ ghi thông điệp lỗi gốc (có thể chứa khóa / URL).
            raise ValueError("error_code phải là mã ngắn [A-Z0-9_]")
        if self.state in (JobState.FAILED, JobState.DEAD) and self.error_code is None:
            raise ValueError("FAILED / DEAD phải có error_code")
        if self.output_ref is not None and len(self.output_ref) > 256:
            raise ValueError("output_ref quá dài")


@dataclass(frozen=True)
class JobRow:
    """Một job + lần thử mới nhất + sự kiện gây ra (trang trạng thái pipeline, DSH-08)."""

    job: Job
    last: Attempt
    event_type: str
    subject: str
    attempts: int          # số lần chạy thật (attempt lớn nhất)


class OrchestratorStore:
    """Bản trong bộ nhớ. An toàn luồng."""

    def __init__(self) -> None:
        self._events: dict[str, tuple[Event, datetime]] = {}
        self._jobs: dict[str, Job] = {}
        self._attempts: list[Attempt] = []
        self._lock = threading.Lock()

    # ---------------- sự kiện
    def record_event(self, e: Event, *, recorded_at: datetime) -> bool:
        """Ghi sự kiện; đã có cùng ``event_id`` → False (không đổi gì)."""
        _utc("recorded_at", recorded_at)
        with self._lock:
            if e.event_id in self._events:
                return False
            self._events[e.event_id] = (e, recorded_at)
            return True

    def record_events(self, events, *, recorded_at: datetime) -> int:
        """Ghi nhiều sự kiện; trả số sự kiện mới (trùng → bỏ qua)."""
        return sum(self.record_event(e, recorded_at=recorded_at) for e in events)

    def events(self, *, until: datetime, since: datetime | None = None,
               event_type: EventType | None = None) -> list[Event]:
        """Sự kiện có ``since < known_at <= until``, theo thứ tự nhân quả."""
        until = _utc("until", until)
        since = _utc("since", since)
        with self._lock:
            out = [e for e, _ in self._events.values()
                   if e.known_at <= until and (since is None or e.known_at > since)
                   and (event_type is None or e.event_type is event_type)]
        return sorted(out, key=Event.order_key)

    def max_known_at(self, event_type: EventType, until: datetime) -> datetime | None:
        until = _utc("until", until)
        with self._lock:
            ts = [e.known_at for e, _ in self._events.values()
                  if e.event_type is event_type and e.known_at <= until]
        return max(ts, default=None)

    # ---------------- job
    def create_job(self, j: Job) -> bool:
        with self._lock:
            if j.job_key in self._jobs:
                return False
            self._jobs[j.job_key] = j
            return True

    def create_jobs_bulk(self, jobs, attempts) -> list[str]:
        """Tạo nhiều job + lần thử đầu; trả các ``job_key`` vừa tạo (trùng → bỏ qua)."""
        made = []
        by_key = {a.job_key: a for a in attempts}
        for j in jobs:
            if self.create_job(j):
                made.append(j.job_key)
                self.append_attempt(by_key[j.job_key])
        return made

    def open_jobs_since(self, since: datetime) -> list[tuple[Job, Attempt]]:
        """Job tạo sau ``since`` mà lần thử mới nhất chưa kết thúc (khôi phục khi khởi động)."""
        out = []
        for j in self.jobs_created_since(since):
            last = self.latest(j.job_key)
            if last is not None and last.state not in TERMINAL:
                out.append((j, last))
        return out

    def append_attempts(self, attempts) -> None:
        for a in attempts:
            self.append_attempt(a)

    def job(self, job_key: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_key)

    def jobs_created_since(self, since: datetime) -> list[Job]:
        since = _utc("since", since)
        with self._lock:
            return sorted((j for j in self._jobs.values() if j.created_at > since),
                          key=lambda j: (j.created_at, j.job_key))

    def append_attempt(self, a: Attempt) -> None:
        with self._lock:
            if a.job_key not in self._jobs:
                raise ValueError("job chưa tạo")
            self._attempts.append(a)

    def attempts(self, job_key: str) -> list[Attempt]:
        with self._lock:
            rows = [a for a in self._attempts if a.job_key == job_key]
        return sorted(rows, key=lambda a: a.at)   # sort ổn định: cùng giờ giữ thứ tự ghi

    def latest(self, job_key: str) -> Attempt | None:
        rows = self.attempts(job_key)
        return rows[-1] if rows else None

    def job_rows(self, since: datetime, *, states=None, limit: int | None = None
                 ) -> list[JobRow]:
        """Job tạo sau ``since`` + lần thử mới nhất (mới nhất trước); lọc theo trạng thái mới
        nhất (``states``), tối đa ``limit`` dòng."""
        since = _utc("since", since)
        with self._lock:
            jobs = [j for j in self._jobs.values() if j.created_at > since]
            ev = {k: e for k, (e, _) in self._events.items()}
            att: dict[str, list[Attempt]] = {}
            for a in self._attempts:
                if a.job_key in {j.job_key for j in jobs}:
                    att.setdefault(a.job_key, []).append(a)
        out = []
        for j in jobs:
            rows = sorted(att.get(j.job_key, []), key=lambda a: a.at)
            if not rows:
                continue
            e = ev.get(j.event_id)
            out.append(JobRow(j, rows[-1], e.event_type.value if e else "?",
                              e.subject if e else "?", max(a.attempt for a in rows)))
        if states is not None:
            want = {JobState(x) for x in states}
            out = [r for r in out if r.last.state in want]
        out.sort(key=lambda r: (r.job.created_at, r.job.job_key), reverse=True)
        return out if limit is None else out[:limit]
