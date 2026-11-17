"""Báo cáo khả thi — GĐ5 bước 8a (RPF-02, RPF-03, RPF-04). Thiết kế 37 mục 2.

Số broker / vốn GIẢ chỉ để test. Bảng tính tay (ví dụ thiết kế 36 mục 6): ATR 13 → SL 19,5;
spread 0,30, đệm p95 0,40, phí 7 $/lot, 1 lot = 100 oz → R1 = (19,5 + 0,3 + 0,4) × 100 + 7 = 2.027.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from gold_trading.risk.feasibility import Inputs, compute

D = Decimal
NOW = datetime(2026, 1, 6, 14, 15, tzinfo=UTC)          # thứ Ba → mốc kế tiếp thứ Ba (×1)
SPEC = dict(contract_size=100.0, volume_min=0.01, volume_max=50.0, volume_step=0.01, point=0.01,
            swap_mode=1, swap_long=0.0, swap_short=0.0, swap_rollover3days=3)


def inp(**kw):
    base = dict(now=NOW, is_sample=False, equity=D(10_000), equity_note="nhịp tim", spec=SPEC,
                atr=D(13), atr_as_of=NOW - timedelta(minutes=5), spread_points=30,
                baseline_points=40, commission=D(7), profile_risk=None)
    return Inputs(**(base | kw))


def test_hand_computed_both_levels():
    r = compute(inp())
    assert r.status == "OK" and r.missing == []
    assert (r.sl_distance, r.tp_distance, r.risk_per_lot) == (D("19.5"), D("39.0"), D("2027"))
    assert r.min_lot_risk == D("20.27") and r.min_lot_risk_pct == D("0.20")
    assert r.reward_risk == D("1.9058")                       # (3.870 − 7) / 2.027
    a, b = r.levels
    assert (a.risk_fraction, a.lots, a.risk_amount, a.min_equity, a.verdict) == (
        D("0.0025"), D("0.01"), D("20.27"), D("8108"), "KHA_THI")
    assert (b.risk_fraction, b.lots, b.risk_amount, b.min_equity) == (
        D("0.005"), D("0.02"), D("40.54"), D("4054"))
    assert "13 giờ 45 phút" in r.max_hold


def test_small_account_not_feasible_with_shortfall():           # RPF-03, 5-C01
    r = compute(inp(equity=D(5_000), profile_risk=D("0.0025")))
    (lv,) = r.levels
    # 0,25 % × 5.000 = 12,50 < 20,27 → thiếu 7,77; không làm tròn lên
    assert (lv.lots, lv.verdict, lv.shortfall) == (D(0), "KHONG_KHA_THI", D("7.77"))


def test_review_example_hundred_dollars():                      # RPF-03 (đánh giá: vốn 100 $)
    r = compute(inp(equity=D(100)))
    assert r.min_lot_risk_pct == D("20.27")                       # 0,01 lot mất ~20 % vốn
    assert all(lv.verdict == "KHONG_KHA_THI" for lv in r.levels)


def test_no_fresh_quote_uses_p95_and_says_so():
    r = compute(inp(spread_points=None))
    assert r.spread == D("0.40") and "p95" in r.spread_note
    assert r.risk_per_lot == D("2037")                             # spread 0,40 thay 0,30


def test_swap_worst_side_and_wednesday_triple():
    spec = SPEC | {"swap_long": -15.0, "swap_short": 2.0}          # 15 point = 15 $/lot
    assert compute(inp(spec=spec)).swap_per_lot == D("15.00")
    tue_evening = datetime(2026, 1, 7, 14, 0, tzinfo=UTC)          # thứ Tư → mốc thứ Tư ×3
    assert compute(inp(spec=spec, now=tue_evening)).swap_per_lot == D("45.00")


def test_low_reward_risk_warns():
    r = compute(inp(commission=D(400)))
    assert any("REWARD_RISK_TOO_LOW" in w for w in r.warnings)


@pytest.mark.parametrize("kw,code", [
    (dict(equity=None), "EQUITY"), (dict(equity=D(0)), "EQUITY"),
    (dict(spec=None), "BROKER_SPEC:contract_size"),
    (dict(spec=SPEC | {"point": None}), "BROKER_SPEC:point"),
    (dict(atr=None), "ATR_M15"), (dict(baseline_points=None), "SPREAD_P95_30D"),
    (dict(commission=None), "COMMISSION"),
])
def test_missing_inputs_never_guessed(kw, code):
    r = compute(inp(**kw))
    assert r.status == "KHONG_DU_DU_LIEU" and code in r.missing and r.levels == []


def test_sample_is_only_illustrative():                          # RPF-04
    r = compute(inp(is_sample=True))
    assert r.status == "CHI_MINH_HOA" and r.label == "CHỈ MINH HỌA — dữ liệu mẫu"
    assert all(lv.verdict == "CHI_MINH_HOA" for lv in r.levels)   # không bao giờ KHA_THI
    r = compute(inp(is_sample=True, equity=None))
    assert r.status == "CHI_MINH_HOA" and "EQUITY" in r.missing


def test_stale_atr_warns():
    r = compute(inp(atr_as_of=NOW - timedelta(days=2)))
    assert any("ATR cũ" in w for w in r.warnings)


def test_same_formula_as_risk_engine():
    """Đối chiếu với Risk: cùng đầu vào → cùng rủi ro / lot (không có công thức thứ hai)."""
    from gold_trading.risk.sizing import SizingSpec, size
    spec = SizingSpec(D(100), D("0.01"), D(50), D("0.01"))
    res = size(D(25), D("19.5"), D("0.30"), D("0.40"), D(7), spec)
    lv = compute(inp(profile_risk=D("0.0025"))).levels[0]
    assert (res.risk_per_lot, res.volume, res.risk_amount) == (D(2027), lv.lots, lv.risk_amount)


# ---------------------------------------------------------------- cli kha-thi (DB thật SQLite)

def _db(tmp_path, *, equity_age=timedelta(minutes=30), with_link=True):
    from gold_trading.analysts.framework import Scope, output_id
    from gold_trading.storage.analyst_outputs import SqlAnalystOutputStore
    from gold_trading.storage.broker_history import (
        EQUITY_FIELDS,
        SpecKey,
        SqlBrokerHistoryStore,
    )
    from gold_trading.storage.commissions import Commission, SqlCommissionStore
    from gold_trading.storage.quotes import SqlQuoteMinuteStore
    from gold_trading.storage.repository import SqlRepository
    from tests.factories import analyst
    from tests.mt5_helpers import BROKER_SYMBOL, FEED, LOGIN, SERVER, link_active
    from tests.test_risk_engine import minutes_rows

    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'k.db'}")
    repo.create_all()
    if not with_link:
        return repo
    link = link_active(repo)
    repo.lock_link_symbol("default", link.link_id, BROKER_SYMBOL)
    eng = repo.engine
    hist = SqlBrokerHistoryStore(eng)
    hist.record_spec(SpecKey("default", LOGIN, SERVER, BROKER_SYMBOL), SPEC | dict(
        digits=2, currency_profit="USD", stops_level=20, freeze_level=10, leverage=100,
        account_currency="USD"), observed_at=NOW - timedelta(days=2), gateway_version="t")
    hist.record_equity("default", LOGIN, SERVER,
                       dict.fromkeys(EQUITY_FIELDS) | {"equity": 10_000.0},
                       observed_at=NOW - equity_age)
    sc = Scope.of_feed("XAUUSD", "M15", "MT5", FEED)
    at = NOW - timedelta(minutes=5)
    SqlAnalystOutputStore(eng).append_scoped(
        analyst("technical", at, features={"atr14": 13.0},
                output_id=output_id("technical", "0", sc, at, "0" * 16)),
        sc, computed_at=at)
    rows = [replace(r, feed_id=FEED) for r in minutes_rows(NOW, p95=40)]
    SqlQuoteMinuteStore(eng).append(rows)
    SqlCommissionStore(eng).record(Commission("default", D(7), "USD", NOW - timedelta(days=1),
                                              "u", "test"))
    return repo


def test_cli_kha_thi_hand_computed(tmp_path, capsys):
    from gold_trading.ingestion import cli
    repo = _db(tmp_path)
    assert cli._kha_thi("default", repo=repo, now=NOW) == 0
    out = capsys.readouterr().out
    # không có giây giá mới → spread = p95 (0,40) → R1 = (19,5 + 0,4 + 0,4) × 100 + 7 = 2.037
    assert "Rủi ro thật / 1 lot (gồm chi phí): 2037" in out
    assert "Mức 0,25 %: KHẢ THI — 0.01 lot" in out and "Mức 0,5 %: KHẢ THI — 0.02 lot" in out
    assert "bản ghi theo giờ của Gateway" in out


def test_cli_kha_thi_stale_equity_is_missing(tmp_path, capsys):
    from gold_trading.ingestion import cli
    repo = _db(tmp_path, equity_age=timedelta(hours=3))
    assert cli._kha_thi("default", repo=repo, now=NOW) == 0
    assert "KHÔNG ĐỦ DỮ LIỆU — thiếu: EQUITY" in capsys.readouterr().out


def test_cli_kha_thi_without_mt5_link(tmp_path, capsys):
    from gold_trading.ingestion import cli
    repo = _db(tmp_path, with_link=False)
    assert cli._kha_thi(None, repo=repo, now=NOW) == 0
    assert "Chưa có nguồn giá MT5" in capsys.readouterr().out


def test_cli_kha_thi_is_read_only(tmp_path):
    from sqlalchemy import func, select

    from gold_trading.ingestion import cli
    from gold_trading.storage.schema import metadata
    repo = _db(tmp_path)

    def counts():
        with repo.engine.connect() as c:
            return {t: c.execute(select(func.count()).select_from(metadata.tables[t]))
                    .scalar_one() for t in metadata.tables}
    before = counts()
    cli._kha_thi("default", repo=repo, now=NOW)
    assert counts() == before
