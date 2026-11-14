import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { json, makeAccount, makeCandles, makeLiveQuote, makeMe, makeQuality, makeStatus, makeSummary, makeSystem, makeTechnical } from "../test/fixtures";

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
    "/api/auth/me": makeMe(),
    "/api/status": makeSystem(),
    "/api/accounts": [makeAccount()],
    "/api/accounts/default/status": makeStatus(),
    "/api/accounts/default/mode/live-requests": [],
    "/api/accounts/default/market/summary": makeSummary(),
    "/api/accounts/default/market/candles": makeCandles(),
    "/api/accounts/default/market/quality": makeQuality(),
    "/api/accounts/default/analysts/technical/latest": makeTechnical(),
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
    routes({ "/api/accounts/default/market/summary": makeSummary({ freshness: "STALE" }) });
    render(<App />);
    expect(await screen.findByText("Giá đã cũ", { selector: "div" })).toBeInTheDocument();
  });

  it("trạng thái chưa cấu hình nguồn và chưa có nến", async () => {
    routes({ "/api/accounts/default/market/candles": makeCandles(0, { source: null, is_sample: false }) });
    const { unmount } = render(<App />);
    expect(await screen.findByText("Chưa cấu hình nguồn dữ liệu")).toBeInTheDocument();
    unmount();
    routes({ "/api/accounts/default/market/candles": makeCandles(0) });
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
      "/api/accounts/default/analysts/technical/latest": makeTechnical({}, {
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
    routes({ "/api/accounts/default/analysts/technical/latest": makeTechnical({ valid_now: false }) });
    render(<App />);
    expect(await screen.findByText("Đã hết hạn")).toBeInTheDocument();
    expect(screen.getByText(/quá thời hạn/)).toBeInTheDocument();
    expect(srLines()).toEqual([]);
  });

  it("chưa có kết quả", async () => {
    routes({ "/api/accounts/default/analysts/technical/latest": makeTechnical({ output: null, computed_at: null, valid_now: false }) });
    render(<App />);
    expect(await screen.findByText("Chưa có kết quả phân tích")).toBeInTheDocument();
  });
});

describe("Trạng thái MT5 Gateway", () => {
  it("hiện ở sidebar khi nguồn dữ liệu là MT5", async () => {
    routes({
      "/api/status": makeSystem({ data_source: "MT5", data_is_sample: false }),
      "/api/accounts/default/gateway/status": {
        state: "CONNECTED", last_seen_at: "2026-01-06T14:45:00Z", age_seconds: 3,
        heartbeat: { account_type: "DEMO" },
      },
    });
    render(<App />);
    expect(await screen.findByText(/MT5: đã kết nối · demo/)).toBeInTheDocument();
  });

  it("MT-05: chỉ gọi giá của tài khoản đang chọn, không gọi endpoint giá chung", async () => {
    routes();
    render(<App />);
    const urls = () =>
      (fetch as unknown as { mock: { calls: [RequestInfo | URL][] } }).mock.calls.map(([u]) => String(u));
    await waitFor(() =>
      expect(urls().some((u) => u.startsWith("/api/accounts/default/market/candles"))).toBe(true),
    );
    expect(urls().some((u) => u.startsWith("/api/accounts/default/analysts/technical/latest"))).toBe(true);
    // Lịch sự kiện là dữ liệu chung (không phải giá) — endpoint chung duy nhất được phép.
    const shared = urls().filter((u) => u.startsWith("/api/market/") || u.startsWith("/api/analysts/"));
    const allowed = ["/api/analysts/event/latest", "/api/analysts/positioning/latest"];
    expect(shared.every((u) => allowed.some((a) => u.startsWith(a)))).toBe(true);
  });

  it("GĐ3: thẻ Lịch sự kiện — đang trong cửa sổ, số actual '0' khác chưa công bố", async () => {
    routes({
      "/api/analysts/event/latest": {
        computed_at: "2026-12-10T13:30:05Z",
        valid_now: true,
        confidence_meaning: "DATA_QUALITY_ONLY",
        observer_only: true,
        output: {
          output_id: "event:event-1.0.0:GLOBAL::*:*:2026-12-10T13:30:00+00:00:abc",
          analyst_id: "event",
          as_of: "2026-12-10T13:30:00Z",
          expires_at: "2026-12-10T13:35:00Z",
          confidence: 1,
          features: {
            event_risk: "HIGH",
            window: { start: "2026-12-10T13:15:00Z", end: "2026-12-10T13:45:00Z", reasons: ["CALENDAR_HIGH"] },
            next_event: null,
            soon: false,
            upcoming: [],
            recent_releases: [
              { event: "BLS_CPI", release_at: "2026-12-10T13:30:00Z", importance: "HIGH", actual_status: "RECEIVED", actuals: [["CUUR0000SA0", "0"]] },
              { event: "DOL_JOBLESS_CLAIMS", release_at: "2026-12-10T13:30:00Z", importance: "MEDIUM", actual_status: "AWAITING", actuals: [] },
            ],
            removed: [],
          },
          drivers: ["EVENT_RISK_HIGH", "IN_EVENT_WINDOW"],
          risk_flags: ["EVENT_WINDOW"],
          source_status: "HEALTHY",
          quality_flags: [],
          version: "event-1.0.0",
          correlation_id: "c",
        },
      },
    });
    render(<App />);
    expect(await screen.findByText("Lịch sự kiện kinh tế")).toBeInTheDocument();
    expect((await screen.findAllByText("Cao")).length).toBeGreaterThan(0);
    expect(screen.getByText(/Đang trong cửa sổ công bố tới/)).toBeInTheDocument();
    expect(screen.getByText(/CUUR0000SA0=0/)).toBeInTheDocument();
    expect(screen.getByText(/Đang chờ số/)).toBeInTheDocument();
    expect(screen.getByText(/không đánh giá được mức bất ngờ/)).toBeInTheDocument();
  });

  it("GĐ3: thẻ Trạng thái thị trường — xu hướng, sát ngưỡng, RISK_OFF chưa đánh giá", async () => {
    routes({
      "/api/accounts/default/analysts/regime/latest": makeTechnical(
        {},
        {
          analyst_id: "regime",
          version: "regime-1.0.0",
          confidence: 0.5,
          features: {
            regime: "TREND",
            direction: "DOWN",
            ambiguous: true,
            adx14: 23.4,
            vol_ratio: 1.12,
            bars_in_regime: 7,
            bars_in_regime_capped: false,
            regime_since: "2026-01-06T13:00:00Z",
            previous_regime: "RANGE",
            risk_off: "NOT_EVALUATED",
            fusion_weights: { calibrated: false },
          },
        },
      ),
    });
    render(<App />);
    expect(await screen.findByText(/Có xu hướng · đi xuống/)).toBeInTheDocument();
    expect(screen.getByText("Sát ngưỡng — chưa rõ ràng")).toBeInTheDocument();
    expect(screen.getByText(/7 nến \(từ .*trước đó: Đi ngang\)/)).toBeInTheDocument();
    expect(screen.getByText(/RISK_OFF\) chưa đánh giá/)).toBeInTheDocument();
  });

  it("GĐ3: Regime RISK_OFF từ proxy trú ẩn — vẫn hiện nhãn theo giá", async () => {
    routes({
      "/api/accounts/default/analysts/regime/latest": makeTechnical(
        {},
        {
          analyst_id: "regime",
          version: "regime-1.1.0",
          features: { regime: "RISK_OFF", price_regime: "RANGE", risk_off: "YES", bars_in_regime: 3, fusion_weights: { calibrated: false } },
        },
      ),
    });
    render(<App />);
    expect(await screen.findByText("Né rủi ro (proxy)")).toBeInTheDocument();
    expect(screen.getByText(/Theo giá riêng: Đi ngang/)).toBeInTheDocument();
  });

  it("GĐ3: thẻ Bối cảnh vĩ mô — bias một phần, USD chưa có, lợi suất chưa đủ lịch sử", async () => {
    routes({
      "/api/accounts/default/analysts/macro/latest": makeTechnical(
        {},
        {
          analyst_id: "macro",
          version: "macro-1.0.0",
          confidence: 0.5,
          features: {
            macro_bias: "HEADWIND",
            bias_complete: false,
            rates: {
              real_yield_10y: { value: "1.92", change_5d_bp: 9, z_5d: 1.4, direction: "UP" },
              nominal_10y: { value: "4.15", change_5d_bp: 3, z_5d: null, direction: null },
            },
            usd_index: { status: "INSUFFICIENT_DATA", reason: "PAIR_MISSING" },
            fed_proxy: { status: "OK", lean: "LEANS_CUT", spread_bp: -12 },
            stress: [],
            flight_to_safety_proxy: null,
          },
        },
      ),
    });
    render(<App />);
    expect(await screen.findByText("Gây cản")).toBeInTheDocument();
    expect(screen.getByText("chỉ dựa trên một phần yếu tố")).toBeInTheDocument();
    expect(screen.getByText(/1.92%/)).toBeInTheDocument();
    expect(screen.getByText(/chưa đủ lịch sử để đo độ bất thường/)).toBeInTheDocument();
    expect(screen.getByText(/Chưa có \(PAIR_MISSING\)/)).toBeInTheDocument();
    expect(screen.getByText(/Nghiêng về cắt lãi/)).toBeInTheDocument();
  });

  it("GĐ3: thẻ COT — luôn báo trễ, chưa đủ lịch sử thì không nói đông đúc", async () => {
    routes({
      "/api/analysts/positioning/latest": {
        computed_at: "2026-11-13T12:00:05Z",
        valid_now: true,
        confidence_meaning: "DATA_QUALITY_ONLY",
        observer_only: true,
        output: {
          output_id: "positioning:x",
          analyst_id: "positioning",
          as_of: "2026-11-13T12:00:00Z",
          expires_at: "2026-11-13T18:00:00Z",
          confidence: 0.5,
          features: {
            report_date: "2026-11-03",
            data_lag_days: 9.3,
            noncomm_net: 179548,
            noncomm_net_change: -2000,
            net_pct_oi: 44.98,
            history_weeks: 1,
            min_weeks_for_extremes: 52,
            crowding: "INSUFFICIENT_DATA",
          },
          drivers: ["POSITIONING_INSUFFICIENT_DATA"],
          risk_flags: [],
          source_status: "HEALTHY",
          quality_flags: ["COT_LAGGED", "COT_HISTORY_SHORT"],
          version: "positioning-1.0.0",
          correlation_id: "c",
        },
      },
    });
    render(<App />);
    expect(await screen.findByText(/Báo cáo chốt ngày 2026-11-03 — trễ 9 ngày/)).toBeInTheDocument();
    expect(screen.getByText("Chưa đủ lịch sử")).toBeInTheDocument();
    expect(screen.getByText(/1 \/ 52 tuần/)).toBeInTheDocument();
    expect(screen.queryByText(/Giả thuyết/)).not.toBeInTheDocument();
  });

  it("GĐ3: thẻ Lịch sự kiện — lịch thiếu thì báo không đạt, không nói 'không có sự kiện'", async () => {
    routes({
      "/api/analysts/event/latest": {
        computed_at: "2026-12-10T13:30:05Z",
        valid_now: true,
        confidence_meaning: "DATA_QUALITY_ONLY",
        observer_only: true,
        output: {
          output_id: "event:x",
          analyst_id: "event",
          as_of: "2026-12-10T13:30:00Z",
          expires_at: "2026-12-10T13:32:00Z",
          confidence: 0,
          features: { input: {} },
          drivers: ["MISSING_INPUT:bls_schedule"],
          risk_flags: [],
          source_status: "MISSING",
          quality_flags: ["MISSING_INPUT:bls_schedule"],
          version: "event-1.0.0",
          correlation_id: "c",
        },
      },
    });
    render(<App />);
    expect(await screen.findByText("Không đánh giá được lịch vì dữ liệu không đạt")).toBeInTheDocument();
    expect(screen.getByText("Thiếu lịch của nguồn bls_schedule")).toBeInTheDocument();
    expect(screen.queryByText(/Không có sự kiện nào trong 24 giờ tới/)).not.toBeInTheDocument();
  });

  it("DSH-07: thẻ giá sống hiện bid/ask/spread đúng chữ số của broker", async () => {
    routes({ "/api/accounts/default/market/quote": makeLiveQuote({ bid: 2412.355, ask: 2412.605, spread_max_points: 40 }) });
    render(<App />);
    expect(await screen.findByText("Đang cập nhật")).toBeInTheDocument();
    expect(screen.getByText("2.412,355")).toBeInTheDocument(); // không làm tròn về 2 số lẻ
    expect(screen.getByText("2.412,605")).toBeInTheDocument();
    expect(screen.getByText("25 point (0,25)")).toBeInTheDocument();
    expect(screen.getByText("lớn nhất trong giây: 40 point")).toBeInTheDocument();
  });

  it("DSH-07: giá cũ khi thị trường mở → báo đỏ, không im lặng", async () => {
    routes({ "/api/accounts/default/market/quote": makeLiveQuote({ state: "STALE", age_seconds: 95 }) });
    render(<App />);
    expect(await screen.findByText("Giá sống đã cũ: không dùng để ra quyết định")).toBeInTheDocument();
    expect(screen.getByText(/đã 95 giây/)).toBeInTheDocument();
  });

  it("DSH-07: đóng cửa, cờ spread giãn, chưa có nguồn", async () => {
    routes({ "/api/accounts/default/market/quote": makeLiveQuote({ state: "CLOSED", market_open: false, flags: ["WIDE_SPREAD"] }) });
    const { unmount } = render(<App />);
    expect(await screen.findByText("Thị trường đóng cửa")).toBeInTheDocument();
    expect(screen.getByText("Đây là giá cuối cùng trước khi đóng cửa.")).toBeInTheDocument();
    expect(screen.getByText("Spread giãn bất thường")).toBeInTheDocument();
    unmount();
    routes({ "/api/accounts/default/market/quote": makeLiveQuote({ state: "NO_FEED", t: null, bid: null, ask: null, spread_points: null }) });
    render(<App />);
    expect((await screen.findAllByText("Chưa có nguồn giá")).length).toBeGreaterThan(0);
    expect(screen.queryByText("Bid (giá bán ra)")).not.toBeInTheDocument();
  });
});
