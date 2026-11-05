/** Đọc màu biểu đồ từ design tokens (tokens.css) để biểu đồ theo đúng theme đang bật. */
export interface ChartColors {
  bg: string;
  text: string;
  grid: string;
  border: string;
  up: string;
  down: string;
  ema20: string;
  ema50: string;
  rsi: string;
  guide: string;
}

export function readChartColors(): ChartColors {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
  return {
    bg: v("--bg-surface", "#151b2b"),
    text: v("--text-muted", "#8290a8"),
    grid: v("--chart-grid", "rgba(156,168,188,0.08)"),
    border: v("--chart-axis", "rgba(156,168,188,0.2)"),
    up: v("--chart-up", "#0ecb81"),
    down: v("--chart-down", "#f6465d"),
    ema20: v("--chart-ema20", "#f0b90b"),
    ema50: v("--chart-ema50", "#5d8ef7"),
    rsi: v("--chart-rsi", "#b58cff"),
    guide: v("--text-disabled", "#64738c"),
  };
}
