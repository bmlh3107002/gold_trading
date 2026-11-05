"""Dịch vụ dữ liệu thị trường: đọc nến point-in-time, tóm tắt giá, độ mới dữ liệu, chỉ báo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from gold_trading.analysts.indicators import ema, rsi
from gold_trading.contracts.candle import Candle, DataSource
from gold_trading.market.hours import MarketSession, bar_in_session, session_at
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.candles import CandleStore, QuarantineEntry, SeriesStats

INDICATOR_WARMUP = 200  # số nến lấy thêm phía trước để EMA/RSI ổn định
# Nguồn được phép trễ bao lâu sau khi nến đóng trước khi coi là "cũ"
FRESHNESS_GRACE = timedelta(minutes=2)


class Freshness(StrEnum):
    NO_DATA = "NO_DATA"
    FRESH = "FRESH"
    STALE = "STALE"  # thiếu nến lẽ ra đã phải có (kể cả khi bây giờ thị trường đã đóng)
    MARKET_CLOSED = "MARKET_CLOSED"  # đủ nến tới lúc đóng cửa; không có nến mới là bình thường


@dataclass(frozen=True)
class Summary:
    symbol: str
    timeframe: Timeframe
    source: DataSource | None
    session: MarketSession
    freshness: Freshness
    last: Candle | None
    change: float | None
    change_pct: float | None
    as_of: datetime


@dataclass(frozen=True)
class IndicatorSeries:
    ema20: list[float | None]
    ema50: list[float | None]
    rsi14: list[float | None]


class MarketDataService:
    def __init__(
        self,
        store: CandleStore,
        *,
        source: DataSource | None,
        symbol: str = "XAUUSD",
        timeframe: Timeframe = Timeframe.M15,
    ) -> None:
        self.store = store
        self.source = source
        self.symbol = symbol
        self.timeframe = timeframe

    @property
    def is_sample(self) -> bool:
        return self.source is not None and self.source.is_sample

    def candles(self, *, as_of: datetime, limit: int, end: datetime | None = None) -> list[Candle]:
        if self.source is None:
            return []
        return self.store.query(
            self.symbol, self.timeframe, self.source, as_of=as_of, end=end, limit=limit
        )

    def candles_with_indicators(
        self, *, as_of: datetime, limit: int, end: datetime | None = None
    ) -> tuple[list[Candle], IndicatorSeries]:
        rows = self.candles(as_of=as_of, limit=limit + INDICATOR_WARMUP, end=end)
        closes = [c.close for c in rows]
        series = IndicatorSeries(ema(closes, 20), ema(closes, 50), rsi(closes, 14))
        cut = max(len(rows) - limit, 0)
        return rows[cut:], IndicatorSeries(
            series.ema20[cut:], series.ema50[cut:], series.rsi14[cut:]
        )

    def summary(self, now: datetime) -> Summary:
        session = session_at(now)
        recent = self.candles(as_of=now, limit=200)
        last = recent[-1] if recent else None
        change = change_pct = None
        if last:
            # So với nến gần nhất cách khoảng 24 giờ (bỏ qua cuối tuần thì dùng nến xa nhất có được)
            ref_time = last.close_time - timedelta(hours=24)
            ref = next((c for c in reversed(recent) if c.close_time <= ref_time), None)
            if ref is None:
                # end lọc theo open_time: lùi 1 nến để đảm bảo close_time <= ref_time
                older = self.candles(as_of=now, limit=1, end=ref_time - self.timeframe.delta)
                ref = older[-1] if older else None
            if ref:
                change = round(last.close - ref.close, 2)
                change_pct = (last.close / ref.close - 1) if ref.close else None
        return Summary(
            symbol=self.symbol,
            timeframe=self.timeframe,
            source=self.source,
            session=session,
            freshness=self._freshness(last, session, now),
            last=last,
            change=change,
            change_pct=change_pct,
            as_of=now,
        )

    def expected_last_close(self, now: datetime) -> datetime:
        """Thời điểm đóng của nến gần nhất (trong giờ mở cửa) lẽ ra đã phải có tại ``now``."""
        tf = self.timeframe
        t = tf.floor(now - FRESHNESS_GRACE)
        for _ in range(7 * 24 * 60):  # tối đa một tuần nến M1; luôn dừng sớm hơn nhiều
            if bar_in_session(t - tf.delta, t):
                return t
            t -= tf.delta
        return t

    def _freshness(self, last: Candle | None, session: MarketSession, now: datetime) -> Freshness:
        if last is None:
            return Freshness.NO_DATA
        if last.close_time < self.expected_last_close(now):
            return Freshness.STALE
        if session is not MarketSession.OPEN:
            return Freshness.MARKET_CLOSED
        return Freshness.FRESH

    def stats(self) -> SeriesStats | None:
        if self.source is None:
            return None
        return self.store.stats(self.symbol, self.timeframe, self.source)

    def quarantine(self, limit: int = 20) -> list[QuarantineEntry]:
        return [q for q in self.store.quarantine(limit * 5) if q.symbol == self.symbol][:limit]
