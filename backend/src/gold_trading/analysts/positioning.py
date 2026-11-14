"""Analyst Positioning (GĐ3 bước 5 — POSN-01, POSN-02).

Thiết kế: ``docs/thiet-ke/31-positioning.md``.

Đầu vào: báo cáo COT vàng của CFTC (legacy, futures only, GĐ1 ``cftc_cot_gold``) — vị thế ròng của
nhóm **không thương mại** (quỹ / đầu cơ). Phạm vi toàn cục (một chuỗi cho mọi tài khoản).

- **COT trễ**: chốt thứ Ba, công bố thứ Sáu 15:30 New York → luôn ghi ``data_lag_days`` + cờ
  ``COT_LAGGED``; không bao giờ coi là dữ liệu thời gian thực. Báo cáo cũ > 14 ngày → STALE.
- **Độ cực trị** chỉ tính khi có ≥ 52 tuần lịch sử (đọc tối đa 156 tuần): z-score + thứ hạng
  phần trăm của ``ròng / khối lượng mở``. Ít hơn → ``crowding = INSUFFICIENT_DATA`` (không đoán).
- ``|z| ≥ 2`` → ``CROWDED_LONG`` / ``CROWDED_SHORT`` + giả thuyết contrarian (chỉ là giả thuyết).
- ETF / ngân hàng trung ương: chưa có nguồn (quyết ở Gate GĐ1) → cờ ``OPTIONAL_MISSING``.
Không xác suất, không tín hiệu; ngưỡng chưa hiệu chỉnh. Đổi số → tăng ``VERSION``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from statistics import mean, pstdev

from gold_trading.analysts.framework import GLOBAL_SCOPE, InputCheck, assess, build_output
from gold_trading.contracts.analyst import AnalystOutput

log = logging.getLogger("gold_trading.analysts")

ANALYST_ID = "positioning"
VERSION = "positioning-1.0.0"
HANDLER_VERSION = "positioning-job-1"
SOURCE = "cftc_cot_gold"
MAX_REPORT_AGE = timedelta(days=14)   # như data_ttl của nguồn (lễ dời công bố)
MIN_WEEKS = 52
LOOKBACK_WEEKS = 156
CROWD_Z = 2.0
TTL = timedelta(hours=6)
BLOCKED_TTL = timedelta(minutes=15)
SHORT_HISTORY_CONFIDENCE_CAP = 0.5
SETTLE = timedelta(seconds=5)
FALLBACK_GRACE = timedelta(seconds=60)


def _ratio(p: dict) -> float | None:
    oi, net = p.get("open_interest"), p.get("noncomm_net")
    if not isinstance(oi, int) or not isinstance(net, int) or oi <= 0:
        return None
    return net / oi


def net_change(p: dict) -> int | None:
    ch = p.get("changes")
    if not isinstance(ch, dict):
        return None
    lo, sh = ch.get("noncomm_long"), ch.get("noncomm_short")
    return lo - sh if isinstance(lo, int) and isinstance(sh, int) else None


def compute(record_store, as_of: datetime, correlation_id: str = "positioning") -> AnalystOutput:
    rows = record_store.as_of(as_of, source=SOURCE, kind="positioning",
                              event_from=as_of - timedelta(weeks=LOOKBACK_WEEKS + 2))
    rows = sorted((r for r in rows if r.event_time <= as_of), key=lambda r: r.event_time)
    reports = [(r, _ratio(r.payload)) for r in rows]
    bad = [r for r, x in reports if x is None]
    reports = [(r, x) for r, x in reports if x is not None]
    last = reports[-1][0] if reports else None
    stale = last is not None and as_of - last.event_time > MAX_REPORT_AGE
    checks = [InputCheck("cot_gold", last.known_at if last else None, timedelta(days=3650),
                         healthy=not stale),
              InputCheck("etf_flows", None, timedelta(days=7), required=False),
              InputCheck("central_banks", None, timedelta(days=60), required=False)]
    a = assess(checks, as_of)
    q_flags = {"COT_LAGGED"}
    if bad:
        q_flags.add("COT_REPORT_UNUSABLE_SKIPPED")
    digest = {"reports": [[r.logical_key, r.revision, r.payload.get("noncomm_net"),
                           r.payload.get("open_interest")] for r, _ in reports]}
    lag = (as_of - last.event_time) if last else None
    expires = as_of + (BLOCKED_TTL if a.blocked else TTL)
    if last is not None and not stale:
        expires = min(expires, last.event_time + MAX_REPORT_AGE + timedelta(seconds=1))
    base = dict(analyst_id=ANALYST_ID, version=VERSION, scope=GLOBAL_SCOPE, as_of=as_of,
                expires_at=expires, correlation_id=correlation_id, assessment=a,
                digest_of=digest, quality_flags=q_flags)
    if a.blocked:
        return build_output(**base)

    p = last.payload
    ratios = [x for _, x in reports][-LOOKBACK_WEEKS:]
    cur = ratios[-1]
    z = pct = None
    crowding = "INSUFFICIENT_DATA"
    confidence = 1.0
    drivers: list[str] = []
    risk_flags: set[str] = set()
    hypothesis = None
    if len(ratios) >= MIN_WEEKS:
        sd = pstdev(ratios)
        z = (cur - mean(ratios)) / sd if sd > 0 else None
        pct = sum(1 for x in ratios if x <= cur) / len(ratios)
        if z is None:
            q_flags.add("COT_ZERO_DISPERSION")
        elif z >= CROWD_Z:
            crowding = "CROWDED_LONG"
            hypothesis = "CONTRARIAN_DOWNSIDE_RISK"
        elif z <= -CROWD_Z:
            crowding = "CROWDED_SHORT"
            hypothesis = "CONTRARIAN_UPSIDE_RISK"
        else:
            crowding = "NORMAL"
    else:
        q_flags.add("COT_HISTORY_SHORT")
        confidence = SHORT_HISTORY_CONFIDENCE_CAP
    drivers.append(f"POSITIONING_{crowding}")
    if crowding.startswith("CROWDED"):
        risk_flags.add("CROWDING_RISK")
        drivers.append(f"HYPOTHESIS_{hypothesis}")

    features = {
        "report_date": p.get("as_of"),
        "released_at": p.get("release_at"),
        "data_lag_days": round(lag.total_seconds() / 86400, 1),
        "horizon": "WEEKS",
        "noncomm_net": p.get("noncomm_net"),
        "noncomm_net_change": net_change(p),
        "open_interest": p.get("open_interest"),
        "net_pct_oi": round(cur * 100, 2),
        "history_weeks": len(ratios),
        "min_weeks_for_extremes": MIN_WEEKS,
        "z_net_pct_oi": round(z, 3) if z is not None else None,
        "percentile": round(pct, 3) if pct is not None else None,
        "crowding": crowding,
        "contrarian_hypothesis": hypothesis,
        "hypothesis_note": "giả thuyết đảo chiều khi quá đông một phía — chưa kiểm chứng",
        "etf_flows": "NOT_AVAILABLE",
        "central_banks": "NOT_AVAILABLE",
        "source_note": "CFTC Commitments of Traders (legacy, futures only), GOLD 088691",
    }
    return build_output(**base, features=features, drivers=drivers, risk_flags=risk_flags,
                        confidence=confidence)


class PositioningAnalyst:
    def __init__(self, record_store, out_store) -> None:
        self.record_store = record_store
        self.out_store = out_store

    def current(self, now: datetime):
        got = self.out_store.latest_scoped(ANALYST_ID, GLOBAL_SCOPE, known_by=now)
        return got if got is not None and got.output.version == VERSION else None

    def run_at(self, as_of: datetime, now: datetime, correlation_id="positioning") -> bool:
        out = compute(self.record_store, as_of, correlation_id)
        return self.out_store.append_scoped(out, GLOBAL_SCOPE, computed_at=now)

    def ensure_fresh(self, now: datetime) -> bool:
        got = self.current(now)
        if got is not None and got.output.expires_at > now - FALLBACK_GRACE:
            return False
        return self.run_at(now - SETTLE, now, "positioning:fallback")


def positioning_handler(analyst: PositioningAnalyst):
    """Job ``POSITIONING`` (báo cáo COT mới / sửa; kết quả hết hạn)."""
    from gold_trading.orchestrator.dispatcher import Handler

    def run(e, now: datetime) -> str | None:
        got = analyst.current(now)
        if got is not None and got.output.is_valid_at(now) and got.output.as_of >= e.known_at:
            return "positioning:unchanged"
        as_of = min(now, max(now - SETTLE, e.known_at))
        return "positioning:stored" if analyst.run_at(as_of, now, e.correlation_id or "pos") \
            else "positioning:unchanged"

    return Handler(HANDLER_VERSION, run, deadline=timedelta(seconds=30), max_attempts=3)

