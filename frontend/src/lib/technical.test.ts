import { describe, expect, it } from "vitest";
import { readTechnical } from "./technical";

describe("readTechnical", () => {
  it("bỏ qua giá trị sai kiểu thay vì đoán", () => {
    const f = readTechnical({ atr14: "4.2", trend: "SIDEWAYS", rsi14: Number.NaN, nearest_support: { price: 1 } });
    expect(f.atr14).toBeNull();
    expect(f.trend).toBeNull();
    expect(f.rsi14).toBeNull();
    expect(f.nearest_support).toBeNull();
  });
  it("đọc đúng giá trị hợp lệ", () => {
    const f = readTechnical({ atr14: 4.2, trend: "DOWN", input: { coverage: 0.995 } });
    expect(f).toMatchObject({ atr14: 4.2, trend: "DOWN", coverage: 0.995 });
  });
});
