import type { components } from "./schema";

export type SystemStatus = components["schemas"]["SystemStatus"];
export type AccountStatus = components["schemas"]["AccountStatus"];
export type AccountSummary = components["schemas"]["AccountSummary"];
export type LiveRequest = components["schemas"]["LiveRequestOut"];
export type OpsHealth = components["schemas"]["OpsHealth"];
export type GatewayTokenInfo = components["schemas"]["GatewayTokenInfo"];
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
export type UserCreate = components["schemas"]["UserCreate"];
export type UserCreated = components["schemas"]["UserCreated"];
export type UserAdmin = components["schemas"]["UserAdminOut"];
export type UserUpdate = components["schemas"]["UserUpdate"];
export type DeleteResult = components["schemas"]["DeleteResult"];
export type GatewayCredential = components["schemas"]["GatewayCredential"];
export type LockResult = components["schemas"]["LockResult"];
export type PasswordReset = components["schemas"]["PasswordReset"];

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
  if (res.status === 204) return undefined as T;
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

const acc = (id: string) => `/api/accounts/${encodeURIComponent(id)}`;
const usr = (sub: string) => `/api/admin/users/${encodeURIComponent(sub)}`;
const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const api = {
  me: () => request<Me>("/api/auth/me"),
  logout: () => request<LogoutResult>("/api/auth/logout", { method: "POST" }),
  system: () => request<SystemStatus>("/api/status"),
  opsHealth: () => request<OpsHealth>("/api/system/health"),
  accounts: () => request<AccountSummary[]>("/api/accounts"),
  accountStatus: (id: string) => request<AccountStatus>(`${acc(id)}/status`),
  safety: (id: string, cmd: SafetyCommand) => request<AccountStatus>(`${acc(id)}/safety`, post(cmd)),
  mode: (id: string, cmd: ModeCommand) => request<AccountStatus>(`${acc(id)}/mode`, post(cmd)),
  liveRequests: (id: string) => request<LiveRequest[]>(`${acc(id)}/mode/live-requests`),
  requestLive: (id: string, checklist: Record<string, boolean>) =>
    request<LiveRequest>(`${acc(id)}/mode/live-requests`, post({ checklist })),
  marketSummary: () => request<MarketSummary>("/api/market/summary"),
  candles: (limit = 300) => request<CandlesResponse>(`/api/market/candles?limit=${limit}`),
  dataQuality: () => request<DataQuality>("/api/market/quality"),
  technicalLatest: () => request<AnalystLatest>("/api/analysts/technical/latest"),
  gatewayStatus: (id: string) => request<GatewayStatus>(`${acc(id)}/gateway/status`),
  gatewayTokenInfo: (id: string) => request<GatewayTokenInfo>(`${acc(id)}/gateway/token`),
  /** DEC-17: USER xin cấp (lại) token Gateway; ADMIN cấp hoặc từ chối. */
  requestGatewayToken: (id: string) =>
    request<GatewayTokenInfo>(`${acc(id)}/gateway/token-request`, { method: "POST" }),
  // --- Quản trị (DEC-16, DEC-17): chỉ ADMIN; backend kiểm lại ---
  users: () => request<UserAdmin[]>("/api/admin/users"),
  createUser: (body: UserCreate) => request<UserCreated>("/api/admin/users", post(body)),
  lockUser: (sub: string) => request<LockResult>(`${usr(sub)}/lock`, { method: "POST" }),
  unlockUser: (sub: string) => request<LockResult>(`${usr(sub)}/unlock`, { method: "POST" }),
  resetPassword: (sub: string) => request<PasswordReset>(`${usr(sub)}/reset-password`, { method: "POST" }),
  updateUser: (sub: string, body: UserUpdate) =>
    request<UserAdmin>(usr(sub), { method: "PUT", body: JSON.stringify(body) }),
  deleteUser: (sub: string) => request<DeleteResult>(usr(sub), { method: "DELETE" }),
  issueToken: (sub: string) => request<GatewayCredential>(`${usr(sub)}/gateway-token`, { method: "POST" }),
  rejectTokenRequest: (sub: string) =>
    request<void>(`${usr(sub)}/gateway-token/reject`, { method: "POST" }),
  adminLiveRequests: () => request<LiveRequest[]>("/api/admin/live-requests"),
  approveLive: (requestId: string) =>
    request<LiveRequest>(`/api/admin/live-requests/${encodeURIComponent(requestId)}/approve`, { method: "POST" }),
  rejectLive: (requestId: string) =>
    request<LiveRequest>(`/api/admin/live-requests/${encodeURIComponent(requestId)}/reject`, { method: "POST" }),
};
