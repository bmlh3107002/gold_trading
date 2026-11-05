import type { components } from "./schema";

export type SystemStatus = components["schemas"]["SystemStatus"];
export type SafetyCommand = components["schemas"]["SafetyCommand"];
export type ModeCommand = components["schemas"]["ModeCommand"];
export type TradingMode = components["schemas"]["TradingMode"];

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  status: () => request<SystemStatus>("/api/status"),
  safety: (cmd: SafetyCommand) =>
    request<SystemStatus>("/api/safety", { method: "POST", body: JSON.stringify(cmd) }),
  mode: (cmd: ModeCommand) =>
    request<SystemStatus>("/api/mode", { method: "POST", body: JSON.stringify(cmd) }),
};
