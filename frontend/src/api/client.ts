import type { components } from "./schema";

export type SystemStatus = components["schemas"]["SystemStatus"];
export type AccountStatus = components["schemas"]["AccountStatus"];
export type AccountSummary = components["schemas"]["AccountSummary"];
export type Perm = components["schemas"]["Perm"];
export type LiveRequest = components["schemas"]["LiveRequestOut"];
export type KillSwitchResult = components["schemas"]["KillSwitchResult"];
export type OpsHealth = components["schemas"]["OpsHealth"];
export type MemberOut = components["schemas"]["MemberOut"];
export type GatewayTokenInfo = components["schemas"]["GatewayTokenInfo"];
export type GatewayTokenIssued = components["schemas"]["GatewayTokenIssued"];
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

/** Request không có body trả về (204). */
async function requestEmpty(path: string, init?: RequestInit): Promise<void> {
  let res: Response;
  try {
    res = await fetch(path, { credentials: "same-origin", headers: { "Content-Type": "application/json" }, ...init });
  } catch {
    throw new ApiError("network", null);
  }
  if (res.status === 401) unauthorizedListeners.forEach((fn) => fn());
  if (!res.ok) throw new ApiError(kindFor(res.status), res.status);
}

/** Chuyển trình duyệt sang trang đăng nhập Keycloak (qua backend), quay lại đúng trang đang xem. */
export function loginUrl(next: string): string {
  return `/api/auth/login?next=${encodeURIComponent(next)}`;
}

const acc = (id: string) => `/api/accounts/${encodeURIComponent(id)}`;
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
  approveLive: (id: string, requestId: string) =>
    request<AccountStatus>(`${acc(id)}/mode/live-requests/${encodeURIComponent(requestId)}/approve`, {
      method: "POST",
    }),
  killSwitch: (reason_code: string) => request<KillSwitchResult>("/api/admin/kill-switch", post({ reason_code })),
  marketSummary: () => request<MarketSummary>("/api/market/summary"),
  candles: (limit = 300) => request<CandlesResponse>(`/api/market/candles?limit=${limit}`),
  dataQuality: () => request<DataQuality>("/api/market/quality"),
  technicalLatest: () => request<AnalystLatest>("/api/analysts/technical/latest"),
  gatewayStatus: (id: string) => request<GatewayStatus>(`${acc(id)}/gateway/status`),
  members: (id: string) => request<MemberOut[]>(`${acc(id)}/members`),
  addMember: (id: string, user: string, role: MemberOut["role"]) =>
    request<MemberOut>(`${acc(id)}/members`, post({ user, role })),
  setMemberRole: (id: string, sub: string, role: MemberOut["role"]) =>
    request<MemberOut>(`${acc(id)}/members/${encodeURIComponent(sub)}`, {
      method: "PUT",
      body: JSON.stringify({ role }),
    }),
  removeMember: (id: string, sub: string) =>
    requestEmpty(`${acc(id)}/members/${encodeURIComponent(sub)}`, { method: "DELETE" }),
  gatewayTokenInfo: (id: string) => request<GatewayTokenInfo>(`${acc(id)}/gateway/token`),
  rotateGatewayToken: (id: string) => request<GatewayTokenIssued>(`${acc(id)}/gateway/token`, { method: "POST" }),
};
