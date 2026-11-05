import type { SystemStatus } from "../api/client";

export function makeStatus(over: Partial<SystemStatus> = {}): SystemStatus {
  return {
    version: "0.1.0",
    mode: "PAPER",
    live_unlocked: false,
    live_checklist: [],
    safety_state: "PAUSED",
    allows_new_orders: false,
    safety_history: [],
    market_view: null,
    ...over,
  };
}
