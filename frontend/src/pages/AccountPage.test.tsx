import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AccountPage } from "./AccountPage";
import { json, makeAccount, makeMe } from "../test/fixtures";

const ACC = "/api/accounts/default";
const MEMBERS = [
  { sub: "sub-admin", username: "admin", email: "a@x", display_name: null, role: "OWNER", granted_at: "2026-11-06T03:00:00Z", granted_by: "bootstrap" },
];

function mock(extra: (url: string, init?: RequestInit) => Response | null = () => null) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const r = extra(url, init);
    if (r) return r;
    if (url === `${ACC}/members`) return json(MEMBERS);
    if (url === `${ACC}/gateway/token` && init?.method !== "POST")
      return json({ has_token: false, legacy_token_active: true, price_feed: true });
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("Trang Tài khoản", () => {
  it("tạo token Gateway: cần xác nhận, token chỉ hiện trong hộp thoại", async () => {
    const fn = mock((url, init) =>
      url === `${ACC}/gateway/token` && init?.method === "POST"
        ? json({ token_id: "gtk_1", token: "gtk_SECRETVALUE", created_at: "2026-11-06T03:00:00Z" })
        : null,
    );
    render(<AccountPage account={makeAccount()} me={makeMe()} />);
    expect(await screen.findByText(/Token cũ trong file .env/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Tạo token Gateway" }));
    expect(fn).not.toHaveBeenCalledWith(`${ACC}/gateway/token`, expect.objectContaining({ method: "POST" }));
    const confirm = screen.getByRole("dialog", { name: "Tạo token Gateway mới?" });
    await userEvent.click(within(confirm).getByRole("button", { name: "Tạo token mới" }));
    const dialog = await screen.findByRole("dialog", { name: "Token Gateway mới" });
    expect(within(dialog).getByText("gtk_SECRETVALUE")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Tôi đã lưu token" }));
    await waitFor(() => expect(screen.queryByText("gtk_SECRETVALUE")).not.toBeInTheDocument());
  });

  it("VIEWER: không có nút thêm thành viên, đổi vai trò hay xoay token", async () => {
    mock();
    render(<AccountPage account={makeAccount({ role: "VIEWER", permissions: ["VIEW"] })} me={makeMe()} />);
    expect(await screen.findByText("admin")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Thêm" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /token Gateway/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("thêm thành viên bị từ chối (chưa nhận người thứ hai): hiện thông báo thân thiện", async () => {
    mock((url, init) =>
      url === `${ACC}/members` && init?.method === "POST" ? json({ detail: "raw DEC-12" }, 409) : null,
    );
    render(<AccountPage account={makeAccount()} me={makeMe()} />);
    await userEvent.type(await screen.findByLabelText(/Thêm người dùng/), "bob");
    await userEvent.click(screen.getByRole("button", { name: "Thêm" }));
    expect(await screen.findByText(/chưa nhận người dùng thứ hai/)).toBeInTheDocument();
    expect(screen.queryByText("raw DEC-12")).not.toBeInTheDocument();
  });
});
