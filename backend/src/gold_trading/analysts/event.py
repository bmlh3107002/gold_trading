"""Analyst Lịch sự kiện (GĐ3 bước 2 — EVT-01..04; 3-C08, 3-C09).

Thiết kế + lý do: ``docs/thiet-ke/28-event-analyst.md``. Luật cứng, không LLM, không dự báo.

- **Chỉ quan sát, không chặn.** Chặn mở lệnh mới vẫn do Safety / làn nhanh (DEC-20). Cửa sổ của
  analyst tính bằng **đúng** hàm của làn nhanh (``economic_calendar`` + ``calendar_blocks`` cùng
  trạng thái nguồn) → cờ ``EVENT_WINDOW`` không thể lệch phần lịch của Safety tại cùng ``as_of``.
- **Không có forecast** (DEC-01) → ``surprise_status = INSUFFICIENT_DATA``, không suy hướng bất ngờ.
  "Chưa công bố" (``actual_status`` NOT_DUE / AWAITING / UNKNOWN_*) khác hẳn số actual = "0":
  số giữ nguyên dạng chuỗi của nguồn.
- **Lịch rỗng không có nghĩa là "không có rủi ro":** nguồn lịch không có lịch phủ quá
  ``HORIZON`` → MISSING (chặn); nguồn không khỏe (ING-30) → STALE (chặn).
- Phạm vi toàn cục (``GLOBAL_SCOPE``): một chuỗi kết quả cho mọi tài khoản.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from gold_trading.analysts.framework import GLOBAL_SCOPE, InputCheck, assess, build_output
from gold_trading.common.enums import SourceStatus
from gold_trading.contracts.analyst import AnalystOutput
from gold_trading.ingestion import economic_calendar as EC
from gold_trading.ingestion.event_importance import POLICY_VERSION as EVENT_POLICY
from gold_trading.risk import fast_lane as FL
from gold_trading.risk.blocks import is_active

log = logging.getLogger("gold_trading.analysts")

ANALYST_ID = "event"
VERSION = "event-1.0.0"
HANDLER_VERSION = "event-job-1"

HORIZON = timedelta(hours=24)        # danh sách sắp tới + yêu cầu lịch phủ tối thiểu
RECENT = timedelta(hours=24)         # danh sách vừa công bố
SOON = timedelta(minutes=60)         # cờ EVENT_SOON: cửa sổ bắt đầu trong 60 phút (chưa hiệu chỉnh)
TTL = timedelta(minutes=15)          # hết hạn chậm nhất (trạng thái nguồn đổi không sinh sự kiện)
BLOCKED_TTL = timedelta(minutes=2)   # kết quả bị chặn: thử lại sớm
SETTLE = timedelta(seconds=5)        # tính tại now − 5 giây: bản ghi commit chậm vẫn được thấy
FALLBACK_GRACE = timedelta(seconds=60)
CONFLICT_CONFIDENCE_CAP = 0.5        # 3-C08: nguồn lịch mâu thuẫn (chưa hiệu chỉnh)
NO_HEALTH_MAX_AGE = timedelta(days=400)   # tuổi do trạng thái nguồn quyết; số này chỉ là chặn trên
VALUE_SOURCES = tuple(sorted(set(EC.ACTUAL_SOURCES.values())))
_RANK = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}


def _iso(v: datetime | date | None) -> str | None:
    return v.isoformat() if v is not None else None


def item_dict(it: EC.CalendarItem) -> dict[str, Any]:
    return {
        "source": it.source, "logical_key": it.logical_key, "revision": it.revision,
        "event": it.event, "variant": it.variant, "title": it.title,
        "release_at": _iso(it.release_at), "release_date_local": _iso(it.release_date_local),
        "time_confirmed": it.time_confirmed, "all_day": it.all_day, "status": it.status,
        "tentative": it.tentative, "flags": list(it.flags), "importance": it.importance,
        "importance_known": it.importance_known, "window_start": _iso(it.window_start),
        "window_end": _iso(it.window_end), "notes": list(it.notes),
        "actual_status": it.actual_status, "actual_received_at": _iso(it.actual_received_at),
        "actuals": [list(a) for a in it.actuals],
        # DEC-01: không có forecast → không tính được bất ngờ, không đoán hướng.
        "forecast_status": it.forecast_status, "surprise_status": it.surprise_status,
    }


def _short(it: EC.CalendarItem, as_of: datetime) -> dict[str, Any]:
    d = {k: v for k, v in item_dict(it).items()
         if k in ("event", "variant", "title", "importance", "release_at", "window_start",
                  "window_end", "time_confirmed", "all_day", "tentative", "status",
                  "actual_status", "notes", "revision")}
    d["minutes_until"] = round((it.release_at - as_of).total_seconds() / 60, 1)
    return d


def _block_importance(code: str) -> str:
    if code == "RELEASE_HIGH_RECEIVED":
        return "HIGH"
    return code.removeprefix("CALENDAR_") if code.startswith("CALENDAR_") else "HIGH"


def compute(store, as_of: datetime, *, check_log=None, market_calendar=None,
            correlation_id: str = "event") -> AnalystOutput:
    """Kết quả tại ``as_of`` từ dữ liệu đã biết tới ``as_of`` (point-in-time). Đọc lỗi → ném lỗi
    (job thử lại / dead-letter — không giả kết quả)."""
    details = EC.health_details(check_log, store, as_of) if check_log is not None else None
    health = ({s: h.status is SourceStatus.HEALTHY for s, h in details.items()}
              if details is not None else None)
    items = EC.economic_calendar(store, as_of, start=as_of - RECENT,
                                 end=as_of + HORIZON + SOON, health=health,
                                 include_removed=True)
    live = [i for i in items if i.status != "REMOVED"]
    removed = [i for i in items if i.status == "REMOVED"]

    # --- đầu vào: lịch của từng nguồn phải phủ quá HORIZON (lịch rỗng ≠ không có sự kiện) ---
    checks: list[InputCheck] = []
    coverage: dict[str, str | None] = {}
    for src in EC.CALENDAR_SOURCES:
        ahead = [r for r in store.as_of(as_of, source=src, kind="calendar",
                                         event_from=as_of + HORIZON)
                 if (r.payload.get("status") or "SCHEDULED") != "REMOVED"]
        coverage[src] = _iso(max((r.event_time for r in ahead), default=None))
        h = details.get(src) if details is not None else None
        if not ahead:
            known = None
        elif h is not None:
            known = h.last_ok_at or max(r.known_at for r in ahead)
        else:
            known = max(r.known_at for r in ahead)
        checks.append(InputCheck(src, known, NO_HEALTH_MAX_AGE,
                                 healthy=h is None or h.status is SourceStatus.HEALTHY))
    # Số actual: tùy chọn (thiếu → actual_status UNKNOWN_* + chỉ cờ). Không có nhật ký kiểm nguồn
    # → không đánh giá được (cờ SOURCE_HEALTH_UNKNOWN), không bịa thời điểm.
    for src in VALUE_SOURCES if details is not None else ():
        h = details.get(src)
        checks.append(InputCheck(src, h.last_ok_at if h is not None else None,
                                 NO_HEALTH_MAX_AGE, required=False,
                                 healthy=h is not None and h.status is SourceStatus.HEALTHY))
    a = assess(checks, as_of)

    # --- cửa sổ: đúng hàm của làn nhanh ---
    blocks = FL.calendar_blocks(live, as_of, market_calendar)
    active = [b for b in blocks if is_active(b, None, as_of)]
    merged = [w for w in FL.merge_windows(blocks)
              if w.start_at <= as_of and (w.end_at is None or as_of < w.end_at)]
    risk = max((_block_importance(b.reason_code) for b in active), key=_RANK.get,
               default="NONE")
    future = sorted((i for i in live if i.release_at > as_of), key=lambda i: i.release_at)
    nxt = future[0] if future else None
    starts = sorted(i.window_start for i in live
                    if i.window_start is not None and i.window_start > as_of)
    soon = bool(starts) and starts[0] - as_of <= SOON
    soon_items = [i for i in live if i.window_start is not None
                  and as_of < i.window_start <= as_of + SOON]
    recent = [i for i in live if as_of - RECENT <= i.release_at <= as_of]
    upcoming = [i for i in live if as_of < i.release_at <= as_of + HORIZON
                or (i.window_start is not None and as_of < i.window_start <= as_of + HORIZON)]

    q_flags: set[str] = set()
    confidence = 1.0
    if details is None:
        q_flags.add("SOURCE_HEALTH_UNKNOWN")
    for i in live:
        if "CALENDAR_SOURCES_DISAGREE" in i.flags:          # 3-C08
            q_flags.add("CALENDAR_SOURCES_DISAGREE")
            confidence = min(confidence, CONFLICT_CONFIDENCE_CAP)
        if not i.importance_known:
            q_flags.add("IMPORTANCE_UNKNOWN_EVENT")
        if "SCHEDULE_SOURCE_UNHEALTHY" in i.notes:
            q_flags.add("SCHEDULE_DISTRUSTED_WHOLE_DAY")

    drivers = [f"EVENT_RISK_{risk}"]
    risk_flags: set[str] = set()
    if active:
        risk_flags.add("EVENT_WINDOW")
        drivers.append("IN_EVENT_WINDOW")
    if soon:
        risk_flags.add("EVENT_SOON")
        drivers += sorted({f"EVENT_SOON:{i.event}" for i in soon_items})
    drivers += sorted({f"ACTUAL_UNKNOWN:{i.event}" for i in recent
                       if i.actual_status.startswith("UNKNOWN")})
    drivers += sorted({f"EVENT_REMOVED:{i.event}" for i in removed})
    if "CALENDAR_SOURCES_DISAGREE" in q_flags:              # 3-C08: ghi cả driver
        drivers.append("CALENDAR_SOURCES_DISAGREE")
    if any(i.actual_status == "RECEIVED" for i in recent):
        drivers.append("SURPRISE_INSUFFICIENT_DATA")

    features = {
        "policy": {"event_importance": EVENT_POLICY, "fast_lane": FL.POLICY_VERSION},
        "event_risk": risk,
        "window": ({"start": _iso(merged[0].start_at), "end": _iso(merged[0].end_at),
                    "reasons": list(merged[0].reason_codes),
                    "causes": list(merged[0].causes)} if merged else None),
        "active_reasons": sorted({b.reason_code for b in active}),
        "next_event": _short(nxt, as_of) if nxt else None,
        "soon": soon,
        "upcoming": [_short(i, as_of) for i in upcoming],
        "recent_releases": [
            {**_short(i, as_of), "actual_received_at": _iso(i.actual_received_at),
             "actuals": [list(x) for x in i.actuals], "forecast_status": i.forecast_status,
             "surprise_status": i.surprise_status} for i in recent],
        "removed": [{"event": i.event, "release_at": _iso(i.release_at),
                     "logical_key": i.logical_key} for i in removed],
        "schedule_coverage_until": coverage,
    }

    # --- hết hạn: mốc gần nhất làm kết quả đổi, chậm nhất TTL ---
    marks = [as_of + (BLOCKED_TTL if a.blocked else TTL)]
    for b in blocks:
        marks += [b.start_at, b.end_at] if b.end_at else [b.start_at]
    for i in live:
        marks += [x for x in (i.window_start, i.window_end, i.release_at) if x is not None]
        if i.window_start is not None:
            marks.append(i.window_start - SOON)
    expires = min(m for m in marks if m > as_of)

    return build_output(
        analyst_id=ANALYST_ID, version=VERSION, scope=GLOBAL_SCOPE, as_of=as_of,
        expires_at=expires, correlation_id=correlation_id, assessment=a,
        digest_of={"items": [item_dict(i) for i in items],
                   "health": ({s: [h.status.value, _iso(h.last_ok_at)]
                               for s, h in sorted(details.items())} if details else None),
                   "coverage": coverage},
        features=features, drivers=drivers, risk_flags=risk_flags, quality_flags=q_flags,
        confidence=confidence)


class EventAnalyst:
    """Tính + lưu (chỉ-thêm) cho orchestrator. ``check_log`` / ``market_calendar`` như làn nhanh."""

    def __init__(self, record_store, out_store, *, check_log=None, market_calendar=None) -> None:
        self.record_store = record_store
        self.out_store = out_store
        self.check_log = check_log
        self.market_calendar = market_calendar

    def run_at(self, as_of: datetime, now: datetime, correlation_id: str = "event") -> bool:
        out = compute(self.record_store, as_of, check_log=self.check_log,
                      market_calendar=self.market_calendar, correlation_id=correlation_id)
        return self.out_store.append_scoped(out, GLOBAL_SCOPE, computed_at=now)

    def current(self, now: datetime):
        got = self.out_store.latest_scoped(ANALYST_ID, GLOBAL_SCOPE, known_by=now)
        return got if got is not None and got.output.version == VERSION else None

    def ensure_fresh(self, now: datetime) -> bool:
        """Dự phòng (lần chạy đầu / chuỗi hết hạn bị đứt): không có kết quả còn hạn quá
        ``FALLBACK_GRACE`` → tính ngay. Đường chính là job ``EVENT_CALENDAR``."""
        got = self.current(now)
        if got is not None and got.output.expires_at > now - FALLBACK_GRACE:
            return False
        stored = self.run_at(now - SETTLE, now, "event:fallback")
        if stored:
            log.info("Analyst Lịch sự kiện: tính dự phòng (chưa có kết quả còn hạn)")
        return stored


def event_handler(analyst: EventAnalyst):
    """Job ``EVENT_CALENDAR`` (lịch / số actual mới, kết quả hết hạn). Đã có kết quả còn hạn tính
    sau khi sự kiện được biết → bỏ qua (nạp bù hàng trăm bản ghi không sinh hàng trăm kết quả)."""
    from gold_trading.orchestrator.dispatcher import Handler

    def run(e, now: datetime) -> str | None:
        got = analyst.current(now)
        if got is not None and got.output.is_valid_at(now) and got.output.as_of >= e.known_at:
            return "event:unchanged"
        as_of = min(now, max(now - SETTLE, e.known_at))
        return "event:stored" if analyst.run_at(as_of, now, e.correlation_id or "event") \
            else "event:unchanged"

    return Handler(HANDLER_VERSION, run, deadline=timedelta(seconds=30), max_attempts=3)

