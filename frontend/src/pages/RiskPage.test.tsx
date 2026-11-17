import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { pct, reasonText, RiskPage, shiftDecimal } from "./RiskPage";
import { json, makeAccount } from "../test/fixtures";

const R = "/api/accounts/default/risk";

const EMPTY_OV = {
  account_id: "default", is_sample: false, strategy_enabled: true,
  readiness: { profile: false, commission: false, paper_started: false },
  profile: null, profile_history: [], commission: null, commission_history: [],
  paper: { started: false, positions: [], reservations: [], halted: false },
  usage: null, decisions: [], evaluations: [],
};

const FEAS = {
  status: "OK", is_sample: false, label: null, missing: [], as_of: "2026-11-17T10:00:00Z",
  equity: "10000", equity_note: "nhịp tim MT5", atr: "13", atr_as_of: "2026-11-17T09:55:00Z",
  sl_distance: "19.5", tp_distance: "39.0", spread: "0.30", spread_note: "", slippage: "0.40",
  commission_per_lot: "7", swap_per_lot: "0", risk_per_lot: "2027", min_lot: "0.01",
  min_lot_risk: "20.27", min_lot_risk_pct: "0.20", reward_risk: "1.9058", max_hold: "",
  levels: [
    { risk_fraction: "0.0025", risk_money: "25", lots: "0.01", risk_amount: "20.27", min_equity: "8108", shortfall: null, verdict: "KHA_THI" },
    { risk_fraction: "0.005", risk_money: "50", lots: "0", risk_amount: "0", min_equity: "4054", shortfall: "1.5", verdict: "KHONG_KHA_THI" },
  ],
  warnings: [], strategy: "xu-huong-m15@1.0.0",
};

function mock(ov: unknown = EMPTY_OV, feas: unknown = FEAS, status = 200) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "POST") return status === 200 ? json(ov) : json({}, status);
    if (url === `${R}/overview`) return json(ov);
    if (url === `${R}/feasibility`) return json(feas);
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const posts = (fn: ReturnType<typeof mock>) =>
  fn.mock.calls
    .filter(([, i]) => (i as RequestInit | undefined)?.method === "POST")
    .map(([u, i]) => [String(u), JSON.parse(String((i as RequestInit).body))]);

afterEach(() => vi.unstubAllGlobals());

describe("số thập phân chính xác (không qua số thực)", () => {
  it("dời dấu phẩy đúng", () => {
    expect(shiftDecimal("0.0025", 2)).toBe("0.25");
    expect(shiftDecimal("0.35", -2)).toBe("0.0035");      // 0.35 / 100 bằng số thực = 0.0034999…
    expect(shiftDecimal("5", -2)).toBe("0.05");
    expect(shiftDecimal("10.500", 0)).toBe("10.5");
    expect(shiftDecimal("-600.00", 0)).toBe("-600");
    expect(shiftDecimal("0.000000", 2)).toBe("0");
    expect(pct("0.0075")).toBe("0,75");
  });
  it("mã lý do → tiếng Việt, mã lạ giữ nguyên", () => {
    expect(reasonText("COMMISSION_UNKNOWN")).toBe("chưa nhập phí");
    expect(reasonText("RISK_FLAGS:EVENT_WINDOW")).toBe("cờ rủi ro (EVENT_WINDOW)");
    expect(reasonText("ABC_LA")).toBe("ABC_LA");
  });
});

describe("Trang Rủi ro (DSH-05)", () => {
  it("chưa có gì: báo 3 việc cần làm, mọi lệnh bị từ chối", async () => {
    mock();
    render(<RiskPage account={makeAccount()} />);
    expect(await screen.findByText(/Hồ sơ rủi ro: Chưa có/)).toBeInTheDocument();
    expect(screen.getByText(/Phí giao dịch \/ lot: Chưa có/)).toBeInTheDocument();
    expect(screen.getByText(/Bắt đầu sổ paper: Chưa có/)).toBeInTheDocument();
    expect(screen.getByText(/Chưa có hồ sơ rủi ro — mọi lệnh bị từ chối/)).toBeInTheDocument();
  });

  it("tạo hồ sơ: điền sẵn H1–H11, gửi đúng tỷ lệ dạng chuỗi chính xác", async () => {
    const fn = mock();
    render(<RiskPage account={makeAccount()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Tạo phiên bản mới" }));
    const form = within(screen.getByRole("form", { name: "Tạo phiên bản mới" }));
    const risk = form.getByLabelText(/Rủi ro mỗi lệnh/);
    expect(risk).toHaveValue("0.25");
    await userEvent.clear(risk);
    await userEvent.type(risk, "0,35");
    const save = form.getByRole("button", { name: "Lưu" });
    expect(save).toBeDisabled();                                      // cần lý do
    await userEvent.type(form.getByLabelText(/Lý do/), "thử");
    await userEvent.click(save);
    await waitFor(() => expect(posts(fn)).toHaveLength(1));
    const [url, body] = posts(fn)[0];
    expect(url).toBe(`${R}/profile`);
    expect(body.values.risk_per_trade).toBe("0.0035");
    expect(body.values.max_daily_loss).toBe("0.0075");
    expect(body.values.max_trades_per_day).toBe(4);
    expect(body.values.news_hold_policy).toBe("KEEP_SAFE_ONLY");
    expect(body.reason).toBe("thử");
  });

  it("hồ sơ bị backend từ chối → báo lỗi, không đóng biểu mẫu", async () => {
    mock(EMPTY_OV, FEAS, 422);
    render(<RiskPage account={makeAccount()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Tạo phiên bản mới" }));
    const form = within(screen.getByRole("form", { name: "Tạo phiên bản mới" }));
    await userEvent.type(form.getByLabelText(/Lý do/), "x");
    await userEvent.click(form.getByRole("button", { name: "Lưu" }));
    expect(await screen.findByText(/ngoài giới hạn cho phép/)).toBeInTheDocument();
  });

  it("nhập phí: dấu phẩy đổi thành dấu chấm", async () => {
    const fn = mock();
    render(<RiskPage account={makeAccount()} />);
    const form = within(await screen.findByRole("form", { name: "Phí giao dịch" }));
    await userEvent.type(form.getByLabelText(/Phí \/ lot/), "7,5");
    await userEvent.type(form.getByLabelText(/Lý do/), "theo sàn");
    await userEvent.click(form.getByRole("button", { name: "Lưu" }));
    await waitFor(() => expect(posts(fn)).toEqual([[`${R}/commission`, { per_lot: "7.5", reason: "theo sàn" }]]));
  });

  it("bắt đầu sổ paper không cho gõ vốn (lấy equity MT5)", async () => {
    const fn = mock();
    render(<RiskPage account={makeAccount()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Bắt đầu sổ paper" }));
    await waitFor(() => expect(posts(fn)[0][0]).toBe(`${R}/paper/start`));
    expect(Object.keys(posts(fn)[0][1])).toEqual(["reason"]);
  });

  it("đang dừng vì sụt: xác nhận cần đánh dấu + lý do", async () => {
    const ov = { ...EMPTY_OV, readiness: { profile: true, commission: true, paper_started: true },
      paper: { started: true, capital: "10000", realized_equity: "9400", unrealized: "0", peak: "10000",
        drawdown: "0.060000", halted: true, positions: [], reservations: [] } };
    const fn = mock(ov);
    render(<RiskPage account={makeAccount()} />);
    expect(await screen.findByText(/chạm ngưỡng dừng hẳn/)).toBeInTheDocument();
    expect(screen.getByText("6 %")).toBeInTheDocument();
    const form = within(screen.getByRole("form", { name: "Xác nhận sau khi dừng" }));
    const btn = form.getByRole("button", { name: "Xác nhận" });
    expect(btn).toBeDisabled();
    await userEvent.click(form.getByRole("checkbox"));
    await userEvent.type(form.getByLabelText(/Lý do/), "đã xem lại");
    await waitFor(() => expect(btn).toBeEnabled());
    await userEvent.click(btn);
    await waitFor(() => expect(posts(fn)[0]).toEqual([`${R}/paper/drawdown-reset`, { confirm: true, reason: "đã xem lại" }]));
  });

  it("khả thi + hoạt động: số từ chuỗi, lý do tiếng Việt", async () => {
    const ov = { ...EMPTY_OV, decisions: [{ risk_decision_id: "rd1", decided_at: "2026-11-17T10:00:00Z",
      outcome: "REJECTED", reason_codes: ["NO_RISK_PROFILE", "RISK_FLAGS:EVENT_WINDOW"], volume: "0", risk_amount: "0" }] };
    mock(ov);
    render(<RiskPage account={makeAccount()} />);
    expect(await screen.findByText(/Khả thi ở mức 0,25 %: 0,01 lot, rủi ro thật 20,27 USD/)).toBeInTheDocument();
    expect(screen.getByText(/Không khả thi ở mức 0,5 %: thiếu 1,5 USD/)).toBeInTheDocument();
    expect(screen.getByText(/chưa có hồ sơ rủi ro, cờ rủi ro \(EVENT_WINDOW\)/)).toBeInTheDocument();
  });

  it("dữ liệu mẫu: nhãn CHỈ MINH HỌA", async () => {
    mock({ ...EMPTY_OV, is_sample: true },
      { ...FEAS, status: "CHI_MINH_HOA", is_sample: true, label: "CHỈ MINH HỌA — dữ liệu mẫu", missing: ["EQUITY"], levels: [] });
    render(<RiskPage account={makeAccount()} />);
    expect(await screen.findByText("CHỈ MINH HỌA — dữ liệu mẫu")).toBeInTheDocument();
    expect(screen.getByText(/Nguồn giá mẫu/)).toBeInTheDocument();
  });
});
