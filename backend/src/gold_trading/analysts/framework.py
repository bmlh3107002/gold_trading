"""Khung chung cho analyst (GĐ3 bước 1 — ANA-01; 3-C01..C07).

Thiết kế + lý do: ``docs/thiet-ke/27-khung-analyst.md``. Gom phần mọi analyst đều cần:
phạm vi lưu (theo nguồn giá / toàn cục), ``output_id`` xác định có phiên bản, kiểm đầu vào
(thiếu / cũ / thiếu lịch sử / cực đoan / SAMPLE / nhìn trước tương lai) và dựng ``AnalystOutput``
không xuất đặc trưng khi dữ liệu hỏng. ``confidence`` luôn là chất lượng dữ liệu, KHÔNG phải xác
suất dự báo.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from gold_trading.common.enums import SourceStatus
from gold_trading.contracts.analyst import AnalystOutput

GLOBAL_SOURCE = "GLOBAL"
ANY = "*"
SPIKE_CONFIDENCE_CAP = 0.5   # như Technical: có điểm cực đoan → confidence × 0,5


@dataclass(frozen=True)
class Scope:
    """Chuỗi kết quả: theo nguồn giá ``(symbol, timeframe, source, feed)`` hoặc toàn cục."""

    symbol: str
    timeframe: str
    source: str
    feed: str = ""

    def __post_init__(self) -> None:
        for name in ("symbol", "timeframe", "source"):
            v = getattr(self, name)
            if not v or ":" in v:
                raise ValueError(f"Scope.{name} không hợp lệ: {v!r}")
        if ":" in self.feed:
            raise ValueError(f"Scope.feed không hợp lệ: {self.feed!r}")
        is_global = self.source == GLOBAL_SOURCE
        if is_global != (self.symbol == ANY and self.timeframe == ANY and self.feed == ""):
            raise ValueError("phạm vi toàn cục phải là (*, *, GLOBAL, '') và ngược lại")

    @property
    def is_global(self) -> bool:
        return self.source == GLOBAL_SOURCE

    @property
    def key(self) -> str:
        return f"{self.source}:{self.feed}:{self.symbol}:{self.timeframe}"

    @classmethod
    def of_feed(cls, symbol: str, timeframe, source, feed: str = "") -> Scope:
        tf = getattr(timeframe, "value", timeframe)
        src = getattr(source, "value", source)
        return cls(symbol, tf, src, feed)


GLOBAL_SCOPE = Scope(ANY, ANY, GLOBAL_SOURCE, "")


def _utc(v: datetime) -> datetime:
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError("thời điểm phải có múi giờ (UTC)")
    return v.astimezone(UTC)


def _canon(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError("không băm được số NaN / vô cực")
        return v
    if isinstance(v, datetime):
        return _utc(v).isoformat()
    if isinstance(v, Mapping):
        out = {}
        for k, x in v.items():
            if not isinstance(k, str):
                raise TypeError(f"khóa phải là chuỗi: {k!r}")
            out[k] = _canon(x)
        return out
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    raise TypeError(f"kiểu không băm được: {type(v).__name__}")


def input_digest(obj: Any) -> str:
    """sha256 của JSON chuẩn (sắp khóa, không khoảng trắng). Kiểu lạ → lỗi, không ``str()``."""
    raw = json.dumps(_canon(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def output_id(analyst_id: str, version: str, scope: Scope, as_of: datetime, digest: str) -> str:
    return f"{analyst_id}:{version}:{scope.key}:{_utc(as_of).isoformat()}:{digest[:16]}"


@dataclass(frozen=True)
class InputCheck:
    """Một đầu vào tại ``as_of``. ``known_at``: lúc hệ thống biết bản ghi mới nhất được dùng
    (None = không có). ``history`` / ``min_history``: số mẫu có / cần. ``spikes``: số điểm cực đoan
    analyst đã phát hiện. ``sample``: dữ liệu mẫu."""

    name: str
    known_at: datetime | None
    max_age: timedelta
    required: bool = True
    history: int = 1
    min_history: int = 1
    spikes: int = 0
    sample: bool = False

    def __post_init__(self) -> None:
        if not self.name or ":" in self.name:
            raise ValueError(f"tên đầu vào không hợp lệ: {self.name!r}")
        if self.max_age <= timedelta(0):
            raise ValueError("max_age phải > 0")
        if self.history < 0 or self.min_history < 0 or self.spikes < 0:
            raise ValueError("số mẫu không được âm")


class LookAheadError(ValueError):
    """Đầu vào được biết SAU ``as_of`` — lỗi lập trình (nhìn trước tương lai)."""


_RANK = {SourceStatus.HEALTHY: 0, SourceStatus.INVALID: 1, SourceStatus.STALE: 2,
         SourceStatus.MISSING: 3}


@dataclass(frozen=True)
class Assessment:
    status: SourceStatus
    blocking: tuple[str, ...]
    quality_flags: frozenset[str]
    confidence_cap: float
    inputs: tuple[dict[str, Any], ...] = field(default=())

    @property
    def blocked(self) -> bool:
        return bool(self.blocking)


def assess(checks: Iterable[InputCheck], as_of: datetime) -> Assessment:
    as_of = _utc(as_of)
    checks = list(checks)
    names = [c.name for c in checks]
    if len(set(names)) != len(names):
        raise ValueError("tên đầu vào bị trùng")
    status = SourceStatus.HEALTHY
    blocking: list[str] = []
    flags: set[str] = set()
    cap = 1.0
    summary: list[dict[str, Any]] = []

    def worsen(s: SourceStatus) -> None:
        nonlocal status
        if _RANK[s] > _RANK[status]:
            status = s

    for c in sorted(checks, key=lambda c: c.name):
        known = _utc(c.known_at) if c.known_at is not None else None
        if known is not None and known > as_of:
            raise LookAheadError(f"đầu vào {c.name} biết lúc {known.isoformat()} > as_of "
                                 f"{as_of.isoformat()}")
        age = (as_of - known) if known is not None else None
        summary.append({"name": c.name, "required": c.required,
                        "known_at": known.isoformat() if known else None,
                        "age_s": int(age.total_seconds()) if age is not None else None,
                        "history": c.history, "min_history": c.min_history,
                        "spikes": c.spikes, "sample": c.sample})
        problems: list[tuple[SourceStatus, str]] = []
        if known is None:
            problems.append((SourceStatus.MISSING, "MISSING"))
        else:
            if age > c.max_age:
                problems.append((SourceStatus.STALE, "STALE"))
            if c.history < c.min_history:
                problems.append((SourceStatus.INVALID, "INSUFFICIENT_HISTORY"))
        for st, code in problems:
            if c.required:
                worsen(st)
                reason = f"{code}_INPUT:{c.name}" if code != "INSUFFICIENT_HISTORY" \
                    else f"INSUFFICIENT_HISTORY:{c.name}"
                blocking.append(reason)
                flags.add(reason)
            else:
                flags.add(f"OPTIONAL_{code}:{c.name}")
        if known is not None and c.spikes:
            flags.add(f"SPIKE_IN_INPUT:{c.name}")
            cap = min(cap, SPIKE_CONFIDENCE_CAP)
        if known is not None and c.sample:
            flags.add("SAMPLE_DATA")
    return Assessment(status, tuple(blocking), frozenset(flags), cap, tuple(summary))


def build_output(
    *,
    analyst_id: str,
    version: str,
    scope: Scope,
    as_of: datetime,
    expires_at: datetime,
    correlation_id: str,
    assessment: Assessment,
    digest_of: Any,
    features: Mapping[str, Any] | None = None,
    drivers: Iterable[str] = (),
    risk_flags: Iterable[str] = (),
    quality_flags: Iterable[str] = (),
    confidence: float = 1.0,
) -> AnalystOutput:
    """Dựng kết quả. Có lý do chặn → không xuất đặc trưng (3-C01), confidence 0, drivers = lý do.
    ``digest_of``: toàn bộ đầu vào đã dùng (băm vào ``output_id`` + lưu ``input_digest``)."""
    as_of = _utc(as_of)
    digest = input_digest(digest_of)
    info = {"scope": scope.key, "input_digest": digest, "inputs": list(assessment.inputs)}
    if features and "input" in features:
        raise ValueError("'input' là khóa dành riêng của khung")
    base = dict(
        output_id=output_id(analyst_id, version, scope, as_of, digest),
        analyst_id=analyst_id,
        as_of=as_of,
        expires_at=expires_at,
        version=version,
        correlation_id=correlation_id,
        risk_flags=frozenset(risk_flags),
        quality_flags=frozenset(assessment.quality_flags | set(quality_flags)),
    )
    if assessment.blocked:
        return AnalystOutput(**base, confidence=0.0, features={"input": info},
                             drivers=assessment.blocking, source_status=assessment.status)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence phải trong [0, 1]")
    feats = json.loads(json.dumps(_canon({**(features or {}), "input": info})))
    return AnalystOutput(**base, confidence=round(min(confidence, assessment.confidence_cap), 3),
                         features=feats, drivers=tuple(drivers),
                         source_status=SourceStatus.HEALTHY)
