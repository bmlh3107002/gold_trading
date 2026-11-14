/** Đọc an toàn features của analyst Regime (docs/thiet-ke/29). Thiếu/sai kiểu → null. */
export type RegimeLabel = "TREND" | "RANGE" | "HIGH_VOL";

export interface RegimeFeatures {
  regime: RegimeLabel | null;
  direction: "UP" | "DOWN" | null;
  ambiguous: boolean;
  adx14: number | null;
  vol_ratio: number | null;
  bars_in_regime: number | null;
  bars_in_regime_capped: boolean;
  regime_since: string | null;
  previous_regime: RegimeLabel | null;
  risk_off: string | null;
  weights_calibrated: boolean;
}

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const LABELS = ["TREND", "RANGE", "HIGH_VOL"] as const;
const oneOf = <T extends string>(v: unknown, allowed: readonly T[]) =>
  typeof v === "string" && (allowed as readonly string[]).includes(v) ? (v as T) : null;

export function readRegime(features: Record<string, unknown> | undefined): RegimeFeatures {
  const f = features ?? {};
  const w = f.fusion_weights && typeof f.fusion_weights === "object" ? (f.fusion_weights as Record<string, unknown>) : {};
  return {
    regime: oneOf(f.regime, LABELS),
    direction: oneOf(f.direction, ["UP", "DOWN"] as const),
    ambiguous: f.ambiguous === true,
    adx14: num(f.adx14),
    vol_ratio: num(f.vol_ratio),
    bars_in_regime: num(f.bars_in_regime),
    bars_in_regime_capped: f.bars_in_regime_capped === true,
    regime_since: typeof f.regime_since === "string" ? f.regime_since : null,
    previous_regime: oneOf(f.previous_regime, LABELS),
    risk_off: typeof f.risk_off === "string" ? f.risk_off : null,
    weights_calibrated: w.calibrated === true,
  };
}
