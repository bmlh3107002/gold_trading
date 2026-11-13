"""Tổng quan trạng thái các nguồn dữ liệu ngoài cho trang "Nguồn dữ liệu" (GĐ1 bước 10e, DSH-09).

Chỉ ĐỌC: nhật ký lần kiểm (ING-30), store point-in-time, bảng cách ly. Trạng thái tính lại tại
``as_of`` bằng đúng hàm ``evaluate`` mà phần còn lại của hệ thống dùng — trang web không có quy tắc
riêng. Thiết kế: ``docs/thiet-ke/22-trang-nguon-du-lieu.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from gold_trading.ingestion.source_status import SourceRegistry, evaluate
from gold_trading.ingestion.source_terms import SOURCE_TERMS, SourceTerms

QUARANTINE_WINDOW = timedelta(days=7)


@dataclass(frozen=True)
class SourceOverview:
    name: str
    kind: str
    provider: str
    terms_status: str              # VERIFIED / NEEDS_REVIEW / BLOCKED / UNKNOWN
    enabled: bool
    status: str                    # HEALTHY / STALE / MISSING / INVALID
    reason: str
    flags: tuple[str, ...]
    last_check_at: datetime | None
    last_ok_at: datetime | None
    last_error_code: str | None
    failures_since_ok: int
    latest_event_at: datetime | None
    fetch_ttl_seconds: int
    data_ttl_seconds: int | None
    receive_age_seconds: int | None   # as_of − lần nhận OK cuối ("lần nhận cuối cách đây")
    data_age_seconds: int | None      # as_of − event_time mới nhất ("độ trễ dữ liệu")
    quarantine_7d: int
    quarantine_total: int


def _age(as_of: datetime, t: datetime | None) -> int | None:
    return None if t is None else max(0, int((as_of - t).total_seconds()))


def overview(registry: SourceRegistry, store, check_log, as_of: datetime,
             terms: dict[str, SourceTerms] | None = None) -> list[SourceOverview]:
    terms = SOURCE_TERMS if terms is None else terms
    q7 = store.quarantine_counts(as_of, as_of - QUARANTINE_WINDOW)
    qall = store.quarantine_counts(as_of)
    out = []
    for name in registry.names():
        spec = registry.get(name)
        latest = store.latest_event_time(name, as_of)
        h = evaluate(name, spec, check_log.summary(name, as_of), as_of, latest)
        t = terms.get(spec.provider)
        out.append(SourceOverview(
            name=name, kind=spec.kind, provider=spec.provider,
            terms_status=t.status.value if t else "UNKNOWN", enabled=spec.enabled,
            status=h.status.value, reason=h.reason, flags=tuple(sorted(h.flags)),
            last_check_at=h.last_check_at, last_ok_at=h.last_ok_at,
            last_error_code=h.last_error_code, failures_since_ok=h.failures_since_ok,
            latest_event_at=h.latest_event_at,
            fetch_ttl_seconds=int(spec.fetch_ttl.total_seconds()),
            data_ttl_seconds=int(spec.data_ttl.total_seconds()) if spec.data_ttl else None,
            receive_age_seconds=_age(as_of, h.last_ok_at),
            data_age_seconds=_age(as_of, latest),
            quarantine_7d=q7.get(name, 0), quarantine_total=qall.get(name, 0)))
    return out
