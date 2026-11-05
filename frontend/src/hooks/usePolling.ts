import { useCallback, useEffect, useRef, useState } from "react";
import { deriveConnection, isDataStale, type ConnectionState } from "../lib/connection";

/** Polling chung: giữ dữ liệu cũ khi lỗi, suy ra trạng thái kết nối. */
export function usePolling<T>(fetcher: () => Promise<T>, intervalMs: number, staleAfterMs: number) {
  const [data, setData] = useState<T | null>(null);
  const [lastSuccessAt, setLastSuccessAt] = useState<number | null>(null);
  const [failing, setFailing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const fetchRef = useRef(fetcher);
  fetchRef.current = fetcher;
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const value = await fetchRef.current();
      if (!mounted.current) return;
      setData(value);
      setLastSuccessAt(Date.now());
      setFailing(false);
    } catch {
      if (mounted.current) setFailing(true);
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const poll = setInterval(refresh, intervalMs);
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      mounted.current = false;
      clearInterval(poll);
      clearInterval(tick);
    };
  }, [refresh, intervalMs]);

  const connection: ConnectionState = deriveConnection({
    hasData: data !== null,
    lastSuccessAt,
    failing,
    now,
    staleAfterMs,
  });
  return { data, loading, connection, stale: isDataStale(connection, data !== null), lastSuccessAt, refresh };
}
