import type { UTCTimestamp } from "lightweight-charts";

/**
 * lightweight-charts đặt vạch ngày theo UTC. Để vạch "05/11" nằm đúng nửa đêm giờ máy người xem,
 * dời mỗi mốc thời gian đi đúng độ lệch múi giờ của chính mốc đó (tính cả DST), rồi format như UTC.
 *
 * Nếu sau khi dời mà thời gian không còn tăng dần (giờ bị lặp lúc lùi đồng hồ DST), thư viện sẽ lỗi
 * → giữ nguyên giờ UTC (vạch ngày lệch nhưng không sai dữ liệu). ``toReal`` luôn trả về mốc thật.
 */
export interface ChartTimes {
  times: UTCTimestamp[];
  shifted: boolean;
  toReal: (chartTime: number) => number;
}

export function toChartTimes(
  isoTimes: string[],
  offsetMinutes: (d: Date) => number = (d) => d.getTimezoneOffset(),
): ChartTimes {
  const real = isoTimes.map((iso) => Math.floor(new Date(iso).getTime() / 1000));
  const local = real.map((s) => s - offsetMinutes(new Date(s * 1000)) * 60);
  const increasing = local.every((s, i) => i === 0 || s > local[i - 1]);
  if (!increasing) {
    return { times: real as UTCTimestamp[], shifted: false, toReal: (t) => t };
  }
  const back = new Map(local.map((s, i) => [s, real[i]]));
  return {
    times: local as UTCTimestamp[],
    shifted: true,
    // Mốc không có trong dữ liệu (hiếm): đảo theo độ lệch tại chính mốc đó
    toReal: (t) => back.get(t) ?? t + offsetMinutes(new Date(t * 1000)) * 60,
  };
}
