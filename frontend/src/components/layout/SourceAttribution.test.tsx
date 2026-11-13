import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BEA_ATTRIBUTION, SourceAttribution } from "./SourceAttribution";

describe("SourceAttribution", () => {
  it("hiện nguyên văn câu ghi nguồn BEA và ghi nguồn Fed", () => {
    render(<SourceAttribution />);
    // Nguyên văn theo thỏa thuận API của BEA (đọc 2026-11-13) — không được dịch hay sửa.
    expect(BEA_ATTRIBUTION).toBe(
      "This product uses the Bureau of Economic Analysis (BEA) Data API but is not endorsed or certified by BEA.",
    );
    expect(screen.getByText(BEA_ATTRIBUTION)).toBeInTheDocument();
    expect(screen.getByText(/Federal Reserve Board/)).toBeInTheDocument();
  });
});
