import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { MarketView } from "../../api/client";
import { MarketViewCard } from "./MarketViewCard";

function makeView(over: Partial<MarketView> = {}): MarketView {
  return {
    market_view_id: "mv:fusion-rules-1.0.0:x",
    snapshot_id: "snap:x",
    symbol: "XAUUSD",
    timeframe: "M15",
    source: "MT5",
    feed_id: "f1",
    as_of: "2026-11-16T10:00:00Z",
    expires_at: "2026-11-16T10:17:00Z",
    bias: "LONG",
    p_up: null,
    p_down: null,
    confidence: 0.5,
    regime: "TREND",
    vol_forecast: 0.92,
    drivers: [],
    risk_flags: [],
    quality_flags: ["UNCALIBRATED", "UNVALIDATED_RULES"],
    model_version: "fusion-rules-1.0.0",
    quality_policy_version: "quality-policy-1",
    ...over,
  };
}

describe("MarketViewCard (GĐ4 bước 1b — DEC-25, DEC-27)", () => {
  it("chưa có MarketView → trạng thái trống", () => {
    render(<MarketViewCard view={null} />);
    expect(screen.getByText("Chưa có MarketView hợp lệ")).toBeInTheDocument();
  });

  it("xác suất để trống hiện 'Chưa có — chưa hiệu chỉnh', không hiện số %", () => {
    render(<MarketViewCard view={makeView()} />);
    expect(screen.getByTestId("mv-prob-none")).toHaveTextContent("Chưa có — chưa hiệu chỉnh");
    expect(screen.queryByText("0%")).toBeNull();
    expect(screen.queryByText("50%")).toBeNull();
  });

  it("có nhãn 'Theo luật — chưa kiểm chứng' khi mang cờ UNVALIDATED_RULES", () => {
    render(<MarketViewCard view={makeView()} />);
    expect(screen.getByText("Theo luật — chưa kiểm chứng")).toBeInTheDocument();
  });

  it("biến động: có số → kèm %, không có → 'Chưa đủ dữ liệu'", () => {
    const { unmount } = render(<MarketViewCard view={makeView()} />);
    expect(screen.getByText(/0[,.]92 %/)).toBeInTheDocument();
    unmount();
    render(<MarketViewCard view={makeView({ vol_forecast: null })} />);
    expect(screen.getByText("Chưa đủ dữ liệu")).toBeInTheDocument();
  });
});
