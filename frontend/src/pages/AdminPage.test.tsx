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
  gateway_status: "WAITING", gateway_last_seen_at: null, token_requested_at: null, price_feed: false,
};

type Handler = (url: string, init?: RequestInit) => Response | null;

function mock(handler: Handler = () => null, users: unknown[] = []) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const r = handler(url, init);
    if (r) return r;
    if (url === "/api/admin/users" && (init?.method ?? "GET") === "GET") return json(users);
    if (url === "/api/admin/live-requests") return json([]);
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const calls = (fn: ReturnType<typeof mock>, method: string) =>
  fn.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === method).map(([u]) => String(u));
const posts = (fn: ReturnType<typeof mock>) => calls(fn, "POST");

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

  it("tạo USER: gửi đúng dữ liệu, KHÔNG có token (USER xin sau), xóa mật khẩu khỏi form", async () => {
    const fn = mock((url, init) =>
      url === "/api/admin/users" && init?.method === "POST"
        ? json({ sub: "kc-1", username: "lanng", email: "lan@example.com", display_name: "Lan Nguyen",
                 status: "ACTIVE", temporary_password: null }, 201)
        : null,
    );
    render(<AdminPage me={ADMIN} multiUser />);
    expect(screen.queryByLabelText(/Tên tài khoản giao dịch/)).not.toBeInTheDocument();
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Tạo người dùng" }));
    const dialog = await screen.findByRole("dialog", { name: "Đã tạo người dùng lanng" });
    expect(within(dialog).getByText(/Xin cấp token/)).toBeInTheDocument();
    expect(within(dialog).queryByText(/gtk_/)).not.toBeInTheDocument();
    const [, init] = fn.mock.calls.find(([, i]) => (i as RequestInit)?.method === "POST") as unknown as [
      string,
      RequestInit,
    ];
    expect(JSON.parse(String(init.body))).toEqual({
      username: "lanng", email: "lan@example.com", first_name: "Lan", last_name: "Nguyen",
      password: PW,
    });
    expect(screen.getByLabelText(/^Mật khẩu tạm/)).toHaveValue("");
    await userEvent.click(within(dialog).getByRole("button", { name: "Tôi đã lưu" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("bỏ trống mật khẩu: gửi null, hiện mật khẩu tạm hệ thống sinh", async () => {
    const fn = mock((url, init) =>
      url === "/api/admin/users" && init?.method === "POST"
        ? json({ sub: "kc-1", username: "lanng", email: "lan@example.com", display_name: "Lan Nguyen",
                 status: "ACTIVE", temporary_password: "GENERATED-pw-123456" }, 201)
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

  it("danh sách: một người một dòng (không lộ tài khoản giao dịch nội bộ), khóa cần xác nhận", async () => {
    const fn = mock(
      (url) =>
        url === "/api/admin/users/kc-1/lock"
          ? json({ sub: "kc-1", status: "LOCKED", sessions_revoked: 1, keycloak_synced: false })
          : null,
      [LAN],
    );
    render(<AdminPage me={ADMIN} multiUser />);
    await screen.findByText("Lan Nguyen");
    expect(screen.getAllByRole("table")).toHaveLength(1);
    expect(screen.getAllByRole("row")).toHaveLength(2); // tiêu đề + một người
    expect(screen.getByText("Đang hoạt động")).toBeInTheDocument();
    expect(screen.getByText("Đã cấp token · chờ Gateway kết nối")).toBeInTheDocument();
    expect(screen.queryByText(/Tài khoản chính|Nguồn giá chung|u-lanng|default/)).not.toBeInTheDocument();
    for (const name of ["Cấp token", "Sửa", "Khóa", "Đặt lại mật khẩu", "Xóa"])
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Từ chối" })).not.toBeInTheDocument(); // không có yêu cầu
    await userEvent.click(screen.getByRole("button", { name: "Khóa" }));
    expect(posts(fn)).toEqual([]); // chưa gửi khi chưa xác nhận
    const dialog = screen.getByRole("dialog", { name: "Khóa người dùng lanng?" });
    expect(within(dialog).getByText(/KHÔNG bị đóng tự động/)).toBeInTheDocument();
    expect(within(dialog).queryByText(/CẤP GIÁ/)).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Khóa" }));
    await waitFor(() => expect(posts(fn)).toEqual(["/api/admin/users/kc-1/lock"]));
    // Keycloak chưa cập nhật: vẫn báo khóa có hiệu lực + nhắc bấm lại
    expect(await screen.findByText(/Keycloak chưa cập nhật/)).toBeInTheDocument();
  });

  it("người đang cấp giá cho hệ thống: ghi chú rõ, cảnh báo khi khóa, không cho xóa", async () => {
    const fn = mock(() => null, [{ ...LAN, price_feed: true, gateway_status: "CONNECTED" }]);
    render(<AdminPage me={ADMIN} multiUser />);
    expect(await screen.findByText(/đang cấp giá XAUUSD cho cả hệ thống/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Xóa" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Khóa" }));
    const dialog = screen.getByRole("dialog", { name: "Khóa người dùng lanng?" });
    expect(within(dialog).getByText(/CẤP GIÁ cho cả hệ thống/)).toBeInTheDocument();
    expect(calls(fn, "DELETE")).toEqual([]);
  });

  it("USER đã khóa: nút Mở khóa, không cấp token", async () => {
    const fn = mock(
      (url) =>
        url === "/api/admin/users/kc-1/unlock"
          ? json({ sub: "kc-1", status: "ACTIVE", sessions_revoked: 0, keycloak_synced: true })
          : null,
      [{ ...LAN, status: "LOCKED", gateway_status: "BLOCKED" }],
    );
    render(<AdminPage me={ADMIN} multiUser />);
    expect(await screen.findByText("Đã khóa")).toBeInTheDocument();
    expect(screen.getByText("Bị chặn (người dùng đã khóa)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cấp token" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Mở khóa" }));
    const dialog = screen.getByRole("dialog", { name: "Mở khóa người dùng lanng?" });
    expect(within(dialog).getByText(/Bot KHÔNG tự chạy lại/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Mở khóa" }));
    await waitFor(() => expect(posts(fn)).toEqual(["/api/admin/users/kc-1/unlock"]));
  });

  it("đặt lại mật khẩu và cấp token: xác nhận rồi hiện bí mật MỘT lần cho ADMIN", async () => {
    const fn = mock(
      (url) =>
        url === "/api/admin/users/kc-1/reset-password"
          ? json({ sub: "kc-1", temporary_password: "NEWTEMP-pw-987654", sessions_revoked: 1 })
          : url === "/api/admin/users/kc-1/gateway-token"
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

    await userEvent.click(screen.getByRole("button", { name: "Cấp token" }));
    const confirm = screen.getByRole("dialog", { name: "Cấp token Gateway cho lanng?" });
    expect(within(confirm).getByText(/hết hiệu lực NGAY/)).toBeInTheDocument();
    await userEvent.click(within(confirm).getByRole("button", { name: "Cấp token" }));
    expect(await screen.findByText(TOKEN)).toBeInTheDocument();
    expect(posts(fn)).toEqual([
      "/api/admin/users/kc-1/reset-password",
      "/api/admin/users/kc-1/gateway-token",
    ]);
  });

  it("USER đang xin token: hiện yêu cầu, ADMIN cấp hoặc từ chối", async () => {
    const fn = mock(
      (url) => (url === "/api/admin/users/kc-1/gateway-token/reject" ? new Response(null, { status: 204 }) : null),
      [{ ...LAN, gateway_status: "NO_TOKEN", token_requested_at: "2026-11-07T03:00:00Z" }],
    );
    render(<AdminPage me={ADMIN} multiUser />);
    expect(await screen.findByText(/Xin cấp token lúc/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Từ chối" }));
    const dialog = screen.getByRole("dialog", { name: "Từ chối yêu cầu xin token của lanng?" });
    expect(within(dialog).getByText(/không bị đổi/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Từ chối" }));
    await waitFor(() => expect(posts(fn)).toEqual(["/api/admin/users/kc-1/gateway-token/reject"]));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(); // 204 không bị coi là lỗi
  });

  it("sửa: điền sẵn, gửi PUT đúng dữ liệu; email trùng báo rõ", async () => {
    let status = 200;
    const fn = mock(
      (url, init) =>
        url === "/api/admin/users/kc-1" && init?.method === "PUT" ? json({ ...LAN, detail: "raw" }, status) : null,
      [LAN],
    );
    render(<AdminPage me={ADMIN} multiUser />);
    await userEvent.click(await screen.findByRole("button", { name: "Sửa" }));
    const dialog = screen.getByRole("dialog", { name: "Sửa thông tin lanng" });
    const email = within(dialog).getByLabelText(/Email/);
    expect(email).toHaveValue("lan@example.com");
    expect(within(dialog).getByLabelText(/^Tên\*?$/)).toHaveValue("Lan");
    expect(within(dialog).getByLabelText(/^Họ\*?$/)).toHaveValue("Nguyen");
    status = 409;
    await userEvent.clear(email);
    await userEvent.type(email, "minh@example.com");
    await userEvent.click(within(dialog).getByRole("button", { name: "Lưu" }));
    expect(await within(dialog).findByText("Email này đã có người dùng.")).toBeInTheDocument();
    expect(screen.queryByText(/raw/)).not.toBeInTheDocument();
    status = 200;
    await userEvent.click(within(dialog).getByRole("button", { name: "Lưu" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const puts = fn.mock.calls.filter(([, i]) => (i as RequestInit)?.method === "PUT");
    expect(JSON.parse(String((puts[1][1] as RequestInit).body))).toEqual({
      email: "minh@example.com", first_name: "Lan", last_name: "Nguyen",
    });
  });

  it("xóa: cần xác nhận; backend từ chối (409) thì báo lý do", async () => {
    let status = 409;
    const fn = mock(
      (url, init) =>
        url === "/api/admin/users/kc-1" && init?.method === "DELETE"
          ? json({ sub: "kc-1", sessions_revoked: 0, tokens_revoked: 1, keycloak_synced: true }, status)
          : null,
      [LAN],
    );
    render(<AdminPage me={ADMIN} multiUser />);
    await userEvent.click(await screen.findByRole("button", { name: "Xóa" }));
    expect(calls(fn, "DELETE")).toEqual([]);
    let dialog = screen.getByRole("dialog", { name: "Xóa người dùng lanng?" });
    expect(within(dialog).getByText(/Không hoàn tác được/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Xóa người dùng" }));
    expect(await screen.findByText(/Gateway đang kết nối/)).toBeInTheDocument();
    status = 200;
    await userEvent.click(screen.getByRole("button", { name: "Xóa" }));
    dialog = screen.getByRole("dialog", { name: "Xóa người dùng lanng?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Xóa người dùng" }));
    await waitFor(() => expect(calls(fn, "DELETE")).toHaveLength(2));
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
