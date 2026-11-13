"""Nhật ký lần kiểm nguồn ngoài bằng SQL (ING-30, migration 0013).

Cùng giao diện + quy tắc với ``gold_trading.ingestion.source_status.SourceCheckLog`` (bản tham
chiếu trong bộ nhớ). Bảng chỉ thêm. Cùng ``checked_at`` thì thứ tự ghi (``seq``) quyết định.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, and_, func, or_, select

from gold_trading.ingestion.source_status import (
    FATAL_ERROR_CODES,
    CheckOutcome,
    CheckSummary,
    SourceCheck,
)
from gold_trading.storage.schema import external_source_checks

_C = external_source_checks.c


def _utc(v: datetime) -> datetime:
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


def _check(m) -> SourceCheck:
    return SourceCheck(m.source, _utc(m.checked_at), CheckOutcome(m.outcome), m.error_code,
                       m.inserted, m.duplicate, m.conflict, m.invalid)


class SqlSourceCheckLog:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def record(self, check: SourceCheck) -> None:
        with self.engine.begin() as conn:
            conn.execute(external_source_checks.insert().values(
                source=check.source, checked_at=check.checked_at, outcome=check.outcome.value,
                error_code=check.error_code, inserted=check.inserted,
                duplicate=check.duplicate, conflict=check.conflict, invalid=check.invalid))

    def summary(self, source: str, as_of: datetime) -> CheckSummary:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of phải có múi giờ (UTC)")
        as_of = as_of.astimezone(UTC)
        base = [_C.source == source, _C.checked_at <= as_of]
        newest = (_C.checked_at.desc(), _C.seq.desc())
        with self.engine.connect() as conn:
            last = conn.execute(select(external_source_checks).where(*base)
                                .order_by(*newest).limit(1)).mappings().first()
            ok = conn.execute(select(_C.checked_at, _C.seq)
                              .where(*base, _C.outcome == CheckOutcome.OK.value)
                              .order_by(*newest).limit(1)).first()
            after = list(base)
            if ok is not None:
                after.append(or_(_C.checked_at > ok.checked_at,
                                 and_(_C.checked_at == ok.checked_at, _C.seq > ok.seq)))
            failures = conn.execute(select(func.count()).select_from(external_source_checks)
                                    .where(*after)).scalar_one()
            fatal = conn.execute(select(_C.error_code).where(
                *after, _C.outcome == CheckOutcome.ERROR.value,
                _C.error_code.in_(sorted(FATAL_ERROR_CODES))).order_by(*newest).limit(1)).scalar()
            invalid = conn.execute(select(_C.error_code).where(
                *after, _C.outcome == CheckOutcome.INVALID.value)
                .order_by(*newest).limit(1)).scalar()
            last_err = conn.execute(select(_C.error_code).where(
                *base, _C.error_code.is_not(None)).order_by(*newest).limit(1)).scalar()
        return CheckSummary(
            last_check=_check(last) if last is not None else None,
            last_ok_at=_utc(ok.checked_at) if ok is not None else None,
            failures_since_ok=failures, fatal_code_since_ok=fatal,
            invalid_code_since_ok=invalid, last_error_code=last_err)
