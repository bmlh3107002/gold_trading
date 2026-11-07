import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AccountPage } from "./AccountPage";
import { json, makeAccount } from "../test/fixtures";

const ACC = "/api/accounts/default";
const BASE = { has_token: true, legacy_token_active: false, price_feed: true, request_status: "NONE", requested_at: null };

const NEVER = { state: "NEVER", last_seen_at: null, age_seconds: null, heartbeat: null };

function mock(info: unknown, after: unknown = info, requestStatus = 200, status: unknown = NEVER) {
  let current = info;
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === `${ACC}/gateway/status`) return json(status);
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

  it("MT-12/GW-09: hiện login, server, số liệu tài khoản đúng như Gateway gửi; thiếu → —", async () => {
    const hb = {
      gateway_id: "win-1", gateway_version: "0.3.0", read_only: true, terminal_connected: true,
      account_type: "DEMO", server: "Broker-Demo", company: "Demo Ltd", server_tz: "Europe/Athens",
      identity: { login: 51234567, server: "Broker-Demo", company: "Demo Ltd", account_type: "DEMO",
        terminal_name: "MetaTrader 5", terminal_path: null },
      account: { currency: "USD", balance: 10000, equity: 10012.5, margin: 0, margin_free: 10012.5,
        margin_level: null, leverage: 100, trade_allowed: true },
      symbol: { broker_symbol: "XAUUSD", digits: 2, point: 0.01, contract_size: 100, volume_min: 0.01,
        volume_max: 100, volume_step: 0.01, stops_level: 10, freeze_level: null, swap_long: -25.3, swap_short: null },
      timeframes: [],
    };
    mock(BASE, BASE, 200, { state: "CONNECTED", last_seen_at: "2026-11-07T03:00:00Z", age_seconds: 1, heartbeat: hb });
    render(<AccountPage account={makeAccount()} />);
    expect(await screen.findByText("51234567")).toBeInTheDocument();
    expect(screen.getByText("Broker-Demo")).toBeInTheDocument();
    expect(screen.getByText("1:100")).toBeInTheDocument();
    expect(screen.getByText("10 / —")).toBeInTheDocument();
    // margin_level null (không có vị thế) → —, không hiện 0%
    const label = screen.getByText("Mức ký quỹ");
    expect(label.nextElementSibling).toHaveTextContent("—");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("tài khoản THẬT: cảnh báo rõ; MT5 chưa đăng nhập: báo không có danh tính", async () => {
    const base = { gateway_id: "w", gateway_version: "0.3.0", read_only: true, terminal_connected: true,
      server_tz: "Europe/Athens", timeframes: [] };
    const real = { ...base, account_type: "REAL", server: "R", identity: { login: 7, server: "R",
      account_type: "REAL" }, account: null, symbol: null };
    mock(BASE, BASE, 200, { state: "CONNECTED", last_seen_at: null, age_seconds: 1, heartbeat: real });
    const { unmount } = render(<AccountPage account={makeAccount()} />);
    expect(await screen.findByText(/TÀI KHOẢN THẬT\. Gateway chỉ đọc/)).toBeInTheDocument();
    unmount();
    const out = { ...base, account_type: "UNKNOWN", server: null, identity: null, account: null, symbol: null };
    mock(BASE, BASE, 200, { state: "CONNECTED", last_seen_at: null, age_seconds: 1, heartbeat: out });
    render(<AccountPage account={makeAccount()} />);
    expect(await screen.findByText(/Chưa thấy danh tính MT5/)).toBeInTheDocument();
    expect(screen.queryByText("Số tài khoản (login)")).not.toBeInTheDocument();
  });

  it("không có tài khoản: thông báo", () => {
    render(<AccountPage account={null} />);
    expect(screen.getByText("Bạn chưa có tài khoản giao dịch nào")).toBeInTheDocument();
  });
});
