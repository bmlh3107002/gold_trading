import type { components } from "./schema";

export type SystemStatus = components["schemas"]["SystemStatus"];
export type SafetyCommand = components["schemas"]["SafetyCommand"];
export type ModeCommand = components["schemas"]["ModeCommand"];
export type TradingMode = components["schemas"]["TradingMode"];
export type MarketView = components["schemas"]["MarketView"];
export type SafetyTransition = components["schemas"]["SafetyTransition"];
export type MarketSummary = components["schemas"]["MarketSummary"];
export type CandlesResponse = components["schemas"]["CandlesResponse"];
export type CandleOut = components["schemas"]["CandleOut"];
export type DataQuality = components["schemas"]["DataQuality"];
export type AnalystLatest = components["schemas"]["AnalystLatest"];
export type GatewayStatus = components["schemas"]["GatewayStatus"];
export type AnalystOutputDto = components["schemas"]["AnalystOutput"];
export type Me = components["schemas"]["Me"];
export type LogoutResult = components["schemas"]["LogoutResult"];

export type ApiErrorKind = "network" | "conflict" | "validation" | "server" | "unauthorized" | "forbidden";

/** Lỗi đã phân loại. UI chỉ hiển thị thông báo theo `kind`, không hiện chi tiết thô từ API. */
export class ApiError extends Error {
  constructor(
    public readonly kind: ApiErrorKind,
    public readonly status: number | null,
  ) {
    super(kind);
    this.name = "ApiError";
  }
}

/** Gọi khi API trả 401 (phiên hết hạn / bị thu hồi): App chuyển về màn hình đăng nhập. */
type UnauthorizedListener = () => void;
const unauthorizedListeners = new Set<UnauthorizedListener>();
export function onUnauthorized(fn: UnauthorizedListener): () => void {
  unauthorizedListeners.add(fn);
  return () => unauthorizedListeners.delete(fn);
}

function kindFor(status: number): ApiErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 403 || status === 404) return "forbidden";
  if (status === 409) return "conflict";
  if (status === 400 || status === 422) return "validation";
  return "server";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    // Cookie phiên HttpOnly do trình duyệt tự gửi (cùng origin); JS không đọc/giữ token.
    res = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError("network", null);
  }
  if (res.status === 401) unauthorizedListeners.forEach((fn) => fn());
  if (!res.ok) throw new ApiError(kindFor(res.status), res.status);
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError("server", res.status);
  }
}

/** Chuyển trình duyệt sang trang đăng nhập Keycloak (qua backend), quay lại đúng trang đang xem. */
export function loginUrl(next: string): string {
  return `/api/auth/login?next=${encodeURIComponent(next)}`;
}

export const api = {
  me: () => request<Me>("/api/auth/me"),
  logout: () => request<LogoutResult>("/api/auth/logout", { method: "POST" }),
  status: () => request<SystemStatus>("/api/status"),
  safety: (cmd: SafetyCommand) =>
    request<SystemStatus>("/api/safety", { method: "POST", body: JSON.stringify(cmd) }),
  marketSummary: () => request<MarketSummary>("/api/market/summary"),
  candles: (limit = 300) => request<CandlesResponse>(`/api/market/candles?limit=${limit}`),
  dataQuality: () => request<DataQuality>("/api/market/quality"),
  technicalLatest: () => request<AnalystLatest>("/api/analysts/technical/latest"),
  gatewayStatus: () => request<GatewayStatus>("/api/gateway/status"),
  mode: (cmd: ModeCommand) =>
    request<SystemStatus>("/api/mode", { method: "POST", body: JSON.stringify(cmd) }),
};
