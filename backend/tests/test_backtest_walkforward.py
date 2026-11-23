"""GĐ6 bước 7 — đăng ký, walk-forward, khóa đoạn để dành (protocol-1 mục 3–4; 6-C04)."""

from __future__ import annotations

import pathlib
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from gold_trading.backtest import walkforward as WF
from gold_trading.backtest.protocol import Combo, grid, make_split
from gold_trading.backtest.registry import (
    HoldoutAlreadyRun,
    InMemoryRegistryStore,
    RegistryError,
    SqlRegistryStore,
    check_grid,
    n_trials,
    new_registration,
)
from gold_trading.backtest.simulate import Bars, HistoricalView, HistoricalViews, SimBar
from gold_trading.common.enums import Bias
from gold_trading.market.hours import is_open
from gold_trading.storage.repository import SqlRepository
from tests.factories import market_view
from tests.test_backtest_simulate import FEED, SCOPE, cfg

D = Decimal
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryRegistryStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'bt.db'}")
    repo.create_all()
    return SqlRegistryStore(repo.engine)


def _split():
    return make_split(datetime(2024, 1, 2, 23, 0, tzinfo=UTC),
                      datetime(2025, 11, 1, 0, 0, tzinfo=UTC))


def _reg(**kw):
    base = dict(fingerprint="a" * 64, code_version="gd6-test", created_by="u", at=NOW)
    return new_registration(_split(), **(base | kw))


# ---------------------------------------------------------------------- kho đăng ký


def test_register_roundtrip_trials_and_holdout_once(store):
    r = _reg(notes="thử")
    store.register(r)
    got = store.get(r.registration_id)
    assert got == r and got.grid == tuple(c.key for c in grid()) and len(got.grid) == 27
    with pytest.raises(RegistryError):
        store.register(r)                                         # không ghi đè
    assert n_trials(store, r) == 27
    store.add_trial(r.registration_id, "thử thêm ATR 2,5", by="u", at=NOW)
    store.add_trial(r.registration_id, "thử thêm giờ 02:00", by="u", at=NOW)
    assert n_trials(store, r) == 29
    assert store.trials(r.registration_id) == ["thử thêm ATR 2,5", "thử thêm giờ 02:00"]
    with pytest.raises(RegistryError):
        store.add_trial("khong-co", "x", by="u", at=NOW)
    assert store.holdout(r.registration_id) is None
    c = store.claim_holdout(r.registration_id, "P1=0.6|P7=1.5|P8=2", by="u", at=NOW)
    assert store.holdout(r.registration_id) == c
    with pytest.raises(HoldoutAlreadyRun):
        store.claim_holdout(r.registration_id, "P1=0.5|P7=1.0|P8=1.5", by="u", at=NOW)
    assert store.holdout(r.registration_id).combo == "P1=0.6|P7=1.5|P8=2"   # không đổi
    with pytest.raises(RegistryError):
        store.claim_holdout("khong-co", "x", by="u", at=NOW)


def test_new_registration_validation_and_grid_check():
    with pytest.raises(RegistryError):
        _reg(fingerprint="ngan")
    with pytest.raises(RegistryError):
        _reg(created_by="")
    r = _reg()
    check_grid(r, [c.key for c in grid()])
    with pytest.raises(RegistryError):
        check_grid(r, [c.key for c in grid()][:26])               # bớt tổ hợp
    with pytest.raises(RegistryError):
        check_grid(r, [*[c.key for c in grid()], "P1=0.9|P7=3|P8=5"])   # thêm ngoài lưới


def test_sql_order_constraint(tmp_path):
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'bt.db'}")
    repo.create_all()
    s = SqlRegistryStore(repo.engine)
    r = _reg()
    from dataclasses import replace
    with pytest.raises(RegistryError):
        s.register(replace(r, dev_end=r.data_end))                # ranh giới = hết dữ liệu


def test_migration_0028_append_only_all_tables():
    src = (pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions" /
           "0028_backtest_registry.py").read_text()
    assert "forbid_mutation" in src and 'down_revision = "0027"' in src
    for t in ("backtest_registrations", "backtest_trials", "backtest_holdout_runs"):
        assert f'"{t}"' in src


# ---------------------------------------------------------------------- walk-forward


SMALL = (Combo(0.5, D("1.0"), D("1.5")), Combo(0.6, D("1.5"), D("2")),
         Combo(0.7, D("2.0"), D("3")))


@pytest.fixture(scope="module")
def data():
    """~22 tháng giá đi ngẫu nhiên; MarketView "cài lợi thế" (biết trước 2 giờ) mỗi 2 giờ."""
    rng = random.Random(4)
    start = datetime(2024, 1, 2, 23, 0, tzinfo=UTC)
    end = datetime(2025, 11, 1, 0, 0, tzinfo=UTC)
    bl, t, p = [], start, 2000.0
    while t < end:
        if is_open(t) and is_open(t + timedelta(minutes=14)):
            o = round(p, 2)
            c = round(o + rng.gauss(0, 2.0), 2)
            bl.append(SimBar(t, D(str(o)), D(str(round(max(o, c) + 0.4, 2))),
                             D(str(round(min(o, c) - 0.4, 2))), D(str(c)), 20))
            p = c
        t += timedelta(minutes=15)
    chain = []
    for i in range(0, len(bl) - 9, 8):
        tc = bl[i].close_time
        fut = float(bl[i + 9].close - bl[i + 1].open)
        bias = Bias.LONG if fut > 3 else Bias.SHORT if fut < -3 else Bias.NEUTRAL
        v = market_view(tc, market_view_id=f"w{i}", bias=bias, confidence=0.8, feed_id=FEED)
        chain.append(HistoricalView(v, tc, {"atr14": 4.0, "ema20": float(bl[i + 1].open)}))
    return Bars(bl), chain


def _views(ch):
    return HistoricalViews(ch, SCOPE)


@pytest.fixture
def small_grid(monkeypatch):
    monkeypatch.setattr(WF, "grid", lambda: SMALL)


def _registered(store, bars, chain):
    split = make_split(bars.bars[0].open_time, bars.bars[-1].close_time)
    fp = WF.fingerprint_of(bars, chain)
    r = new_registration(split, fingerprint=fp, code_version="t", created_by="u", at=NOW)
    from dataclasses import replace
    r = replace(r, grid=tuple(c.key for c in SMALL))
    store.register(r)
    return r, split, fp


def test_walk_forward_refuses_holdout_data_and_changed_data(data, small_grid):
    bars, chain = data
    st = InMemoryRegistryStore()
    r, split, fp = _registered(st, bars, chain)
    with pytest.raises(WF.HoldoutLeak):                               # chưa cắt nến
        WF.walk_forward(r, split, bars, [], _views, cfg(), full_fingerprint=fp)
    db, dc = WF.cut(bars, chain, r.dev_end)
    late = chain[-1]
    with pytest.raises(WF.HoldoutLeak):                               # lọt một MarketView sau
        WF.walk_forward(r, split, db, [*dc, late], _views, cfg(), full_fingerprint=fp)
    with pytest.raises(RegistryError):                                # dữ liệu đổi sau đăng ký
        WF.walk_forward(r, split, db, dc, _views, cfg(), full_fingerprint="b" * 64)
    from dataclasses import replace
    with pytest.raises(RegistryError):                                # lưới khác đăng ký
        WF.walk_forward(replace(r, grid=r.grid[:2]), split, db, dc, _views, cfg(),
                        full_fingerprint=fp)


def test_walk_forward_rounds_slices_and_holdout_once(data, small_grid):
    bars, chain = data
    st = InMemoryRegistryStore()
    r, split, fp = _registered(st, bars, chain)
    db, dc = WF.cut(bars, chain, r.dev_end)
    dev = WF.walk_forward(r, split, db, dc, _views, cfg(), full_fingerprint=fp)
    assert set(dev.per_combo) == set(SMALL) and len(dev.rounds) == len(split.windows) == 2
    for rd in dev.rounds:
        w = rd.window
        for c in SMALL:                                               # lát học = lệnh trong cửa sổ
            n = sum(1 for t in dev.trades[c] if w.learn_start <= t.opened_at < w.learn_end)
            assert rd.learn[c].trades == n
        assert rd.chosen is not None
        assert all(w.test_start <= t.opened_at < w.test_end for t in rd.oos)
        assert all(t.closed_at <= w.test_end for t in rd.oos)        # không vắt qua ranh giới
        assert {t.position_id for t in rd.oos} <= {t.position_id for t in dev.trades[rd.chosen]}
    assert all(t.closed_at <= r.dev_end for c in SMALL for t in dev.trades[c])
    oos = dev.oos_trades
    assert oos and sum(t.r for t in oos) / len(oos) > 0               # có lợi thế cài sẵn
    # Đoạn để dành: một lần, chỉ sau ranh giới, đúng tổ hợp được chọn nhiều nhất.
    h = WF.run_holdout(st, r, dev, bars, chain, _views, cfg(), by="u", at=NOW,
                       full_fingerprint=fp)
    assert h.combo is not None and st.holdout(r.registration_id).combo == h.combo.key
    assert h.trades and all(t.opened_at >= r.dev_end for t in h.trades)
    with pytest.raises(HoldoutAlreadyRun):
        WF.run_holdout(st, r, dev, bars, chain, _views, cfg(), by="u", at=NOW,
                       full_fingerprint=fp)


def test_holdout_claimed_before_run_even_if_run_fails(data, small_grid, monkeypatch):
    bars, chain = data
    st = InMemoryRegistryStore()
    r, split, fp = _registered(st, bars, chain)
    db, dc = WF.cut(bars, chain, r.dev_end)
    dev = WF.walk_forward(r, split, db, dc, _views, cfg(), full_fingerprint=fp)

    def boom(*a, **k):
        raise RuntimeError("mất điện giữa chừng")
    monkeypatch.setattr(WF, "simulate", boom)
    with pytest.raises(RuntimeError):
        WF.run_holdout(st, r, dev, bars, chain, _views, cfg(), by="u", at=NOW,
                       full_fingerprint=fp)
    assert st.holdout(r.registration_id) is not None                  # đã giành → không chạy lại
    with pytest.raises(HoldoutAlreadyRun):
        WF.run_holdout(st, r, dev, bars, chain, _views, cfg(), by="u", at=NOW,
                       full_fingerprint=fp)


def test_fingerprint_changes_with_any_number(data):
    bars, chain = data
    fp = WF.fingerprint_of(bars, chain)
    from dataclasses import replace
    b2 = list(bars.bars)
    b2[100] = replace(b2[100], close=b2[100].close + D("0.01"))
    assert WF.fingerprint_of(Bars(b2), chain) != fp
    assert WF.fingerprint_of(bars, chain[:-1]) != fp
    assert WF.fingerprint_of(bars, chain) == fp
