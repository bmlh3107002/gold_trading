import { describe, expect, it } from "vitest";
import dict from "../i18n/vi";
import { readMacro } from "./macro";

describe("readMacro", () => {
  it("bỏ giá trị sai kiểu, không đoán", () => {
    const f = readMacro({ macro_bias: "BULLISH", rates: { real_yield_10y: { z_5d: "1" } }, usd_index: "x" });
    expect(f.bias).toBeNull();
    expect(f.realYield?.z_5d).toBeNull();
    expect(f.usd).toBeNull();
  });
  it("giữ lợi suất dạng chuỗi gốc H.15; proxy Fed chỉ khi OK", () => {
    const f = readMacro({
      macro_bias: "SUPPORTIVE",
      rates: { real_yield_10y: { value: "1.85", change_5d_bp: -12, direction: "DOWN" } },
      fed_proxy: { status: "INSUFFICIENT_DATA", lean: "LEANS_CUT" },
    });
    expect(f.realYield?.value).toBe("1.85");
    expect(f.fedLean).toBeNull();
    for (const k of ["SUPPORTIVE", "HEADWIND", "MIXED", "NEUTRAL", "INSUFFICIENT_DATA"] as const) expect(dict.macro.bias[k]).toBeTruthy();
  });
});
