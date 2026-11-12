"""5d: Gateway gửi nến M15 của 6 cặp tiền chỉ số USD (chỉ đọc), mỗi cặp độc lập."""

from __future__ import annotations

from datetime import timedelta

import pytest

from mt5_gateway import checks, config
from mt5_gateway.backend_client import BackendError
from mt5_gateway.config import USD_INDEX_PAIRS, parse_usd_pairs
from mt5_gateway.sync import Syncer
from tests.fake_mt5 import FakeMt5
from tests.test_gateway import NOW_WINTER, FakeBackend, cfg

ALL = tuple((p, p) for p in USD_INDEX_PAIRS)
K = {"EURUSD": 0.00045, "USDJPY": 0.064, "GBPUSD": 0.00053, "USDCAD": 0.00057, "USDSEK": 0.0045,
     "USDCHF": 0.00037}


# ---------- cấu hình ----------


def test_default_pairs_follow_gold_symbol_suffix():
    assert parse_usd_pairs("", "XAUUSD") == ALL
    assert dict(parse_usd_pairs("", "XAUUSD.r"))["EURUSD"] == "EURUSD.r"
    assert dict(parse_usd_pairs("", "XAUUSDm"))["USDJPY"] == "USDJPYm"
    assert dict(parse_usd_pairs("", "GOLD"))["EURUSD"] == "EURUSD"  # không đoán hậu tố lạ


def test_override_and_off():
    m = dict(parse_usd_pairs("eurusd=EURUSD.x, USDSEK=USDSEK_i", "XAUUSD"))
    assert m["EURUSD"] == "EURUSD.x" and m["USDSEK"] == "USDSEK_i" and m["USDJPY"] == "USDJPY"
    for off in ("off", "OFF", "0", "tắt"):
        assert parse_usd_pairs(off, "XAUUSD") == ()


@pytest.mark.parametrize("raw", ["EURUSD", "AUDUSD=AUDUSD", "EURUSD=GBPUSD", "EURUSD=",
                                 "EURUSD=EUR USD"])
def test_bad_config_refused(raw):
    with pytest.raises(ValueError):
        parse_usd_pairs(raw, "XAUUSD")


def test_config_load_reads_usd_pairs(tmp_path):
    f = tmp_path / "gateway.env"
    f.write_text("GT_BROKER_SYMBOL=XAUUSD.r\nGT_USD_PAIRS=USDCHF=USDCHF.x\n", "utf-8")
    m = dict(config.load(f, use_environ=False).usd_pairs)
    assert m["EURUSD"] == "EURUSD.r" and m["USDCHF"] == "USDCHF.x"


# ---------- check ----------


def world(pairs=ALL, have=None, no_history=(), backend=None):
    fake = FakeMt5(now_utc=NOW_WINTER)
    fake.extra_symbols = {b: K[p] for p, b in pairs if have is None or p in have}
    fake.no_history = set(no_history)
    be = backend or FxBackend()
    conf = cfg(usd_pairs=pairs)
    rep = checks.run_checks(conf, fake, be, now=lambda: NOW_WINTER, tick_wait_s=1)
    t = [0.0]

    def sleep(x):
        t[0] += x

    s = Syncer(conf, rep.reader, be, rep, sleep=sleep, clock=lambda: t[0],
               now_utc=lambda: fake.now)
    return fake, be, s, rep, t


class FxBackend(FakeBackend):
    def __init__(self, fail=None):
        super().__init__()
        self.fx: list[dict] = []
        self.fail = fail or {}

    def post_fx_candles(self, body):
        err = self.fail.get(body["pair"])
        if err:
            raise BackendError(*err)
        self.fx.append(body)
        n = len(body["bars"])
        return {"received": n, "accepted": n, "duplicates": 0, "revised": 0, "quarantined": 0,
                "reasons": {}}


def step(rep):
    return [x for x in rep.steps if x.name == "Cặp tiền chỉ số USD"][0]


def test_check_all_six_pass():
    _, _, _, rep, _ = world()
    assert step(rep).status == checks.PASS and len(rep.fx_pairs_ok) == 6


def test_check_missing_pairs_warn_only():
    _, _, _, rep, _ = world(have={"EURUSD", "USDJPY"}, no_history={"USDJPY"})
    st = step(rep)
    assert st.status == checks.WARN and rep.ok  # vàng vẫn chạy
    assert rep.fx_pairs_ok == [("EURUSD", "EURUSD")]
    assert "USDJPY: USDJPY chưa có lịch sử M15" in st.detail
    assert "GBPUSD: không có GBPUSD" in st.detail


def test_check_disabled():
    _, _, _, rep, _ = world(pairs=())
    assert step(rep).status == checks.WARN and "tắt" in step(rep).detail and rep.fx_pairs_ok == []


# ---------- đồng bộ ----------


def test_backfill_then_only_new_bar_or_resend():
    fake, be, s, _, t = world()
    s.backfill()
    s.fx.push(lambda: t[0])
    assert {b["pair"] for b in be.fx} == set(USD_INDEX_PAIRS)
    first = [b for b in be.fx if b["pair"] == "USDJPY"][0]
    assert first["backfill"] and first["broker_symbol"] == "USDJPY"
    assert first["mt5_login"] == 51234567 and first["timeframe"] == "M15"
    assert first["bars"][-1]["close"] < 200  # giá của USDJPY, không phải vàng
    n = len(be.fx)
    s.fx.push(lambda: t[0])
    assert len(be.fx) == n  # chưa có nến mới, chưa tới lúc gửi lại
    fake.now += timedelta(minutes=15)
    s.fx.push(lambda: t[0])
    assert len(be.fx) == n + 6 and all(not b["backfill"] for b in be.fx[n:])
    t[0] += 61
    s.fx.push(lambda: t[0])
    assert len(be.fx) == n + 12  # gửi lại định kỳ để bắt bản sửa
    assert fake.order_send_called is False


def test_one_pair_error_isolated_and_retried():
    be = FxBackend(fail={"USDSEK": (503, "lỗi lưu trữ")})
    fake, be, s, _, t = world(backend=be)
    s.fx.push(lambda: t[0])
    assert {b["pair"] for b in be.fx} == set(USD_INDEX_PAIRS) - {"USDSEK"}
    be.fail = {}
    s.fx.push(lambda: t[0])
    assert not [b for b in be.fx if b["pair"] == "USDSEK"]  # chờ 60 giây
    t[0] += 61
    s.fx.push(lambda: t[0])
    assert [b for b in be.fx if b["pair"] == "USDSEK" and b["backfill"]]


def test_link_wait_propagates_and_old_backend_disables():
    _, be, s, _, t = world(backend=FxBackend(fail={"EURUSD": (409, "MT5_LINK_REQUIRED: x")}))
    with pytest.raises(BackendError):
        s.fx.push(lambda: t[0])
    _, be, s, _, t = world(backend=FxBackend(fail={"EURUSD": (404, "Not Found")}))
    s.fx.push(lambda: t[0])
    assert not s.fx.enabled and be.fx == []


def test_symbol_vanished_isolated():
    fake, be, s, _, t = world()
    del fake.extra_symbols["USDCAD"]  # broker gỡ symbol khi đang chạy
    s.fx.push(lambda: t[0])
    assert {b["pair"] for b in be.fx} == set(USD_INDEX_PAIRS) - {"USDCAD"}


def test_account_switch_during_read_drops_fx_batch():
    fake, be, s, _, t = world()
    real = fake.copy_rates_from_pos

    def switch(name, *a):
        out = real(name, *a)
        if name == "EURUSD":
            fake.login = 999
        return out

    fake.copy_rates_from_pos = switch
    from mt5_gateway.sync import IdentityUnstable

    with pytest.raises(IdentityUnstable):
        s.fx.push(lambda: t[0])
    assert be.fx == []


def test_reset_after_block_backfills_again():
    fake, be, s, _, t = world()
    s.fx.push(lambda: t[0])
    s.fx.reset()
    be.fx.clear()
    s.fx.push(lambda: t[0])
    assert len(be.fx) >= 6 and all(b["backfill"] for b in be.fx)


def test_run_loop_includes_fx():
    fake, be, s, _, _ = world()
    loops = iter([False, False, True])
    s.run_forever(stop=lambda: next(loops))
    assert {b["pair"] for b in be.fx} == set(USD_INDEX_PAIRS)
