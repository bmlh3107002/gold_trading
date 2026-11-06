import type {
  Me,
  AnalystLatest,
  CandlesResponse,
  DataQuality,
  MarketSummary,
  SystemStatus,
} from "../api/client";

export function makeMe(over: Partial<Me> = {}): Me {
  return {
    sub: "sub-admin",
    username: "admin",
    email: "admin@example.com",
    display_name: null,
    is_admin: true,
    session_expires_at: "2026-11-06T12:00:00Z",
    idle_timeout_seconds: 1800,
    ...over,
  };
}

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

export function makeTechnical(
  over: Partial<AnalystLatest> = {},
  outOver: Partial<NonNullable<AnalystLatest["output"]>> = {},
): AnalystLatest {
  return {
    computed_at: "2026-01-06T14:46:00Z",
    valid_now: true,
    is_sample: true,
    confidence_meaning: "DATA_QUALITY_ONLY",
    output: {
      output_id: "technical:1",
      analyst_id: "technical",
      as_of: "2026-01-06T14:45:00Z",
      expires_at: "2026-01-06T15:02:00Z",
      confidence: 1,
      features: {
        close: 2412.5,
        atr14: 4.2,
        atr_pct: 0.0017,
        vol_ratio: 1.1,
        trend: "UP",
        structure: "BULLISH",
        rsi14: 61.2,
        nearest_support: { price: 2405.1, low: 2404.8, high: 2405.4, touches: 3, distance_atr: 1.8 },
        nearest_resistance: { price: 2420.0, low: 2419.7, high: 2420.3, touches: 2, distance_atr: 1.8 },
        levels: [],
        input: { coverage: 1 },
      },
      drivers: ["TREND_UP"],
      risk_flags: [],
      source_status: "HEALTHY",
      quality_flags: ["SAMPLE_DATA"],
      version: "technical-1.0.0",
      correlation_id: "c",
      ...outOver,
    },
    ...over,
  };
}
