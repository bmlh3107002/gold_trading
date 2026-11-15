"""Data Quality Gate (docs/05; thiết kế 33 mục 4 — GĐ4 bước 3: DQG-01..03; 4-C01, 4-C02, 4-C07).

- Bắt buộc (DEC-24: Technical, Regime, Event) vắng / hết hạn / không ``HEALTHY`` / sai schema
  → ``REJECTED``, không tạo MarketView.
- Tùy chọn (Macro, Positioning, News) như trên → ``DEGRADED``, nhân hệ số có phiên bản.
- Technical và Regime phải tính trên **cùng một nến đóng** → lệch: ``REJECTED TIMESTAMP_CONFLICT``.
- Gate **không tự chữa dữ liệu**; mọi quyết định có lý do + phiên bản chính sách, lưu chỉ-thêm
  (DQG-03).
- Output ``as_of > at`` hoặc đánh giá snapshot trước lúc nó tồn tại → lỗi lập trình → ném lỗi.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from numbers import Real
from typing import Any

from gold_trading.analysts.framework import input_digest
from gold_trading.common.enums import QualityVerdict, SourceStatus
from gold_trading.contracts.analyst import AnalystOutput
from gold_trading.contracts.market_view import SAMPLE_DATA
from gold_trading.contracts.snapshot import QualityReport, Snapshot
from gold_trading.intelligence.snapshot_builder import REQUIRED

# Cờ chất lượng đầu vào cực đoan của analyst (thiết kế 27 mục 4, Macro 3-C04) → truyền xuống.
EXTREME_PREFIXES = ("SPIKE_IN_INPUT:", "EXTREME_INPUT:")


def _num_or_none(v: Any) -> bool:
    return v is None or (isinstance(v, Real) and not isinstance(v, bool) and v == v)


def _technical(f: Mapping[str, Any]) -> bool:
    vol = f.get("vol_forecast")
    vol_ok = vol is None or (isinstance(vol, Mapping) and _num_or_none(vol.get("sigma_day_pct"))
                             and (vol.get("sigma_day_pct") is None or vol["sigma_day_pct"] >= 0))
    return (f.get("trend") in ("UP", "DOWN", "FLAT")
            and f.get("mtf_alignment") in ("ALIGNED_UP", "ALIGNED_DOWN", "CONFLICT", "MIXED",
                                           "NOT_EVALUATED")
            and vol_ok)


def _regime(f: Mapping[str, Any]) -> bool:
    return (f.get("regime") in ("TREND", "RANGE", "RISK_OFF", "HIGH_VOL")
            and f.get("direction") in ("UP", "DOWN", None)
            and isinstance(f.get("ambiguous"), bool))


SCHEMA: Mapping[str, Callable[[Mapping[str, Any]], bool]] = {
    "technical": _technical,
    "regime": _regime,
    "event": lambda f: f.get("event_risk") in ("NONE", "LOW", "MEDIUM", "HIGH"),
    "macro": lambda f: f.get("macro_bias") in ("SUPPORTIVE", "HEADWIND", "MIXED", "NEUTRAL",
                                               "INSUFFICIENT_DATA"),
    "positioning": lambda f: f.get("crowding") in ("CROWDED_LONG", "CROWDED_SHORT", "NORMAL",
                                                   "INSUFFICIENT_DATA"),
    "news": lambda f: "tone_score" in f and _num_or_none(f.get("tone_score")),
}


@dataclass(frozen=True)
class QualityPolicy:
    version: str
    required: frozenset[str]
    # analyst_id tùy chọn -> hệ số nhân confidence khi thiếu / hết hạn / không khỏe / sai schema
    optional_penalty: Mapping[str, float] = field(default_factory=dict)
    schema: Mapping[str, Callable[[Mapping[str, Any]], bool]] = field(default_factory=dict)
    same_bar: tuple[str, ...] = ()   # các analyst phải có cùng as_of (cùng nến đóng)

    def __post_init__(self) -> None:
        if self.required & set(self.optional_penalty):
            raise ValueError("một analyst không thể vừa bắt buộc vừa tùy chọn")
        for a, p in self.optional_penalty.items():
            if not (0.0 < p <= 1.0):
                raise ValueError(f"hệ số của {a} phải trong (0, 1]")


# quality-policy-1 (GĐ4 bước 3, 2026-11-15). Hệ số 0,9 = GIÁ TRỊ KHỞI ĐẦU CHƯA HIỆU CHỈNH; lý do ở
# thiết kế 33 mục 4. Đổi bất kỳ điều gì ở đây → tăng ``version``.
POLICY_V1 = QualityPolicy(
    version="quality-policy-1",
    required=REQUIRED,
    optional_penalty={"macro": 0.9, "positioning": 0.9, "news": 0.9},
    schema=SCHEMA,
    same_bar=("technical", "regime"),
)


def _problem(out: AnalystOutput | None, analyst_id: str, snapshot: Snapshot,
             policy: QualityPolicy, at: datetime) -> str | None:
    """Mã vấn đề của một analyst (None = dùng được)."""
    if out is None:
        return "EXPIRED" if analyst_id in snapshot.excluded_inputs else "MISSING"
    if not out.is_valid_at(at):
        return "EXPIRED"
    if out.source_status is not SourceStatus.HEALTHY:
        return out.source_status.value
    check = policy.schema.get(analyst_id)
    if check is not None and not check(out.features):
        return "SCHEMA"
    return None


def evaluate(snapshot: Snapshot, policy: QualityPolicy, at: datetime) -> QualityReport:
    if at < snapshot.available_at:
        raise ValueError("đánh giá snapshot trước lúc nó tồn tại — nhìn trước tương lai")
    by_id = {o.analyst_id: o for o in snapshot.analyst_outputs}
    for o in snapshot.analyst_outputs:
        if o.as_of > at:
            raise ValueError(f"nhìn trước tương lai: {o.output_id!r} có as_of > at")

    reasons: list[str] = []
    for a in sorted(policy.required):
        if (p := _problem(by_id.get(a), a, snapshot, policy, at)) is not None:
            reasons.append(f"REQUIRED_{p}:{a}")
    bar = {by_id[a].as_of for a in policy.same_bar if a in by_id}
    if len(bar) > 1:
        reasons.append("TIMESTAMP_CONFLICT:" + ",".join(policy.same_bar))

    multiplier = 1.0
    if reasons:
        verdict, multiplier = QualityVerdict.REJECTED, 0.0
    else:
        for a, penalty in sorted(policy.optional_penalty.items()):
            if (p := _problem(by_id.get(a), a, snapshot, policy, at)) is not None:
                reasons.append(f"OPTIONAL_{p}:{a}")
                multiplier *= penalty
        verdict = QualityVerdict.DEGRADED if reasons else QualityVerdict.ACCEPTED
    multiplier = round(multiplier, 6)

    flags = {f for f in snapshot.quality_flags if f == SAMPLE_DATA}
    flags |= {f"{o.analyst_id}:{f}" for o in snapshot.analyst_outputs for f in o.quality_flags
              if f.startswith(EXTREME_PREFIXES)}
    digest = input_digest({"snapshot": snapshot.snapshot_id, "policy": policy.version,
                           "verdict": verdict.value, "reasons": reasons,
                           "multiplier": multiplier, "flags": sorted(flags)})
    return QualityReport(
        report_id=f"qr:{policy.version}:{digest[:24]}",
        snapshot_id=snapshot.snapshot_id,
        evaluated_at=at,
        verdict=verdict,
        reasons=tuple(reasons),
        confidence_multiplier=multiplier,
        flags=frozenset(flags),
        policy_version=policy.version,
    )
