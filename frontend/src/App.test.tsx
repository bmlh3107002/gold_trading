import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { json, makeAccount, makeMe, makeStatus, makeSummary, makeSystem } from "./test/fixtures";

const ACC = "/api/accounts/default";

/** Handler lo trạng thái tài khoản và lệnh ghi; các API khác có giá trị mặc định. */
const OK_HEALTH = { clock: { state: "OK", offset_s: 0.2, sources_ok: 5, measured_at: "2026-11-06T03:00:00Z" } };

function mockFetch(
  handler: (url: string, init?: RequestInit) => Response | Promise<Response>,
  handlesHealth = false,
) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/auth/me") return json(makeMe());
    if (url === "/api/status") return json(makeSystem());
    if (url === "/api/accounts") return json([makeAccount()]);
    if (url === `${ACC}/mode/live-requests` && init?.method !== "POST") return json([]);
    if (url === "/api/system/health" && !handlesHealth) return json(OK_HEALTH);
    if (url.startsWith("/api/market/summary")) {
      return json(makeSummary({ last_price: null, change: null, change_pct: null, is_sample: false }));
    }
    return handler(url, init);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("hiển thị loading rồi dữ liệu, không có giá giả", async () => {
    mockFetch(() => json(makeStatus()));
    render(<App />);
    expect((await screen.findAllByText("Tạm dừng")).length).toBeGreaterThan(0);
    expect(screen.getByText("Chưa có dữ liệu giá")).toBeInTheDocument();
    expect(screen.getAllByText("Chưa có MarketView hợp lệ").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Tổng quan" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByText("Lưu trữ: PostgreSQL")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Tài khoản giao dịch" })).toHaveValue("default");
  });

  it("hiển thị lỗi kèm nút thử lại khi backend không phản hồi", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    render(<App />);
    expect(await screen.findByText("Không kiểm tra được đăng nhập")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Thử lại" }).length).toBeGreaterThan(0);
  });

  it("dừng khẩn cấp cần xác nhận, sau đó gửi lệnh halt", async () => {
    let state = makeStatus({ safety_state: "ACTIVE", allows_new_orders: true });
    const fetchMock = mockFetch((url) => {
      if (url === `${ACC}/safety`) {
        state = makeStatus({ safety_state: "HALTED" });
        return json(state);
      }
      return json(state);
    });
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Dừng khẩn cấp" }));
    const dialog = screen.getByRole("dialog", { name: "Dừng khẩn cấp toàn hệ thống?" });
    expect(fetchMock).not.toHaveBeenCalledWith(`${ACC}/safety`, expect.anything());
    await userEvent.click(within(dialog).getByRole("button", { name: "Dừng khẩn cấp" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        `${ACC}/safety`,
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ action: "halt", reason_code: "MANUAL_HALT", operator_approved: false }),
        }),
      ),
    );
  });

  it("không có ô nhập người thao tác: người thao tác lấy từ phiên đăng nhập", async () => {
    mockFetch(() => json(makeStatus()));
    render(<App />);
    expect(await screen.findByRole("button", { name: "Cho phép giao dịch" })).toBeInTheDocument();
    expect(screen.queryByLabelText(/Người thao tác/)).not.toBeInTheDocument();
    expect(screen.getByText("admin")).toBeInTheDocument();
  });

  it("VIEWER: nút điều khiển bị khóa, có thông báo chỉ xem", async () => {
    mockFetch(() => json(makeStatus({ role: "VIEWER", permissions: ["VIEW"] })));
    render(<App />);
    expect(await screen.findByText("Bạn chỉ có quyền xem tài khoản này.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cho phép giao dịch" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Dừng khẩn cấp" })).toBeDisabled();
  });

  it("không có tài khoản nào: thông báo chưa được cấp quyền", async () => {
    const fn = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/auth/me") return json(makeMe({ is_admin: false }));
      if (url === "/api/accounts") return json([]);
      if (url === "/api/status") return json(makeSystem());
      return json(makeSummary({ last_price: null, change: null, change_pct: null, is_sample: false }));
    });
    vi.stubGlobal("fetch", fn);
    render(<App />);
    expect(await screen.findByText("Bạn chưa được cấp quyền tài khoản nào")).toBeInTheDocument();
  });

  it("yêu cầu LIVE của người khác: hiện nút duyệt; của chính mình: cần người khác", async () => {
    const reqs = [
      { request_id: "lr1", account_id: "default", requested_by: "bob", requested_at: "2026-11-06T03:00:00Z",
        expires_at: "2026-11-06T03:15:00Z", checklist: {} },
    ];
    const fn = mockFetch((url) => (url === `${ACC}/mode/live-requests` ? json(reqs) : json(makeStatus())));
    // mockFetch trả [] cho GET live-requests; ghi đè để trả danh sách
    fn.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/auth/me") return json(makeMe());
      if (url === "/api/status") return json(makeSystem());
      if (url === "/api/accounts") return json([makeAccount()]);
      if (url === `${ACC}/mode/live-requests`) return json(reqs);
      if (url.startsWith("/api/market/summary")) return json(makeSummary({ last_price: null, change: null, change_pct: null }));
      if (url === `${ACC}/mode/live-requests/lr1/approve` && init?.method === "POST") return json(makeStatus({ mode: "LIVE" }));
      return json(makeStatus());
    });
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Duyệt bật LIVE" }));
    await waitFor(() =>
      expect(fn).toHaveBeenCalledWith(`${ACC}/mode/live-requests/lr1/approve`, expect.objectContaining({ method: "POST" })),
    );
  });

  it("đồng hồ lệch quá 30 giây: banner báo đã ngừng nhận nến", async () => {
    mockFetch(
      (url) =>
        url === "/api/system/health"
          ? json({ clock: { state: "BLOCKED", offset_s: -41.5, sources_ok: 5, measured_at: "2026-11-06T03:00:00Z" } })
          : json(makeStatus()),
      true,
    );
    render(<App />);
    expect(await screen.findByText(/lệch -41.5 giây: ĐÃ NGỪNG nhận nến/)).toBeInTheDocument();
  });

  it("chưa đăng nhập: hiện trang đăng nhập, không gọi API trạng thái", async () => {
    const fn = vi.fn(async (input: RequestInfo | URL) =>
      String(input) === "/api/auth/me" ? json({ detail: "x" }, 401) : json(makeStatus()),
    );
    vi.stubGlobal("fetch", fn);
    render(<App />);
    expect(await screen.findByRole("button", { name: "Đăng nhập" })).toBeInTheDocument();
    expect(fn).not.toHaveBeenCalledWith(`${ACC}/status`, expect.anything());
    expect(screen.queryByLabelText(/Mật khẩu/)).not.toBeInTheDocument();
  });

  it("phiên hết hạn giữa chừng (401) → quay về trang đăng nhập", async () => {
    let expired = false;
    mockFetch(() => (expired ? json({ detail: "x" }, 401) : json(makeStatus())));
    render(<App />);
    expect((await screen.findAllByText("Tạm dừng")).length).toBeGreaterThan(0);
    expired = true;
    await userEvent.click(screen.getByRole("button", { name: "Cho phép giao dịch" }));
    expect(await screen.findByRole("button", { name: "Đăng nhập" })).toBeInTheDocument();
  });

  it("đăng xuất chuyển tới trang đăng xuất của Keycloak", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    mockFetch((url) =>
      url === "/api/auth/logout" ? json({ logout_url: "/auth/realms/x/logout?y=1" }) : json(makeStatus()),
    );
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Đăng xuất" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/auth/realms/x/logout?y=1"));
  });

  it("lỗi 409 hiển thị thông báo thân thiện, không hiện lỗi thô", async () => {
    mockFetch((url) =>
      url === `${ACC}/mode/live-requests` ? json({ detail: "raw backend detail" }, 409) : json(makeStatus()),
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
    await userEvent.click(await screen.findByRole("button", { name: "Chuyển sang giao diện sáng" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    await userEvent.click(screen.getByRole("button", { name: "Chuyển sang giao diện tối" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
