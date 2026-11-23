"""Walk-forward trên phần phát triển + chạy đoạn để dành (GĐ6 bước 7 — protocol-1 mục 3–4;
thiết kế 39 mục 10; 6-C04).

- **Phần phát triển:** mỗi tổ hợp của lưới chạy **liền một mạch** trên phần phát triển (một sổ,
  một lần mô phỏng / tổ hợp). Kết quả "học" và "kiểm" của từng vòng là **lát cắt theo thời gian
  mở lệnh** của lần chạy đó (lệnh luôn đóng trong ngày, ranh giới vòng là 17:00 NY → không lệnh
  nào vắt qua ranh giới). Mỗi vòng chọn tổ hợp bằng ``select_combo`` trên lát học, lấy lát kiểm
  của tổ hợp được chọn → ghép = **ngoài mẫu**. Cùng 27 lần chạy cho bảng "mọi tổ hợp", PBO, DSR.
- **Chặn đọc đoạn để dành:** ``walk_forward`` từ chối (``HoldoutLeak``) nếu nhận bất kỳ nến hay
  MarketView nào sau ranh giới — bên gọi phải ``cut`` dữ liệu trước. Dữ liệu khác dấu vân tay lúc
  đăng ký → từ chối.
- **Đoạn để dành:** ``run_holdout`` giành quyền chạy (ghi dòng) **trước**, rồi chạy đúng một tổ
  hợp (``holdout_combo``) trên [ranh giới, hết dữ liệu] với sổ mới.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from gold_trading.backtest import stats as S
from gold_trading.backtest.metrics import Trade, trades_of
from gold_trading.backtest.protocol import (
    Combo,
    LearnResult,
    Split,
    Window,
    grid,
    holdout_combo,
    select_combo,
)
from gold_trading.backtest.registry import (
    Registration,
    RegistryError,
    RegistryStore,
    check_grid,
    data_fingerprint,
)
from gold_trading.backtest.simulate import (
    Bars,
    HistoricalView,
    HistoricalViews,
    SimConfig,
    SimResult,
    simulate,
)


class HoldoutLeak(RegistryError):
    """Có dữ liệu sau ranh giới để dành trong lần chạy phần phát triển."""


def fingerprint_of(bars: Bars, chain: Sequence[HistoricalView]) -> str:
    rows = (f"B|{b.open_time.isoformat()}|{b.open}|{b.high}|{b.low}|{b.close}|{b.spread_points}"
            for b in bars.bars)
    vrows = (f"V|{v.computed_at.isoformat()}|{v.view.market_view_id}" for v in chain)
    return data_fingerprint([*rows, *vrows])


def cut(bars: Bars, chain: Sequence[HistoricalView], dev_end: datetime
        ) -> tuple[Bars, list[HistoricalView]]:
    """Dữ liệu cho phần phát triển: nến **đã đóng** tới ``dev_end``, MarketView có tới
    ``dev_end``."""
    return (Bars([b for b in bars.bars if b.close_time <= dev_end]),
            [v for v in chain if v.computed_at <= dev_end])


def _guard(r: Registration, bars: Bars, chain: Sequence[HistoricalView]) -> None:
    if bars.bars and bars.bars[-1].close_time > r.dev_end:
        raise HoldoutLeak("có nến sau ranh giới để dành")
    if any(v.computed_at > r.dev_end for v in chain):
        raise HoldoutLeak("có MarketView sau ranh giới để dành")


def _slice(trades: Sequence[Trade], lo: datetime, hi: datetime) -> list[Trade]:
    return [t for t in trades if lo <= t.opened_at < hi]


def learn_result(trades: Sequence[Trade]) -> LearnResult:
    return LearnResult(len(trades), S.mean([t.r for t in trades]))


@dataclass(frozen=True)
class Round:
    window: Window
    learn: dict[Combo, LearnResult]
    chosen: Combo | None
    oos: list[Trade]                          # lát kiểm của tổ hợp được chọn ([] nếu None)


@dataclass(frozen=True)
class DevResult:
    registration_id: str
    per_combo: dict[Combo, SimResult]          # mọi tổ hợp, cả phần phát triển (báo cáo + PBO)
    trades: dict[Combo, list[Trade]]
    rounds: list[Round]

    @property
    def oos_trades(self) -> list[Trade]:
        return [t for r in self.rounds for t in r.oos]

    @property
    def chosen(self) -> list[Combo | None]:
        return [r.chosen for r in self.rounds]


def walk_forward(r: Registration, split: Split, bars: Bars, chain: Sequence[HistoricalView],
                 views_for: Callable[[Sequence[HistoricalView]], HistoricalViews],
                 base: SimConfig, *, full_fingerprint: str,
                 regimes: dict[str, str] | None = None) -> DevResult:
    """``bars`` / ``chain`` phải đã ``cut`` ở ``r.dev_end``. ``full_fingerprint`` = dấu vân tay
    của **toàn bộ** dữ liệu (tính trước khi cắt) — phải trùng lúc đăng ký."""
    if full_fingerprint != r.data_fingerprint:
        raise RegistryError("dữ liệu khác dữ liệu lúc đăng ký (dấu vân tay)")
    if (split.data_start, split.dev_end, split.data_end) != (r.data_start, r.dev_end,
                                                              r.data_end):
        raise RegistryError("cách chia khác cách chia đã đăng ký")
    _guard(r, bars, chain)
    combos = grid()
    check_grid(r, [c.key for c in combos])
    hv = views_for(chain)
    per: dict[Combo, SimResult] = {}
    trades: dict[Combo, list[Trade]] = {}
    for c in combos:
        res = simulate(bars, hv, replace(base, params=c.params(base.params)), split.data_start,
                       split.dev_end)
        per[c] = res
        trades[c] = trades_of(res, regimes)
    rounds = []
    for w in split.windows:
        learn = {c: learn_result(_slice(trades[c], w.learn_start, w.learn_end)) for c in combos}
        chosen = select_combo(learn)
        oos = _slice(trades[chosen], w.test_start, w.test_end) if chosen is not None else []
        rounds.append(Round(w, learn, chosen, oos))
    return DevResult(r.registration_id, per, trades, rounds)


@dataclass(frozen=True)
class HoldoutResult:
    combo: Combo | None
    result: SimResult | None
    trades: list[Trade]


def run_holdout(store: RegistryStore, r: Registration, dev: DevResult, bars: Bars,
                chain: Sequence[HistoricalView],
                views_for: Callable[[Sequence[HistoricalView]], HistoricalViews],
                base: SimConfig, *, by: str, at: datetime, full_fingerprint: str,
                regimes: dict[str, str] | None = None) -> HoldoutResult:
    """Chạy đoạn để dành **một lần**. Giành quyền (ghi dòng) trước khi chạy → lần hai
    ``HoldoutAlreadyRun``. Không vòng nào chọn được tổ hợp → vẫn ghi (combo ``NONE``), không
    chạy."""
    if full_fingerprint != r.data_fingerprint:
        raise RegistryError("dữ liệu khác dữ liệu lúc đăng ký (dấu vân tay)")
    if dev.registration_id != r.registration_id:
        raise RegistryError("kết quả phát triển không thuộc đăng ký này")
    combo = holdout_combo(dev.chosen)
    store.claim_holdout(r.registration_id, combo.key if combo else "NONE", by=by, at=at)
    if combo is None:
        return HoldoutResult(None, None, [])
    res = simulate(bars, views_for(chain), replace(base, params=combo.params(base.params)),
                   r.dev_end, r.data_end)
    return HoldoutResult(combo, res, trades_of(res, regimes))
