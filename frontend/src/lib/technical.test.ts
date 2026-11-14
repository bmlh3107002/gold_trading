import { describe, expect, it } from "vitest";
import dict from "../i18n/vi";
import { BLOCKING_FLAGS, NOTICE_FLAGS, readTechnical } from "./technical";

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

describe("TEC-07 / TEC-09", () => {
  it("đọc dự báo biến động + khung lớn, sai kiểu → null", () => {
    const f = readTechnical({
      vol_forecast: { sigma_day_pct: 0.91 },
      mtf_alignment: "ALIGNED_UP",
      mtf: { H1: { status: "OK", trend: "UP" }, H4: { status: "STALE" }, D1: { status: "OK", trend: "SIDEWAYS" } },
    });
    expect(f.volDayPct).toBe(0.91);
    expect(f.mtfAlignment).toBe("ALIGNED_UP");
    expect(f.mtf.map((m) => m.trend)).toEqual(["UP", null, null]);
    expect(readTechnical({ mtf_alignment: "MAGIC" }).mtfAlignment).toBeNull();
  });
});

describe("cờ của analyst", () => {
  it("lịch sai (CALENDAR_MISMATCH) là cờ chặn và có nhãn tiếng Việt", () => {
    expect(BLOCKING_FLAGS).toContain("CALENDAR_MISMATCH");
    for (const f of [...BLOCKING_FLAGS, ...NOTICE_FLAGS]) {
      expect(dict.technical.flag[f]).toBeTruthy();
    }
  });
  it("cờ ngày lễ (bước 2 GĐ1) được hiển thị và có nhãn, phiên HOLIDAY có nhãn", () => {
    expect(NOTICE_FLAGS).toContain("LOW_LIQUIDITY_HOLIDAY");
    expect(NOTICE_FLAGS).toContain("HOLIDAY_TABLE_MISMATCH");
    expect(dict.header.session.HOLIDAY).toBeTruthy();
  });
});
