import type { CandlesResponse, DataQuality, MarketSummary, SystemStatus } from "../api/client";

export function makeStatus(over: Partial<SystemStatus> = {}): SystemStatus {
  return {
    version: "0.1.0",
    storage: "postgres",
    data_source: "SAMPLE",
    data_is_sample: true,
    mode: "PAPER",
    live_unlocked: false,
    live_checklist: [],
    safety_state: "PAUSED",
    allows_new_orders: false,
    safety_history: [],
    market_view: null,
    ...over,
  };
}

export function makeSummary(over: Partial<MarketSummary> = {}): MarketSummary {
  return {
    symbol: "XAUUSD",
    timeframe: "M15",
    source: "SAMPLE",
    is_sample: true,
    session: "OPEN",
    freshness: "FRESH",
    as_of: "2026-01-06T14:20:00Z",
    last_price: 2412.5,
    last_close_time: "2026-01-06T14:15:00Z",
    change: 12.5,
    change_pct: 0.0052,
    ...over,
  };
}

export function makeCandles(n = 3, over: Partial<CandlesResponse> = {}): CandlesResponse {
  const candles = Array.from({ length: n }, (_, i) => {
    const t = new Date(Date.UTC(2026, 0, 6, 14, 0) + i * 15 * 60_000);
    return {
      open_time: t.toISOString(),
      close_time: new Date(t.getTime() + 15 * 60_000).toISOString(),
      open: 2400 + i,
      high: 2402 + i,
      low: 2399 + i,
      close: 2401 + i,
      tick_volume: 100,
      spread_points: 20,
      revision: 0,
      flags: [] as CandlesResponse["candles"][number]["flags"],
    };
  });
  return {
    symbol: "XAUUSD",
    timeframe: "M15",
    source: "SAMPLE",
    is_sample: true,
    as_of: "2026-01-06T15:00:00Z",
    candles,
    ema20: candles.map(() => 2400),
    ema50: candles.map(() => null),
    rsi14: candles.map(() => 55),
    ...over,
  };
}

export function makeQuality(over: Partial<DataQuality> = {}): DataQuality {
  return {
    source: "SAMPLE",
    is_sample: true,
    candle_count: 3,
    first_open_time: "2026-01-06T14:00:00Z",
    last_open_time: "2026-01-06T14:30:00Z",
    last_ingested_at: "2026-01-06T14:45:00Z",
    quarantined: 1,
    recent_quarantine: [
      { received_at: "2026-01-06T14:45:00Z", source: "SAMPLE", reason: "INVALID_OHLC", raw: {} },
    ],
    ...over,
  };
}

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
