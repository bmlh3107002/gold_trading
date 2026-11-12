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
    // MT-05: tài khoản không phải tài khoản chính vẫn ghi nến từ MT5 của mình → không còn câu sai này
    expect(screen.queryByText(/chỉ gửi được nhịp tim/)).not.toBeInTheDocument();
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

  it("ING-16: đồng hồ lệch → hiện số giây + hướng dẫn; chưa đo được → không hiện", async () => {
    const hb = {
      gateway_id: "w", gateway_version: "0.9.0", read_only: true, terminal_connected: true,
      account_type: "DEMO", server: "S", company: null, server_tz: "Europe/Athens",
      identity: { login: 1, server: "S", company: null, account_type: "DEMO", terminal_name: null, terminal_path: null },
      timeframes: [],
    };
    const base = { state: "CONNECTED", last_seen_at: "2026-11-07T03:00:00Z", age_seconds: 1, heartbeat: hb };
    mock(BASE, BASE, 200, { ...base, gateway_clock_skew_s: -45.2, gateway_clock: "BAD", mt5_clock_residual_s: 1.2, mt5_clock: "OK" });
    const { unmount } = render(<AccountPage account={makeAccount()} />);
    expect(await screen.findByText("Chậm 45 giây")).toBeInTheDocument();
    expect(screen.getByText("Khớp")).toBeInTheDocument();
    expect(screen.getByText(/Set time automatically/)).toBeInTheDocument();
    unmount();
    vi.unstubAllGlobals();
    mock(BASE, BASE, 200, { ...base, gateway_clock: "UNKNOWN", mt5_clock: "UNKNOWN" });
    render(<AccountPage account={makeAccount()} />);
    expect(await screen.findByText("S")).toBeInTheDocument();
    expect(screen.queryByText("Đồng hồ máy chạy Gateway")).not.toBeInTheDocument();
    expect(screen.queryByText("Khớp")).not.toBeInTheDocument();
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

// ---------- MT-13: liên kết MT5 ----------

const LINK = {
  link_id: "mtl_1", status: "PENDING_CONFIRM", login: 51234567, server: "Broker-Demo", company: "Demo Ltd",
  trade_mode: "DEMO", gateway_id: "win-1", created_at: "2026-11-07T03:00:00Z", verified_at: null,
  verified_by: null, ended_at: null, end_reason: null,
};
const NO_LINK = { current: null, pending: null, terminal_matches_pending: false, history: [] };

function mockLink(state: unknown, after: unknown = state, postStatus = 200) {
  let current = state;
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === `${ACC}/gateway/status`) return json(NEVER);
    if (url === `${ACC}/gateway/token`) return json(BASE);
    if (url === `${ACC}/mt5-link` && init?.method !== "POST") return json(current);
    if (url.startsWith(`${ACC}/mt5-link/`) && init?.method === "POST") {
      if (postStatus !== 200) return json({ detail: "x" }, postStatus);
      current = after;
      return json(after);
    }
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const bodies = (fn: ReturnType<typeof mockLink>) =>
  fn.mock.calls
    .filter(([, i]) => (i as RequestInit | undefined)?.method === "POST")
    .map(([u, i]) => [String(u), JSON.parse(String((i as RequestInit).body))]);

describe("Liên kết MT5 (MT-13)", () => {
  it("chưa liên kết: hướng dẫn, không có nút xác nhận", async () => {
    mockLink(NO_LINK);
    render(<AccountPage account={makeAccount()} />);
    expect(await screen.findByText(/Chưa liên kết\. Mở MT5/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Xác nhận đây là MT5/ })).not.toBeInTheDocument();
  });

  it("chờ xác nhận: phải gõ đúng login mới bấm được; gửi đúng link_id/login/server", async () => {
    const active = { ...NO_LINK, current: { ...LINK, status: "ACTIVE", verified_by: "trader", verified_at: "2026-11-07T03:01:00Z" } };
    const fn = mockLink({ ...NO_LINK, pending: LINK, terminal_matches_pending: true }, active);
    render(<AccountPage account={makeAccount()} />);
    const btn = await screen.findByRole("button", { name: "Xác nhận đây là MT5 của tôi" });
    expect(btn).toBeDisabled();
    const input = screen.getByLabelText(/Gõ lại số login/);
    await userEvent.type(input, "51234568"); // sai một số
    expect(btn).toBeDisabled();
    await userEvent.clear(input);
    await userEvent.type(input, "51234567");
    expect(btn).toBeEnabled();
    await userEvent.click(btn);
    expect(await screen.findByText(/Xác nhận bởi trader/)).toBeInTheDocument();
    expect(bodies(fn)).toEqual([[`${ACC}/mt5-link/confirm`,
      { link_id: "mtl_1", login: 51234567, server: "Broker-Demo", acknowledge_real: false }]]);
  });

  it("terminal không còn đúng MT5: cảnh báo, không bấm được dù gõ đúng", async () => {
    mockLink({ ...NO_LINK, pending: LINK, terminal_matches_pending: false });
    render(<AccountPage account={makeAccount()} />);
    expect(await screen.findByText(/Terminal hiện không còn đăng nhập MT5 này/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Gõ lại số login/), "51234567");
    expect(screen.getByRole("button", { name: "Xác nhận đây là MT5 của tôi" })).toBeDisabled();
  });

  it("tài khoản THẬT: phải đánh dấu đã hiểu; backend từ chối (409) → báo lỗi rõ", async () => {
    const real = { ...LINK, trade_mode: "REAL", server: "Broker-Live" };
    const fn = mockLink({ ...NO_LINK, pending: real, terminal_matches_pending: true }, null, 409);
    render(<AccountPage account={makeAccount()} />);
    await userEvent.type(await screen.findByLabelText(/Gõ lại số login/), "51234567");
    const btn = screen.getByRole("button", { name: "Xác nhận đây là MT5 của tôi" });
    expect(btn).toBeDisabled();
    await userEvent.click(screen.getByLabelText(/TIỀN THẬT/));
    expect(btn).toBeEnabled();
    await userEvent.click(btn);
    expect(await screen.findByText(/MT5 này có thể đã liên kết ở tài khoản khác/)).toBeInTheDocument();
    expect(bodies(fn)[0][1]).toMatchObject({ acknowledge_real: true, server: "Broker-Live" });
  });

  it("đã liên kết: gỡ cần bấm xác nhận lần hai", async () => {
    const active = { ...NO_LINK, current: { ...LINK, status: "ACTIVE", verified_by: "trader", verified_at: "2026-11-07T03:01:00Z" } };
    const fn = mockLink(active, NO_LINK);
    render(<AccountPage account={makeAccount()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Gỡ liên kết" }));
    expect(bodies(fn)).toEqual([]);
    await userEvent.click(screen.getByRole("button", { name: "Có, gỡ liên kết" }));
    expect(await screen.findByText(/Chưa liên kết\. Mở MT5/)).toBeInTheDocument();
    expect(bodies(fn)).toEqual([[`${ACC}/mt5-link/revoke`, { link_id: "mtl_1" }]]);
  });

  it("MT-14 MISMATCH: cảnh báo đỏ có login terminal đang báo; xác minh lại chỉ khi terminal về đúng MT5", async () => {
    const mism = { ...LINK, status: "MISMATCH", verified_by: "trader", verified_at: "2026-11-07T03:01:00Z" };
    const base = { ...NO_LINK, current: mism, current_effective: "MISMATCH",
      terminal: { login: 999, server: "Broker-Demo", trade_mode: "DEMO" }, terminal_matches_current: false };
    const ok = { ...NO_LINK, current: { ...mism, status: "ACTIVE" }, current_effective: "ACTIVE",
      terminal: { login: 51234567, server: "Broker-Demo", trade_mode: "DEMO" }, terminal_matches_current: true };
    const fn = mockLink(base, ok);
    const { unmount } = render(<AccountPage account={makeAccount()} />);
    expect(await screen.findByText(/terminal đang báo login 999/)).toBeInTheDocument();
    expect(screen.getByText(/Terminal chưa báo lại đúng MT5/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Gõ lại số login/), "51234567");
    expect(screen.getByRole("button", { name: "Xác minh lại MT5 này" })).toBeDisabled();
    unmount();
    mockLink({ ...base, terminal: ok.terminal, terminal_matches_current: true }, ok);
    render(<AccountPage account={makeAccount()} />);
    const btn = await screen.findByRole("button", { name: "Xác minh lại MT5 này" });
    await userEvent.type(screen.getByLabelText(/Gõ lại số login/), "51234567");
    expect(btn).toBeEnabled();
    await userEvent.click(btn);
    expect(await screen.findByText(/Đã liên kết · đang liên kết/)).toBeInTheDocument();
    expect(fn.mock.calls.length).toBeGreaterThan(0);
  });

  it("MT-14: ACTIVE nhưng nhịp tim quá hạn → báo mất kết nối, không có nút xác minh lại", async () => {
    const act = { ...LINK, status: "ACTIVE", verified_by: "trader", verified_at: "2026-11-07T03:01:00Z" };
    mockLink({ ...NO_LINK, current: act, current_effective: "DISCONNECTED", terminal: null, terminal_matches_current: false });
    render(<AccountPage account={makeAccount()} />);
    expect(await screen.findByText(/Mất kết nối MT5/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Xác minh lại MT5 này" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Gỡ liên kết" })).toBeInTheDocument();
  });
});
