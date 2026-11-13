"""Nhật ký sự kiện + job của Event Orchestrator bằng SQL (GĐ2 bước 1, migration 0014).

Cùng giao diện + quy tắc với ``gold_trading.orchestrator.model.OrchestratorStore`` (bản tham chiếu
trong bộ nhớ). Ghi trùng (cùng ``event_id`` / ``job_key``) → False, kể cả khi hai tiến trình ghi
cùng lúc (ràng buộc duy nhất của DB quyết định).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError

from gold_trading.orchestrator.model import Attempt, Event, EventType, Job, JobState
from gold_trading.storage.schema import (
    orchestrator_events,
    orchestrator_job_attempts,
    orchestrator_jobs,
)

_E = orchestrator_events.c
_J = orchestrator_jobs.c
_A = orchestrator_job_attempts.c


def _utc(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


def _req(name: str, v: datetime) -> datetime:
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError(f"{name} phải có múi giờ (UTC)")
    return v.astimezone(UTC)


def _event(m) -> Event:
    return Event(EventType(m.event_type), m.subject, m.event_version, _utc(m.occurred_at),
                 _utc(m.known_at), dict(m.payload), m.correlation_id)


def _attempt(m) -> Attempt:
    return Attempt(m.job_key, JobState(m.state), m.attempt, _utc(m.at), _utc(m.deadline_at),
                   m.error_code, m.output_ref)


class SqlOrchestratorStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # ---------------- sự kiện
    def record_event(self, e: Event, *, recorded_at: datetime) -> bool:
        recorded_at = _req("recorded_at", recorded_at)
        try:
            with self.engine.begin() as conn:
                if conn.execute(select(_E.seq).where(_E.event_id == e.event_id)).first():
                    return False
                conn.execute(orchestrator_events.insert().values(
                    event_id=e.event_id, event_type=e.event_type.value, subject=e.subject,
                    event_version=e.event_version, occurred_at=e.occurred_at,
                    known_at=e.known_at, recorded_at=recorded_at,
                    correlation_id=e.correlation_id, payload=e.payload))
        except IntegrityError:
            return False   # tiến trình khác ghi trước
        return True

    def record_events(self, events, *, recorded_at: datetime) -> int:
        """Ghi nhiều sự kiện trong một transaction (bỏ khóa đã có); đụng ghi đồng thời → ghi lại
        từng cái. Trả số sự kiện mới."""
        recorded_at = _req("recorded_at", recorded_at)
        uniq = {e.event_id: e for e in events}
        if not uniq:
            return 0
        try:
            with self.engine.begin() as conn:
                have: set[str] = set()
                ids = list(uniq)
                for i in range(0, len(ids), 500):
                    have |= set(conn.execute(select(_E.event_id).where(
                        _E.event_id.in_(ids[i:i + 500]))).scalars())
                new = [e for k, e in uniq.items() if k not in have]
                if new:
                    conn.execute(orchestrator_events.insert(), [dict(
                        event_id=e.event_id, event_type=e.event_type.value, subject=e.subject,
                        event_version=e.event_version, occurred_at=e.occurred_at,
                        known_at=e.known_at, recorded_at=recorded_at,
                        correlation_id=e.correlation_id, payload=e.payload) for e in new])
                return len(new)
        except IntegrityError:
            return sum(self.record_event(e, recorded_at=recorded_at) for e in uniq.values())

    def events(self, *, until: datetime, since: datetime | None = None,
               event_type: EventType | None = None) -> list[Event]:
        q = select(orchestrator_events).where(_E.known_at <= _req("until", until))
        if since is not None:
            q = q.where(_E.known_at > _req("since", since))
        if event_type is not None:
            q = q.where(_E.event_type == EventType(event_type).value)
        with self.engine.connect() as conn:
            rows = [_event(m) for m in conn.execute(q).mappings()]
        return sorted(rows, key=Event.order_key)

    def max_known_at(self, event_type: EventType, until: datetime) -> datetime | None:
        q = select(func.max(_E.known_at)).where(
            _E.event_type == EventType(event_type).value, _E.known_at <= _req("until", until))
        with self.engine.connect() as conn:
            return _utc(conn.execute(q).scalar())

    # ---------------- job
    def create_job(self, j: Job) -> bool:
        try:
            with self.engine.begin() as conn:
                if conn.execute(select(_J.job_key).where(_J.job_key == j.job_key)).first():
                    return False
                conn.execute(orchestrator_jobs.insert().values(
                    job_key=j.job_key, event_id=j.event_id, job_type=j.job_type,
                    analyzer_version=j.analyzer_version, correlation_id=j.correlation_id,
                    created_at=j.created_at))
        except IntegrityError:
            return False
        return True

    def create_jobs_bulk(self, jobs, attempts) -> list[str]:
        """Một transaction: bỏ khóa đã có (một truy vấn / 500 khóa), chèn job + lần thử đầu.
        Đụng ghi đồng thời → làm lại từng cái."""
        jobs = {j.job_key: j for j in jobs}
        by_key = {a.job_key: a for a in attempts}
        if not jobs:
            return []
        try:
            with self.engine.begin() as conn:
                have: set[str] = set()
                keys = list(jobs)
                for i in range(0, len(keys), 500):
                    have |= set(conn.execute(select(_J.job_key).where(
                        _J.job_key.in_(keys[i:i + 500]))).scalars())
                new = [j for k, j in jobs.items() if k not in have]
                if new:
                    conn.execute(orchestrator_jobs.insert(), [dict(
                        job_key=j.job_key, event_id=j.event_id, job_type=j.job_type,
                        analyzer_version=j.analyzer_version, correlation_id=j.correlation_id,
                        created_at=j.created_at) for j in new])
                    conn.execute(orchestrator_job_attempts.insert(), [dict(
                        job_key=a.job_key, state=a.state.value, attempt=a.attempt, at=a.at,
                        deadline_at=a.deadline_at, error_code=a.error_code,
                        output_ref=a.output_ref) for a in (by_key[j.job_key] for j in new)])
                return [j.job_key for j in new]
        except IntegrityError:
            made = []
            for k, j in jobs.items():
                if self.create_job(j):
                    made.append(k)
                    self.append_attempt(by_key[k])
            return made

    def job(self, job_key: str) -> Job | None:
        with self.engine.connect() as conn:
            m = conn.execute(select(orchestrator_jobs).where(_J.job_key == job_key)
                             ).mappings().first()
        if m is None:
            return None
        return Job(m.job_key, m.event_id, m.job_type, m.analyzer_version, m.correlation_id,
                   _utc(m.created_at))

    def jobs_created_since(self, since: datetime) -> list[Job]:
        q = (select(orchestrator_jobs).where(_J.created_at > _req("since", since))
             .order_by(_J.created_at, _J.job_key))
        with self.engine.connect() as conn:
            return [Job(m.job_key, m.event_id, m.job_type, m.analyzer_version,
                        m.correlation_id, _utc(m.created_at)) for m in conn.execute(q).mappings()]

    def append_attempt(self, a: Attempt) -> None:
        with self.engine.begin() as conn:
            if not conn.execute(select(_J.job_key).where(_J.job_key == a.job_key)).first():
                raise ValueError("job chưa tạo")
            conn.execute(orchestrator_job_attempts.insert().values(
                job_key=a.job_key, state=a.state.value, attempt=a.attempt, at=a.at,
                deadline_at=a.deadline_at, error_code=a.error_code, output_ref=a.output_ref))

    def attempts(self, job_key: str) -> list[Attempt]:
        q = (select(orchestrator_job_attempts).where(_A.job_key == job_key)
             .order_by(_A.at, _A.seq))
        with self.engine.connect() as conn:
            return [_attempt(m) for m in conn.execute(q).mappings()]

    def latest(self, job_key: str) -> Attempt | None:
        rows = self.attempts(job_key)
        return rows[-1] if rows else None
