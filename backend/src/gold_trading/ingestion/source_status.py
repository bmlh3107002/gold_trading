"""Trạng thái từng nguồn ngoài HEALTHY / STALE / MISSING / INVALID với TTL riêng (ING-30).

Quy tắc đầy đủ + lý do: ``docs/thiet-ke/10-nguon-ngoai.md`` mục 2. Tóm tắt:

- Mỗi lần bộ nạp gọi nguồn → ghi một ``SourceCheck`` (OK / ERROR / INVALID) vào nhật ký chỉ-thêm.
- Trạng thái **tính lại** tại ``as_of`` từ nhật ký (chỉ các lần kiểm có ``checked_at <= as_of``)
  và từ dữ liệu đã biết tại ``as_of`` — không lưu trạng thái, nên tính lại quá khứ ra cùng kết quả.
- Thứ tự (gặp điều nào trước thì dừng): nguồn lạ / tắt → MISSING; chưa kiểm lần nào → MISSING;
  sau lần OK cuối có lỗi "chết" (khóa sai, series ngừng) → MISSING; sau lần OK cuối có lần trả về
  dữ liệu hỏng → INVALID; chưa OK lần nào → MISSING; lần OK cuối cũ hơn ``fetch_ttl`` → STALE;
  có ``data_ttl`` mà chưa có dữ kiện → MISSING, dữ kiện mới nhất cũ hơn ``data_ttl`` → STALE;
  còn lại HEALTHY.
- Lỗi tạm (mạng, 5xx, giới hạn tần suất) không đổi trạng thái ngay: còn trong ``fetch_ttl`` thì
  vẫn HEALTHY (đó là ý nghĩa của TTL), quá TTL → STALE.
- ``error_code`` chỉ là mã ngắn ``[A-Z0-9_]`` — không bao giờ lưu thông điệp lỗi gốc (có thể
  chứa URL kèm khóa API).
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from gold_trading.common.enums import SourceStatus
from gold_trading.contracts.records import EXTERNAL_KINDS
from gold_trading.ingestion.point_in_time import AppendCounts
from gold_trading.ingestion.source_terms import SOURCE_TERMS, SourceTerms, terms_problem

SOURCE_NAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
ERROR_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
MAX_TTL = timedelta(days=400)  # trần chống gõ nhầm (series năm chậm nhất vẫn < 400 ngày)

# Lỗi không tự hết theo thời gian — cần người can thiệp → MISSING ngay (1E-C03, 1E-C05).
FATAL_ERROR_CODES = frozenset({
    "AUTH_FAILED",          # khóa API sai / hết hạn / bị thu hồi
    "KEY_MISSING",          # nguồn cần khóa mà .env chưa có
    "KEY_INVALID",          # khóa trong .env sai định dạng (ING-31)
    "SOURCE_DISCONTINUED",  # series / nguồn ngừng
    "FORBIDDEN",            # nguồn từ chối (điều khoản / chặn IP)
})


class CheckOutcome(StrEnum):
    OK = "OK"            # nguồn trả lời, đọc được (dù không có gì mới)
    ERROR = "ERROR"      # không lấy được (mạng, HTTP lỗi, khóa sai...)
    INVALID = "INVALID"  # lấy được nhưng nội dung hỏng / không đọc được


def _require_utc(name: str, v: datetime) -> datetime:
    """Bắt buộc có múi giờ; trả về giờ UTC (giờ không múi → từ chối, không đoán)."""
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError(f"{name} phải có múi giờ (UTC)")
    return v.astimezone(UTC)


@dataclass(frozen=True)
class SourceSpec:
    """Cấu hình một nguồn. ``fetch_ttl``: lâu nhất được phép kể từ lần gọi OK cuối.
    ``data_ttl`` (tùy chọn): lâu nhất kể từ ``event_time`` của dữ kiện mới nhất đã biết — bắt
    nguồn vẫn trả lời nhưng không có số mới (công bố trễ, chính phủ đóng cửa: 1F-C02).
    Không dùng ``data_ttl`` cho lịch (``calendar``): sự kiện lịch nằm ở tương lai.
    ``provider``: nhà cung cấp để tra điều khoản (ING-32); mặc định trùng ``name``."""

    name: str
    kind: str
    fetch_ttl: timedelta
    data_ttl: timedelta | None = None
    enabled: bool = True
    provider: str = ""

    def __post_init__(self) -> None:
        if not SOURCE_NAME_RE.match(self.name):
            raise ValueError(f"tên nguồn không hợp lệ: {self.name!r}")
        if self.kind not in EXTERNAL_KINDS:
            raise ValueError(f"kind không hợp lệ: {self.kind!r}")
        for label, ttl in (("fetch_ttl", self.fetch_ttl), ("data_ttl", self.data_ttl)):
            if ttl is not None and not (timedelta(0) < ttl <= MAX_TTL):
                raise ValueError(f"{label} phải > 0 và <= {MAX_TTL.days} ngày: {ttl}")
        if self.data_ttl is not None and self.kind == "calendar":
            raise ValueError("calendar không dùng data_ttl (sự kiện lịch nằm ở tương lai)")
        if not self.provider:
            object.__setattr__(self, "provider", self.name)


class SourceRegistry:
    """Danh sách nguồn đã khai báo. Trùng tên → lỗi (không để cấu hình sau âm thầm đè trước).
    Nguồn bật mà điều khoản nhà cung cấp chưa ``VERIFIED`` → lỗi (ING-32)."""

    def __init__(self, specs: Iterable[SourceSpec] = (),
                 terms: dict[str, SourceTerms] | None = None) -> None:
        terms = SOURCE_TERMS if terms is None else terms
        self._specs: dict[str, SourceSpec] = {}
        for s in specs:
            if s.name in self._specs:
                raise ValueError(f"nguồn khai báo trùng: {s.name}")
            if s.enabled and (problem := terms_problem(s.provider, terms)):
                raise ValueError(f"không bật được nguồn {s.name}: {problem}")
            self._specs[s.name] = s

    def get(self, name: str) -> SourceSpec | None:
        return self._specs.get(name)

    def names(self) -> list[str]:
        return sorted(self._specs)


@dataclass(frozen=True)
class SourceCheck:
    source: str
    checked_at: datetime
    outcome: CheckOutcome
    error_code: str | None = None
    inserted: int = 0
    duplicate: int = 0
    conflict: int = 0
    invalid: int = 0

    def __post_init__(self) -> None:
        if not SOURCE_NAME_RE.match(self.source):
            raise ValueError(f"tên nguồn không hợp lệ: {self.source!r}")
        object.__setattr__(self, "checked_at", _require_utc("checked_at", self.checked_at))
        if not isinstance(self.outcome, CheckOutcome):
            object.__setattr__(self, "outcome", CheckOutcome(self.outcome))
        if self.outcome is CheckOutcome.OK:
            if self.error_code is not None:
                raise ValueError("lần kiểm OK không có error_code")
        elif self.error_code is None or not ERROR_CODE_RE.match(self.error_code):
            # Chỉ mã ngắn: chặn việc vô tình ghi thông điệp lỗi gốc (có thể chứa khóa API).
            raise ValueError("lần kiểm lỗi cần error_code dạng [A-Z][A-Z0-9_]{0,63}")
        if min(self.inserted, self.duplicate, self.conflict, self.invalid) < 0:
            raise ValueError("số đếm không được âm")

    @classmethod
    def from_counts(cls, source: str, checked_at: datetime, counts: AppendCounts) -> SourceCheck:
        """Lần gọi lấy được dữ liệu: có bản ghi hỏng mà không có bản ghi tốt nào → INVALID;
        còn lại OK (số hỏng / xung đột vẫn ghi lại để hiện cờ)."""
        good = counts.inserted + counts.duplicate
        bad = counts.invalid + counts.conflict
        if bad > 0 and good == 0:
            return cls(source, checked_at, CheckOutcome.INVALID, "ALL_RECORDS_REJECTED",
                       counts.inserted, counts.duplicate, counts.conflict, counts.invalid)
        return cls(source, checked_at, CheckOutcome.OK, None, counts.inserted, counts.duplicate,
                   counts.conflict, counts.invalid)


@dataclass(frozen=True)
class CheckSummary:
    """Tóm tắt nhật ký một nguồn tại ``as_of`` (đủ để tính trạng thái)."""

    last_check: SourceCheck | None
    last_ok_at: datetime | None
    failures_since_ok: int
    fatal_code_since_ok: str | None
    invalid_code_since_ok: str | None
    last_error_code: str | None


def summarize(checks: Iterable[SourceCheck], as_of: datetime) -> CheckSummary:
    """Bản tham chiếu (bộ nhớ). Bỏ qua lần kiểm sau ``as_of``. Cùng ``checked_at`` thì giữ thứ
    tự ghi."""
    as_of = _require_utc("as_of", as_of)
    seen = [c for c in checks if c.checked_at <= as_of]
    seen.sort(key=lambda c: c.checked_at)  # sort ổn định: giữ thứ tự ghi khi cùng giờ
    last_ok_idx = max((i for i, c in enumerate(seen) if c.outcome is CheckOutcome.OK),
                      default=-1)
    after = seen[last_ok_idx + 1:]
    fatal = [c.error_code for c in after if c.outcome is CheckOutcome.ERROR
             and c.error_code in FATAL_ERROR_CODES]
    invalid = [c.error_code for c in after if c.outcome is CheckOutcome.INVALID]
    errors = [c.error_code for c in seen if c.error_code is not None]
    return CheckSummary(
        last_check=seen[-1] if seen else None,
        last_ok_at=seen[last_ok_idx].checked_at if last_ok_idx >= 0 else None,
        failures_since_ok=len(after),
        fatal_code_since_ok=fatal[-1] if fatal else None,
        invalid_code_since_ok=invalid[-1] if invalid else None,
        last_error_code=errors[-1] if errors else None,
    )


@dataclass(frozen=True)
class SourceHealth:
    source: str
    as_of: datetime
    status: SourceStatus
    reason: str
    last_check_at: datetime | None
    last_ok_at: datetime | None
    failures_since_ok: int
    last_error_code: str | None
    latest_event_at: datetime | None
    flags: frozenset[str]


def evaluate(source: str, spec: SourceSpec | None, summary: CheckSummary, as_of: datetime,
             latest_event_at: datetime | None) -> SourceHealth:
    """Trạng thái tại ``as_of``. ``latest_event_at``: ``event_time`` lớn nhất trong các dữ kiện
    của nguồn đã biết tại ``as_of`` (không tính sự kiện ở tương lai)."""
    as_of = _require_utc("as_of", as_of)
    flags: set[str] = set()
    last = summary.last_check
    if last is not None and last.outcome is CheckOutcome.OK:
        if last.invalid:
            flags.add("PARTIAL_INVALID")
        if last.conflict:
            flags.add("CONFLICT_SEEN")
    if summary.failures_since_ok and summary.last_ok_at is not None:
        flags.add("RECENT_FAILURES")

    def out(status: SourceStatus, reason: str) -> SourceHealth:
        return SourceHealth(source, as_of, status, reason,
                            last.checked_at if last else None, summary.last_ok_at,
                            summary.failures_since_ok, summary.last_error_code,
                            latest_event_at, frozenset(flags))

    if spec is None:
        return out(SourceStatus.MISSING, "UNKNOWN_SOURCE")
    if not spec.enabled:
        return out(SourceStatus.MISSING, "DISABLED")
    if last is None:
        return out(SourceStatus.MISSING, "NEVER_CHECKED")
    if summary.fatal_code_since_ok is not None:
        return out(SourceStatus.MISSING, summary.fatal_code_since_ok)
    if summary.invalid_code_since_ok is not None:
        return out(SourceStatus.INVALID, summary.invalid_code_since_ok)
    if summary.last_ok_at is None:
        return out(SourceStatus.MISSING, "NEVER_OK")
    if as_of - summary.last_ok_at > spec.fetch_ttl:
        return out(SourceStatus.STALE, "FETCH_TTL_EXPIRED")
    if spec.data_ttl is not None:
        if latest_event_at is None:
            return out(SourceStatus.MISSING, "NO_DATA")
        if as_of - latest_event_at > spec.data_ttl:
            return out(SourceStatus.STALE, "DATA_TTL_EXPIRED")
    return out(SourceStatus.HEALTHY, "OK")


class SourceCheckLog:
    """Nhật ký lần kiểm trong bộ nhớ (test/dev). Bản SQL: ``storage.source_checks``."""

    def __init__(self) -> None:
        self._checks: list[SourceCheck] = []
        self._lock = threading.Lock()

    def record(self, check: SourceCheck) -> None:
        with self._lock:
            self._checks.append(check)

    def summary(self, source: str, as_of: datetime) -> CheckSummary:
        with self._lock:
            rows = [c for c in self._checks if c.source == source]
        return summarize(rows, as_of)


class _Log:  # giao diện chung (bộ nhớ + SQL)
    def summary(self, source: str, as_of: datetime) -> CheckSummary: ...


class _Records:
    def latest_event_time(self, source: str, as_of: datetime) -> datetime | None: ...


def source_health(registry: SourceRegistry, log: _Log, records: _Records, as_of: datetime,
                  sources: Sequence[str] | None = None) -> list[SourceHealth]:
    """Trạng thái các nguồn (mặc định: mọi nguồn đã khai báo) tại ``as_of``."""
    as_of = _require_utc("as_of", as_of)
    names = list(sources) if sources is not None else registry.names()
    return [evaluate(n, registry.get(n), log.summary(n, as_of), as_of,
                     records.latest_event_time(n, as_of)) for n in names]
