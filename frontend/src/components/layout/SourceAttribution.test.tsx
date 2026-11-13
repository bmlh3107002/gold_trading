import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BEA_ATTRIBUTION, CENSUS_ATTRIBUTION, SourceAttribution } from "./SourceAttribution";

describe("SourceAttribution", () => {
  it("hiện nguyên văn câu ghi nguồn BEA, Census và ghi nguồn Fed", () => {
    render(<SourceAttribution />);
    // Nguyên văn theo thỏa thuận API của BEA (đọc 2026-11-13) — không được dịch hay sửa.
    expect(BEA_ATTRIBUTION).toBe(
      "This product uses the Bureau of Economic Analysis (BEA) Data API but is not endorsed or certified by BEA.",
    );
    expect(screen.getByText(BEA_ATTRIBUTION)).toBeInTheDocument();
    expect(screen.getByText(/Lịch FOMC, thông cáo và phát biểu: Federal Reserve Board/)).toBeInTheDocument();
    // Bước 9b: lãi suất từ H.15 của Fed, lợi suất do Bộ Tài chính Mỹ tính (chú thích 9, 10 của H.15)
    expect(screen.getByText(/Federal Reserve Board H\.15.*U\.S\. Treasury/)).toBeInTheDocument();
    expect(screen.getByText(/Thông cáo báo chí: U\.S\. Department of the Treasury/)).toBeInTheDocument();
    expect(screen.getByText(/U\.S\. Department of Labor/)).toBeInTheDocument();
    // Bước 9e: COT vàng — CFTC yêu cầu ghi nguồn (webpolicy, đọc 2026-11-13)
    expect(screen.getByText(/Commodity Futures Trading Commission/)).toBeInTheDocument();
    expect(CENSUS_ATTRIBUTION).toBe(
      "This product uses the Census Bureau Data API but is not endorsed or certified by the Census Bureau.",
    );
    expect(screen.getByText(CENSUS_ATTRIBUTION)).toBeInTheDocument();
  });
});
