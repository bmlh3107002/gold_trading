"""GĐ6 bước 8 — chấm T1–T8, báo cáo, 6-C05 (protocol-1 mục 7, 9)."""

from __future__ import annotations

import ast
import pathlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from gold_trading.backtest import evaluation as E
from gold_trading.backtest import report as RP
from gold_trading.backtest.metrics import Trade, summarize
from gold_trading.backtest.protocol import current_combo, grid, make_split
from gold_trading.backtest.registry import new_registration

D = Decimal
T0 = datetime(2025, 3, 3, 14, 0, tzinfo=UTC)


def tr(i, pnl, risk="10", year=2025, regime="TREND", side="BUY"):
    t = datetime(year, 3, 3, 14, 0, tzinfo=UTC) + timedelta(days=i % 300)
    return Trade(f"p{i}", side, t, t + timedelta(hours=1), D(str(pnl)), D(risk), "X", None,
                 regime)


def good_inputs(**kw) -> E.Inputs:
    """200 lệnh ngoài mẫu: 100 thắng +20, 100 thua −10 (R +2 / −1) → kỳ vọng 0,5R, hệ số 2,0;
    lãi chia đều 2 năm × 2 regime; 30 lệnh để dành kỳ vọng 0,5R."""
    oos = [tr(i, 20 if i % 2 == 0 else -10, year=2024 + (i // 2) % 2,
              regime="TREND" if (i // 4) % 2 == 0 else "RANGE") for i in range(200)]
    hold = [tr(i, 20 if i % 2 == 0 else -10) for i in range(30)]
    daily = [(T0 + timedelta(days=i), D(5)) for i in range(400)]
    base = dict(sample=False, oos_trades=oos, oos_daily=daily, capital=D(10_000),
                ci_low_r=0.1, random_p95_r=0.2, dsr=0.97, pbo=0.1, holdout_ran=True,
                holdout_trades=hold)
    return E.Inputs(**(base | kw))


def by_code(ev):
    return {c.code: c for c in ev.criteria}


def test_all_pass_hand_values():
    ev = E.criteria(good_inputs())
    assert [c.code for c in ev.criteria] == [f"T{i}" for i in range(1, 9)]
    assert all(c.passed for c in ev.criteria), [c for c in ev.criteria if not c.passed]
    assert ev.passed and ev.conclusion.startswith("ĐẠT")
    assert ev.numbers["oos_expectancy_r"] == "0.500"
    assert ev.numbers["oos_profit_factor"] == "2.00"


@pytest.mark.parametrize("kw,code", [
    (dict(oos_trades=good_inputs().oos_trades[:199]), "T1"),
    (dict(holdout_trades=good_inputs().holdout_trades[:29]), "T1"),
    (dict(holdout_ran=False, holdout_trades=()), "T1"),
    (dict(ci_low_r=0.0), "T2"),
    (dict(ci_low_r=None), "T2"),
    (dict(random_p95_r=0.5), "T4"),                      # bằng nhau → không vượt
    (dict(random_p95_r=None), "T4"),
    (dict(dsr=0.9499), "T5"),
    (dict(pbo=0.2001), "T5"),
    (dict(dsr=None), "T5"),
    (dict(pbo=None), "T5"),
    (dict(oos_daily=[(T0, D(-500))]), "T6"),               # sụt đúng 5 % → không đạt
    (dict(oos_daily=[]), "T6"),
    (dict(holdout_ran=False, holdout_trades=()), "T7"),
])
def test_each_threshold_fails_at_edge(kw, code):
    ev = E.criteria(good_inputs(**kw))
    assert by_code(ev)[code].passed is False
    assert not ev.passed and "quay lại GĐ5" in ev.conclusion


def test_edges_that_pass():
    assert by_code(E.criteria(good_inputs(dsr=0.95, pbo=0.2)))["T5"].passed
    assert by_code(E.criteria(good_inputs(oos_daily=[(T0, D(-499))])))["T6"].passed  # 4,99 %
    assert by_code(E.criteria(good_inputs(random_p95_r=0.4999)))["T4"].passed


def test_t3_profit_factor_edge():
    # 12 thắng +10, 10 thua −10 … tạo đúng hệ số 1,2: lãi 120 / lỗ 100
    oos = [tr(i, 10) for i in range(12)] + [tr(100 + i, -10) for i in range(10)]
    assert by_code(E.criteria(good_inputs(oos_trades=oos)))["T3"].passed
    oos2 = [tr(i, 10) for i in range(12)] + [tr(100 + i, -10.01) for i in range(10)]
    assert not by_code(E.criteria(good_inputs(oos_trades=oos2)))["T3"].passed


def test_t7_holdout_half_of_oos_edge():
    # ngoài mẫu 0,5R → để dành phải ≥ 0,25R và > 0
    ok = [tr(i, 5) for i in range(30)]                                   # 0,5R
    half = [tr(i, 12.5 if i % 2 == 0 else -7.5) for i in range(30)]      # (1,25 − 0,75)/2 = 0,25R
    low = [tr(i, 12.4 if i % 2 == 0 else -7.5) for i in range(30)]       # 0,245R
    assert by_code(E.criteria(good_inputs(holdout_trades=ok)))["T7"].passed
    assert by_code(E.criteria(good_inputs(holdout_trades=half)))["T7"].passed
    assert not by_code(E.criteria(good_inputs(holdout_trades=low)))["T7"].passed
    neg = [tr(i, -1) for i in range(30)]
    assert not by_code(E.criteria(good_inputs(holdout_trades=neg)))["T7"].passed


def test_t8_concentration_and_no_profit():
    one_year = [replace(t, opened_at=t.opened_at.replace(year=2025)) if t.pnl > 0 else t
                for t in good_inputs().oos_trades]
    ev = E.criteria(good_inputs(oos_trades=one_year))
    assert not by_code(ev)["T8"].passed and "2025" in by_code(ev)["T8"].value
    loss = [tr(i, -1) for i in range(200)]
    assert not by_code(E.criteria(good_inputs(oos_trades=loss)))["T8"].passed
    assert E.share_max(loss, lambda t: t.year) == (None, "tổng lãi ròng ≤ 0")


def test_sample_data_never_passes():
    ev = E.criteria(good_inputs(sample=True))
    assert not ev.passed and all(not c.passed for c in ev.criteria)
    assert all("dữ liệu mẫu" in c.value for c in ev.criteria)


def _ctx(**kw):
    split = make_split(datetime(2024, 1, 2, 23, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC))
    r = new_registration(split, fingerprint="f" * 64, code_version="t", created_by="u",
                         at=datetime(2026, 11, 23, tzinfo=UTC))
    base = dict(registration=r, n_trials=28, extra_trials=["thử ATR 2,5"],
                versions={"chiến lược": "xu-huong-m15@1.0.0", "Risk": "risk-policy-gd5-2"},
                costs={"Phí / lot": "0 USD"}, data_gaps=["2024-07-04: ngày lễ"],
                combos={}, chosen=[current_combo(), grid()[0], None])
    return RP.ReportContext(**(base | kw))


def test_render_has_all_protocol_sections_and_conclusion():
    x = good_inputs(holdout_ran=False, holdout_trades=(), pbo=0.4)
    ev = E.criteria(x)
    text = RP.render(ev, x, _ctx())
    for s in ("KẾT LUẬN: KHÔNG ĐẠT", "quay lại GĐ5", "| T1 |", "| T8 |", "## 2. Cảnh báo",
              "Số lần thử (cho Deflated Sharpe): **28**", "thử thêm: thử ATR 2,5",
              "2024-07-04: ngày lễ", "risk-policy-gd5-2", "Phí / lot", "Mốc ngẫu nhiên",
              "## 8. Sai lệch đã biết", "Đoạn để dành CHƯA chạy", "PBO = 0.40",
              "Tổ hợp được chọn thay đổi", "không tổ hợp nào đủ 30 lệnh học", "không chọn"):
        assert s in text, s
    assert all(b in text for b in RP.KNOWN_BIASES)


def test_render_sample_banner_and_banned_words():
    x = good_inputs(sample=True)
    text = RP.render(E.criteria(x), x, _ctx())
    assert "DỮ LIỆU MẪU" in text and "KHÔNG ĐẠT" in text
    with pytest.raises(ValueError):
        RP.render(E.criteria(x), x, _ctx(data_gaps=["Xác suất thắng 70 %"]))


# ---------------------------------------------------------------------- số từ walk-forward thật


def test_inputs_from_walk_forward_daily_pnl_matches_trades(monkeypatch):
    import gold_trading.backtest.walkforward as WF
    from gold_trading.backtest.registry import InMemoryRegistryStore
    from tests.test_backtest_simulate import cfg
    from tests.test_backtest_walkforward import SMALL, _registered, _views
    from tests.test_backtest_walkforward import data as data_fixture
    monkeypatch.setattr(WF, "grid", lambda: SMALL)
    bars, chain = data_fixture.__wrapped__()
    st = InMemoryRegistryStore()
    r, split, fp = _registered(st, bars, chain)
    db, dc = WF.cut(bars, chain, r.dev_end)
    dev = WF.walk_forward(r, split, db, dc, _views, cfg(), full_fingerprint=fp)
    x = E.inputs_from(dev, capital=D(10_000), n_trials=3, random_p95_r=0.0,
                      bootstrap_seed=1, bootstrap_resamples=500)
    # Bất biến: tổng lãi / lỗ ngày ngoài mẫu = tổng lãi / lỗ các lệnh ngoài mẫu.
    assert sum(p for _, p in x.oos_daily) == sum(t.pnl for t in x.oos_trades)
    assert x.oos_trades and x.ci_low_r is not None and x.dsr is not None and x.pbo is not None
    days = [d for d, _ in x.oos_daily]
    assert days == sorted(days) and len(set(days)) == len(days)
    assert days[0] > split.windows[0].test_start and days[-1] <= r.dev_end
    ev = E.criteria(x)
    assert len(ev.criteria) == 8 and not ev.passed          # chưa chạy để dành → T1 / T7 trượt
    text = RP.render(ev, x, _ctx(registration=r, combos={c: summarize(dev.per_combo[c])
                                                         for c in SMALL},
                                 chosen=dev.chosen))
    assert "(hiện tại)" in text


# ---------------------------------------------------------------------- 6-C05


PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "gold_trading" / "backtest"


@pytest.mark.parametrize("mod", sorted(p.name for p in PKG.glob("*.py")))
def test_no_path_to_mark_strategy_validated(mod):                              # 6-C05
    """Mã GĐ6 không đụng tới cờ "chưa kiểm chứng" (``UNVALIDATED_RULES``) hay chính sách Risk —
    báo cáo ĐẠT cũng không tự mở SHADOW / LIVE; đổi trạng thái là quyết định của người dùng."""
    src = (PKG / mod).read_text()
    assert "UNVALIDATED_RULES" not in src
    tree = ast.parse(src)
    names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [x for x in names if x.startswith(("gold_trading.modes",
                                                  "gold_trading.intelligence.quality_gate"))]


def test_t7_zero_holdout_fails_even_when_oos_negative():
    # Lỗi lọt khi soát đột biến 23/11: để dành đúng 0R, ngoài mẫu âm → "≥ ½ ngoài mẫu" đúng
    # nhưng "> 0" sai → T7 phải KHÔNG ĐẠT.
    neg_oos = [tr(i, 10 if i % 2 == 0 else -12) for i in range(200)]       # −0,1R
    zero = [tr(i, 10 if i % 2 == 0 else -10) for i in range(30)]          # 0R
    assert not by_code(E.criteria(good_inputs(oos_trades=neg_oos, holdout_trades=zero)))[
        "T7"].passed
