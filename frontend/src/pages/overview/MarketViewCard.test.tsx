import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { MarketView, MarketViewLatest } from "../../api/client";
import { MarketViewCard } from "./MarketViewCard";

const NOW = Date.parse("2026-11-16T10:05:00Z");

function makeView(over: Partial<MarketView> = {}): MarketView {
  return {
    market_view_id: "mv:fusion-rules-1.0.0:x",
    snapshot_id: "snap:x",
    symbol: "XAUUSD",
    timeframe: "M15",
    source: "MT5",
    feed_id: "f1",
    as_of: "2026-11-16T10:00:00Z",
    expires_at: "2026-11-16T10:15:00Z",
    bias: "LONG",
    p_up: null,
    p_down: null,
    confidence: 0.45,
    regime: "TREND",
    vol_forecast: 0.92,
    drivers: ["PRICE_LEAN_LONG", "MTF_ALIGNED_UP", "OPPOSED_BY:macro"],
    risk_flags: ["EVENT_WINDOW"],
    quality_flags: ["UNCALIBRATED", "UNVALIDATED_RULES", "OPTIONAL_MISSING:news"],
    model_version: "fusion-rules-1.0.0",
    quality_policy_version: "quality-policy-1",
    ...over,
  };
}

function latest(over: Partial<MarketViewLatest> = {}): MarketViewLatest {
  return {
    market_view: makeView(),
    state: "VALID",
    is_sample: false,
    rules_validated: false,
    gate: { verdict: "DEGRADED", reasons: ["OPTIONAL_MISSING:news"], evaluated_at: "2026-11-16T10:00:00Z", policy_version: "quality-policy-1" },
    ...over,
  } as MarketViewLatest;
}

describe("MarketViewCard (GĐ4 bước 6 — MKV-03; DEC-25, DEC-27)", () => {
  it("chưa tải được gì → trạng thái 'Chưa có nhận định', không có hướng", () => {
    render(<MarketViewCard latest={null} now={NOW} />);
    expect(screen.getByTestId("mv-empty")).toHaveTextContent("Chưa có nhận định");
    expect(screen.queryByText("LONG")).toBeNull();
  });

  it("có nhận định: nhãn chưa kiểm chứng, xác suất để trống, lý do + cờ tiếng Việt", () => {
    render(<MarketViewCard latest={latest()} now={NOW} />);
    expect(screen.getByText("LONG")).toBeInTheDocument();
    expect(screen.getByText("Theo luật — chưa kiểm chứng")).toBeInTheDocument();
    expect(screen.getByTestId("mv-prob-none")).toHaveTextContent("Chưa có — chưa hiệu chỉnh");
    expect(screen.getByTestId("mv-unvalidated-note")).toHaveTextContent("không dùng cho Shadow / Live");
    const d = screen.getByTestId("mv-drivers");
    expect(d).toHaveTextContent("Giá đang xu hướng lên, Trạng thái thị trường xác nhận");
    expect(d).toHaveTextContent("Vĩ mô ngược chiều (độ tin cậy giảm một nửa)");
    expect(screen.getByTestId("mv-risk")).toHaveTextContent("Đang trong cửa sổ công bố tin");
    expect(screen.getByTestId("mv-notes")).toHaveTextContent("Không có Tin tức (độ tin cậy giảm)");
    expect(screen.getByText(/0[,.]92 %/)).toBeInTheDocument();
  });

  it("dữ liệu mẫu có nhãn", () => {
    const v = makeView({ source: "SAMPLE", quality_flags: ["UNCALIBRATED", "UNVALIDATED_RULES", "SAMPLE_DATA"] });
    render(<MarketViewCard latest={latest({ market_view: v, is_sample: true })} now={NOW} />);
    expect(screen.getByText("Dữ liệu mẫu")).toBeInTheDocument();
  });

  it("quá hạn theo đồng hồ trình duyệt → coi như hết hạn dù máy chủ báo VALID", () => {
    render(<MarketViewCard latest={latest()} now={Date.parse("2026-11-16T10:15:00Z")} />);
    expect(screen.getByTestId("mv-empty")).toHaveTextContent("Nhận định đã hết hạn");
    expect(screen.queryByText("LONG")).toBeNull();
  });

  it("mất kết nối → không hiện nhận định cũ", () => {
    render(<MarketViewCard latest={latest()} stale now={NOW} />);
    expect(screen.getByTestId("mv-empty")).toBeInTheDocument();
    expect(screen.queryByText("LONG")).toBeNull();
  });

  it("bị bộ kiểm chất lượng loại → hiện lý do tiếng Việt", () => {
    const l = latest({
      market_view: null,
      state: "INVALIDATED",
      invalidation_reason: "QUALITY_REJECTED",
      gate: { verdict: "REJECTED", reasons: ["REQUIRED_MISSING:event", "TIMESTAMP_CONFLICT:technical,regime"], evaluated_at: "2026-11-16T10:00:00Z", policy_version: "quality-policy-1" },
    });
    render(<MarketViewCard latest={l} now={NOW} />);
    expect(screen.getByTestId("mv-empty")).toHaveTextContent("Nhận định đã bị vô hiệu");
    expect(screen.getByTestId("mv-invalidated")).toHaveTextContent("bộ kiểm chất lượng từ chối dữ liệu mới");
    const g = screen.getByTestId("mv-gate");
    expect(g).toHaveTextContent("Thiếu Lịch sự kiện");
    expect(g).toHaveTextContent("chưa tính trên cùng một nến");
  });

  it("mã lạ → hiện nguyên mã, không đoán nghĩa", () => {
    render(<MarketViewCard latest={latest({ market_view: makeView({ drivers: ["SOMETHING_NEW:x"] }) })} now={NOW} />);
    expect(screen.getByTestId("mv-drivers")).toHaveTextContent("SOMETHING_NEW:x");
  });
});
