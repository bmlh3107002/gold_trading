import type { components } from "./schema";

export type SystemStatus = components["schemas"]["SystemStatus"];
export type SafetyCommand = components["schemas"]["SafetyCommand"];
export type ModeCommand = components["schemas"]["ModeCommand"];
export type TradingMode = components["schemas"]["TradingMode"];
export type MarketView = components["schemas"]["MarketView"];
export type SafetyTransition = components["schemas"]["SafetyTransition"];

export type ApiErrorKind = "network" | "conflict" | "validation" | "server";

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

function kindFor(status: number): ApiErrorKind {
  if (status === 409) return "conflict";
  if (status === 400 || status === 422) return "validation";
  return "server";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError("network", null);
  }
  if (!res.ok) throw new ApiError(kindFor(res.status), res.status);
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError("server", res.status);
  }
}

export const api = {
  status: () => request<SystemStatus>("/api/status"),
  safety: (cmd: SafetyCommand) =>
    request<SystemStatus>("/api/safety", { method: "POST", body: JSON.stringify(cmd) }),
  mode: (cmd: ModeCommand) =>
    request<SystemStatus>("/api/mode", { method: "POST", body: JSON.stringify(cmd) }),
};
