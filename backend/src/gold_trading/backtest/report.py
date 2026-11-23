"""Báo cáo backtest GĐ6 (BT-03, BT-04, 6-C04, 6-C05) — Markdown, tiếng Việt.

Đủ mục 9 của ``protocol-1`` (thiết kế 38): giả định chi phí; khoảng dữ liệu + chỗ thiếu; phiên bản
mọi thành phần; số lần thử thật; bias còn lại; kết quả **mọi** tổ hợp (tổ hợp hiện tại riêng);
ĐẠT / KHÔNG ĐẠT từng T1–T8; kết luận. Kèm cảnh báo quá khớp (6-C04).

Không bao giờ dùng chữ "xác suất thắng" / "độ tin cậy dự báo" (test khẳng định).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from gold_trading.backtest.evaluation import (
    T1_MIN_OOS_TRADES,
    T5_MAX_PBO,
    Evaluation,
    Inputs,
)
from gold_trading.backtest.metrics import Summary
from gold_trading.backtest.protocol import PROTOCOL_ID, Combo, current_combo
from gold_trading.backtest.registry import Registration

# Thiết kế 39 mục 8 — in nguyên trong mọi báo cáo.
KNOWN_BIASES = (
    "Bảng ngày lễ chỉ phủ 2024–2027: dữ liệu năm khác bị chặn hết (an toàn, phí dữ liệu).",
    "Spread nến MT5 có thể thấp hơn spread thật trung bình (một số / nến).",
    "Đệm trượt giá = p95 spread nến 30 ngày — proxy, không phải trượt giá đo được.",
    "Không có giây giá: SL / TP dò theo high / low nến, cùng nến chạm cả hai → SL; hòa vốn chỉ "
    "xét ở giá mở nến kế tiếp.",
    "Thông số broker hiện hành dùng cho cả quá khứ.",
    "Lịch kinh tế quá khứ dựng lại (giả định thời điểm biết lịch).",
    "Không có tin tức (News) lịch sử → độ tin cậy MarketView × 0,9 so với lúc chạy thật.",
    "Chỉ số USD (Macro) có / không tùy dữ liệu 6 cặp tiền.",
    "Khớp đủ khối lượng; độ trễ cố định (giá mở nến kế tiếp); không mô phỏng mất kết nối.",
    "Dữ liệu sàn demo — giá / spread có thể khác sàn thật.",
    "Walk-forward theo lát cắt: đầu mỗi đoạn kiểm, tài khoản mô phỏng mang trạng thái (equity, "
    "chuỗi thua, đang dừng) của chính tổ hợp đó từ đầu phần phát triển.",
)
BANNED_WORDS = ("xác suất thắng", "độ tin cậy dự báo")


@dataclass(frozen=True)
class ReportContext:
    registration: Registration
    n_trials: int
    extra_trials: Sequence[str]
    versions: Mapping[str, str]                 # thành phần → phiên bản
    costs: Mapping[str, str]                    # giả định chi phí (đọc từ SimConfig)
    data_gaps: Sequence[str]                    # chỗ thiếu dữ liệu (đã liệt kê ở bước 2)
    combos: Mapping[Combo, Summary]             # mọi tổ hợp — phần phát triển
    chosen: Sequence[Combo | None]              # tổ hợp được chọn từng vòng
    holdout_combo: Combo | None = None
    random_median_trades: float | None = None
    random_draws: int | None = None
    no_filter: Summary | None = None
    buy_hold_pct: float | None = None
    extra_bias: Sequence[str] = field(default_factory=tuple)


def warnings(ev: Evaluation, x: Inputs, ctx: ReportContext) -> list[str]:
    """Cảnh báo quá khớp / dữ liệu (6-C04). Rỗng không có nghĩa là đạt."""
    out = []
    if ev.sample:
        out.append("Dữ liệu MẪU (SAMPLE): báo cáo không có giá trị đánh giá.")
    if ctx.extra_trials:
        out.append(f"Đã thử thêm {len(ctx.extra_trials)} lần ngoài lưới — đã cộng vào số lần thử "
                   f"({ctx.n_trials}).")
    if x.pbo is not None and x.pbo > T5_MAX_PBO:
        out.append(f"PBO = {x.pbo:.2f} > {T5_MAX_PBO}: nhiều khả năng chọn tổ hợp do may mắn.")
    if len(x.oos_trades) < T1_MIN_OOS_TRADES:
        out.append(f"Chỉ {len(x.oos_trades)} lệnh ngoài mẫu (< {T1_MIN_OOS_TRADES}): kết quả "
                   "rất nhiễu.")
    if not x.holdout_ran:
        out.append("Đoạn để dành CHƯA chạy — T1 / T7 chưa chấm được.")
    if any(c is None for c in ctx.chosen):
        out.append("Có vòng walk-forward không tổ hợp nào đủ 30 lệnh học → đoạn kiểm đó không "
                   "giao dịch.")
    if len({c for c in ctx.chosen if c is not None}) > 1:
        out.append("Tổ hợp được chọn thay đổi giữa các vòng — tham số không ổn định.")
    return out


def _n(x: float | None, nd: int = 3, pct: bool = False) -> str:
    if x is None:
        return "—"
    return f"{x:.{nd}%}" if pct else f"{x:.{nd}f}"


def _summary_row(name: str, s: Summary) -> str:
    return (f"| {name} | {s.n} | {_n(s.win_rate, 1, True)} | {_n(s.expectancy_r)} | "
            f"{_n(s.profit_factor, 2)} | {_n(s.max_drawdown, 2, True)} | "
            f"{s.longest_losing_streak} | {s.h4_count} / {s.h6_count} | {s.total_pnl} |")


HEAD = ("| Tổ hợp | Lệnh | Lệnh lãi | Kỳ vọng (R) | Hệ số LN | Sụt giảm | Chuỗi thua | "
        "Dừng H4 / H6 | Lãi ròng (USD) |\n|---|---|---|---|---|---|---|---|---|")


def render(ev: Evaluation, x: Inputs, ctx: ReportContext) -> str:
    r = ctx.registration
    cur = current_combo()
    L: list[str] = []
    L.append(f"# Báo cáo backtest GĐ6 — {r.strategy_ref} — {PROTOCOL_ID}")
    L.append("")
    L.append(f"**KẾT LUẬN: {ev.conclusion}**")
    L.append("")
    if ev.sample:
        L.append("> ⚠️ DỮ LIỆU MẪU — báo cáo **không có giá trị đánh giá**.")
        L.append("")
    L.append("Đây là kết quả **quá khứ** dưới các giả định bên dưới, không phải dự báo.")
    L.append("")
    L.append("## 1. Tiêu chí ĐẠT (protocol-1 mục 7)")
    L.append("")
    L.append("| # | Tiêu chí | Số đo | Kết quả |\n|---|---|---|---|")
    for c in ev.criteria:
        L.append(f"| {c.code} | {c.rule} | {c.value} | {'ĐẠT' if c.passed else 'KHÔNG ĐẠT'} |")
    L.append("")
    w = warnings(ev, x, ctx)
    L.append("## 2. Cảnh báo")
    L.append("")
    L += [f"- {s}" for s in w] or ["- (không có)"]
    L.append("")
    L.append("## 3. Đăng ký + dữ liệu")
    L.append("")
    L.append(f"- Mã đăng ký: `{r.registration_id}` (lúc {r.created_at.isoformat()}, bởi "
             f"{r.created_by})")
    L.append(f"- Dữ liệu: {r.data_start.isoformat()} → {r.data_end.isoformat()}; phát triển tới "
             f"{r.dev_end.isoformat()}; để dành từ {r.dev_end.isoformat()}")
    L.append(f"- Dấu vân tay dữ liệu: `{r.data_fingerprint}`")
    L.append(f"- Số lần thử (cho Deflated Sharpe): **{ctx.n_trials}** = lưới {len(r.grid)} + "
             f"thử thêm {len(ctx.extra_trials)}")
    for s in ctx.extra_trials:
        L.append(f"  - thử thêm: {s}")
    L.append("- Chỗ thiếu dữ liệu:" + ("" if ctx.data_gaps else " (không có)"))
    L += [f"  - {g}" for g in ctx.data_gaps]
    L.append("")
    L.append("## 4. Phiên bản + giả định chi phí")
    L.append("")
    L += [f"- {k}: `{v}`" for k, v in sorted(ctx.versions.items())]
    L += [f"- {k}: {v}" for k, v in sorted(ctx.costs.items())]
    L.append("")
    L.append("## 5. Ngoài mẫu (ghép các đoạn kiểm walk-forward)")
    L.append("")
    L += [f"- {k}: {v}" for k, v in ev.numbers.items()]
    rounds = ", ".join(c.key if c else "không chọn" for c in ctx.chosen)
    L.append(f"- Tổ hợp được chọn từng vòng: {rounds}")
    L.append(f"- Tổ hợp cho đoạn để dành: "
             f"{ctx.holdout_combo.key if ctx.holdout_combo else 'không có'}")
    L.append("")
    L.append("## 6. Mốc so sánh")
    L.append("")
    L.append(f"- Mốc ngẫu nhiên: p95 kỳ vọng {_n(x.random_p95_r)}R; số lần bốc "
             f"{ctx.random_draws if ctx.random_draws is not None else '—'}, trung vị số lệnh "
             f"{_n(ctx.random_median_trades, 0)}")
    if ctx.no_filter is not None:
        L.append(HEAD)
        L.append(_summary_row("mốc không lọc (V3–V6)", ctx.no_filter))
    L.append(f"- Tham chiếu (chỉ để đọc): không giao dịch = 0; mua – giữ = "
             f"{_n(ctx.buy_hold_pct, 2, True)}")
    L.append("")
    L.append("## 7. Mọi tổ hợp — phần phát triển (trong mẫu, chỉ để đọc)")
    L.append("")
    L.append(HEAD)
    if cur in ctx.combos:
        L.append(_summary_row(f"**{cur.key} (hiện tại)**", ctx.combos[cur]))
    for c, s in ctx.combos.items():
        if c != cur:
            L.append(_summary_row(c.key, s))
    L.append("")
    L.append("## 8. Sai lệch đã biết (bias còn lại)")
    L.append("")
    L += [f"- {b}" for b in (*KNOWN_BIASES, *ctx.extra_bias)]
    L.append("")
    text = "\n".join(L) + "\n"
    low = text.lower()
    for word in BANNED_WORDS:
        if word in low:
            raise ValueError(f"báo cáo không được dùng chữ '{word}'")
    return text


def costs_of(cfg) -> dict[str, str]:
    """Giả định chi phí từ ``SimConfig`` (để báo cáo ghi đúng số đã chạy)."""
    s = cfg.spec
    return {"Phí / lot (khứ hồi)": f"{cfg.commission_per_lot} USD",
            "Vốn đầu mô phỏng": f"{cfg.capital} USD",
            "Rủi ro / lệnh (H1)": f"{Decimal(cfg.profile.risk_per_trade) * 100}%",
            "Thông số broker": f"cỡ HĐ {s['contract_size']}, point {s['point']}, lot "
                               f"{s['volume_min']}–{s['volume_max']} bước {s['volume_step']}, "
                               f"đòn bẩy {s['leverage']}, swap {s['swap_long']} / "
                               f"{s['swap_short']} (kiểu {s['swap_mode']})",
            "Spread": "spread nến M15 (point); đệm trượt giá = p95 spread nến 30 ngày trước",
            "Khớp": "giá mở nến kế tiếp (BUY ask + đệm, SELL bid − đệm); SL thoát trừ thêm đệm"}
