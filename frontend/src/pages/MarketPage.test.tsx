import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { json, makeCandles, makeQuality, makeStatus, makeSummary, makeTechnical } from "../test/fixtures";

// jsdom không có canvas: thay biểu đồ bằng stub, chỉ kiểm tra dữ liệu được đưa vào.
const setData = vi.fn();
const createPriceLine = vi.fn(() => ({ applyOptions: vi.fn() }));
vi.mock("lightweight-charts", () => {
  const series = () => ({ setData, applyOptions: vi.fn(), createPriceLine, removePriceLine: vi.fn() });
  const scale = () => ({ subscribeVisibleLogicalRangeChange: vi.fn(), setVisibleLogicalRange: vi.fn() });
  return {
    ColorType: { Solid: "solid" },
    CrosshairMode: { Normal: 0 },
    LineStyle: { Dotted: 1, Dashed: 2 },
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
    "/api/analysts/technical/latest": makeTechnical(),
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
  createPriceLine.mockClear();
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

const srLines = () =>
  createPriceLine.mock.calls.map((c) => (c as unknown as [{ title: string; price: number }])[0]).filter((o) => o.title !== "");

describe("Thẻ Phân tích kỹ thuật", () => {
  it("kết quả hợp lệ: hiện xu hướng, ATR, hỗ trợ/kháng cự và vẽ lên biểu đồ", async () => {
    routes();
    render(<App />);
    expect(await screen.findByText("Còn hiệu lực")).toBeInTheDocument();
    expect(screen.getByText("Tăng")).toBeInTheDocument();
    expect(screen.getByText("Đỉnh và đáy cao dần")).toBeInTheDocument();
    expect(screen.getByText("Tính từ dữ liệu mẫu")).toBeInTheDocument();
    expect(screen.getByText(/chỉ phản ánh chất lượng dữ liệu/)).toBeInTheDocument();
    await vi.waitFor(() => expect(srLines().map((l) => l.price)).toEqual([2405.1, 2420.0]));
  });

  it("dữ liệu không đạt: hiện lý do, không hiện đặc trưng, không vẽ hỗ trợ/kháng cự", async () => {
    routes({
      "/api/analysts/technical/latest": makeTechnical({}, {
        quality_flags: ["LOW_COVERAGE"], source_status: "INVALID", confidence: 0, features: { input: {} },
      }),
    });
    render(<App />);
    expect(await screen.findByText("Dữ liệu không đạt")).toBeInTheDocument();
    expect(screen.getByText(/độ phủ dưới 99%/)).toBeInTheDocument();
    expect(screen.queryByText("Xu hướng")).not.toBeInTheDocument();
    expect(srLines()).toEqual([]);
  });

  it("kết quả hết hạn: cảnh báo và không vẽ hỗ trợ/kháng cự", async () => {
    routes({ "/api/analysts/technical/latest": makeTechnical({ valid_now: false }) });
    render(<App />);
    expect(await screen.findByText("Đã hết hạn")).toBeInTheDocument();
    expect(screen.getByText(/quá thời hạn/)).toBeInTheDocument();
    expect(srLines()).toEqual([]);
  });

  it("chưa có kết quả", async () => {
    routes({ "/api/analysts/technical/latest": makeTechnical({ output: null, computed_at: null, valid_now: false }) });
    render(<App />);
    expect(await screen.findByText("Chưa có kết quả phân tích")).toBeInTheDocument();
  });
});
