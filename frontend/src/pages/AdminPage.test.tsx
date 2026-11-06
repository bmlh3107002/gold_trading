import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdminPage } from "./AdminPage";
import { Sidebar } from "../components/layout/Sidebar";
import { json, makeMe } from "../test/fixtures";

const PW = "TamThoi12345xyz";

function mock(res: () => Response) {
  const fn = vi.fn(async () => res());
  vi.stubGlobal("fetch", fn);
  return fn;
}

async function fill(pw = PW, confirm = PW) {
  await userEvent.type(screen.getByLabelText(/Tên đăng nhập/), "lanng");
  await userEvent.type(screen.getByLabelText(/Email/), "lan@example.com");
  await userEvent.type(screen.getByLabelText(/^Họ\*?$/), "Nguyen");
  await userEvent.type(screen.getByLabelText(/^Tên\*?$/), "Lan");
  await userEvent.type(screen.getByLabelText(/^Mật khẩu tạm/), pw);
  await userEvent.type(screen.getByLabelText(/Nhập lại mật khẩu/), confirm);
}

afterEach(() => vi.unstubAllGlobals());

describe("Trang Quản trị", () => {
  it("người không phải ADMIN: không có form, không gọi API", () => {
    const fn = mock(() => json({}));
    render(<AdminPage me={makeMe({ is_admin: false })} multiUser onUserCreated={() => {}} />);
    expect(screen.getByText("Bạn không có quyền xem trang này")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tạo người dùng" })).not.toBeInTheDocument();
    expect(fn).not.toHaveBeenCalled();
  });

  it("ADMIN tạo người dùng: gửi đúng dữ liệu, báo thành công, xóa mật khẩu khỏi form", async () => {
    const fn = mock(() =>
      json({ sub: "kc-1", username: "lanng", email: "lan@example.com", display_name: "Lan Nguyen",
             account_id: "u-lanng", account_name: "Tài khoản của Lan Nguyen" }, 201),
    );
    const onCreated = vi.fn();
    render(<AdminPage me={makeMe({ is_admin: true })} multiUser onUserCreated={onCreated} />);
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Tạo người dùng" }));
    expect(await screen.findByText("Đã tạo người dùng lanng")).toBeInTheDocument();
    const [url, init] = fn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/admin/users");
    expect(JSON.parse(String(init.body))).toEqual({
      username: "lanng", email: "lan@example.com", first_name: "Lan", last_name: "Nguyen",
      password: PW, account_name: null,
    });
    expect(onCreated).toHaveBeenCalled();
    expect(screen.getByLabelText(/^Mật khẩu tạm/)).toHaveValue("");
    expect(screen.getByLabelText(/Tên đăng nhập/)).toHaveValue("");
  });

  it("mật khẩu ngắn hoặc nhập lại sai: không gửi", async () => {
    const fn = mock(() => json({}, 201));
    render(<AdminPage me={makeMe({ is_admin: true })} multiUser onUserCreated={() => {}} />);
    await fill("ngan123", "ngan123");
    await userEvent.click(screen.getByRole("button", { name: "Tạo người dùng" }));
    expect(screen.getByText("Mật khẩu tạm cần ít nhất 12 ký tự.")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText(/^Mật khẩu tạm/));
    await userEvent.type(screen.getByLabelText(/^Mật khẩu tạm/), PW);
    await userEvent.click(screen.getByRole("button", { name: "Tạo người dùng" }));
    expect(screen.getByText("Hai lần nhập mật khẩu không khớp.")).toBeInTheDocument();
    expect(fn).not.toHaveBeenCalled();
  });

  it("trùng tên/email và Keycloak chưa cho phép: thông báo thân thiện, không hiện lỗi thô", async () => {
    let status = 409;
    mock(() => json({ detail: "raw keycloak" }, status));
    render(<AdminPage me={makeMe({ is_admin: true })} multiUser onUserCreated={() => {}} />);
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Tạo người dùng" }));
    expect(await screen.findByText("Tên đăng nhập hoặc email đã có.")).toBeInTheDocument();
    status = 503;
    await userEvent.type(screen.getByLabelText(/^Mật khẩu tạm/), PW);
    await userEvent.type(screen.getByLabelText(/Nhập lại mật khẩu/), PW);
    await userEvent.click(screen.getByRole("button", { name: "Tạo người dùng" }));
    await waitFor(() => expect(screen.getByText(/sync-client\.sh/)).toBeInTheDocument());
    expect(screen.queryByText(/raw keycloak/)).not.toBeInTheDocument();
  });

  it("chưa bật nhiều người dùng: cảnh báo và khóa nút", async () => {
    mock(() => json({}));
    render(<AdminPage me={makeMe({ is_admin: true })} multiUser={false} onUserCreated={() => {}} />);
    await fill();
    expect(screen.getByText(/GT_MULTI_USER_ENABLED=1/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tạo người dùng" })).toBeDisabled();
  });
});

describe("Menu Quản trị", () => {
  const base = { open: false, onClose: () => {}, connection: "live" as const, version: "0.1", storage: "postgres",
                 route: "overview" as const, gateway: null };
  it("chỉ hiện với ADMIN", () => {
    const { rerender } = render(<Sidebar {...base} isAdmin={false} />);
    expect(screen.queryByRole("link", { name: "Quản trị" })).not.toBeInTheDocument();
    rerender(<Sidebar {...base} isAdmin />);
    expect(screen.getByRole("link", { name: "Quản trị" })).toHaveAttribute("href", "#admin");
  });
});
