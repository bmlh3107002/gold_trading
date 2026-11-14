import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { PipelineJob, PipelineResponse } from "../api/client";
import { json, makeAccount, makeMe, makeStatus, makeSummary, makeSystem } from "../test/fixtures";

function job(over: Partial<PipelineJob> = {}): PipelineJob {
  return {
    job_type: "FAST_LANE",
    analyzer_version: "fast-lane-1",
    event_type: "ACTUAL_RELEASED",
    subject: "bls_values:CUUR0000SA0:2026-11",
    created_at: "2026-12-10T13:31:22Z",
    state: "SUCCEEDED",
    state_at: "2026-12-10T13:31:22Z",
    attempts: 1,
    error_code: null,
    output_ref: "block:abc123",
    ...over,
  };
}

function routes(p: PipelineResponse) {
  const table: Record<string, unknown> = {
    "/api/auth/me": makeMe(),
    "/api/status": makeSystem(),
    "/api/accounts": [makeAccount()],
    "/api/accounts/default/status": makeStatus(),
    "/api/accounts/default/mode/live-requests": [],
    "/api/accounts/default/market/summary": makeSummary(),
    "/api/pipeline": p,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input).split("?")[0];
      return json(table[path] ?? {}, table[path] ? 200 : 404);
    }),
  );
}

const base: PipelineResponse = {
  as_of: "2026-12-10T13:40:00Z",
  orchestrator_enabled: true,
  window_hours: 24,
  dead_window_days: 7,
  counts: [],
  open_jobs: [],
  stuck_jobs: 0,
  dead_letter: [],
  recent: [],
  lanes: [],
  budget_breaches: 0,
  last_latency_ms: null,
};

beforeEach(() => {
  window.location.hash = "#pipeline";
});
afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

describe("Trang Pipeline (DSH-08)", () => {
  it("hiện làn nhanh, dead-letter, job đang chờ, đếm theo loại", async () => {
    routes({
      ...base,
      lanes: [
        { lane: "events", started_at: "2026-12-10T13:00:00Z", last_ok_at: "2026-12-10T13:39:58Z", backlog_since: null, ok: true },
        { lane: "spread", started_at: "2026-12-10T13:00:00Z", last_ok_at: "2026-12-10T13:39:40Z", backlog_since: null, ok: false },
      ],
      budget_breaches: 2,
      last_latency_ms: 3000,
      dead_letter: [job({ state: "DEAD", error_code: "BOOM", attempts: 3, output_ref: null, subject: "fed_rss_monetary:n:x" })],
      open_jobs: [job({ state: "FAILED", error_code: "TIMEOUT_ERROR", job_type: "LOAI_MOI" })],
      stuck_jobs: 1,
      counts: [
        { job_type: "TECHNICAL", state: "SUCCEEDED", count: 96 },
        { job_type: "REGIME", state: "NO_HANDLER", count: 96 },
      ],
      recent: [job()],
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Pipeline" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Pipeline" })).toHaveAttribute("aria-current", "page");
    const lanes = within(await screen.findByRole("region", { name: "Làn nhanh" }));
    expect(lanes.getByText("Sự kiện (số liệu, tin)")).toBeInTheDocument();
    expect(lanes.getByText("Đạt")).toBeInTheDocument();
    expect(lanes.getByText("Chậm / chưa chạy")).toBeInTheDocument();
    expect(screen.getByText(/chậm hơn 10 giây: 2 · độ trễ gần nhất: 3[.,]000 ms/)).toBeInTheDocument();
    const dead = within(screen.getByRole("region", { name: "Dead-letter (7 ngày)" }));
    expect(dead.getByText("Bỏ cuộc")).toBeInTheDocument();
    expect(dead.getByText("BOOM")).toBeInTheDocument();
    expect(dead.getByText("fed_rss_monetary:n:x")).toBeInTheDocument();
    expect(screen.getByText("1 job chưa xong quá 2 phút")).toBeInTheDocument();
    const open = within(screen.getByRole("region", { name: "Đang chờ / đang chạy" }));
    expect(open.getByText("LOAI_MOI")).toBeInTheDocument(); // loại lạ → hiện nguyên mã
    expect(open.getByText("Lỗi, sẽ thử lại")).toBeInTheDocument();
    const counts = within(screen.getByRole("region", { name: "Job trong 24 giờ qua" }));
    expect(counts.getByText("Phân tích kỹ thuật")).toBeInTheDocument();
    expect(counts.getByText("Chưa có bộ xử lý")).toBeInTheDocument();
  });

  it("báo rõ khi bộ điều phối tắt", async () => {
    routes({ ...base, orchestrator_enabled: false });
    render(<App />);
    expect(await screen.findByText("Bộ điều phối đang tắt")).toBeInTheDocument();
  });
});
