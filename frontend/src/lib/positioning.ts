/** Đọc an toàn features của analyst Positioning (COT — docs/thiet-ke/31). Sai kiểu → null. */
export type Crowding = "CROWDED_LONG" | "CROWDED_SHORT" | "NORMAL" | "INSUFFICIENT_DATA";

export interface PositioningFeatures {
  reportDate: string | null;
  lagDays: number | null;
  net: number | null;
  netChange: number | null;
  netPctOi: number | null;
  historyWeeks: number | null;
  minWeeks: number | null;
  z: number | null;
  percentile: number | null;
  crowding: Crowding | null;
  hypothesis: "CONTRARIAN_DOWNSIDE_RISK" | "CONTRARIAN_UPSIDE_RISK" | null;
}

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const oneOf = <T extends string>(v: unknown, allowed: readonly T[]) =>
  typeof v === "string" && (allowed as readonly string[]).includes(v) ? (v as T) : null;

export function readPositioning(features: Record<string, unknown> | undefined): PositioningFeatures {
  const f = features ?? {};
  return {
    reportDate: typeof f.report_date === "string" ? f.report_date : null,
    lagDays: num(f.data_lag_days),
    net: num(f.noncomm_net),
    netChange: num(f.noncomm_net_change),
    netPctOi: num(f.net_pct_oi),
    historyWeeks: num(f.history_weeks),
    minWeeks: num(f.min_weeks_for_extremes),
    z: num(f.z_net_pct_oi),
    percentile: num(f.percentile),
    crowding: oneOf(f.crowding, ["CROWDED_LONG", "CROWDED_SHORT", "NORMAL", "INSUFFICIENT_DATA"] as const),
    hypothesis: oneOf(f.contrarian_hypothesis, ["CONTRARIAN_DOWNSIDE_RISK", "CONTRARIAN_UPSIDE_RISK"] as const),
  };
}
