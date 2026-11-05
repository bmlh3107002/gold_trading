import { useCallback } from "react";
import { api } from "../api/client";
import { usePolling } from "./usePolling";

/** Tóm tắt giá cho header: 5 giây/lần. */
export function useMarketSummary() {
  return usePolling(useCallback(() => api.marketSummary(), []), 5000, 20_000);
}

/** Nến + chỉ báo: 30 giây/lần (nến M15 chỉ đổi khi đóng nến). */
export function useCandles(limit = 300) {
  return usePolling(useCallback(() => api.candles(limit), [limit]), 30_000, 90_000);
}

export function useDataQuality() {
  return usePolling(useCallback(() => api.dataQuality(), []), 60_000, 180_000);
}

/** Kết quả Technical analyst: 30 giây/lần. */
export function useTechnical() {
  return usePolling(useCallback(() => api.technicalLatest(), []), 30_000, 90_000);
}
