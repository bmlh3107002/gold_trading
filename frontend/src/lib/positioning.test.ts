import { describe, expect, it } from "vitest";
import dict from "../i18n/vi";
import { readPositioning } from "./positioning";

describe("readPositioning", () => {
  it("bỏ giá trị sai kiểu", () => {
    const f = readPositioning({ crowding: "EXTREME", noncomm_net: "179548", z_net_pct_oi: Number.NaN });
    expect(f.crowding).toBeNull();
    expect(f.net).toBeNull();
    expect(f.z).toBeNull();
  });
  it("mọi mức đông đúc có nhãn tiếng Việt", () => {
    for (const k of ["CROWDED_LONG", "CROWDED_SHORT", "NORMAL", "INSUFFICIENT_DATA"] as const) expect(dict.positioning.crowding[k]).toBeTruthy();
  });
});
