import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AccountPage } from "./AccountPage";
import { json, makeAccount } from "../test/fixtures";

const ACC = "/api/accounts/default";

function mock(info: unknown) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
    String(input) === `${ACC}/gateway/token` && init?.method !== "POST" ? json(info) : json({}, 404),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("Trang Tài khoản (USER, DEC-16)", () => {
  it("chỉ xem trạng thái token; không có nút tạo/xoay token, không có mục thành viên", async () => {
    const fn = mock({ has_token: true, legacy_token_active: false, price_feed: true });
    render(<AccountPage account={makeAccount()} />);
    expect(await screen.findByText("Đã có token Gateway.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /token/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Thành viên")).not.toBeInTheDocument();
    expect(fn.mock.calls.every(([, init]) => (init as RequestInit | undefined)?.method !== "POST")).toBe(true);
  });

  it("chưa có token: nhắc nhờ quản trị cấp", async () => {
    mock({ has_token: false, legacy_token_active: false, price_feed: false });
    render(<AccountPage account={makeAccount()} />);
    expect(await screen.findByText(/Nhờ quản trị hệ thống cấp/)).toBeInTheDocument();
    expect(screen.getByText(/chỉ gửi được nhịp tim/)).toBeInTheDocument();
  });

  it("không có tài khoản: thông báo", () => {
    render(<AccountPage account={null} />);
    expect(screen.getByText("Bạn chưa có tài khoản giao dịch nào")).toBeInTheDocument();
  });
});
