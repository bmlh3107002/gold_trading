import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { json, makeCandles, makeQuality, makeStatus, makeSummary } from "../test/fixtures";

// jsdom không có canvas: thay biểu đồ bằng stub, chỉ kiểm tra dữ liệu được đưa vào.
const setData = vi.fn();
vi.mock("lightweight-charts", () => {
  const series = () => ({ setData, applyOptions: vi.fn(), createPriceLine: () => ({ applyOptions: vi.fn() }) });
  const scale = () => ({ subscribeVisibleLogicalRangeChange: vi.fn(), setVisibleLogicalRange: vi.fn() });
  return {
    ColorType: { Solid: "solid" },
    CrosshairMode: { Normal: 0 },
    LineStyle: { Dashed: 2 },
    TickMarkType: { Year: 0, Month: 1, DayOfMonth: 2, Time: 3, TimeWithSeconds: 4 },
    createChart: () => ({
      addCandlestickSeries: series,
      addLineSeries: series,
      applyOptions: vi.fn(),
      timeScale: scale,
      priceScale: () => ({ applyOptions: vi.fn() }),
      subscribeCrosshairMove: vi.fn(),
      remove: vi.fn(),
    }),
  };
});

function routes(over: Record<string, unknown> = {}) {
  const table: Record<string, unknown> = {
    "/api/status": makeStatus(),
    "/api/market/summary": makeSummary(),
    "/api/market/candles": makeCandles(),
    "/api/market/quality": makeQuality(),
    ...over,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input).split("?")[0];
      return json(table[path] ?? {}, table[path] ? 200 : 404);
    }),
  );
}

beforeEach(() => {
  window.location.hash = "#market";
  setData.mockClear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

describe("Trang Thị trường", () => {
  it("hiển thị nhãn dữ liệu mẫu, biểu đồ và chất lượng dữ liệu", async () => {
    routes();
    render(<App />);
    expect(await screen.findByText("Đây là dữ liệu mẫu, không phải giá thật")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Thị trường" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByText("3 nến gần nhất")).toBeInTheDocument();
    // nến + EMA20 + EMA50 + RSI đều nhận dữ liệu
    expect(setData).toHaveBeenCalledTimes(4);
    expect(setData.mock.calls[0][0]).toHaveLength(3);
    expect(await screen.findByText("OHLC không hợp lệ")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "tradingview.com" })).toHaveAttribute("href", "https://www.tradingview.com/");
  });

  it("header hiện giá, thay đổi 24h, phiên và nhãn dữ liệu mẫu", async () => {
    routes();
    render(<App />);
    expect(await screen.findByText("Đang mở cửa")).toBeInTheDocument();
    expect(screen.getByText(/2\.412,50/)).toBeInTheDocument();
    expect(screen.getByText(/\+12,50/)).toBeInTheDocument();
    expect(screen.getByText(/\+0,5\s?%/)).toBeInTheDocument();
    expect(screen.getAllByText("Dữ liệu mẫu").length).toBeGreaterThan(0);
  });

  it("cảnh báo khi giá đã cũ trong giờ mở cửa", async () => {
    routes({ "/api/market/summary": makeSummary({ freshness: "STALE" }) });
    render(<App />);
    expect(await screen.findByText("Giá đã cũ", { selector: "div" })).toBeInTheDocument();
  });

  it("trạng thái chưa cấu hình nguồn và chưa có nến", async () => {
    routes({ "/api/market/candles": makeCandles(0, { source: null, is_sample: false }) });
    const { unmount } = render(<App />);
    expect(await screen.findByText("Chưa cấu hình nguồn dữ liệu")).toBeInTheDocument();
    unmount();
    routes({ "/api/market/candles": makeCandles(0) });
    render(<App />);
    expect(await screen.findByText("Chưa có nến nào")).toBeInTheDocument();
  });
});
