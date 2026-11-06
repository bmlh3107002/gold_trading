import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "light";
const KEY = "cutlotdesk.theme";
/** Khóa cũ trước khi đổi tên AurumDesk → CutlotDesk: chỉ đọc, để không mất lựa chọn đã lưu. */
const LEGACY_KEY = "aurumdesk.theme";

function readStored(): Theme {
  try {
    return (localStorage.getItem(KEY) ?? localStorage.getItem(LEGACY_KEY)) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(readStored);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      // Bộ nhớ trình duyệt bị chặn: vẫn đổi theme trong phiên hiện tại.
    }
  }, [theme]);

  const toggle = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);
  return { theme, toggle };
}
