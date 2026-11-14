import { useCallback } from "react";
import { api } from "../api/client";
import { usePolling } from "./usePolling";

// MT-05: mọi hook giá nhận tài khoản đang chọn — mỗi tài khoản xem giá broker của chính mình.
// Chưa có tài khoản (đang tải / ADMIN) → không gọi gì (không có "giá chung").

/** Tóm tắt giá cho header: 5 giây/lần. */
export function useMarketSummary(accountId: string | null) {
  return usePolling(useCallback(() => (accountId ? api.marketSummary(accountId) : Promise.resolve(null)), [accountId]), 5000, 20_000);
}

/** DSH-07: giá sống bid/ask/spread, 2 giây/lần (Gateway gửi theo chu kỳ ~5 giây). */
export function useLiveQuote(accountId: string | null) {
  return usePolling(useCallback(() => (accountId ? api.liveQuote(accountId) : Promise.resolve(null)), [accountId]), 2000, 10_000);
}

/** Nến + chỉ báo: 30 giây/lần (nến M15 chỉ đổi khi đóng nến). */
export function useCandles(accountId: string | null, limit = 300) {
  return usePolling(useCallback(() => (accountId ? api.candles(accountId, limit) : Promise.resolve(null)), [accountId, limit]), 30_000, 90_000);
}

export function useDataQuality(accountId: string | null) {
  return usePolling(useCallback(() => (accountId ? api.dataQuality(accountId) : Promise.resolve(null)), [accountId]), 60_000, 180_000);
}

/** Kết quả Technical analyst: 30 giây/lần. */
export function useTechnical(accountId: string | null) {
  return usePolling(useCallback(() => (accountId ? api.technicalLatest(accountId) : Promise.resolve(null)), [accountId]), 30_000, 90_000);
}

/** Regime của nguồn giá tài khoản: 30 giây/lần. */
export function useRegime(accountId: string | null) {
  return usePolling(useCallback(() => (accountId ? api.regimeLatest(accountId) : Promise.resolve(null)), [accountId]), 30_000, 90_000);
}

/** Macro của nguồn giá tài khoản: 60 giây/lần. */
export function useMacro(accountId: string | null) {
  return usePolling(useCallback(() => (accountId ? api.macroLatest(accountId) : Promise.resolve(null)), [accountId]), 60_000, 180_000);
}

/** Analyst Lịch sự kiện: 30 giây/lần (chung cho mọi tài khoản). */
export function useEventAnalyst() {
  return usePolling(useCallback(() => api.eventLatest(), []), 30_000, 90_000);
}

/** Trạng thái MT5 Gateway: 10 giây/lần. */
/** Trạng thái Gateway của tài khoản đang chọn (mỗi tài khoản một Gateway). */
export function useGatewayStatus(accountId: string | null) {
  return usePolling(
    useCallback(() => (accountId ? api.gatewayStatus(accountId) : Promise.resolve(null)), [accountId]),
    10_000,
    30_000,
  );
}
