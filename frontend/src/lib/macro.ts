/** Đọc an toàn features của analyst Macro (docs/thiet-ke/30). Thiếu/sai kiểu → null. */
export type MacroBias = "SUPPORTIVE" | "HEADWIND" | "MIXED" | "NEUTRAL" | "INSUFFICIENT_DATA";
export type Dir = "UP" | "DOWN" | "FLAT";

export interface RateView {
  value: string | null;
  date: string | null;
  change_5d_bp: number | null;
  z_5d: number | null;
  direction: Dir | null;
}

export interface MacroFeatures {
  bias: MacroBias | null;
  biasComplete: boolean;
  realYield: RateView | null;
  nominal10y: RateView | null;
  usd: { status: string | null; reason: string | null; value: number | null; change_5d_pct: number | null; z_5d: number | null; direction: Dir | null } | null;
  fedLean: string | null;
  fedSpreadBp: number | null;
  stress: string[];
  flight: boolean | null;
}

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown) => (typeof v === "string" && v.length > 0 ? v : null);
const obj = (v: unknown) => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null);
const oneOf = <T extends string>(v: unknown, allowed: readonly T[]) =>
  typeof v === "string" && (allowed as readonly string[]).includes(v) ? (v as T) : null;
const DIRS = ["UP", "DOWN", "FLAT"] as const;

function rate(v: unknown): RateView | null {
  const o = obj(v);
  if (!o) return null;
  return {
    value: str(o.value),
    date: str(o.date),
    change_5d_bp: num(o.change_5d_bp),
    z_5d: num(o.z_5d),
    direction: oneOf(o.direction, DIRS),
  };
}

export function readMacro(features: Record<string, unknown> | undefined): MacroFeatures {
  const f = features ?? {};
  const rates = obj(f.rates) ?? {};
  const u = obj(f.usd_index);
  const fed = obj(f.fed_proxy);
  return {
    bias: oneOf(f.macro_bias, ["SUPPORTIVE", "HEADWIND", "MIXED", "NEUTRAL", "INSUFFICIENT_DATA"] as const),
    biasComplete: f.bias_complete === true,
    realYield: rate(rates.real_yield_10y),
    nominal10y: rate(rates.nominal_10y),
    usd: u
      ? {
          status: str(u.status),
          reason: str(u.reason),
          value: num(u.value),
          change_5d_pct: num(u.change_5d_pct),
          z_5d: num(u.z_5d),
          direction: oneOf(u.direction, DIRS),
        }
      : null,
    fedLean: fed && fed.status === "OK" ? str(fed.lean) : null,
    fedSpreadBp: fed && fed.status === "OK" ? num(fed.spread_bp) : null,
    stress: Array.isArray(f.stress) ? f.stress.filter((x): x is string => typeof x === "string") : [],
    flight: typeof f.flight_to_safety_proxy === "boolean" ? f.flight_to_safety_proxy : null,
  };
}
