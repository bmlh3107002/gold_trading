"""Báo cáo khả thi (GĐ5 bước 8a — RPF-02, RPF-03, RPF-04). Thiết kế 37 mục 2.

"Với vốn, sàn và biến động **thật** hiện nay, chiến lược v1 có vào được lệnh trong mức rủi ro đã
chọn không?" Cùng công thức Risk (``sizing.size``, ``swap_night_cost``) + tham số chiến lược v1
(SL 1,5 ATR, TP 2 × SL, đóng 16:45 NY) — không có công thức thứ hai.

Hàm thuần ``compute``: thiếu đầu vào → ``KHONG_DU_DU_LIEU`` + danh sách thiếu (không đoán).
Dữ liệu mẫu → ``CHI_MINH_HOA`` (không bao giờ ``KHA_THI``). Chỉ đọc, không dẫn tới quyết định nào.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from gold_trading.common.enums import Side
from gold_trading.risk.engine import swap_night_cost, swap_nights_next
from gold_trading.risk.sizing import SizingSpec, dec, size
from gold_trading.storage.risk_profiles import RISK_PER_TRADE_MAX, RISK_PER_TRADE_MIN
from gold_trading.strategy.trend_m15 import V1, Params

Status = Literal["OK", "KHONG_DU_DU_LIEU", "CHI_MINH_HOA"]
Verdict = Literal["KHA_THI", "KHONG_KHA_THI", "CHI_MINH_HOA"]
SPEC_KEYS = ("contract_size", "volume_min", "volume_max", "volume_step", "point", "swap_mode",
             "swap_long", "swap_short", "swap_rollover3days")
MIN_RR = Decimal("1.5")      # H2 — chỉ để cảnh báo trong báo cáo (Risk đọc hồ sơ lúc quyết)


@dataclass(frozen=True)
class Inputs:
    now: datetime
    is_sample: bool
    equity: Decimal | None              # equity dùng (min MT5, paper nếu đã bắt đầu)
    equity_note: str                    # nguồn equity (nhịp tim / bản theo giờ …)
    spec: dict | None                   # thông số broker spec_at
    atr: Decimal | None                 # ATR14 M15 từ output Technical thật
    atr_as_of: datetime | None
    spread_points: int | None           # giây giá mới nhất (None → dùng p95)
    baseline_points: int | None         # p95 30 ngày
    commission: Decimal | None
    profile_risk: Decimal | None        # mức / lệnh của hồ sơ (None → tính cả 0,25 % và 0,5 %)
    min_reward_risk: Decimal | None = None
    day_reset_tz: str = "America/New_York"
    day_reset_time: str = "17:00"


class Level(BaseModel):
    risk_fraction: Decimal = Field(description="Mức rủi ro / lệnh (0,0025 = 0,25 %)")
    risk_money: Decimal
    lots: Decimal = Field(description="Lot làm tròn xuống; 0 khi không đủ lot tối thiểu")
    risk_amount: Decimal
    min_equity: Decimal = Field(description="Vốn tối thiểu để lot nhỏ nhất nằm trong mức này")
    shortfall: Decimal | None = Field(default=None, description="Tiền còn thiếu (không khả thi)")
    verdict: Verdict


class FeasibilityReport(BaseModel):
    status: Status
    is_sample: bool
    label: str | None = Field(default=None, description="'CHỈ MINH HỌA — dữ liệu mẫu' khi SAMPLE")
    missing: list[str] = []
    as_of: datetime
    equity: Decimal | None = None
    equity_note: str = ""
    atr: Decimal | None = None
    atr_as_of: datetime | None = None
    sl_distance: Decimal | None = None
    tp_distance: Decimal | None = None
    spread: Decimal | None = None
    spread_note: str = ""
    slippage: Decimal | None = None
    commission_per_lot: Decimal | None = None
    swap_per_lot: Decimal | None = None
    risk_per_lot: Decimal | None = None
    min_lot: Decimal | None = None
    min_lot_risk: Decimal | None = Field(default=None, description="Rủi ro của lot nhỏ nhất")
    min_lot_risk_pct: Decimal | None = Field(default=None, description="… theo % vốn")
    reward_risk: Decimal | None = Field(default=None, description="R:R sau chi phí với TP = 2 × SL")
    max_hold: str = Field(default="", description="Giữ lệnh tối đa (đóng 16:45 New York)")
    levels: list[Level] = []
    warnings: list[str] = []
    strategy: str = ""


def _max_hold(p: Params) -> str:
    start = datetime.combine(datetime(2000, 1, 3).date(), p.session_start)
    end = datetime.combine(start.date(), p.close_at)
    mins = int((end - start) / timedelta(minutes=1))
    return f"{mins // 60} giờ {mins % 60} phút (vào sớm nhất {p.session_start:%H:%M}, đóng " \
           f"{p.close_at:%H:%M} New York)"


def compute(inp: Inputs, p: Params = V1) -> FeasibilityReport:
    from gold_trading.strategy.trend_m15 import STRATEGY_REF

    base = dict(as_of=inp.now, is_sample=inp.is_sample, equity=inp.equity,
                equity_note=inp.equity_note, atr=inp.atr, atr_as_of=inp.atr_as_of,
                max_hold=_max_hold(p), strategy=STRATEGY_REF,
                label="CHỈ MINH HỌA — dữ liệu mẫu" if inp.is_sample else None)
    missing: list[str] = []
    if inp.equity is None or inp.equity <= 0:
        missing.append("EQUITY")
    s = inp.spec or {}
    for k in SPEC_KEYS:
        if s.get(k) is None:
            missing.append(f"BROKER_SPEC:{k}")
    if inp.atr is None or inp.atr <= 0:
        missing.append("ATR_M15")
    if inp.baseline_points is None:
        missing.append("SPREAD_P95_30D")
    if inp.commission is None:
        missing.append("COMMISSION")
    if missing:
        return FeasibilityReport(status="CHI_MINH_HOA" if inp.is_sample else "KHONG_DU_DU_LIEU",
                                 missing=missing, **base)
    assert inp.equity is not None and inp.atr is not None and inp.commission is not None
    assert inp.baseline_points is not None
    cs, point = dec(s["contract_size"]), dec(s["point"])
    spec = SizingSpec(cs, dec(s["volume_min"]), dec(s["volume_max"]), dec(s["volume_step"]))
    if inp.spread_points is not None:
        spread, note = inp.spread_points * point, "spread hiện tại"
    else:
        spread, note = inp.baseline_points * point, "không có giá mới → dùng p95 30 ngày"
    slip = inp.baseline_points * point
    d = p.sl_atr * inp.atr
    nights = swap_nights_next(s, inp.now, inp.day_reset_tz, inp.day_reset_time)
    swap = max(swap_night_cost(s, side, point, cs) for side in (Side.BUY, Side.SELL)) * nights
    costs = inp.commission + swap
    one = size(Decimal(0), d, spread, slip, costs, spec)
    r1 = one.risk_per_lot
    reward = (p.tp_r * d - spread) * cs - costs
    rr = reward / r1
    fractions = ([inp.profile_risk] if inp.profile_risk is not None
                 else [RISK_PER_TRADE_MIN, RISK_PER_TRADE_MAX])
    levels = []
    for f in fractions:
        money = f * inp.equity
        res = size(money, d, spread, slip, costs, spec)
        ok = res.volume > 0
        verdict: Verdict = "CHI_MINH_HOA" if inp.is_sample else (
            "KHA_THI" if ok else "KHONG_KHA_THI")
        levels.append(Level(
            risk_fraction=f, risk_money=money, lots=res.volume, risk_amount=res.risk_amount,
            min_equity=spec.volume_min * r1 / f, shortfall=None if ok else res.shortfall,
            verdict=verdict))
    warnings = []
    need = inp.min_reward_risk or MIN_RR
    if rr < need:
        warnings.append(f"R:R sau chi phí {rr.quantize(Decimal('0.01'))} < {need}: Risk sẽ từ "
                        "chối (REWARD_RISK_TOO_LOW)")
    if inp.atr_as_of is not None and inp.now - inp.atr_as_of > timedelta(days=1):
        warnings.append("ATR cũ hơn 1 ngày — chạy lại khi có nến M15 mới")
    return FeasibilityReport(
        status="CHI_MINH_HOA" if inp.is_sample else "OK", sl_distance=d, tp_distance=p.tp_r * d,
        spread=spread, spread_note=note, slippage=slip, commission_per_lot=inp.commission,
        swap_per_lot=swap, risk_per_lot=r1, min_lot=spec.volume_min,
        min_lot_risk=spec.volume_min * r1,
        min_lot_risk_pct=(spec.volume_min * r1 / inp.equity * 100).quantize(Decimal("0.01")),
        reward_risk=rr.quantize(Decimal("0.0001")), levels=levels, warnings=warnings, **base)



def gather(*, now: datetime, is_sample: bool, equity: Decimal | None, equity_note: str,
           spec: dict | None, technical, quote, minute_rows, commission, profile,
           paper_state) -> Inputs:
    """Ghép số thật đã đọc (bên gọi đọc point-in-time) thành ``Inputs``. Cùng luật Risk:
    equity dùng = min(MT5, paper đã chốt) khi sổ paper đã bắt đầu; giây giá chỉ dùng khi ≤ 10 giây
    và thị trường mở; p95 30 ngày cần đủ phút (``spread_baseline``)."""
    from gold_trading.risk.engine import spread_baseline
    from gold_trading.risk.paper import fresh_quote

    eq, note = equity, equity_note
    if eq is not None and paper_state is not None and paper_state.realized < eq:
        eq, note = paper_state.realized, "equity paper đã chốt (nhỏ hơn MT5)"
    atr = atr_at = None
    if technical is not None:
        atr = dec(technical.output.features["atr14"]) if technical.output.features.get(
            "atr14") is not None else None
        atr_at = technical.output.as_of
    spread = None
    if quote is not None and fresh_quote(quote, now) is None:
        spread = max(quote.spread_points, quote.spread_max_points)
    _, base = spread_baseline(minute_rows, now)
    pv = profile.values if profile is not None else None
    return Inputs(
        now=now, is_sample=is_sample, equity=eq, equity_note=note, spec=spec, atr=atr,
        atr_as_of=atr_at, spread_points=spread, baseline_points=base,
        commission=commission.per_lot if commission is not None else None,
        profile_risk=pv.risk_per_trade if pv is not None else None,
        min_reward_risk=pv.min_reward_risk if pv is not None else None,
        day_reset_tz=pv.day_reset_tz if pv is not None else "America/New_York",
        day_reset_time=pv.day_reset_time if pv is not None else "17:00")


def _pct(f: Decimal) -> str:
    return f"{(f * 100).normalize():f} %".replace(".", ",")


def render(r: FeasibilityReport) -> list[str]:
    """Báo cáo tiếng Việt cho ``cli kha-thi``."""
    out = []
    if r.label:
        out.append(f"*** {r.label} — không dùng để quyết định ***")
    out.append(f"Báo cáo khả thi — chiến lược {r.strategy} — lúc {r.as_of:%Y-%m-%d %H:%M} UTC")
    if r.missing:
        out.append("KHÔNG ĐỦ DỮ LIỆU — thiếu: " + ", ".join(r.missing))
        return out
    out += [
        f"Vốn dùng để tính: {r.equity} USD ({r.equity_note})",
        f"ATR14 M15 đo thật: {r.atr} (lúc {r.atr_as_of:%Y-%m-%d %H:%M} UTC)"
        if r.atr_as_of else f"ATR14 M15: {r.atr}",
        f"Cắt lỗ (1,5 ATR): {r.sl_distance} · chốt lời (2 × SL): {r.tp_distance}",
        f"Spread: {r.spread} ({r.spread_note}) · đệm trượt giá p95 30 ngày: {r.slippage}",
        f"Phí / lot: {r.commission_per_lot} USD · swap một đêm / lot: {r.swap_per_lot} USD",
        f"Rủi ro thật / 1 lot (gồm chi phí): {r.risk_per_lot} USD",
        f"Lot nhỏ nhất {r.min_lot} → rủi ro {r.min_lot_risk} USD = {r.min_lot_risk_pct} % vốn",
        f"R:R sau chi phí: {r.reward_risk}",
        f"Giữ lệnh tối đa: {r.max_hold}",
    ]
    for lv in r.levels:
        if lv.verdict == "KHA_THI":
            out.append(f"Mức {_pct(lv.risk_fraction)}: KHẢ THI — {lv.lots} lot, rủi ro thật "
                       f"{lv.risk_amount} USD (cho phép {lv.risk_money})")
        elif lv.verdict == "KHONG_KHA_THI":
            out.append(f"Mức {_pct(lv.risk_fraction)}: KHÔNG KHẢ THI — thiếu {lv.shortfall} USD; "
                       f"vốn tối thiểu {lv.min_equity.quantize(Decimal('0.01'))} USD")
        else:
            out.append(f"Mức {_pct(lv.risk_fraction)}: chỉ minh họa — {lv.lots} lot")
    out += [f"Cảnh báo: {w}" for w in r.warnings]
    return out
