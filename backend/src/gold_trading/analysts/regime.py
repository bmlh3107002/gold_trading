"""Analyst Regime bằng luật (GĐ3 bước 3 — REG-01, REG-02). Bản HMM / classifier ở GĐ7.

Thiết kế + lý do: ``docs/thiet-ke/29-regime-analyst.md``. Mô tả trạng thái thị trường của
nguồn giá (mỗi broker một chuỗi — MT-05) từ nến M15 **đã đóng**:

- ``HIGH_VOL``: ATR14 ≥ 2 × trung vị ATR14 của 960 nến (~10 ngày giao dịch).
- ``TREND``: ADX14 (Wilder) ≥ 25 — hướng theo +DI / −DI.
- ``RANGE``: ADX14 ≤ 20.
- ADX trong (20, 25) hoặc tỉ lệ biến động trong [1,8; 2,2) → **mơ hồ**: vẫn gán nhãn gần nhất
  nhưng gắn ``AMBIGUOUS_REGIME`` + trần confidence 0,5.
- ``RISK_OFF``: cần dữ liệu liên thị trường (USD, lợi suất) → **chưa đánh giá** tới khi có Macro
  analyst (bước 4); không suy từ giá vàng.

KHÔNG có xác suất (luật chưa hiệu chỉnh), KHÔNG ra tín hiệu mua/bán. Ngưỡng ADX 25 / 20 là quy
ước của Wilder; 2× biến động như Technical; vùng mơ hồ và cửa sổ là giá trị khởi đầu **chưa hiệu
chỉnh**. Đổi bất kỳ số nào → tăng ``VERSION``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median
from typing import Any

from gold_trading.analysts.framework import InputCheck, Scope, assess, build_output
from gold_trading.analysts.indicators import adx, atr
from gold_trading.contracts.analyst import AnalystOutput
from gold_trading.contracts.candle import Candle, DataSource
from gold_trading.market.hours import REFERENCE, MarketCalendar
from gold_trading.market.quality import assess_window
from gold_trading.market.timeframes import Timeframe

ANALYST_ID = "regime"
VERSION = "regime-1.0.0"
HANDLER_VERSION = "regime-job-1"

PERIOD = 14
VOL_BASELINE = 960            # ~10 ngày giao dịch M15
HISTORY = 96                  # số nến gần nhất phân loại lại để theo dõi chuyển regime (~1 ngày)
QUALITY_WINDOW = 300          # cổng chất lượng "hiện tại" như Technical
MIN_BARS = VOL_BASELINE + HISTORY + 2 * PERIOD
WINDOW = MIN_BARS + 100
ADX_TREND = 25.0
ADX_RANGE = 20.0
VOL_HIGH = 2.0
VOL_AMBIGUOUS = (1.8, 2.2)
AMBIGUOUS_CONFIDENCE_CAP = 0.5
EXPIRY_GRACE = timedelta(minutes=2)

# REG-02: trọng số gợi ý cho Fusion. CHƯA có cơ sở hiệu chỉnh → trung tính (mọi analyst như nhau),
# ghi rõ ``calibrated: false``. GĐ4 / GĐ6 chốt bảng thật (đổi bảng → đổi WEIGHTS_VERSION + VERSION).
WEIGHTS_VERSION = "regime-weights-0-neutral"
_ANALYSTS = ("event", "macro", "news", "positioning", "technical")
FUSION_WEIGHTS = {r: {a: 1.0 for a in _ANALYSTS} for r in ("TREND", "RANGE", "HIGH_VOL")}


def classify(adx_v: float, vol_ratio: float) -> tuple[str, bool]:
    """(nhãn, mơ hồ). Biến động cao ưu tiên trước xu hướng."""
    vol_amb = VOL_AMBIGUOUS[0] <= vol_ratio < VOL_AMBIGUOUS[1]
    if vol_ratio >= VOL_HIGH:
        return "HIGH_VOL", vol_amb
    if adx_v >= ADX_TREND:
        return "TREND", vol_amb
    if adx_v <= ADX_RANGE:
        return "RANGE", vol_amb
    return ("TREND" if adx_v >= (ADX_TREND + ADX_RANGE) / 2 else "RANGE"), True


def analyze(
    rows: list[Candle],
    *,
    symbol: str,
    timeframe: Timeframe,
    source: DataSource,
    feed: str,
    expected_last_close: datetime,
    correlation_id: str,
    calendar: MarketCalendar = REFERENCE,
) -> AnalystOutput | None:
    """``rows``: nến đã đóng point-in-time (cũ → mới). None nếu không có nến nào."""
    if not rows:
        return None
    window = rows[-WINDOW:]
    last = window[-1]
    as_of = last.close_time
    scope = Scope.of_feed(symbol, timeframe, source, feed)
    recent = assess_window(window[-QUALITY_WINDOW:], timeframe, calendar)
    whole = assess_window(window, timeframe, calendar)

    problems = []
    if recent.low_coverage:
        problems.append("LOW_COVERAGE")
    if recent.outside_session:
        problems.append("CALENDAR_MISMATCH")
    stale = last.close_time < expected_last_close or bool(recent.frozen_runs)
    check = InputCheck("candles", as_of, max_age=timedelta(days=3650), history=len(window),
                       min_history=MIN_BARS, spikes=len(whole.spikes), sample=source.is_sample,
                       healthy=not stale, problems=tuple(problems))
    a = assess([check], as_of)

    q_flags: set[str] = set()
    risk_flags: set[str] = set()
    if last.close_time < expected_last_close:
        q_flags.add("STALE_INPUT")
    if recent.frozen_runs:
        q_flags.add("FROZEN_FEED")
    if whole.low_coverage and not recent.low_coverage:
        q_flags.add("BASELINE_LOW_COVERAGE")
    if calendar.low_liquidity(last.open_time):
        risk_flags.add("LOW_LIQUIDITY_HOLIDAY")

    highs = [c.high for c in window]
    lows = [c.low for c in window]
    closes = [c.close for c in window]
    digest = {"scope": scope.key, "bars": [[c.open_time, c.open, c.high, c.low, c.close,
                                            c.revision] for c in window]}
    base = dict(analyst_id=ANALYST_ID, version=VERSION, scope=scope, as_of=as_of,
                expires_at=as_of + timeframe.delta + EXPIRY_GRACE,
                correlation_id=correlation_id, assessment=a, digest_of=digest,
                quality_flags=q_flags, risk_flags=risk_flags)
    if a.blocked:
        return build_output(**base)

    atr_s = atr(highs, lows, closes, PERIOD)
    adx_s, pdi_s, mdi_s = adx(highs, lows, closes, PERIOD)
    n = len(window)
    labels: list[tuple[str, bool]] = []
    ratios: list[float] = []
    for i in range(n - HISTORY, n):
        base_atr = [x for x in atr_s[i - VOL_BASELINE + 1: i + 1] if x is not None]
        if adx_s[i] is None or atr_s[i] is None or len(base_atr) < VOL_BASELINE // 2:
            raise ValueError("thiếu dữ liệu chỉ báo dù đã đủ số nến")  # lỗi lập trình
        med = median(base_atr)
        ratio = atr_s[i] / med if med > 0 else float("inf")
        ratios.append(ratio)
        labels.append(classify(adx_s[i], ratio))

    regime, ambiguous = labels[-1]
    run = 1
    while run < len(labels) and labels[-1 - run][0] == regime:
        run += 1
    capped = run == len(labels)
    since = None if capped else window[n - run].open_time
    previous = None if capped else labels[-1 - run][0]
    pdi, mdi = pdi_s[-1], mdi_s[-1]
    direction = ("UP" if pdi > mdi else "DOWN" if mdi > pdi else None) \
        if regime == "TREND" else None

    drivers = [f"REGIME_{regime}", "RISK_OFF_NOT_EVALUATED"]
    if direction:
        drivers.append(f"TREND_{direction}")
    if ambiguous:
        drivers.append("AMBIGUOUS_REGIME")
    if run == 1:
        drivers.append("REGIME_CHANGED")
    if regime == "HIGH_VOL":
        risk_flags.add("HIGH_VOLATILITY_REGIME")

    confidence = 1.0 if recent.coverage >= 1.0 else 0.9
    if ambiguous or "BASELINE_LOW_COVERAGE" in q_flags:
        confidence = min(confidence, AMBIGUOUS_CONFIDENCE_CAP)

    def r(x: float | None, d: int = 3) -> float | None:
        return round(x, d) if x is not None and x != float("inf") else None

    features: dict[str, Any] = {
        "regime": regime,
        "direction": direction,
        "ambiguous": ambiguous,
        "adx14": r(adx_s[-1], 2),
        "plus_di": r(pdi, 2),
        "minus_di": r(mdi, 2),
        "atr14": r(atr_s[-1], 4),
        "vol_ratio": r(ratios[-1]),
        "risk_off": "NOT_EVALUATED",
        "bars_in_regime": run,
        "bars_in_regime_capped": capped,
        "regime_since": since,
        "previous_regime": previous,
        "history": [lab for lab, _ in labels[-12:]],
        "thresholds": {"adx_trend": ADX_TREND, "adx_range": ADX_RANGE, "vol_high": VOL_HIGH,
                       "vol_ambiguous": list(VOL_AMBIGUOUS), "vol_baseline_bars": VOL_BASELINE},
        "fusion_weights": {"version": WEIGHTS_VERSION, "calibrated": False,
                           "weights": FUSION_WEIGHTS[regime]},
        "coverage": round(recent.coverage, 4),
    }
    return build_output(**base, features=features, drivers=drivers, confidence=confidence)


class RegimeRunner:
    """Tính + lưu theo nguồn giá cho orchestrator (job ``REGIME``)."""

    def __init__(self, market, store) -> None:
        self.market = market
        self.store = store

    def run_feed(self, feed: str, now: datetime) -> bool:
        m = self.market.with_feed(lambda f=feed: f)
        if m.source is None or m.feed is None:
            return False
        rows = m.candles(as_of=now, limit=WINDOW)
        out = analyze(rows, symbol=m.symbol, timeframe=m.timeframe, source=m.source,
                      feed=m.feed, expected_last_close=m.expected_last_close(now),
                      correlation_id=f"bar-close:{rows[-1].close_time.isoformat()}"
                      if rows else "none", calendar=m.calendar)
        if out is None:
            return False
        return self.store.append_scoped(out, Scope.of_feed(m.symbol, m.timeframe, m.source,
                                                           m.feed), computed_at=now)


def regime_handler(regime_runner: RegimeRunner, active_feeds):
    """Job ``REGIME`` (nến M15 vàng đóng — debounce; kết quả hết hạn → tính lại)."""
    from gold_trading.orchestrator.dispatcher import Handler
    from gold_trading.orchestrator.runner import feed_of

    def run(e, now: datetime) -> str | None:
        feed = feed_of(e)
        if feed is None:
            raise ValueError("sự kiện không có nguồn giá")
        if feed not in active_feeds():
            return "skipped:feed_inactive"
        return "regime:stored" if regime_runner.run_feed(feed, now) else "regime:unchanged"

    return Handler(HANDLER_VERSION, run, deadline=timedelta(seconds=30), max_attempts=3,
                   fatal=(ValueError,))
