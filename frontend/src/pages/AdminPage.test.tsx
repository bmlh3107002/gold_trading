import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdminPage } from "./AdminPage";
import { Sidebar } from "../components/layout/Sidebar";
import { json, makeMe } from "../test/fixtures";

const PW = "TamThoi12345xyz";
const TOKEN = "gtk_SECRETVALUE_0123456789abcdef0123456789";
const ADMIN = makeMe({ username: "admin", is_admin: true });

const LAN = {
  sub: "kc-1", username: "lanng", email: "lan@example.com", display_name: "Lan Nguyen", status: "ACTIVE",
  first_login_at: null, last_login_at: null, updated_at: null,
  accounts: [{ account_id: "u-lanng", name: "Tài khoản của Lan", price_feed: false, gateway_status: "WAITING",
               gateway_last_seen_at: null }],
};

type Handler = (url: string, init?: RequestInit) => Response | null;

function mock(handler: Handler = () => null, users: unknown[] = []) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const r = handler(url, init);
    if (r) return r;
    if (url === "/api/admin/users" && init?.method !== "POST") return json(users);
    if (url === "/api/admin/live-requests") return json([]);
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const posts = (fn: ReturnType<typeof mock>) =>
  fn.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST").map(([u]) => String(u));

async function fill(pw = PW, confirm = PW) {
  await userEvent.type(screen.getByLabelText(/Tên đăng nhập/), "lanng");
  await userEvent.type(screen.getByLabelText(/Email/), "lan@example.com");
  await userEvent.type(screen.getByLabelText(/^Họ\*?$/), "Nguyen");
  await userEvent.type(screen.getByLabelText(/^Tên\*?$/), "Lan");
  if (pw) await userEvent.type(screen.getByLabelText(/^Mật khẩu tạm/), pw);
  if (confirm) await userEvent.type(screen.getByLabelText(/Nhập lại mật khẩu/), confirm);
}

afterEach(() => vi.unstubAllGlobals());

describe("Trang Quản trị", () => {
  it("người không phải ADMIN: không có form, không gọi API", () => {
    const fn = mock();
    render(<AdminPage me={makeMe()} multiUser />);
    expect(screen.getByText("Bạn không có quyền xem trang này")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tạo người dùng" })).not.toBeInTheDocument();
    expect(fn).not.toHaveBeenCalled();
  });

  it("tạo USER: gửi đúng dữ liệu, hiện token Gateway MỘT lần, xóa mật khẩu khỏi form", async () => {
    const fn = mock((url, init) =>
      url === "/api/admin/users" && init?.method === "POST"
        ? json({ sub: "kc-1", username: "lanng", email: "lan@example.com", display_name: "Lan Nguyen",
                 status: "ACTIVE", account_id: "u-lanng", account_name: "Tài khoản của Lan Nguyen",
                 gateway: { account_id: "u-lanng", token_id: "gtk_1", token: TOKEN, created_at: "2026-11-06T03:00:00Z" },
                 gateway_status: "WAITING", temporary_password: null }, 201)
        : null,
    );
    render(<AdminPage me={ADMIN} multiUser />);
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Tạo người dùng" }));
    const dialog = await screen.findByRole("dialog", { name: "Đã tạo người dùng lanng" });
    expect(within(dialog).getByText(TOKEN)).toBeInTheDocument();
    const [, init] = fn.mock.calls.find(([, i]) => (i as RequestInit)?.method === "POST") as unknown as [
      string,
      RequestInit,
    ];
    expect(JSON.parse(String(init.body))).toEqual({
      username: "lanng", email: "lan@example.com", first_name: "Lan", last_name: "Nguyen",
      password: PW, account_name: null,
    });
    expect(screen.getByLabelText(/^Mật khẩu tạm/)).toHaveValue("");
    await userEvent.click(within(dialog).getByRole("button", { name: "Tôi đã lưu" }));
    await waitFor(() => expect(screen.queryByText(TOKEN)).not.toBeInTheDocument());
  });

  it("bỏ trống mật khẩu: gửi null, hiện mật khẩu tạm hệ thống sinh", async () => {
    const fn = mock((url, init) =>
      url === "/api/admin/users" && init?.method === "POST"
        ? json({ sub: "kc-1", username: "lanng", email: "lan@example.com", display_name: "Lan Nguyen",
                 status: "ACTIVE", account_id: "u-lanng", account_name: "TK",
                 gateway: { account_id: "u-lanng", token_id: "gtk_1", token: TOKEN, created_at: "2026-11-06T03:00:00Z" },
                 gateway_status: "WAITING", temporary_password: "GENERATED-pw-123456" }, 201)
        : null,
    );
    render(<AdminPage me={ADMIN} multiUser />);
    await fill("", "");
    await userEvent.click(screen.getByRole("button", { name: "Tạo người dùng" }));
    const dialog = await screen.findByRole("dialog", { name: "Đã tạo người dùng lanng" });
    expect(within(dialog).getByText("GENERATED-pw-123456")).toBeInTheDocument();
    const post = fn.mock.calls.find(([, i]) => (i as RequestInit)?.method === "POST")!;
    expect(JSON.parse(String((post[1] as RequestInit).body)).password).toBeNull();
  });

  it("mật khẩu ngắn hoặc nhập lại sai: không gửi", async () => {
    const fn = mock();
    render(<AdminPage me={ADMIN} multiUser />);
    await fill("ngan123", "ngan123");
    await userEvent.click(screen.getByRole("button", { name: "Tạo người dùng" }));
    expect(screen.getByText("Mật khẩu tạm cần ít nhất 12 ký tự.")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText(/^Mật khẩu tạm/));
    await userEvent.type(screen.getByLabelText(/^Mật khẩu tạm/), PW);
    await userEvent.click(screen.getByRole("button", { name: "Tạo người dùng" }));
    expect(screen.getByText("Hai lần nhập mật khẩu không khớp.")).toBeInTheDocument();
    expect(posts(fn)).toEqual([]);
  });

  it("trùng tên/email và Keycloak chưa cho phép: thông báo thân thiện, không hiện lỗi thô", async () => {
    let status = 409;
    mock((url, init) => (url === "/api/admin/users" && init?.method === "POST" ? json({ detail: "raw keycloak" }, status) : null));
    render(<AdminPage me={ADMIN} multiUser />);
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Tạo người dùng" }));
    expect(await screen.findByText("Tên đăng nhập hoặc email đã có.")).toBeInTheDocument();
    status = 503;
    await userEvent.click(screen.getByRole("button", { name: "Tạo người dùng" }));
    await waitFor(() => expect(screen.getByText(/sync-client\.sh/)).toBeInTheDocument());
    expect(screen.queryByText(/raw keycloak/)).not.toBeInTheDocument();
  });

  it("chưa bật nhiều người dùng: cảnh báo và khóa nút", async () => {
    mock();
    render(<AdminPage me={ADMIN} multiUser={false} />);
    await fill();
    expect(screen.getByText(/GT_MULTI_USER_ENABLED=1/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tạo người dùng" })).toBeDisabled();
  });

  it("danh sách USER: trạng thái + Gateway, khóa cần xác nhận", async () => {
    const fn = mock(
      (url) =>
        url === "/api/admin/users/kc-1/lock"
          ? json({ sub: "kc-1", status: "LOCKED", sessions_revoked: 1, keycloak_synced: false })
          : null,
      [LAN],
    );
    render(<AdminPage me={ADMIN} multiUser />);
    // Hai bảng riêng: người dùng (trạng thái, thao tác tài khoản) và tài khoản giao dịch (Gateway, token)
    await screen.findAllByText("Lan Nguyen");
    const [uTable, aTable] = screen.getAllByRole("table");
    const usersTable = within(uTable);
    expect(usersTable.getByText("Lan Nguyen")).toBeInTheDocument();
    expect(usersTable.getByText("Đang hoạt động")).toBeInTheDocument();
    expect(usersTable.queryByRole("button", { name: "Cấp lại token" })).not.toBeInTheDocument();
    const accTable = within(aTable);
    expect(screen.getByRole("heading", { name: "Tài khoản giao dịch · MT5 Gateway" })).toBeInTheDocument();
    expect(accTable.getByText("Tài khoản của Lan")).toBeInTheDocument();
    expect(accTable.getByText("Đã cấp token · chờ Gateway kết nối")).toBeInTheDocument();
    expect(accTable.getAllByRole("button", { name: "Cấp lại token" })).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Khóa" }));
    expect(posts(fn)).toEqual([]); // chưa gửi khi chưa xác nhận
    const dialog = screen.getByRole("dialog", { name: "Khóa người dùng lanng?" });
    expect(within(dialog).getByText(/KHÔNG bị đóng tự động/)).toBeInTheDocument();
    expect(within(dialog).queryByText(/NGUỒN GIÁ/)).not.toBeInTheDocument(); // tài khoản riêng
    await userEvent.click(within(dialog).getByRole("button", { name: "Khóa" }));
    await waitFor(() => expect(posts(fn)).toEqual(["/api/admin/users/kc-1/lock"]));
    // Keycloak chưa cập nhật: vẫn báo khóa có hiệu lực + nhắc bấm lại
    expect(await screen.findByText(/Keycloak chưa cập nhật/)).toBeInTheDocument();
  });

  it("khóa USER giữ tài khoản nguồn giá: cảnh báo ngừng nhận nến cho cả hệ thống", async () => {
    mock(() => null, [{ ...LAN, accounts: [{ ...LAN.accounts[0], account_id: "default", price_feed: true }] }]);
    render(<AdminPage me={ADMIN} multiUser />);
    await userEvent.click(await screen.findByRole("button", { name: "Khóa" }));
    const dialog = screen.getByRole("dialog", { name: "Khóa người dùng lanng?" });
    expect(within(dialog).getByText(/NGUỒN GIÁ chung/)).toBeInTheDocument();
  });

  it("USER đã khóa: nút Mở khóa", async () => {
    const fn = mock(
      (url) =>
        url === "/api/admin/users/kc-1/unlock"
          ? json({ sub: "kc-1", status: "ACTIVE", sessions_revoked: 0, keycloak_synced: true })
          : null,
      [{ ...LAN, status: "LOCKED", accounts: [{ ...LAN.accounts[0], gateway_status: "BLOCKED" }] }],
    );
    render(<AdminPage me={ADMIN} multiUser />);
    expect(await screen.findByText("Đã khóa")).toBeInTheDocument();
    expect(screen.getByText("Bị chặn (người dùng đã khóa)")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Mở khóa" }));
    const dialog = screen.getByRole("dialog", { name: "Mở khóa người dùng lanng?" });
    expect(within(dialog).getByText(/Bot KHÔNG tự chạy lại/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Mở khóa" }));
    await waitFor(() => expect(posts(fn)).toEqual(["/api/admin/users/kc-1/unlock"]));
  });

  it("đặt lại mật khẩu và cấp lại token: xác nhận rồi hiện bí mật MỘT lần", async () => {
    const fn = mock(
      (url) =>
        url === "/api/admin/users/kc-1/reset-password"
          ? json({ sub: "kc-1", temporary_password: "NEWTEMP-pw-987654", sessions_revoked: 1 })
          : url === "/api/admin/users/kc-1/accounts/u-lanng/gateway-token"
            ? json({ account_id: "u-lanng", token_id: "gtk_2", token: TOKEN, created_at: "2026-11-06T03:00:00Z" })
            : null,
      [LAN],
    );
    render(<AdminPage me={ADMIN} multiUser />);
    await userEvent.click(await screen.findByRole("button", { name: "Đặt lại mật khẩu" }));
    await userEvent.click(
      within(screen.getByRole("dialog", { name: "Đặt lại mật khẩu cho lanng?" })).getByRole("button", {
        name: "Đặt lại mật khẩu",
      }),
    );
    const pwDialog = await screen.findByRole("dialog", { name: "Mật khẩu tạm của lanng" });
    expect(within(pwDialog).getByText("NEWTEMP-pw-987654")).toBeInTheDocument();
    await userEvent.click(within(pwDialog).getByRole("button", { name: "Tôi đã lưu" }));
    await waitFor(() => expect(screen.queryByText("NEWTEMP-pw-987654")).not.toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Cấp lại token" }));
    const confirm = screen.getByRole("dialog", { name: "Cấp lại token Gateway cho Tài khoản của Lan?" });
    expect(within(confirm).getByText(/hết hiệu lực NGAY/)).toBeInTheDocument();
    await userEvent.click(within(confirm).getByRole("button", { name: "Cấp token mới" }));
    expect(await screen.findByText(TOKEN)).toBeInTheDocument();
    expect(posts(fn)).toEqual([
      "/api/admin/users/kc-1/reset-password",
      "/api/admin/users/kc-1/accounts/u-lanng/gateway-token",
    ]);
  });

  it("yêu cầu bật LIVE: ADMIN duyệt (có xác nhận) hoặc từ chối", async () => {
    const req = { request_id: "lr1", account_id: "u-lanng", account_name: "Tài khoản của Lan", requested_by: "lanng",
                  requested_at: "2026-11-06T03:00:00Z", expires_at: "2026-11-06T03:15:00Z", checklist: {} };
    const fn = mock((url) =>
      url === "/api/admin/live-requests"
        ? json([req])
        : url.startsWith("/api/admin/live-requests/lr1/")
          ? json(req)
          : null,
    );
    render(<AdminPage me={ADMIN} multiUser />);
    expect(await screen.findByText(/lanng xin bật LIVE cho Tài khoản của Lan/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Duyệt bật LIVE" }));
    expect(posts(fn)).toEqual([]);
    const dialog = screen.getByRole("dialog", { name: "Duyệt bật LIVE cho Tài khoản của Lan?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Duyệt bật LIVE" }));
    await waitFor(() => expect(posts(fn)).toEqual(["/api/admin/live-requests/lr1/approve"]));
    await userEvent.click(screen.getByRole("button", { name: "Từ chối" }));
    await userEvent.click(
      within(screen.getByRole("dialog", { name: "Từ chối yêu cầu bật LIVE?" })).getByRole("button", { name: "Từ chối" }),
    );
    await waitFor(() => expect(posts(fn)).toContain("/api/admin/live-requests/lr1/reject"));
  });
});

describe("Menu theo vai trò (DEC-16)", () => {
  const base = { open: false, onClose: () => {}, connection: "live" as const, version: "0.1", storage: "postgres",
                 route: "overview" as const, gateway: null };
  it("USER: không có Quản trị; ADMIN: chỉ có Quản trị", () => {
    const { rerender } = render(<Sidebar {...base} isAdmin={false} />);
    expect(screen.queryByRole("link", { name: "Quản trị" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Tổng quan" })).toBeInTheDocument();
    rerender(<Sidebar {...base} isAdmin />);
    expect(screen.getByRole("link", { name: "Quản trị" })).toHaveAttribute("href", "#admin");
    expect(screen.queryByRole("link", { name: "Tổng quan" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Thị trường" })).not.toBeInTheDocument();
  });
});
