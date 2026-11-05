import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, type SystemStatus } from "../api/client";
import { deriveConnection, isDataStale } from "../lib/connection";

const POLL_MS = 3000;
const STALE_AFTER_MS = 10_000;

/** Polling trạng thái hệ thống. Giữ dữ liệu cũ khi mất kết nối để tham khảo. */
export function useSystemStatus() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [lastSuccessAt, setLastSuccessAt] = useState<number | null>(null);
  const [failing, setFailing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const mounted = useRef(true);

  const accept = useCallback((s: SystemStatus) => {
    if (!mounted.current) return;
    setStatus(s);
    setLastSuccessAt(Date.now());
    setFailing(false);
  }, []);

  const refresh = useCallback(async () => {
    try {
      accept(await api.status());
    } catch {
      if (mounted.current) setFailing(true);
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [accept]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const poll = setInterval(refresh, POLL_MS);
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      mounted.current = false;
      clearInterval(poll);
      clearInterval(tick);
    };
  }, [refresh]);

  /** Chạy một lệnh ghi; trả về ApiError nếu thất bại để UI hiển thị thông báo phù hợp. */
  const mutate = useCallback(
    async (fn: () => Promise<SystemStatus>): Promise<ApiError | null> => {
      try {
        accept(await fn());
        return null;
      } catch (e) {
        return e instanceof ApiError ? e : new ApiError("server", null);
      }
    },
    [accept],
  );

  const connection = deriveConnection({
    hasData: status !== null,
    lastSuccessAt,
    failing,
    now,
    staleAfterMs: STALE_AFTER_MS,
  });

  return {
    status,
    loading,
    connection,
    stale: isDataStale(connection, status !== null),
    lastSuccessAt,
    refresh,
    mutate,
  };
}
