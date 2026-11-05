import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { makeStatus } from "./test/fixtures";

function mockFetch(handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => handler(String(input), init));
  vi.stubGlobal("fetch", fn);
  return fn;
}
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("hiển thị loading rồi dữ liệu, không có giá giả", async () => {
    mockFetch(() => json(makeStatus()));
    render(<App />);
    expect(screen.getByText("Đang tải trạng thái hệ thống…")).toBeInTheDocument();
    expect((await screen.findAllByText("Tạm dừng")).length).toBeGreaterThan(0);
    expect(screen.getByText("Chưa có dữ liệu giá")).toBeInTheDocument();
    expect(screen.getAllByText("Chưa có MarketView hợp lệ").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Tổng quan" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("Lưu trữ: PostgreSQL")).toBeInTheDocument();
  });

  it("hiển thị lỗi kèm nút thử lại khi backend không phản hồi", async () => {
    mockFetch(() => {
      throw new TypeError("Failed to fetch");
    });
    render(<App />);
    expect(await screen.findByText("Không tải được trạng thái hệ thống")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Thử lại" }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Mất kết nối").length).toBeGreaterThan(0);
  });

  it("dừng khẩn cấp cần xác nhận, sau đó gửi lệnh halt", async () => {
    let state = makeStatus({ safety_state: "ACTIVE", allows_new_orders: true });
    const fetchMock = mockFetch((url) => {
      if (url === "/api/safety") {
        state = makeStatus({ safety_state: "HALTED" });
        return json(state);
      }
      return json(state);
    });
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Dừng khẩn cấp" }));
    const dialog = screen.getByRole("dialog", { name: "Dừng khẩn cấp toàn hệ thống?" });
    expect(fetchMock).not.toHaveBeenCalledWith("/api/safety", expect.anything());
    await userEvent.click(within(dialog).getByRole("button", { name: "Dừng khẩn cấp" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/safety",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ action: "halt", reason_code: "MANUAL_HALT", actor: "operator", operator_approved: false }),
        }),
      ),
    );
  });

  it("báo lỗi validation khi thiếu người thao tác", async () => {
    mockFetch(() => json(makeStatus()));
    render(<App />);
    const input = await screen.findByLabelText(/Người thao tác/);
    await userEvent.clear(input);
    await userEvent.click(screen.getByRole("button", { name: "Cho phép giao dịch" }));
    expect(screen.getByText("Vui lòng nhập người thao tác")).toBeInTheDocument();
    expect(input).toHaveAttribute("aria-invalid", "true");
  });

  it("lỗi 409 hiển thị thông báo thân thiện, không hiện lỗi thô", async () => {
    mockFetch((url) =>
      url === "/api/mode" ? json({ detail: "raw backend detail" }, 409) : json(makeStatus()),
    );
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: /Live/ }));
    await userEvent.click(screen.getByRole("button", { name: "Gửi yêu cầu LIVE" }));
    expect(await screen.findByText(/Không thể chuyển chế độ/)).toBeInTheDocument();
    expect(screen.queryByText("raw backend detail")).not.toBeInTheDocument();
  });

  it("chuyển dark/light mode", async () => {
    mockFetch(() => json(makeStatus()));
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Chuyển sang giao diện sáng" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    await userEvent.click(screen.getByRole("button", { name: "Chuyển sang giao diện tối" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
