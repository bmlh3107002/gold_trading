"""GĐ4 bước 4 — Fusion bằng luật `fusion-rules-1.0.0` (FUS-01; 4-C03, 4-C04; DEC-25/26/27).

Thiết kế 33 mục 5. Mỗi dòng bảng luật là một test với kết quả tính tay.
"""

import pytest

from gold_trading.analysts.framework import Scope
from gold_trading.common.enums import Bias, QualityVerdict, Regime, SourceStatus
from gold_trading.intelligence import fusion as FU
from gold_trading.intelligence.fusion import fuse
from gold_trading.intelligence.quality_gate import POLICY_V1, evaluate
from gold_trading.intelligence.snapshot_builder import build_snapshot
from tests.conftest import minutes
from tests.test_quality_gate import FEATURES, outputs

FEED = Scope("XAUUSD", "M15", "MT5", "f1")
SAMPLE = Scope("XAUUSD", "M15", "SAMPLE", "")


def view(t0, *, tech=None, reg=None, mac=None, pos=None, nws=None, price=FEED, skip=(),
         at=None, **over):
    """Dựng snapshot → Quality Gate → Fusion. ``tech`` / ``reg`` / ``mac`` / ``pos`` / ``nws`` =
    đặc trưng ghi đè (gộp vào đặc trưng hợp lệ mặc định); ``over[<analyst>]`` = trường output."""
    feats = {"technical": tech, "regime": reg, "macro": mac, "positioning": pos, "news": nws}
    for a, f in feats.items():
        if f is not None:
            over.setdefault(a, {})
            over[a] = {"features": FEATURES[a] | f} | over[a]
    snap = build_snapshot(outputs(t0 - minutes(1), price=price, skip=skip, **over), price, t0)
    report = evaluate(snap, POLICY_V1, at or t0)
    return snap, report, fuse(snap, report)


UP = {"trend": "UP", "mtf_alignment": "ALIGNED_UP"}
DOWN = {"trend": "DOWN", "mtf_alignment": "ALIGNED_DOWN"}
TREND_UP = {"regime": "TREND", "direction": "UP", "ambiguous": False}
TREND_DOWN = {"regime": "TREND", "direction": "DOWN", "ambiguous": False}


# ---------- Bước A: hướng gốc chỉ từ giá ----------

@pytest.mark.parametrize("tech,reg,bias,drivers", [
    (UP, TREND_UP, Bias.LONG, ("PRICE_LEAN_LONG", "MTF_ALIGNED_UP")),
    ({"trend": "DOWN", "mtf_alignment": "MIXED"}, TREND_DOWN, Bias.SHORT,
     ("PRICE_LEAN_SHORT", "MTF_MIXED")),
    ({"trend": "UP", "mtf_alignment": "NOT_EVALUATED"}, TREND_UP, Bias.LONG,
     ("PRICE_LEAN_LONG", "MTF_NOT_EVALUATED")),
    ({"trend": "UP", "mtf_alignment": "CONFLICT"}, TREND_UP, Bias.NEUTRAL, ("MTF_CONFLICT",)),
    (UP, {"regime": "RANGE", "direction": None, "ambiguous": False}, Bias.NEUTRAL,
     ("REGIME_NOT_TREND:RANGE", "MTF_ALIGNED_UP")),
    (UP, {"regime": "HIGH_VOL", "direction": None, "ambiguous": False}, Bias.NEUTRAL,
     ("REGIME_NOT_TREND:HIGH_VOL", "MTF_ALIGNED_UP")),
    # RISK_OFF vẫn có hướng DI từ giá — vẫn phải NEUTRAL
    (UP, {"regime": "RISK_OFF", "direction": "UP", "ambiguous": False}, Bias.NEUTRAL,
     ("REGIME_NOT_TREND:RISK_OFF", "MTF_ALIGNED_UP")),
    (UP, TREND_UP | {"ambiguous": True}, Bias.NEUTRAL, ("REGIME_AMBIGUOUS", "MTF_ALIGNED_UP")),
    ({"trend": "FLAT", "mtf_alignment": "MIXED"}, TREND_UP, Bias.NEUTRAL,
     ("PRICE_NO_TREND", "MTF_MIXED")),
    (UP, TREND_DOWN, Bias.NEUTRAL, ("PRICE_REGIME_DISAGREE", "MTF_ALIGNED_UP")),
    (UP, TREND_UP | {"direction": None}, Bias.NEUTRAL, ("PRICE_REGIME_DISAGREE", "MTF_ALIGNED_UP")),
    # Thứ tự lý do: regime không xu hướng đứng trước mơ hồ / FLAT
    ({"trend": "FLAT", "mtf_alignment": "CONFLICT"},
     {"regime": "RANGE", "direction": None, "ambiguous": True}, Bias.NEUTRAL,
     ("REGIME_NOT_TREND:RANGE", "MTF_CONFLICT")),
])
def test_price_lean_table(t0, tech, reg, bias, drivers):
    _, _, mv = view(t0, tech=tech, reg=reg)
    assert mv.bias is bias and mv.drivers == drivers


# ---------- Bước B: nhóm khác chỉ được hạ ----------

@pytest.mark.parametrize("tech,reg,kw,opposed", [
    (UP, TREND_UP, {"mac": {"macro_bias": "HEADWIND"}}, ["macro"]),
    (UP, TREND_UP, {"mac": {"macro_bias": "SUPPORTIVE"}}, []),
    (UP, TREND_UP, {"mac": {"macro_bias": "MIXED"}}, []),
    (DOWN, TREND_DOWN, {"mac": {"macro_bias": "SUPPORTIVE"}}, ["macro"]),
    (DOWN, TREND_DOWN, {"mac": {"macro_bias": "HEADWIND"}}, []),
    (UP, TREND_UP, {"pos": {"crowding": "CROWDED_LONG"}}, ["positioning"]),
    (UP, TREND_UP, {"pos": {"crowding": "CROWDED_SHORT"}}, []),
    (DOWN, TREND_DOWN, {"pos": {"crowding": "CROWDED_SHORT"}}, ["positioning"]),
    (UP, TREND_UP, {"nws": {"tone_score": -2}}, ["news"]),
    (UP, TREND_UP, {"nws": {"tone_score": 3}}, []),
    (UP, TREND_UP, {"nws": {"tone_score": 0}}, []),
    (UP, TREND_UP, {"nws": {"tone_score": None}}, []),
    (DOWN, TREND_DOWN, {"nws": {"tone_score": 1}}, ["news"]),
])
def test_single_group_opposition(t0, tech, reg, kw, opposed):
    _, _, mv = view(t0, tech=tech, reg=reg, **kw)
    want_bias = Bias.LONG if tech is UP else Bias.SHORT
    assert mv.bias is want_bias
    assert [d.split(":")[1] for d in mv.drivers if d.startswith("OPPOSED_BY:")] == opposed
    # 0,9 (tech) × 1,0 (Gate) × 0,5 nếu bị phản đối — nhóm cùng chiều KHÔNG làm tăng
    assert mv.confidence == (0.45 if opposed else 0.9)


def test_two_groups_against_goes_neutral(t0):                   # 4-C03
    _, _, mv = view(t0, tech=UP, reg=TREND_UP, mac={"macro_bias": "HEADWIND"},
                    nws={"tone_score": -1})
    assert mv.bias is Bias.NEUTRAL
    assert mv.drivers == ("PRICE_LEAN_LONG", "MTF_ALIGNED_UP", "OPPOSED_BY:macro",
                          "OPPOSED_BY:news", "ANALYSTS_DISAGREE")
    assert mv.confidence == 0.45


def test_three_groups_against_goes_neutral(t0):
    _, _, mv = view(t0, tech=DOWN, reg=TREND_DOWN, mac={"macro_bias": "SUPPORTIVE"},
                    pos={"crowding": "CROWDED_SHORT"}, nws={"tone_score": 4})
    assert mv.bias is Bias.NEUTRAL and "ANALYSTS_DISAGREE" in mv.drivers


def test_opposition_ignored_when_neutral(t0):
    _, _, mv = view(t0, tech={"trend": "FLAT", "mtf_alignment": "MIXED"}, reg=TREND_UP,
                    mac={"macro_bias": "HEADWIND"}, nws={"tone_score": -3})
    assert mv.bias is Bias.NEUTRAL
    assert not any(d.startswith(("OPPOSED_BY", "ANALYSTS")) for d in mv.drivers)
    assert mv.confidence == 0.9


def test_supporting_groups_never_create_direction(t0):
    _, _, mv = view(t0, tech={"trend": "FLAT", "mtf_alignment": "MIXED"}, reg=TREND_UP,
                    mac={"macro_bias": "SUPPORTIVE"}, pos={"crowding": "CROWDED_SHORT"},
                    nws={"tone_score": 5})
    assert mv.bias is Bias.NEUTRAL and mv.confidence == 0.9


def test_unhealthy_optional_is_not_counted_against(t0):
    # Macro STALE (Gate gắn OPTIONAL_STALE) dù đặc trưng nói HEADWIND → không tính phản đối.
    _, report, mv = view(t0, tech=UP, reg=TREND_UP, mac={"macro_bias": "HEADWIND"})
    assert "OPPOSED_BY:macro" in mv.drivers                      # đối chứng: khỏe → có tính
    _, report, mv = view(t0, tech=UP, reg=TREND_UP,
                         macro={"source_status": SourceStatus.STALE,
                                "features": {"macro_bias": "HEADWIND"}})
    assert report.verdict is QualityVerdict.DEGRADED
    assert "OPPOSED_BY:macro" not in mv.drivers and mv.bias is Bias.LONG
    assert mv.confidence == pytest.approx(0.81)                  # 0,9 × 0,9


def test_expired_optional_is_not_counted_against(t0):
    _, _, mv = view(t0, tech=UP, reg=TREND_UP,
                    macro={"as_of": t0 - minutes(60), "features": {"macro_bias": "HEADWIND"}})
    assert "OPPOSED_BY:macro" not in mv.drivers and "OPTIONAL_EXPIRED:macro" in mv.quality_flags


# ---------- Bước C, D ----------

def test_confidence_hand_computed(t0):
    # min(0,9 tech; 0,8 regime; 1,0 event) × 0,9 (news vắng) × 0,5 (macro phản đối) = 0,36
    _, _, mv = view(t0, tech=UP, reg=TREND_UP, mac={"macro_bias": "HEADWIND"}, skip=("news",),
                    regime={"confidence": 0.8}, event={"confidence": 1.0})
    assert mv.confidence == 0.36
    assert "OPTIONAL_MISSING:news" in mv.quality_flags


def test_vol_forecast_from_technical(t0):
    _, _, mv = view(t0, tech=UP, reg=TREND_UP)
    assert mv.vol_forecast == 0.9
    _, _, mv = view(t0, tech=UP | {"vol_forecast": None}, reg=TREND_UP)
    assert mv.vol_forecast is None


def test_risk_flags_union_incl_event_window(t0):                 # 4-C04
    _, _, mv = view(t0, tech=UP, reg=TREND_UP,
                    event={"risk_flags": frozenset({"EVENT_WINDOW"})},
                    regime={"risk_flags": frozenset({"HIGH_VOLATILITY_REGIME"})},
                    news={"risk_flags": frozenset({"NEWS_SHOCK"}),
                          "source_status": SourceStatus.STALE, "features": {}})
    # Cờ rủi ro của nguồn tùy chọn không khỏe vẫn giữ (thêm cờ = thận trọng hơn).
    assert mv.risk_flags == {"EVENT_WINDOW", "HIGH_VOLATILITY_REGIME", "NEWS_SHOCK"}


def test_quality_flags(t0):
    _, _, mv = view(t0, price=SAMPLE, tech=UP, reg=TREND_UP, skip=("positioning",),
                    macro={"quality_flags": frozenset({"EXTREME_INPUT:real_yield_10y"})})
    assert {"UNVALIDATED_RULES", "UNCALIBRATED", "SAMPLE_DATA", "OPTIONAL_MISSING:positioning",
            "macro:EXTREME_INPUT:real_yield_10y"} <= mv.quality_flags
    assert mv.p_up is None and mv.p_down is None


def test_regime_and_meta_fields(t0):
    snap, report, mv = view(t0, tech=UP, reg=TREND_UP)
    assert mv.regime is Regime.TREND
    assert (mv.source, mv.feed_id, mv.symbol, mv.timeframe) == ("MT5", "f1", "XAUUSD", "M15")
    assert mv.snapshot_id == snap.snapshot_id and mv.as_of == report.evaluated_at == t0
    assert (mv.model_version, mv.quality_policy_version) == ("fusion-rules-1.0.0",
                                                             "quality-policy-1")


def test_expiry_is_snapshot_expiry_capped(t0):
    snap, _, mv = view(t0, tech=UP, reg=TREND_UP)
    assert mv.expires_at == snap.expires_at                       # event 15 phút
    long_ttl = {a: {"ttl": 600} for a in ("technical", "regime", "event")}
    _, _, mv = view(t0, tech=UP, reg=TREND_UP, **long_ttl)
    assert mv.expires_at == t0 + minutes(30)                      # trần cứng


def test_rejected_gives_no_market_view(t0):                      # 4-C01 → không có MarketView
    snap, report, mv = view(t0, skip=("event",))
    assert report.verdict is QualityVerdict.REJECTED and mv is None


def test_report_of_other_snapshot_raises(t0):
    snap, _, _ = view(t0)
    _, other, _ = view(t0, tech=UP, reg=TREND_UP, skip=("news",))
    with pytest.raises(ValueError, match="không phải của snapshot"):
        fuse(snap, other)


def test_market_view_id_deterministic_and_tracks_report(t0):
    snap, report, mv = view(t0, tech=UP, reg=TREND_UP, news={"ttl": 10})   # News hết hạn t0+9
    assert fuse(snap, report).market_view_id == mv.market_view_id
    assert mv.market_view_id.startswith("mv:fusion-rules-1.0.0:MT5:f1:XAUUSD:M15:")
    # Cùng snapshot, lúc sau News (tùy chọn) hết hạn → báo cáo khác → MarketView khác id.
    later = evaluate(snap, POLICY_V1, t0 + minutes(12))
    mv2 = fuse(snap, later)
    assert later.report_id != report.report_id and mv2.market_view_id != mv.market_view_id


def test_fusion_constants_fingerprint():
    # Đổi luật / hệ số mà không tăng FUSION_VERSION → test này đỏ.
    assert (FU.FUSION_VERSION, FU.OPPOSED_FACTOR, FU.DISAGREE_MIN_GROUPS, FU.MAX_TTL,
            FU.OPTIONAL_GROUPS) == ("fusion-rules-1.0.0", 0.5, 2, minutes(30),
                                    ("macro", "positioning", "news"))
