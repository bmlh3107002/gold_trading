import { useCallback, useEffect, useState } from "react";
import { api, ApiError, onUnauthorized, type Me } from "../api/client";

export type AuthState =
  | { status: "loading" }
  | { status: "anonymous" }
  | { status: "error" }
  | { status: "authenticated"; me: Me };

/** Trạng thái đăng nhập. Mọi 401 từ API (phiên hết hạn/bị thu hồi) đưa về "anonymous". */
export function useAuth() {
  const [state, setState] = useState<AuthState>({ status: "loading" });

  const load = useCallback(async () => {
    try {
      const me = await api.me();
      setState({ status: "authenticated", me });
    } catch (e) {
      setState(e instanceof ApiError && e.kind === "unauthorized" ? { status: "anonymous" } : { status: "error" });
    }
  }, []);

  useEffect(() => {
    void load();
    return onUnauthorized(() => setState({ status: "anonymous" }));
  }, [load]);

  const logout = useCallback(async () => {
    try {
      const { logout_url } = await api.logout();
      window.location.assign(logout_url);
    } catch {
      setState({ status: "anonymous" });
    }
  }, []);

  return { state, reload: load, logout };
}
