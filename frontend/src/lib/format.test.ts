import { describe, expect, it } from "vitest";
import {
  EMPTY,
  formatDayMonth,
  formatMoney,
  formatNumber,
  formatPercent,
  formatSignedMoney,
  formatSignedPercent,
  pnlTone,
} from "./format";

describe("format vi-VN", () => {
  it("dùng dấu phẩy thập phân và dấu chấm hàng nghìn", () => {
    expect(formatNumber(2412.5)).toBe("2.412,50");
  });
  it("định dạng phần trăm từ tỷ lệ", () => {
    expect(formatPercent(0.625)).toContain("62,5");
  });
  it("tiền có dấu khi là PnL", () => {
    expect(formatSignedMoney(12.3)).toBe("+12,30 USD");
    expect(formatSignedMoney(-4)).toBe("-4,00 USD");
    expect(formatMoney(0, "USDT")).toBe("0,00 USDT");
  });
  it("ngày/tháng dạng dd/MM", () => {
    expect(formatDayMonth(new Date(2026, 10, 4, 12))).toBe("04/11");
  });
  it("phần trăm có dấu", () => {
    expect(formatSignedPercent(0.008)).toMatch(/^\+0,8\s?%$/);
    expect(formatSignedPercent(-0.008)).toMatch(/^-0,8\s?%$/);
  });
  it("giá trị thiếu hiển thị gạch ngang", () => {
    expect(formatNumber(null)).toBe(EMPTY);
    expect(formatPercent(Number.NaN)).toBe(EMPTY);
  });
  it("PnL tone", () => {
    expect(pnlTone(1)).toBe("profit");
    expect(pnlTone(-1)).toBe("loss");
    expect(pnlTone(0)).toBe("neutral");
  });
});
