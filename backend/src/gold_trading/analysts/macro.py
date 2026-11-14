"""Analyst Macro bằng luật (GĐ3 bước 4 — MAC-01, MAC-02).

Thiết kế + lý do: ``docs/thiet-ke/30-macro-analyst.md``. Theo nguồn giá vàng của tài khoản (chỉ số
USD tính theo broker — DEC-14), đầu vào đã có từ GĐ1:

- **Lợi suất thực 10 năm** (H.15 ``UST_TIPS_10Y``) — **bắt buộc**.
- Lợi suất danh nghĩa 10 năm / 2 năm (H.15) — tùy chọn.
- **Chỉ số USD tự tính** (6 cặp, giá broker — DEC-03) — tùy chọn (thiếu → vẫn chạy, hạ trần
  confidence; broker chưa gửi đủ 6 cặp không làm tê liệt cả analyst).
- Proxy kỳ vọng Fed (2 năm − EFFR, DEC-04) — chỉ mô tả.

Đầu ra: thay đổi 1 / 5 kỳ, **độ bất thường** (z = thay đổi / độ lệch chuẩn lịch sử của chính chuỗi),
hướng (|z 5 kỳ| ≥ 1), ``macro_bias`` cho vàng theo quan hệ ngược chiều **lý thuyết** với USD và lợi
suất thực, cờ stress (|z 1 kỳ| ≥ 3). KHÔNG phải xác suất, KHÔNG phải dự báo; các ngưỡng chưa hiệu
chỉnh. Revision: dữ liệu lấy point-in-time → bản sửa biết sau không viết lại kết quả cũ.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from statistics import pstdev
from typing import Any

from gold_trading.analysts.framework import InputCheck, Scope, assess, build_output
from gold_trading.contracts.analyst import AnalystOutput
from gold_trading.contracts.candle import DataSource
from gold_trading.ingestion.macro_view import fed_expectation_proxy
from gold_trading.market import usd_index as U
from gold_trading.market.timeframes import Timeframe

log = logging.getLogger("gold_trading.analysts")

ANALYST_ID = "macro"
VERSION = "macro-1.0.0"
HANDLER_VERSION = "macro-job-1"

H15 = "fed_h15"
REAL_10Y, NOM_10Y, NOM_2Y = "UST_TIPS_10Y", "UST_CMT_10Y", "UST_CMT_2Y"
RATE_SERIES = {REAL_10Y: "real_yield_10y", NOM_10Y: "nominal_10y", NOM_2Y: "nominal_2y"}
RATE_MAX_AGE_DAYS = 7            # như proxy Fed / data_ttl H.15 (lễ + cuối tuần)
RATE_LOOKBACK_OBS = 60           # ~3 tháng ngày làm việc để đo độ lệch chuẩn thay đổi ngày
RATE_MIN_OBS = 21                # ≥ 20 thay đổi ngày để tính độ lệch chuẩn → z / hướng
RATE_MIN_FOR_CHANGE = 6          # tối thiểu để có thay đổi 5 kỳ (dưới mức này: chặn)
DAY_BARS = 96                    # 1 ngày giao dịch M15
WEEK_BARS = 5 * DAY_BARS
USD_HISTORY_BARS = 20 * DAY_BARS  # độ lệch chuẩn lợi suất M15 của 20 ngày
USD_MIN_POINTS = WEEK_BARS + 1
DIR_Z = 1.0                      # |z 5 kỳ| ≥ 1 → có hướng (chưa hiệu chỉnh)
STRESS_Z = 3.0                   # |z 1 kỳ| ≥ 3 → cờ stress (chưa hiệu chỉnh)
FLIGHT_Z = 2.0                   # USD z1 ≥ 2 và lợi suất 10 năm z1 ≤ −2 → dấu hiệu trú ẩn (proxy)
DEGRADED_CONFIDENCE_CAP = 0.5
TTL = timedelta(minutes=17)      # nhịp M15 + 2 phút như Technical
SETTLE = timedelta(seconds=5)
FALLBACK_GRACE = timedelta(seconds=60)


def _dec(v) -> Decimal | None:
    try:
        d = Decimal(str(v))
    except (InvalidOperation, TypeError):
        return None
    return d if d.is_finite() else None


def _z(change: float | None, sd: float | None, horizon: int) -> float | None:
    if change is None or not sd:
        return None
    return change / (sd * math.sqrt(horizon))


def _direction(z5: float | None) -> str | None:
    if z5 is None:
        return None
    return "UP" if z5 >= DIR_Z else "DOWN" if z5 <= -DIR_Z else "FLAT"


def _r(x: float | None, d: int = 3) -> float | None:
    return round(x, d) if x is not None else None


# ------------------------------------------------------------------ H.15

def rate_view(record_store, series: str, as_of: datetime) -> dict[str, Any]:
    """Một chuỗi H.15 tại ``as_of`` (point-in-time). Thay đổi theo **điểm cơ bản** bằng Decimal."""
    obs: dict[str, tuple[Decimal, str, datetime]] = {}
    for r in record_store.as_of(as_of, source=H15, kind="macro",
                                event_from=as_of - timedelta(days=200)):
        p = r.payload
        if p.get("series") != series or p.get("value_status") != "AVAILABLE":
            continue
        v = _dec(p.get("value"))
        if v is not None:
            obs[p["date"]] = (v, p["value"], r.known_at)
    days = sorted(obs)[-(RATE_LOOKBACK_OBS + 1):]
    if not days:
        return {"status": "MISSING", "known_at": None, "history": 0}
    last = days[-1]
    v, raw, known = obs[last]
    vals = [obs[d][0] for d in days]
    ch = [float((b - a) * 100) for a, b in zip(vals, vals[1:], strict=False)]
    sd = pstdev(ch) if len(ch) >= RATE_MIN_OBS - 1 else None
    c1 = ch[-1] if ch else None
    c5 = float((vals[-1] - vals[-6]) * 100) if len(vals) >= 6 else None
    z1, z5 = _z(c1, sd, 1), _z(c5, sd, 5)
    age_days = (as_of.date() - date.fromisoformat(last)).days
    return {"status": "OK" if age_days <= RATE_MAX_AGE_DAYS else "STALE",
            "known_at": max(o[2] for o in obs.values()), "history": len(days),
            "date": last, "value": raw, "change_1d_bp": _r(c1, 1), "change_5d_bp": _r(c5, 1),
            "z_1d": _r(z1), "z_5d": _r(z5), "direction": _direction(z5),
            "zero_dispersion": sd == 0}


# ------------------------------------------------------------------ chỉ số USD

def usd_view(repo, candle_store, mt5_server: str | None, as_of: datetime) -> dict[str, Any]:
    """Chỉ số USD hiện tại (đúng ``usd_index``) + chuỗi trên các nến chung để đo thay đổi / z."""
    if not mt5_server or repo is None:
        return {"status": "INSUFFICIENT_DATA", "reason": "NO_MT5_SERVER", "history": 0}
    feeds, problem = U.resolve_feeds(repo, candle_store, mt5_server, as_of)
    cur = (U._insufficient(as_of, "AMBIGUOUS_FEED", problem.split(":")[1]) if problem
           else U.usd_index(candle_store, feeds, as_of))
    base: dict[str, Any] = {"status": cur.status, "reason": cur.reason, "detail": cur.detail,
                            "label": U.LABEL, "formula": U.FORMULA_VERSION,
                            "flags": list(cur.flags), "history": 0}
    if cur.bar_open_time is not None:
        base["bar_close_time"] = cur.bar_open_time + Timeframe.M15.delta
    if cur.status != "OK":
        return base
    bars: dict[str, dict[datetime, float]] = {}
    for pair in U.USD_INDEX_PAIRS:
        rows = candle_store.query(pair, Timeframe.M15, DataSource.MT5, as_of=as_of, end=as_of,
                                  limit=USD_HISTORY_BARS + WEEK_BARS + 16, feed=feeds[pair])
        lo, hi = U.PLAUSIBLE[pair]
        bars[pair] = {c.open_time: c.close for c in rows
                      if c.close_time <= as_of and lo <= c.close <= hi}
    common = sorted(set.intersection(*(set(b) for b in bars.values())))
    common = [t for t in common if t <= cur.bar_open_time]
    series = [U.compute({p: bars[p][t] for p in U.USD_INDEX_PAIRS}) for t in common]
    base.update(value=cur.value, bar_open_time=cur.bar_open_time, history=len(series))
    if len(series) < USD_MIN_POINTS or common[-1] != cur.bar_open_time:
        return base
    rets = [math.log(b / a) for a, b in zip(series, series[1:], strict=False)]
    sd = pstdev(rets[-USD_HISTORY_BARS:])
    c1 = math.log(series[-1] / series[-1 - DAY_BARS])
    c5 = math.log(series[-1] / series[-1 - WEEK_BARS])
    z1, z5 = _z(c1, sd, DAY_BARS), _z(c5, sd, WEEK_BARS)
    base.update(change_1d_pct=_r(c1 * 100, 4), change_5d_pct=_r(c5 * 100, 4), z_1d=_r(z1),
                z_5d=_r(z5), direction=_direction(z5), series_last=round(series[-1], 4))
    return base


# ------------------------------------------------------------------ analyst

_GOLD = {"UP": -1, "DOWN": 1, "FLAT": 0}   # quan hệ ngược chiều lý thuyết với vàng


def bias(dirs: dict[str, str | None]) -> str:
    vals = [_GOLD[d] for d in dirs.values() if d is not None]
    if not vals:
        return "INSUFFICIENT_DATA"
    if 1 in vals and -1 in vals:
        return "MIXED"
    if 1 in vals:
        return "SUPPORTIVE"
    if -1 in vals:
        return "HEADWIND"
    return "NEUTRAL"


def compute(*, repo, candle_store, record_store, scope: Scope, mt5_server: str | None,
            as_of: datetime, correlation_id: str = "macro") -> AnalystOutput:
    rates = {code: rate_view(record_store, code, as_of) for code in RATE_SERIES}
    usd = usd_view(repo, candle_store, mt5_server, as_of)
    proxy = fed_expectation_proxy(record_store, as_of)

    checks = []
    for code, name in RATE_SERIES.items():
        v = rates[code]
        checks.append(InputCheck(name, v["known_at"], timedelta(days=3650),
                                 required=code == REAL_10Y, history=v["history"],
                                 min_history=RATE_MIN_FOR_CHANGE,
                                 healthy=v["status"] != "STALE"))
    usd_known = usd.get("bar_close_time") if usd["status"] == "OK" or usd.get(
        "reason") == "STALE" else None
    usd_problem = () if usd["status"] == "OK" or usd.get("reason") in (
        "STALE", "PAIR_MISSING", "PAIR_NO_DATA", "NO_MT5_SERVER", "NO_COMMON_BAR") \
        else (usd["reason"],)
    checks.append(InputCheck("usd_index", usd_known, U.MAX_AGE, required=False,
                             history=usd["history"], min_history=USD_MIN_POINTS,
                             healthy=usd["status"] == "OK", problems=usd_problem))
    a = assess(checks, as_of)

    usd_ok = usd["status"] == "OK" and usd.get("z_5d") is not None
    real = rates[REAL_10Y]
    dirs = {"real_yield_10y": real.get("direction") if real["status"] == "OK" else None,
            "usd_index": usd.get("direction") if usd_ok else None}
    b = bias(dirs)
    stress = sorted(n for n, z in (("real_yield_10y", real.get("z_1d")),
                                   ("nominal_10y", rates[NOM_10Y].get("z_1d")),
                                   ("usd_index", usd.get("z_1d") if usd_ok else None))
                    if z is not None and abs(z) >= STRESS_Z)
    nom1 = rates[NOM_10Y].get("z_1d")
    flight = (None if not usd_ok or nom1 is None
              else usd["z_1d"] >= FLIGHT_Z and nom1 <= -FLIGHT_Z)

    q_flags: set[str] = set()
    risk_flags: set[str] = set()
    drivers = [f"MACRO_BIAS_{b}"]
    confidence = 1.0
    if not usd_ok:
        q_flags.add("USD_INDEX_UNAVAILABLE")
        confidence = DEGRADED_CONFIDENCE_CAP
    for code, v in rates.items():
        if 0 < v["history"] < RATE_MIN_OBS:            # có mức + thay đổi, chưa đủ để tính z
            q_flags.add(f"Z_HISTORY_SHORT:{RATE_SERIES[code]}")
            if code == REAL_10Y:
                confidence = min(confidence, DEGRADED_CONFIDENCE_CAP)
    if any(v.get("zero_dispersion") for v in rates.values()):
        q_flags.add("RATE_ZERO_DISPERSION")
    if b == "MIXED":                                  # 3-C08: các nguồn mâu thuẫn
        drivers.append("MACRO_DRIVERS_CONFLICT")
        confidence = min(confidence, DEGRADED_CONFIDENCE_CAP)
    for name, d in dirs.items():
        if d in ("UP", "DOWN"):
            drivers.append(f"{name.upper()}_{d}")
    if stress:
        risk_flags.add("MACRO_STRESS")
        drivers += [f"STRESS:{s}" for s in stress]
    if flight:
        risk_flags.add("FLIGHT_TO_SAFETY_PROXY")
    if usd.get("flags"):
        q_flags.update(f"USD:{f}" for f in usd["flags"])

    def clean(v: dict[str, Any]) -> dict[str, Any]:
        return {k: x for k, x in v.items() if k not in ("known_at", "zero_dispersion")}

    features = {
        "macro_bias": b,
        "bias_drivers": dirs,
        "bias_complete": all(d is not None for d in dirs.values()),
        "bias_rule": "vàng ngược chiều USD và lợi suất thực (lý thuyết, chưa hiệu chỉnh)",
        "rates": {RATE_SERIES[c]: clean(v) for c, v in rates.items()},
        "usd_index": usd,
        "fed_proxy": {"status": proxy.status, "reason": proxy.reason, "lean": proxy.lean,
                      "spread_bp": proxy.spread_bp,
                      "observation_date": proxy.observation_date.isoformat()
                      if proxy.observation_date else None, "label": proxy.label,
                      "version": proxy.version},
        "stress": stress,
        "flight_to_safety_proxy": flight,
        "thresholds": {"direction_z": DIR_Z, "stress_z": STRESS_Z, "flight_z": FLIGHT_Z,
                       "rate_lookback_obs": RATE_LOOKBACK_OBS,
                       "usd_history_bars": USD_HISTORY_BARS},
    }
    digest = {"rates": {c: [v.get("date"), v.get("value"), v.get("history")] for c, v in
                        rates.items()},
              "usd": [usd.get("status"), usd.get("reason"), usd.get("bar_open_time"),
                      usd.get("value"), usd.get("series_last"), usd.get("history")],
              "proxy": [proxy.status, str(proxy.observation_date), proxy.spread_bp],
              "server": (mt5_server or "").lower()}
    return build_output(analyst_id=ANALYST_ID, version=VERSION, scope=scope, as_of=as_of,
                        expires_at=as_of + TTL, correlation_id=correlation_id, assessment=a,
                        digest_of=digest, features=features, drivers=drivers,
                        risk_flags=risk_flags, quality_flags=q_flags, confidence=confidence)


class MacroAnalyst:
    """Tính + lưu theo nguồn giá vàng. ``market``: dịch vụ giá (symbol / khung / nguồn)."""

    def __init__(self, *, repo, candle_store, record_store, out_store, market,
                 active_feeds) -> None:
        self.repo = repo
        self.candle_store = candle_store
        self.record_store = record_store
        self.out_store = out_store
        self.market = market
        self.active_feeds = active_feeds

    def server_of(self, feed: str) -> str | None:
        f = self.repo.price_feed(feed) if (self.repo is not None and feed) else None
        return f.mt5_server.lower() if f is not None else None

    def scope(self, feed: str) -> Scope:
        m = self.market
        return Scope.of_feed(m.symbol, m.timeframe, m.source, feed)

    def current(self, feed: str, now: datetime):
        got = self.out_store.latest_scoped(ANALYST_ID, self.scope(feed), known_by=now)
        return got if got is not None and got.output.version == VERSION else None

    def run_at(self, feed: str, as_of: datetime, now: datetime, correlation_id="macro") -> bool:
        if self.market.source is None:
            return False
        out = compute(repo=self.repo, candle_store=self.candle_store,
                      record_store=self.record_store, scope=self.scope(feed),
                      mt5_server=self.server_of(feed), as_of=as_of,
                      correlation_id=correlation_id)
        return self.out_store.append_scoped(out, self.scope(feed), computed_at=now)

    def targets(self, e) -> list[str]:
        """Nguồn giá vàng bị ảnh hưởng bởi sự kiện."""
        from gold_trading.orchestrator.model import EventType
        from gold_trading.orchestrator.runner import feed_of
        active = list(self.active_feeds())
        if e.event_type is EventType.MACRO_UPDATED:
            return active
        feed = feed_of(e)
        if feed is None:
            return []
        if e.event_type is EventType.OUTPUT_EXPIRED:
            return [feed] if feed in active else []
        srv = self.server_of(feed)       # nến cặp tiền → các nguồn vàng cùng server
        return [g for g in active if srv is not None and self.server_of(g) == srv]

    def ensure_fresh(self, now: datetime) -> int:
        n = 0
        for feed in self.active_feeds():
            got = self.current(feed, now)
            if got is None or got.output.expires_at <= now - FALLBACK_GRACE:
                n += self.run_at(feed, now - SETTLE, now, "macro:fallback")
        return n


def macro_handler(analyst: MacroAnalyst):
    """Job ``MACRO`` (nến cặp tiền, số H.15 mới, kết quả hết hạn)."""
    from gold_trading.orchestrator.dispatcher import Handler

    def run(e, now: datetime) -> str | None:
        stored = skipped = 0
        for feed in analyst.targets(e):
            got = analyst.current(feed, now)
            if got is not None and got.output.is_valid_at(now) and got.output.as_of >= e.known_at:
                skipped += 1
                continue
            as_of = min(now, max(now - SETTLE, e.known_at))
            stored += analyst.run_at(feed, as_of, now, e.correlation_id or "macro")
        return f"macro:stored={stored},skipped={skipped}"

    return Handler(HANDLER_VERSION, run, deadline=timedelta(seconds=60), max_attempts=3)
