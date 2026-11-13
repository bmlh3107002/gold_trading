import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { DataSource, DataSourcesResponse } from "../api/client";
import { json, makeAccount, makeMe, makeStatus, makeSummary, makeSystem } from "../test/fixtures";
import { formatAge } from "./SourcesPage";

function src(over: Partial<DataSource> = {}): DataSource {
  return {
    name: "fed_h15",
    kind: "macro",
    provider: "fed",
    terms_status: "VERIFIED",
    enabled: true,
    status: "HEALTHY",
    reason: "OK",
    flags: [],
    last_check_at: "2026-11-13T13:16:00Z",
    last_ok_at: "2026-11-13T13:16:00Z",
    last_error_code: null,
    failures_since_ok: 0,
    latest_event_at: "2026-11-11T00:00:00Z",
    fetch_ttl_seconds: 43200,
    data_ttl_seconds: 604800,
    receive_age_seconds: 300,
    data_age_seconds: 2 * 86400 + 3600,
    quarantine_7d: 0,
    quarantine_total: 0,
    ...over,
  };
}

function routes(ds: DataSourcesResponse | null) {
  const table: Record<string, unknown> = {
    "/api/auth/me": makeMe(),
    "/api/status": makeSystem(),
    "/api/accounts": [makeAccount()],
    "/api/accounts/default/status": makeStatus(),
    "/api/accounts/default/mode/live-requests": [],
    "/api/accounts/default/market/summary": makeSummary(),
    "/api/data-sources": ds,
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
  window.location.hash = "#sources";
});
afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

describe("Trang Nguồn dữ liệu (DSH-09)", () => {
  it("hiện từng nguồn: trạng thái, lần nhận cuối, độ trễ, lỗi, cách ly", async () => {
    routes({
      as_of: "2026-11-13T13:21:00Z",
      runner_enabled: true,
      quarantine_window_days: 7,
      sources: [
        src(),
        src({
          name: "treasury_press", kind: "news", status: "STALE", reason: "FETCH_TTL_EXPIRED",
          last_error_code: "HTTP_503", flags: ["RECENT_FAILURES"], failures_since_ok: 3,
          receive_age_seconds: 13 * 3600, data_age_seconds: 50 * 60,
        }),
        src({
          name: "fed_fomc", kind: "calendar", status: "MISSING", reason: "FORBIDDEN",
          last_error_code: "FORBIDDEN", quarantine_7d: 2, quarantine_total: 5,
          last_ok_at: null, receive_age_seconds: null,
        }),
        src({ name: "nguon_moi", status: "INVALID", reason: "FEED_NOT_XML" }),
      ],
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Nguồn dữ liệu" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Nguồn dữ liệu" })).toHaveAttribute("aria-current", "page");
    const rows = await screen.findAllByRole("row");
    expect(rows).toHaveLength(5); // tiêu đề + 4 nguồn
    const h15 = within(rows[1]);
    expect(h15.getByText("Lãi suất + lợi suất (Fed H.15)")).toBeInTheDocument();
    expect(h15.getByText("Khỏe")).toBeInTheDocument();
    expect(h15.getByText("cách đây 5 phút")).toBeInTheDocument();
    expect(h15.getByText("2 ngày")).toBeInTheDocument();
    const tre = within(rows[2]);
    expect(tre.getByText("Cũ")).toBeInTheDocument();
    expect(tre.getByText(/Quá hạn chưa tải được · 3 lần lỗi gần đây/)).toBeInTheDocument();
    expect(tre.getByText("HTTP_503")).toBeInTheDocument();
    expect(tre.getByText("50 phút")).toBeInTheDocument();
    const fomc = within(rows[3]);
    expect(fomc.getByText("Thiếu")).toBeInTheDocument();
    expect(fomc.getByText("Bị từ chối truy cập (403)")).toBeInTheDocument();
    expect(fomc.getByText("2")).toBeInTheDocument();
    expect(fomc.getByText("/ 5")).toBeInTheDocument();
    // lịch: không hiện "độ trễ dữ liệu"
    expect(fomc.getAllByText("—").length).toBeGreaterThan(0);
    // tên / mã lý do lạ → hiện nguyên mã, không vỡ trang
    const moi = within(rows[4]);
    expect(moi.getAllByText("nguon_moi", { exact: false }).length).toBeGreaterThan(0);
    expect(moi.getByText("Hỏng")).toBeInTheDocument();
    expect(moi.getByText("FEED_NOT_XML")).toBeInTheDocument();
  });

  it("báo rõ khi backend tắt nạp nguồn ngoài", async () => {
    routes({ as_of: "2026-11-13T13:21:00Z", runner_enabled: false, quarantine_window_days: 7, sources: [] });
    render(<App />);
    expect(await screen.findByText("Chưa bật nạp nguồn ngoài")).toBeInTheDocument();
  });
});

describe("formatAge", () => {
  const t = (k: string, o: { n: number }) => `${k}:${JSON.stringify(o)}`;
  it("làm tròn xuống theo đơn vị", () => {
    expect(formatAge(null, t)).toBe("—");
    expect(formatAge(59, t)).toBe('sources.age.seconds:{"n":59}');
    expect(formatAge(60, t)).toBe('sources.age.minutes:{"n":1}');
    expect(formatAge(3599, t)).toBe('sources.age.minutes:{"n":59}');
    expect(formatAge(3600, t)).toBe('sources.age.hours:{"n":1}');
    expect(formatAge(172799, t)).toBe('sources.age.hours:{"n":47}');
    expect(formatAge(172800, t)).toBe('sources.age.days:{"n":2}');
  });
});
