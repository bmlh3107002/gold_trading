import { describe, expect, it } from "vitest";
import { deriveConnection, isDataStale } from "./connection";

const base = { hasData: true, lastSuccessAt: 1000, failing: false, now: 2000, staleAfterMs: 10_000 };

describe("deriveConnection", () => {
  it("connecting khi chưa có dữ liệu", () => {
    expect(deriveConnection({ ...base, hasData: false, lastSuccessAt: null })).toBe("connecting");
  });
  it("live khi dữ liệu mới", () => {
    expect(deriveConnection(base)).toBe("live");
  });
  it("stale khi quá hạn", () => {
    expect(deriveConnection({ ...base, now: 20_000 })).toBe("stale");
  });
  it("disconnected khi lần gọi gần nhất lỗi, dữ liệu cũ được đánh dấu", () => {
    const s = deriveConnection({ ...base, failing: true });
    expect(s).toBe("disconnected");
    expect(isDataStale(s, true)).toBe(true);
    expect(isDataStale("live", true)).toBe(false);
  });
});
