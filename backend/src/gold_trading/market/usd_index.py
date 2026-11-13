"""Chỉ số USD tự tính từ giá MT5 của broker (GĐ1 bước 9d — ING-24, DEC-03, DEC-14).

Thiết kế + lý do: ``docs/thiet-ke/19-chi-so-usd.md``.

Công thức công khai của chỉ số đô la Mỹ (6 cặp, trọng số hình học):

    I = 50.14348112 × EURUSD^-0.576 × USDJPY^0.136 × GBPUSD^-0.119
                    × USDCAD^0.091 × USDSEK^0.042 × USDCHF^0.036

Nhãn bắt buộc: **"chỉ số USD tự tính"** — không phải DXY chính thức (DXY tính trên giá liên ngân
hàng của nhà cung cấp chỉ số; ở đây là giá **của broker người dùng**, nên lệch so với DXY).

An toàn:
- Mỗi tài khoản theo **giá broker của chính mình** (DEC-14): 6 cặp lấy từ các nguồn giá cùng
  **server MT5**; không bao giờ trộn hai broker.
- Chỉ nến **M15 đã đóng** và đã biết tại ``as_of`` (point-in-time). Dùng giá đóng cửa của
  **cùng một nến** (cùng ``open_time``) cho cả 6 cặp; thiếu cặp nào / không có nến chung →
  ``INSUFFICIENT_DATA``, không nội suy, không lấy nến cũ hơn của riêng một cặp (DEC-03).
- Nến chung mới nhất đóng cách ``as_of`` quá 30 phút (cuối tuần, mất kết nối) → không đủ dữ liệu.
- Giá một cặp ngoài khoảng hợp lý (nghi nhầm symbol / đảo chiều báo giá) → không đủ dữ liệu.
- Hai symbol broker cùng một cặp đều có nến mới nhất cùng lúc → mơ hồ → không đủ dữ liệu.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from gold_trading.contracts.candle import DataSource
from gold_trading.market.feeds import USD_INDEX_PAIRS
from gold_trading.market.timeframes import Timeframe

FORMULA_VERSION = "usd-index-6pairs-2026.11.13"
LABEL = "chỉ số USD tự tính (công thức 6 cặp như DXY, giá broker — không phải DXY chính thức)"
CONSTANT = 50.14348112
WEIGHTS: dict[str, float] = {
    "EURUSD": -0.576, "USDJPY": 0.136, "GBPUSD": -0.119,
    "USDCAD": 0.091, "USDSEK": 0.042, "USDCHF": 0.036,
}
# Khoảng hợp lý rất rộng — chỉ bắt nhầm symbol / đảo báo giá / đổi đơn vị, không bắt biến động.
PLAUSIBLE: dict[str, tuple[float, float]] = {
    "EURUSD": (0.5, 2.5), "USDJPY": (50.0, 400.0), "GBPUSD": (0.7, 3.0),
    "USDCAD": (0.7, 2.5), "USDSEK": (4.0, 20.0), "USDCHF": (0.3, 2.5),
}
MAX_AGE = timedelta(minutes=30)   # nến chung mới nhất phải đóng trong 30 phút trước as_of
LOOKBACK = 16                     # số nến M15 gần nhất xét mỗi cặp (4 giờ)
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
# Cờ nến đầu vào được chuyển lên chỉ số (cảnh báo, không chặn)
WARN_FLAGS = frozenset({"PRICE_JUMP", "ZERO_RANGE", "REVISED", "GAP_BEFORE"})


@dataclass(frozen=True)
class UsdIndex:
    as_of: datetime
    status: str                                  # OK / INSUFFICIENT_DATA
    reason: str | None
    bar_open_time: datetime | None               # nến M15 chung dùng để tính
    value: float | None
    components: dict[str, float] = field(default_factory=dict)   # giá đóng cửa từng cặp
    flags: tuple[str, ...] = ()
    detail: str | None = None                    # cặp gây ra "không đủ dữ liệu"
    version: str = FORMULA_VERSION
    label: str = LABEL


def compute(closes: Mapping[str, float]) -> float:
    """Công thức thuần (6 giá đóng cửa → chỉ số). Thiếu cặp → ``KeyError``."""
    log_i = math.log(CONSTANT)
    for pair, w in WEIGHTS.items():
        p = closes[pair]
        if not (p > 0 and math.isfinite(p)):
            raise ValueError(f"giá {pair} không hợp lệ")
        log_i += w * math.log(p)
    return math.exp(log_i)


def _insufficient(as_of, reason, detail=None, bar=None) -> UsdIndex:
    return UsdIndex(as_of, INSUFFICIENT_DATA, reason, bar, None, detail=detail)


def usd_index(store, feeds: Mapping[str, str], as_of: datetime) -> UsdIndex:
    """Chỉ số tại ``as_of`` từ nến M15 của 6 nguồn giá ``feeds`` (cặp → feed_id, cùng server)."""
    if as_of.tzinfo is None:
        raise ValueError("as_of phải có múi giờ (UTC)")
    as_of = as_of.astimezone(UTC)
    missing = [p for p in USD_INDEX_PAIRS if not feeds.get(p)]
    if missing:
        return _insufficient(as_of, "PAIR_MISSING", ",".join(missing))
    bars: dict[str, dict[datetime, object]] = {}
    for pair in USD_INDEX_PAIRS:
        rows = store.query(pair, Timeframe.M15, DataSource.MT5, as_of=as_of, end=as_of,
                           limit=LOOKBACK, feed=feeds[pair])
        # Chỉ nến đã đóng trước as_of (available_at <= as_of đã do store bảo đảm)
        bars[pair] = {c.open_time: c for c in rows if c.close_time <= as_of}
        if not bars[pair]:
            return _insufficient(as_of, "PAIR_NO_DATA", pair)
    common = set.intersection(*(set(b) for b in bars.values()))
    if not common:
        return _insufficient(as_of, "NO_COMMON_BAR")
    t = max(common)
    if as_of - (t + Timeframe.M15.delta) > MAX_AGE:
        return _insufficient(as_of, "STALE", bar=t)
    closes: dict[str, float] = {}
    flags: set[str] = set()
    for pair in USD_INDEX_PAIRS:
        c = bars[pair][t]
        lo, hi = PLAUSIBLE[pair]
        if not lo <= c.close <= hi:
            return _insufficient(as_of, "PAIR_OUT_OF_RANGE", pair, bar=t)
        closes[pair] = c.close
        flags |= {f"{pair}:{f.value}" for f in c.flags if f.value in WARN_FLAGS}
        if max(bars[pair]) > t:
            flags.add(f"{pair}:NEWER_BAR_NOT_COMMON")  # cặp này đã có nến mới hơn nến chung
    return UsdIndex(as_of, "OK", None, t, round(compute(closes), 4), closes,
                    tuple(sorted(flags)))


def resolve_feeds(repo, store, mt5_server: str,
                  as_of: datetime) -> tuple[dict[str, str], str | None]:
    """Cặp → feed_id trên một server: symbol broker chứa tên cặp (như Gateway). Nhiều symbol cho
    một cặp (vd. đổi hậu tố) → chọn cái có nến mới nhất; hai cái cùng mới nhất → mơ hồ."""
    feeds = [f for f in repo.price_feeds_for_server(mt5_server) if "XAU" not in f.broker_symbol]
    out: dict[str, str] = {}
    for pair in USD_INDEX_PAIRS:
        cands = []
        for f in feeds:
            if pair not in f.broker_symbol:
                continue
            last = store.query(pair, Timeframe.M15, DataSource.MT5, as_of=as_of, end=as_of,
                               limit=1, feed=f.feed_id)
            if last:
                cands.append((last[-1].open_time, f.feed_id))
        if not cands:
            continue
        cands.sort(reverse=True)
        if len(cands) > 1 and cands[0][0] == cands[1][0]:
            return {}, f"AMBIGUOUS_FEED:{pair}"
        out[pair] = cands[0][1]
    return out, None


def usd_index_for_server(repo, store, mt5_server: str, as_of: datetime) -> UsdIndex:
    if as_of.tzinfo is None:
        raise ValueError("as_of phải có múi giờ (UTC)")
    feeds, problem = resolve_feeds(repo, store, mt5_server, as_of.astimezone(UTC))
    if problem:
        return _insufficient(as_of.astimezone(UTC), "AMBIGUOUS_FEED", problem.split(":")[1])
    return usd_index(store, feeds, as_of)
