import type { TFunction } from "i18next";

/** GĐ4 bước 6: dịch mã lý do / driver / cờ của MarketView sang tiếng Việt.
 * Mã có dạng `MÃ` hoặc `MÃ:đối số`. Mã lạ → trả nguyên mã (không đoán nghĩa). */

const ANALYSTS = new Set(["technical", "regime", "event", "macro", "positioning", "news"]);
const CODES = new Set([
  "REQUIRED_MISSING", "REQUIRED_EXPIRED", "REQUIRED_STALE", "REQUIRED_INVALID", "REQUIRED_SCHEMA",
  "OPTIONAL_MISSING", "OPTIONAL_EXPIRED", "OPTIONAL_STALE", "OPTIONAL_INVALID", "OPTIONAL_SCHEMA",
  "TIMESTAMP_CONFLICT", "PRICE_LEAN_LONG", "PRICE_LEAN_SHORT", "REGIME_NOT_TREND",
  "REGIME_AMBIGUOUS", "PRICE_NO_TREND", "PRICE_REGIME_DISAGREE", "MTF_CONFLICT",
  "MTF_ALIGNED_UP", "MTF_ALIGNED_DOWN", "MTF_MIXED", "MTF_NOT_EVALUATED", "OPPOSED_BY",
  "ANALYSTS_DISAGREE", "EVENT_WINDOW", "EVENT_SOON", "NEWS_SHOCK", "MACRO_STRESS",
  "CROWDING_RISK", "RISK_OFF_REGIME", "HIGH_VOLATILITY_REGIME", "FLIGHT_TO_SAFETY_PROXY",
  "QUALITY_REJECTED", "REQUIRED_OUTPUT_EXPIRED",
]);
const REGIMES = new Set(["TREND", "RANGE", "RISK_OFF", "HIGH_VOL"]);

export function analystName(t: TFunction, id: string): string {
  return ANALYSTS.has(id) ? t(`marketView.analyst.${id as "technical"}`) : id;
}

export function mvCode(t: TFunction, code: string): string {
  const i = code.indexOf(":");
  const head = i < 0 ? code : code.slice(0, i);
  const arg = i < 0 ? "" : code.slice(i + 1);
  if (!CODES.has(head)) return code;
  let name = arg;
  if (head === "REGIME_NOT_TREND" && REGIMES.has(arg)) {
    name = t(`enum.regime.${arg as "TREND"}`);
  } else if (ANALYSTS.has(arg)) {
    name = analystName(t, arg);
  }
  return t(`marketView.code.${head as "REQUIRED_MISSING"}`, { name });
}

/** KN-13 (F-03): mức hiển thị của `confidence` — chỉ để đọc, không dùng cho quyết định giao dịch.
 * `confidence` = chất lượng dữ liệu × mức đồng thuận (thiết kế 33 §5C), **không phải xác suất** → không
 * hiện dạng %. Ngưỡng chọn theo cấu trúc luật: mâu thuẫn / một nhóm ngược chiều đã kéo trần về 0,5
 * nên "Cao" phải trên mức đó. Giá trị thiếu / không hữu hạn / ngoài [0, 1] → `null` (không đoán). */
export type ConfidenceLevel = "HIGH" | "MEDIUM" | "LOW";
export const CONFIDENCE_HIGH_MIN = 0.6;
export const CONFIDENCE_MEDIUM_MIN = 0.3;

export function confidenceLevel(value: number | null | undefined): ConfidenceLevel | null {
  if (value == null || !Number.isFinite(value) || value < 0 || value > 1) return null;
  if (value >= CONFIDENCE_HIGH_MIN) return "HIGH";
  if (value >= CONFIDENCE_MEDIUM_MIN) return "MEDIUM";
  return "LOW";
}
