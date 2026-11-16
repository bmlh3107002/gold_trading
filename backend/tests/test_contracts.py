from datetime import datetime

import pytest
from pydantic import ValidationError

from gold_trading.common.enums import Side
from tests.conftest import minutes
from tests.factories import intent, market_view, record


def test_naive_datetime_rejected():
    with pytest.raises(ValidationError):
        record("r1", datetime(2026, 1, 1), datetime(2026, 1, 1))


def test_ingested_before_event_rejected(t0):
    with pytest.raises(ValidationError):
        record("r1", t0, t0 - minutes(1))


def test_buy_stop_loss_must_be_below_entry(t0):
    with pytest.raises(ValidationError):
        intent(t0, stop_loss=2410.0)


def test_sell_intent_valid(t0):
    i = intent(t0, side=Side.SELL, stop_loss=2410.0, take_profit=2380.0)
    assert i.stop_distance == 10.0


@pytest.mark.parametrize("probs", [{"p_up": 0.6, "p_down": 0.3}, {"p_up": 0.5}, {"p_down": 0.0},
                                   {"p_up": 0.7, "p_down": 0.5}])
def test_market_view_rejects_probabilities_until_calibrated(t0, probs):
    # DEC-27: chưa hiệu chỉnh → không được có số xác suất nào, kể cả 0 hay 50/50.
    with pytest.raises(ValidationError, match="p_up / p_down"):
        market_view(t0, **probs)


def test_market_view_probabilities_default_none(t0):
    mv = market_view(t0)
    assert mv.p_up is None and mv.p_down is None


@pytest.mark.parametrize("flags", [frozenset(), frozenset({"UNCALIBRATED"}),
                                   frozenset({"UNVALIDATED_RULES"}), frozenset({"SAMPLE_DATA"})])
def test_market_view_requires_uncalibrated_and_unvalidated_flags(t0, flags):
    # DEC-25 / DEC-27: thiếu một trong hai cờ → hợp đồng từ chối (không thể "quên" gắn nhãn).
    with pytest.raises(ValidationError, match="cờ chất lượng bắt buộc"):
        market_view(t0, quality_flags=flags)


def test_market_view_sample_source_requires_sample_flag(t0):
    with pytest.raises(ValidationError, match="SAMPLE_DATA"):
        market_view(t0, source="SAMPLE")
    mv = market_view(t0, source="SAMPLE",
                     quality_flags=frozenset({"UNCALIBRATED", "UNVALIDATED_RULES", "SAMPLE_DATA"}))
    assert "SAMPLE_DATA" in mv.quality_flags


@pytest.mark.parametrize("source", ["sample", " SAMPLE ", "SAMPLE\n", "Mt5", ""])
def test_market_view_source_must_be_canonical(t0, source):
    # Soát 1b: " SAMPLE " từng lọt qua mà không cần cờ SAMPLE_DATA → nguồn phải đúng dạng chữ hoa.
    with pytest.raises(ValidationError):
        market_view(t0, source=source,
                    quality_flags=frozenset({"UNCALIBRATED", "UNVALIDATED_RULES", "SAMPLE_DATA"}))


@pytest.mark.parametrize("update", [{"p_up": 0.6}, {"p_down": 0.1},
                                    {"quality_flags": frozenset()},
                                    {"quality_flags": frozenset({"UNCALIBRATED"})},
                                    {"source": "SAMPLE"}, {"expires_at": None}])
def test_market_view_model_copy_revalidates(t0, update):
    # Soát 1b: model_copy mặc định của Pydantic bỏ qua kiểm tra → lén gắn xác suất / gỡ cờ được.
    mv = market_view(t0)
    if update.get("expires_at", 1) is None:
        update = {"expires_at": t0}
    with pytest.raises(ValidationError):
        mv.model_copy(update=update)


def test_market_view_model_copy_valid_update_ok(t0):
    mv = market_view(t0).model_copy(update={"confidence": 0.3})
    assert mv.confidence == 0.3 and mv.p_up is None


def test_market_view_requires_price_source(t0):
    # MT-05: không có giá trị mặc định cho nguồn giá — thiếu là lỗi, không âm thầm gán.
    from gold_trading.contracts import MarketView
    data = market_view(t0).model_dump()
    for key in ("source", "feed_id", "quality_policy_version", "model_version"):
        bad = {k: v for k, v in data.items() if k != key}
        with pytest.raises(ValidationError):
            MarketView(**bad)


def test_market_view_vol_forecast_optional_not_negative(t0):
    assert market_view(t0, vol_forecast=None).vol_forecast is None
    with pytest.raises(ValidationError):
        market_view(t0, vol_forecast=-0.1)


def test_market_view_expiry_after_as_of(t0):
    with pytest.raises(ValidationError, match="expires_at"):
        market_view(t0, expires_at=t0)


def test_market_view_json_round_trip(t0):
    from gold_trading.contracts import MarketView
    mv = market_view(t0, risk_flags=frozenset({"EVENT_WINDOW"}))
    again = MarketView.model_validate_json(mv.model_dump_json())
    assert again == mv and again.p_up is None


def test_contracts_are_immutable(t0):
    mv = market_view(t0)
    with pytest.raises(ValidationError):
        mv.confidence = 0.1


# --- KN-21 (F-10): model_copy của MỌI hợp đồng luôn kiểm tra lại -----------------------------

def _decision(t0, **kw):
    from gold_trading.common.enums import RiskOutcome
    from gold_trading.contracts.risk import RiskDecision

    base = dict(risk_decision_id="rd1", intent_id="i1", outcome=RiskOutcome.REJECTED,
                reason_codes=("X",), decided_at=t0, expires_at=t0 + minutes(1), policy_version="p")
    base.update(kw)
    return RiskDecision(**base)


@pytest.mark.parametrize("update", [
    {"stop_loss": 2410.0},                    # BUY: SL trên giá vào → sai chiều
    {"side": Side.SELL},                      # đổi chiều mà giữ SL cũ → sai chiều
    {"take_profit": 2300.0},                  # BUY: TP dưới giá vào
    {"expiry": None},                         # bỏ hạn
    {"risk_budget_requested": 0.0},           # rủi ro 0
    {"risk_budget_requested": -0.01},
    {"entry_reference": float("nan")},
    {"unknown_field": 1},                     # trường lạ
])
def test_trade_intent_model_copy_revalidates(t0, update):
    i = intent(t0)
    with pytest.raises(ValidationError):
        i.model_copy(update=update)
    with pytest.raises(ValidationError):
        i.model_copy(update=update, deep=True)


def test_risk_decision_model_copy_cannot_approve_without_reservation(t0):
    from gold_trading.common.enums import RiskOutcome

    d = _decision(t0)
    with pytest.raises(ValidationError):
        d.model_copy(update={"outcome": RiskOutcome.APPROVED})
    with pytest.raises(ValidationError):
        d.model_copy(update={"volume": 1.0})        # REJECTED mà có khối lượng
    with pytest.raises(ValidationError):
        d.model_copy(update={"expires_at": t0})     # hạn không sau lúc quyết


def test_model_copy_valid_update_keeps_type_and_original(t0):
    i = intent(t0)
    j = i.model_copy(update={"stop_loss": 2380.0, "take_profit": None})
    assert type(j) is type(i)
    assert j.stop_loss == 2380.0 and j.take_profit is None
    assert i.stop_loss != 2380.0                     # bản gốc không đổi
    assert i.model_copy() == i                       # sao chép không cập nhật = bằng nhau
    assert i.model_copy() is not i


def test_every_contract_uses_validating_model_copy():
    """Không hợp đồng nào được ghi đè ``model_copy`` bằng bản không kiểm tra."""
    import importlib
    import pkgutil

    import gold_trading.contracts as pkg
    from gold_trading.contracts.base import Contract

    for m in pkgutil.iter_modules(pkg.__path__):
        importlib.import_module(f"{pkg.__name__}.{m.name}")

    def subclasses(c):
        for s in c.__subclasses__():
            yield s
            yield from subclasses(s)

    found = list(subclasses(Contract))
    assert len(found) >= 8
    for cls in found:
        assert cls.model_copy is Contract.model_copy, cls.__name__


def test_source_never_uses_model_construct():
    """``model_construct`` bỏ qua mọi kiểm tra — mã nguồn không được dùng (KN-21)."""
    from pathlib import Path

    import gold_trading

    root = Path(gold_trading.__file__).parent
    hits = [str(p.relative_to(root)) for p in root.rglob("*.py")
            if "model_construct(" in p.read_text()]
    assert hits == []
