import { describe, expect, it } from "vitest";
import { toChartTimes } from "./chartTime";

const VN = () => -420; // UTC+7, không có DST
// New York 2026: EDT (UTC-4) tới 01/11 06:00Z, sau đó EST (UTC-5)
const NY = (d: Date) => (d.getTime() < Date.UTC(2026, 10, 1, 6) ? 240 : 300);
const NY_SPRING = (d: Date) => (d.getTime() < Date.UTC(2026, 2, 8, 7) ? 300 : 240);

function bars(startIso: string, n: number): string[] {
  const t0 = new Date(startIso).getTime();
  return Array.from({ length: n }, (_, i) => new Date(t0 + i * 15 * 60_000).toISOString());
}

describe("toChartTimes", () => {
  it("giờ Việt Nam: nến mở lúc 00:00 VN nằm đúng vạch ngày, đổi ngược đúng mốc thật", () => {
    const iso = ["2026-11-04T16:45:00Z", "2026-11-04T17:00:00Z", "2026-11-04T17:15:00Z"];
    const r = toChartTimes(iso, VN);
    expect(r.shifted).toBe(true);
    expect(r.times[1] % 86400).toBe(0); // 00:00 ngày 05/11 trên trục
    expect(new Date(r.times[1] * 1000).toISOString()).toBe("2026-11-05T00:00:00.000Z");
    iso.forEach((s, i) => expect(r.toReal(r.times[i]) * 1000).toBe(new Date(s).getTime()));
  });

  it("lùi đồng hồ DST làm giờ bị lặp: giữ nguyên UTC, không đưa thời gian giảm dần cho thư viện", () => {
    const iso = bars("2026-11-01T04:30:00Z", 10); // đi qua 06:00Z
    const r = toChartTimes(iso, NY);
    expect(r.shifted).toBe(false);
    expect(r.times.map((t) => t * 1000)).toEqual(iso.map((s) => new Date(s).getTime()));
    expect(r.toReal(r.times[3])).toBe(r.times[3]);
  });

  it("tiến đồng hồ DST (có khoảng trống) vẫn tăng dần nên được dời", () => {
    const iso = bars("2026-03-08T06:00:00Z", 12);
    const r = toChartTimes(iso, NY_SPRING);
    expect(r.shifted).toBe(true);
    for (let i = 1; i < r.times.length; i++) expect(r.times[i]).toBeGreaterThan(r.times[i - 1]);
    iso.forEach((s, i) => expect(r.toReal(r.times[i]) * 1000).toBe(new Date(s).getTime()));
  });

  it("danh sách rỗng không lỗi", () => {
    expect(toChartTimes([], VN).times).toEqual([]);
  });
});
