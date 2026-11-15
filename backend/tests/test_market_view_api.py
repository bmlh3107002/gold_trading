"""GĐ4 bước 6 — API MarketView theo tài khoản (MKV-03; MT-05; DEC-25, DEC-27)."""

from datetime import timedelta

from gold_trading.common.time import utcnow
from gold_trading.contracts.candle import DataSource
from gold_trading.storage.repository import InMemoryRepository
from tests.auth_helpers import user_client
from tests.test_fusion import SAMPLE, TREND_UP, UP, view

URL = "/api/accounts/default/market-view/latest"


def client():
    return user_client(InMemoryRepository(), data_source=DataSource.SAMPLE,
                       run_sample_feed=False, run_analysts=False, external_runner=None)


def put(c, t, **kw):
    snap, report, mv = view(t, price=SAMPLE, tech=UP, reg=TREND_UP, **kw)
    c.app.state.quality_reports.append(report)
    assert c.app.state.market_views.append(mv, report_id=report.report_id, computed_at=t)
    return mv, report


def test_none_before_any_view():
    c = client()
    body = c.get(URL).json()
    assert body["state"] == "NONE" and body["market_view"] is None
    assert body["is_sample"] is True and body["rules_validated"] is False
    assert c.get("/api/accounts/default/status").json()["market_view"] is None


def test_valid_view_and_status_use_it():
    c = client()
    mv, report = put(c, utcnow() - timedelta(minutes=1))
    body = c.get(URL).json()
    assert body["state"] == "VALID"
    got = body["market_view"]
    assert got["market_view_id"] == mv.market_view_id and got["bias"] == "LONG"
    assert got["p_up"] is None and got["p_down"] is None                     # DEC-27
    assert {"UNVALIDATED_RULES", "UNCALIBRATED", "SAMPLE_DATA"} <= set(got["quality_flags"])
    assert body["gate"]["verdict"] == report.verdict.value
    status = c.get("/api/accounts/default/status").json()
    assert status["market_view"]["market_view_id"] == mv.market_view_id


def test_expired_view_not_returned():
    c = client()
    mv, _ = put(c, utcnow() - timedelta(minutes=20))                         # hạn 15 phút
    body = c.get(URL).json()
    assert body["state"] == "EXPIRED" and body["market_view"] is None
    assert body["last_expires_at"] is not None
    assert c.get("/api/accounts/default/status").json()["market_view"] is None


def test_invalidated_view_shows_reason():
    c = client()
    now = utcnow()
    mv, _ = put(c, now - timedelta(minutes=1))
    c.app.state.market_views.invalidate(mv.market_view_id, at=now - timedelta(seconds=5),
                                        reason="QUALITY_REJECTED")
    body = c.get(URL).json()
    assert body["state"] == "INVALIDATED" and body["market_view"] is None
    assert body["invalidation_reason"] == "QUALITY_REJECTED"


def test_rejected_gate_reasons_visible():
    c = client()
    _, report, mv = view(utcnow() - timedelta(minutes=1), price=SAMPLE, skip=("event",))
    assert mv is None
    c.app.state.quality_reports.append(report)
    body = c.get(URL).json()
    assert body["state"] == "NONE"
    assert body["gate"]["verdict"] == "REJECTED"
    assert body["gate"]["reasons"] == ["REQUIRED_MISSING:event"]


def test_other_account_forbidden_and_login_required():
    c = client()
    assert c.get("/api/accounts/khac/market-view/latest").status_code == 404
    from fastapi.testclient import TestClient
    anon = TestClient(c.app)
    assert anon.get(URL).status_code == 401
