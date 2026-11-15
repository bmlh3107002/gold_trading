"""Fusion bằng luật → MarketView (docs/05; thiết kế 33 mục 5–6 — GĐ4 bước 4: FUS-01; 4-C03, 4-C04).

DEC-25 / DEC-26 (người dùng 2026-11-15):
- **Hướng chỉ từ giá**: Technical (xu hướng M15, đa khung không ``CONFLICT``) khi Regime là
  ``TREND`` cùng chiều và không mơ hồ. Technical + Regime cùng một chuỗi nến → **một nhóm**, không
  phải hai phiếu.
- **Nhóm khác chỉ được hạ**: Macro / Positioning / News ngược chiều → confidence × 0,5; từ hai nhóm
  trở lên → ``NEUTRAL``. Nhóm cùng chiều **không bao giờ** làm tăng confidence hay tạo hướng.
- Kết quả là **"nghiêng theo luật, chưa kiểm chứng"**: luôn mang ``UNVALIDATED_RULES`` +
  ``UNCALIBRATED``; ``p_up`` / ``p_down`` = ``None`` (DEC-27). ``confidence`` = chất lượng dữ liệu
  × mức đồng thuận — **không phải xác suất**. Mọi hệ số là giá trị khởi đầu chưa hiệu chỉnh.
- Fusion chỉ mô tả, **không chặn lệnh** (Safety / làn nhanh / Risk chặn).
"""

from __future__ import annotations

from datetime import timedelta

from gold_trading.analysts.framework import Scope, input_digest
from gold_trading.common.enums import Bias, QualityVerdict, Regime
from gold_trading.contracts.analyst import AnalystOutput
from gold_trading.contracts.market_view import REQUIRED_QUALITY_FLAGS, MarketView
from gold_trading.contracts.snapshot import QualityReport, Snapshot

FUSION_VERSION = "fusion-rules-1.0.0"
OPPOSED_FACTOR = 0.5          # ≥ 1 nhóm ngược chiều (chưa hiệu chỉnh; = trần mâu thuẫn analyst)
DISAGREE_MIN_GROUPS = 2       # ≥ 2 nhóm ngược chiều → NEUTRAL
MAX_TTL = timedelta(minutes=30)
OPTIONAL_GROUPS = ("macro", "positioning", "news")
_LEAN = {"UP": Bias.LONG, "DOWN": Bias.SHORT}


def price_lean(technical: AnalystOutput, regime: AnalystOutput) -> tuple[Bias, list[str]]:
    """Bước A: hướng gốc chỉ từ giá + driver (thứ tự lý do NEUTRAL theo thiết kế 33 mục 5A)."""
    t, r = technical.features, regime.features
    trend, align = t["trend"], t["mtf_alignment"]
    mtf = f"MTF_{align}"
    if r["regime"] != "TREND":
        return Bias.NEUTRAL, [f"REGIME_NOT_TREND:{r['regime']}", mtf]
    if r["ambiguous"]:
        return Bias.NEUTRAL, ["REGIME_AMBIGUOUS", mtf]
    if trend == "FLAT":
        return Bias.NEUTRAL, ["PRICE_NO_TREND", mtf]
    if r["direction"] != trend:
        return Bias.NEUTRAL, ["PRICE_REGIME_DISAGREE", mtf]
    if align == "CONFLICT":
        return Bias.NEUTRAL, ["MTF_CONFLICT"]
    lean = _LEAN[trend]
    return lean, [f"PRICE_LEAN_{lean.value}", mtf]


def opposes(group: str, out: AnalystOutput, lean: Bias) -> bool:
    """Bước B: nhóm ``group`` có ngược chiều ``lean`` không (không đánh giá được → False)."""
    f = out.features
    if group == "macro":
        return f.get("macro_bias") == ("HEADWIND" if lean is Bias.LONG else "SUPPORTIVE")
    if group == "positioning":
        return f.get("crowding") == ("CROWDED_LONG" if lean is Bias.LONG else "CROWDED_SHORT")
    if group == "news":
        tone = f.get("tone_score")
        if tone is None:
            return False
        return tone < 0 if lean is Bias.LONG else tone > 0
    raise ValueError(f"nhóm không hợp lệ: {group!r}")


def market_view_id(snapshot: Snapshot, report: QualityReport) -> str:
    scope = Scope(snapshot.symbol, snapshot.timeframe, snapshot.source, snapshot.feed_id)
    digest = input_digest({"fusion": FUSION_VERSION, "snapshot": snapshot.snapshot_id,
                           "report": report.report_id})
    return f"mv:{FUSION_VERSION}:{scope.key}:{digest[:16]}"


def fuse(snapshot: Snapshot, report: QualityReport) -> MarketView | None:
    """MarketView từ snapshot đã qua Quality Gate; ``REJECTED`` → ``None`` (không có tín hiệu)."""
    if report.snapshot_id != snapshot.snapshot_id:
        raise ValueError("báo cáo Quality Gate không phải của snapshot này")
    if report.verdict is QualityVerdict.REJECTED:
        return None
    at = report.evaluated_at
    by_id = {o.analyst_id: o for o in snapshot.analyst_outputs}
    tech, reg, evt = by_id["technical"], by_id["regime"], by_id["event"]   # Gate đã bảo đảm có

    lean, drivers = price_lean(tech, reg)
    factor = 1.0
    if lean is not Bias.NEUTRAL:
        problem = {r.rsplit(":", 1)[1] for r in report.reasons if r.startswith("OPTIONAL_")}
        against = [g for g in OPTIONAL_GROUPS
                   if g in by_id and g not in problem and opposes(g, by_id[g], lean)]
        if against:
            factor = OPPOSED_FACTOR
            drivers += [f"OPPOSED_BY:{g}" for g in against]
        if len(against) >= DISAGREE_MIN_GROUPS:
            lean = Bias.NEUTRAL
            drivers.append("ANALYSTS_DISAGREE")

    quality = min(tech.confidence, reg.confidence, evt.confidence)
    confidence = round(quality * report.confidence_multiplier * factor, 4)
    vol = (tech.features.get("vol_forecast") or {}).get("sigma_day_pct")
    risk = frozenset().union(*(o.risk_flags for o in snapshot.analyst_outputs))
    flags = REQUIRED_QUALITY_FLAGS | report.flags | frozenset(report.reasons)
    return MarketView(
        market_view_id=market_view_id(snapshot, report),
        snapshot_id=snapshot.snapshot_id,
        symbol=snapshot.symbol,
        timeframe=snapshot.timeframe,
        source=snapshot.source,
        feed_id=snapshot.feed_id,
        as_of=at,
        expires_at=min(snapshot.expires_at, at + MAX_TTL),
        bias=lean,
        confidence=confidence,
        regime=Regime(reg.features["regime"]),
        vol_forecast=vol,
        drivers=tuple(drivers),
        risk_flags=risk,
        quality_flags=flags,
        model_version=FUSION_VERSION,
        quality_policy_version=report.policy_version,
    )
