import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, type AccountStatus } from "../api/client";
import { deriveConnection, isDataStale } from "../lib/connection";

const POLL_MS = 3000;
const STALE_AFTER_MS = 10_000;

/** Polling trạng thái của MỘT tài khoản giao dịch. Giữ dữ liệu cũ khi mất kết nối để tham khảo. */
export function useSystemStatus(accountId: string | null) {
  const [status, setStatus] = useState<AccountStatus | null>(null);
  const [lastSuccessAt, setLastSuccessAt] = useState<number | null>(null);
  const [failing, setFailing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const mounted = useRef(true);

  const accept = useCallback((s: AccountStatus) => {
    if (!mounted.current) return;
    setStatus(s);
    setLastSuccessAt(Date.now());
    setFailing(false);
  }, []);

  const refresh = useCallback(async () => {
    if (!accountId) {
      if (mounted.current) setLoading(false);
      return;
    }
    try {
      accept(await api.accountStatus(accountId));
    } catch {
      if (mounted.current) setFailing(true);
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [accept, accountId]);

  useEffect(() => {
    // Đổi tài khoản: bỏ dữ liệu của tài khoản cũ, không hiển thị lẫn.
    setStatus(null);
    setLastSuccessAt(null);
    setLoading(true);
  }, [accountId]);

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
    async (fn: () => Promise<AccountStatus>): Promise<ApiError | null> => {
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
