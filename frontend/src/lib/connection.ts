export type ConnectionState = "connecting" | "live" | "stale" | "disconnected";

export interface ConnectionInput {
  hasData: boolean;
  lastSuccessAt: number | null;
  failing: boolean;
  now: number;
  staleAfterMs: number;
}

/**
 * - Chưa có dữ liệu, chưa lỗi        → connecting
 * - Lần gọi gần nhất lỗi             → disconnected (dữ liệu cũ vẫn giữ, gắn nhãn "đã cũ")
 * - Có dữ liệu nhưng quá staleAfter  → stale
 * - Còn lại                          → live
 */
export function deriveConnection(i: ConnectionInput): ConnectionState {
  if (i.failing) return "disconnected";
  if (!i.hasData || i.lastSuccessAt == null) return "connecting";
  if (i.now - i.lastSuccessAt > i.staleAfterMs) return "stale";
  return "live";
}

export function isDataStale(state: ConnectionState, hasData: boolean): boolean {
  return hasData && (state === "stale" || state === "disconnected");
}
