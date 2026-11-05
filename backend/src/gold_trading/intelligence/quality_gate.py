"""Data Quality Gate (docs/05).

- Thiếu/hỏng nguồn bắt buộc -> REJECTED, không tạo tín hiệu.
- Nguồn tùy chọn thiếu/cũ -> DEGRADED, hạ confidence theo chính sách có phiên bản.
- Gate không tự chữa dữ liệu; mọi quyết định đều có lý do.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from gold_trading.common.enums import QualityVerdict, SourceStatus
from gold_trading.contracts.snapshot import QualityReport, Snapshot


@dataclass(frozen=True)
class QualityPolicy:
    version: str
    required: frozenset[str]
    # analyst_id -> hệ số nhân confidence khi nguồn tùy chọn bị thiếu/không khỏe
    optional_penalty: Mapping[str, float] = field(default_factory=dict)


def evaluate(snapshot: Snapshot, policy: QualityPolicy, at: datetime) -> QualityReport:
    by_id = {o.analyst_id: o for o in snapshot.analyst_outputs}
    reasons: list[str] = []

    if at < snapshot.available_at:
        reasons.append("SNAPSHOT_FROM_FUTURE")
    for analyst_id in sorted(policy.required):
        out = by_id.get(analyst_id)
        if out is None:
            reasons.append(f"REQUIRED_MISSING:{analyst_id}")
        elif not out.is_valid_at(at):
            reasons.append(f"REQUIRED_EXPIRED:{analyst_id}")
        elif out.source_status is not SourceStatus.HEALTHY:
            reasons.append(f"REQUIRED_{out.source_status}:{analyst_id}")
    if reasons:
        return QualityReport(
            snapshot_id=snapshot.snapshot_id,
            verdict=QualityVerdict.REJECTED,
            reasons=tuple(reasons),
            confidence_multiplier=0.0,
            policy_version=policy.version,
        )

    multiplier = 1.0
    for analyst_id, penalty in sorted(policy.optional_penalty.items()):
        out = by_id.get(analyst_id)
        if out is None or not out.is_valid_at(at):
            reasons.append(f"OPTIONAL_MISSING:{analyst_id}")
            multiplier *= penalty
        elif out.source_status is not SourceStatus.HEALTHY:
            reasons.append(f"OPTIONAL_{out.source_status}:{analyst_id}")
            multiplier *= penalty

    return QualityReport(
        snapshot_id=snapshot.snapshot_id,
        verdict=QualityVerdict.DEGRADED if reasons else QualityVerdict.ACCEPTED,
        reasons=tuple(reasons),
        confidence_multiplier=multiplier,
        policy_version=policy.version,
    )
