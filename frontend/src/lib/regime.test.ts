import { describe, expect, it } from "vitest";
import dict from "../i18n/vi";
import { readRegime } from "./regime";

describe("readRegime", () => {
  it("bỏ giá trị sai kiểu thay vì đoán", () => {
    const f = readRegime({ regime: "RISK_ON", adx14: "30", ambiguous: "yes", fusion_weights: { calibrated: "true" } });
    expect(f.regime).toBeNull();
    expect(f.adx14).toBeNull();
    expect(f.ambiguous).toBe(false);
    expect(f.weights_calibrated).toBe(false);
  });
  it("đọc đúng giá trị hợp lệ và mọi nhãn có tiếng Việt", () => {
    const f = readRegime({ regime: "TREND", direction: "UP", adx14: 31.2, bars_in_regime: 7, previous_regime: "RANGE" });
    expect(f).toMatchObject({ regime: "TREND", direction: "UP", adx14: 31.2, bars_in_regime: 7, previous_regime: "RANGE" });
    for (const k of ["TREND", "RANGE", "HIGH_VOL", "RISK_OFF"] as const) expect(dict.regime.value[k]).toBeTruthy();
  });
});
