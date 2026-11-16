"""RSK-11 (KN-02): khối lượng theo thông số thật — bảng tính tay (thiết kế 35 mục 5) + so ngẫu
nhiên với công thức viết lại độc lập bằng phân số chính xác (``Fraction``).

Mức rủi ro trong file là **số chỉ để test**.
"""

from __future__ import annotations

import random
from decimal import Decimal
from fractions import Fraction

import pytest

from gold_trading.risk.sizing import SizingSpec, dec, floor_to_step, size

D = Decimal


def spec(cs="100", vmin="0.01", vmax="50", step="0.01") -> SizingSpec:
    return SizingSpec(D(cs), D(vmin), D(vmax), D(step))


# (tiền rủi ro, D, S, B, cỡ HĐ, phí/lot, bước) → (R1, lot, rủi ro thật)
HAND = [
    ("QLV 5.2 chưa chi phí", "100", "5.0", "0", "0", "100", "0", "0.01", "500", "0.20", "100"),
    ("QLV 5.2 có chi phí", "100", "5.0", "0.3", "0.5", "100", "0", "0.01", "580", "0.17", "98.6"),
    ("QLV 11.2", "40", "18.0", "0.3", "0.5", "100", "0", "0.01", "1880", "0.02", "37.6"),
    ("1 lot = 10 oz", "50", "10.0", "0.2", "0.3", "10", "0", "0.01", "105", "0.47", "49.35"),
    ("1 lot = 1 oz, bước 0,1", "50", "10.0", "0.2", "0.3", "1", "0", "0.1", "10.5", "4.7",
     "49.35"),
    ("có phí (5-C16)", "100", "5.0", "0.3", "0.5", "100", "7", "0.01", "587", "0.17", "99.79"),
]


@pytest.mark.parametrize("row", HAND, ids=[r[0] for r in HAND])
def test_hand_calculated_table(row):
    _, m, d, s, b, cs, c, step, r1, lot, risk = row
    r = size(D(m), D(d), D(s), D(b), D(c), spec(cs=cs, step=step))
    assert r.risk_per_lot == D(r1)
    assert r.volume == D(lot)
    assert r.risk_amount == D(risk)
    assert r.risk_amount <= D(m)


def test_small_account_rejected_with_shortfall():                        # 5-C01
    # equity 1000 × 0,5 % = 5 $; R1 = 10,5 × 100 = 1050 → 0,01 lot cần 10,5 $ → thiếu 5,5 $
    r = size(D(5), D(10), D("0.2"), D("0.3"), D(0), spec())
    assert r.volume == 0 and r.risk_amount == 0
    assert r.shortfall == D("5.5")
    assert D("0.01") * r.risk_per_lot / D("0.005") == D(2100)        # vốn tối thiểu


def test_never_rounds_up():
    # 0,0199999 lot → 0,01 (không phải 0,02)
    r = size(D("20.99999"), D(10), D("0.2"), D("0.3"), D(0), spec())
    assert r.volume == D("0.01")


def test_floor_to_step_exact_decimal():
    assert floor_to_step(D("0.3"), D("0.1")) == D("0.3")       # float: 0.3/0.1 = 2.9999…
    assert floor_to_step(D("0.29999"), D("0.1")) == D("0.2")
    assert floor_to_step(D(0), D("0.01")) == 0
    with pytest.raises(ValueError):
        floor_to_step(D(1), D(0))


def test_dec_uses_reported_decimal_not_binary():
    assert dec(0.01) == D("0.01")
    assert dec(0.1) + dec(0.2) == D("0.3")
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            dec(bad)
    with pytest.raises(TypeError):
        dec(True)


@pytest.mark.parametrize("kw", [dict(d=D(0)), dict(s=D(-1)), dict(b=D("-0.1")), dict(c=D(-1))])
def test_invalid_inputs_raise(kw):
    a = dict(m=D(50), d=D(10), s=D("0.2"), b=D("0.3"), c=D(0)) | kw
    with pytest.raises(ValueError):
        size(a["m"], a["d"], a["s"], a["b"], a["c"], spec())


def _reference(m, d, s, b, c, cs, vmin, vmax, step):
    """Viết lại độc lập bằng phân số: lot = max k·step ≤ M / R1, cắt về max theo bước."""
    r1 = (d + s + b) * cs + c
    k = int((m / r1) // step) if m > 0 else 0
    kmax = int(vmax // step)
    k = min(k, kmax)
    vol = k * step
    if vol < vmin or vol <= 0:
        return r1, Fraction(0)
    return r1, vol


def test_random_against_exact_fraction_reference():
    rng = random.Random(20261116)
    steps = ["0.01", "0.1", "1", "0.001", "0.05"]
    sizes = ["100", "10", "1", "50", "0.1"]
    for _ in range(5000):
        step = rng.choice(steps)
        vmin = str(D(step) * rng.randint(1, 5))
        vmax = str(D(step) * rng.randint(50, 100000))
        cs = rng.choice(sizes)
        m = D(rng.randint(0, 2_000_000)) / 100
        d = D(rng.randint(1, 50_000)) / 1000
        s = D(rng.randint(0, 200)) / 100
        b = D(rng.randint(0, 200)) / 100
        c = D(rng.randint(0, 2000)) / 100
        sp = spec(cs=cs, vmin=vmin, vmax=vmax, step=step)
        got = size(m, d, s, b, c, sp)
        F = lambda x: Fraction(str(x))  # noqa: E731
        r1, vol = _reference(F(m), F(d), F(s), F(b), F(c), F(cs), F(vmin), F(vmax), F(step))
        assert F(got.risk_per_lot) == r1
        assert F(got.volume) == vol, (m, d, s, b, c, cs, step, vmin, vmax)
        # Bất biến: rủi ro thật (gồm spread + đệm + phí) ≤ mức được duyệt; lot đúng bội bước
        assert got.risk_amount <= m
        assert F(got.risk_amount) == vol * r1
        assert (F(got.volume) / F(step)).denominator == 1
        if got.volume > 0:
            assert D(vmin) <= got.volume <= D(vmax)
            # tối đa: thêm một bước nữa thì vượt (hoặc vượt max)
            assert (got.volume + D(step)) * got.risk_per_lot > m or \
                got.volume + D(step) > D(vmax)
