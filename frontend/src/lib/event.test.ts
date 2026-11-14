import { describe, expect, it } from "vitest";
import dict from "../i18n/vi";
import { blockingKind, readEvent } from "./event";

describe("readEvent", () => {
  it("bỏ giá trị sai kiểu thay vì đoán", () => {
    const f = readEvent({ event_risk: "EXTREME", window: { end: "x" }, next_event: { event: "BLS_CPI" }, upcoming: "x" });
    expect(f.event_risk).toBeNull();
    expect(f.window).toBeNull();
    expect(f.next_event).toBeNull();
    expect(f.upcoming).toEqual([]);
  });
  it("giữ số actual dạng chuỗi gốc — '0' khác chưa công bố", () => {
    const f = readEvent({
      recent_releases: [
        { event: "BLS_CPI", release_at: "2026-12-10T13:30:00+00:00", actual_status: "RECEIVED", actuals: [["CPI", "0"]] },
        { event: "BLS_PPI", release_at: "2026-12-10T13:30:00+00:00", actual_status: "AWAITING", actuals: [] },
      ],
    });
    expect(f.recent_releases[0].actuals).toEqual([["CPI", "0"]]);
    expect(f.recent_releases[1].actuals).toEqual([]);
  });
  it("mọi mã chặn của khung và tên sự kiện chính có nhãn tiếng Việt", () => {
    for (const k of ["MISSING_INPUT", "STALE_INPUT", "INSUFFICIENT_HISTORY"]) {
      expect(dict.eventAnalyst.blocked[k as keyof typeof dict.eventAnalyst.blocked]).toBeTruthy();
    }
    expect(blockingKind("MISSING_INPUT:bls_schedule")).toBe("MISSING_INPUT");
    for (const e of ["BLS_CPI", "BLS_EMPSIT", "FOMC_STATEMENT", "BEA_PIO", "DOL_JOBLESS_CLAIMS"]) {
      expect(dict.eventAnalyst.eventName[e as keyof typeof dict.eventAnalyst.eventName]).toBeTruthy();
    }
  });
});
