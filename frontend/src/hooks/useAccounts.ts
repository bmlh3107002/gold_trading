import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type AccountSummary } from "../api/client";
import { usePolling } from "./usePolling";

const KEY = "aurumdesk.account";

function readSaved(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

/** Danh sách tài khoản người dùng được cấp quyền + tài khoản đang chọn (nhớ trong trình duyệt). */
export function useAccounts() {
  const poll = usePolling(api.accounts, 15_000, 60_000);
  const [saved, setSaved] = useState<string | null>(readSaved);
  const list: AccountSummary[] = useMemo(() => poll.data ?? [], [poll.data]);

  // Tài khoản đã lưu không còn quyền → chọn tài khoản đầu tiên còn quyền.
  const selected = list.find((a) => a.account_id === saved) ?? list[0] ?? null;

  const select = useCallback((id: string) => {
    setSaved(id);
    try {
      localStorage.setItem(KEY, id);
    } catch {
      /* trình duyệt chặn lưu: vẫn chọn được trong phiên này */
    }
  }, []);

  useEffect(() => {
    if (selected && selected.account_id !== saved) setSaved(selected.account_id);
  }, [selected, saved]);

  return { list, selected, select, loading: poll.loading, refresh: poll.refresh };
}
