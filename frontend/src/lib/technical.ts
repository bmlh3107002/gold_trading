/** Đọc an toàn phần features của Technical analyst v1 (docs/thiet-ke/03). Thiếu/sai kiểu → null. */
export interface Level {
  price: number;
  low: number;
  high: number;
  touches: number;
  distance_atr?: number;
}

export interface TechnicalFeatures {
  close: number | null;
  atr14: number | null;
  atr_pct: number | null;
  vol_ratio: number | null;
  ema50_slope_atr: number | null;
  trend: "UP" | "DOWN" | "FLAT" | null;
  structure: "BULLISH" | "BEARISH" | "MIXED" | "UNKNOWN" | null;
  rsi14: number | null;
  levels: Level[];
  nearest_support: Level | null;
  nearest_resistance: Level | null;
  coverage: number | null;
}

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const oneOf = <T extends string>(v: unknown, allowed: readonly T[]) =>
  typeof v === "string" && (allowed as readonly string[]).includes(v) ? (v as T) : null;

function level(v: unknown): Level | null {
  if (!v || typeof v !== "object") return null;
  const o = v as Record<string, unknown>;
  const price = num(o.price);
  const low = num(o.low);
  const high = num(o.high);
  const touches = num(o.touches);
  if (price == null || low == null || high == null || touches == null) return null;
  return { price, low, high, touches, distance_atr: num(o.distance_atr) ?? undefined };
}

export function readTechnical(features: Record<string, unknown> | undefined): TechnicalFeatures {
  const f = features ?? {};
  const input = (f.input && typeof f.input === "object" ? f.input : {}) as Record<string, unknown>;
  return {
    close: num(f.close),
    atr14: num(f.atr14),
    atr_pct: num(f.atr_pct),
    vol_ratio: num(f.vol_ratio),
    ema50_slope_atr: num(f.ema50_slope_atr),
    trend: oneOf(f.trend, ["UP", "DOWN", "FLAT"] as const),
    structure: oneOf(f.structure, ["BULLISH", "BEARISH", "MIXED", "UNKNOWN"] as const),
    rsi14: num(f.rsi14),
    levels: Array.isArray(f.levels) ? f.levels.map(level).filter((x): x is Level => x !== null) : [],
    nearest_support: level(f.nearest_support),
    nearest_resistance: level(f.nearest_resistance),
    coverage: num(input.coverage),
  };
}

export const BLOCKING_FLAGS = [
  "INSUFFICIENT_HISTORY",
  "LOW_COVERAGE",
  "CALENDAR_MISMATCH",
  "STALE_INPUT",
  "FROZEN_FEED",
] as const;
export const NOTICE_FLAGS = [
  "SAMPLE_DATA",
  "SPIKE_IN_WINDOW",
  "WIDE_SPREAD",
  "HIGH_VOLATILITY",
  "LOW_LIQUIDITY_HOLIDAY",
  "HOLIDAY_TABLE_MISMATCH",
] as const;
