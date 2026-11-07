import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AccountPage } from "./AccountPage";
import { json, makeAccount } from "../test/fixtures";

const ACC = "/api/accounts/default";
const BASE = { has_token: true, legacy_token_active: false, price_feed: true, request_status: "NONE", requested_at: null };

function mock(info: unknown, after: unknown = info, requestStatus = 200) {
  let current = info;
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === `${ACC}/gateway/token` && init?.method !== "POST") return json(current);
    if (url === `${ACC}/gateway/token-request` && init?.method === "POST") {
      if (requestStatus !== 200) return json({}, requestStatus);
      current = after;
      return json(after);
    }
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const posts = (fn: ReturnType<typeof mock>) =>
  fn.mock.calls.filter(([, i]) => (i as RequestInit | undefined)?.method === "POST").map(([u]) => String(u));

afterEach(() => vi.unstubAllGlobals());

describe("Trang Tài khoản (USER, DEC-17)", () => {
  it("không thấy token; chỉ có nút xin cấp lại, không có mục thành viên", async () => {
    const fn = mock(BASE);
    render(<AccountPage account={makeAccount()} />);
    expect(await screen.findByText("Đã có token Gateway.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Xin cấp lại token" })).toBeInTheDocument();
    expect(screen.queryByText(/gtk_/)).not.toBeInTheDocument();
    expect(screen.queryByText("Thành viên")).not.toBeInTheDocument();
    expect(posts(fn)).toEqual([]);
  });

  it("chưa có token: bấm Xin cấp token → chờ quản trị, nút biến mất", async () => {
    const fn = mock(
      { ...BASE, has_token: false, price_feed: false },
      { ...BASE, has_token: false, price_feed: false, request_status: "PENDING", requested_at: "2026-11-07T03:00:00Z" },
    );
    render(<AccountPage account={makeAccount()} />);
    expect(await screen.findByText(/Chưa có token Gateway/)).toBeInTheDocument();
    expect(screen.getByText(/chỉ gửi được nhịp tim/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Xin cấp token" }));
    expect(await screen.findByText(/Đang chờ quản trị cấp token/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Xin cấp/ })).not.toBeInTheDocument();
    expect(posts(fn)).toEqual([`${ACC}/gateway/token-request`]);
  });

  it("bị từ chối: báo rõ và cho xin lại; lỗi gửi thì báo lỗi", async () => {
    mock({ ...BASE, has_token: false, request_status: "REJECTED", requested_at: "2026-11-07T03:00:00Z" }, null, 500);
    render(<AccountPage account={makeAccount()} />);
    expect(await screen.findByText(/Quản trị đã từ chối/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Xin cấp token" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Không gửi được yêu cầu"));
  });

  it("không có tài khoản: thông báo", () => {
    render(<AccountPage account={null} />);
    expect(screen.getByText("Bạn chưa có tài khoản giao dịch nào")).toBeInTheDocument();
  });
});
