"""MT-04, MT-11, DEC-16: token Gateway riêng từng tài khoản, lưu băm, ADMIN cấp lại.

Case MT-C02 + DEC-16: USER bị khóa → Gateway của họ bị từ chối; mở khóa → token cũ dùng lại.
"""

from __future__ import annotations

import json

from gold_trading.common.time import utcnow
from gold_trading.contracts.candle import DataSource
from gold_trading.market.timeframes import Timeframe
from gold_trading.storage.candles import InMemoryCandleStore
from gold_trading.storage.repository import InMemoryRepository, Member, TradingAccount
from tests.auth_helpers import client, login_owner, make_app
from tests.test_ingest_api import HB, bars, batch

LEGACY = "L" * 32
HB_PATH = "/api/ingest/mt5/heartbeat"


def world(legacy: str | None = LEGACY):
    repo = InMemoryRepository()
    store = InMemoryCandleStore()
    app, kc = make_app(repo, candle_store=store, data_source=DataSource.MT5,
                       run_analysts=False, ingest_token=legacy)
    admin = client(app)
    kc.login(admin, "admin", admin=True)
    trader = login_owner(app, kc, repo, "trader")
    return repo, store, app, kc, admin, trader


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def rotate(admin, sub="sub-trader"):
    r = admin.post(f"/api/admin/users/{sub}/gateway-token")
    assert r.status_code == 200, r.text
    return r


def test_rotation_issues_token_once_and_disables_legacy():
    repo, store, _, _, admin, trader = world()
    assert trader.post(HB_PATH, json=HB, headers=bearer(LEGACY)).status_code == 200
    info = trader.get("/api/accounts/default/gateway/token").json()
    assert info == {"has_token": False, "legacy_token_active": True, "price_feed": True,
                    "request_status": "NONE", "requested_at": None}

    r = rotate(admin)
    tok = r.json()["token"]
    assert tok.startswith("gtk_") and len(tok) >= 40
    assert r.headers["cache-control"] == "no-store"
    # Token cũ trong .env hết hiệu lực NGAY khi đã có token cấp trên giao diện
    assert trader.post(HB_PATH, json=HB, headers=bearer(LEGACY)).status_code == 401
    assert trader.post(HB_PATH, json=HB, headers=bearer(tok)).status_code == 200
    info = trader.get("/api/accounts/default/gateway/token").json()
    assert info["has_token"] is True and info["legacy_token_active"] is False

    tok2 = rotate(admin).json()["token"]
    assert trader.post(HB_PATH, json=HB, headers=bearer(tok)).status_code == 401  # cũ chết ngay
    r = trader.post("/api/ingest/mt5/candles", json=batch(bars(50)), headers=bearer(tok2))
    assert r.status_code == 200 and r.json()["accepted"] == 50


def test_token_never_stored_or_audited_in_clear():
    repo, _, _, _, admin, trader = world()
    tok = rotate(admin).json()["token"]
    dumped = json.dumps([e.__dict__ for e in repo.audit(500)], default=str)
    assert tok not in dumped
    assert tok not in json.dumps(repo._tokens, default=str)  # chỉ băm
    for path in ("/api/accounts/default/gateway/token", "/api/accounts/default/status",
                 "/api/accounts/default/audit", "/api/accounts"):
        assert tok not in trader.get(path).text
    assert tok not in admin.get("/api/admin/users").text


def test_only_admin_issues_tokens_and_only_for_the_users_own_account():
    repo, _, app, kc, admin, trader = world()
    # USER không tự cấp token (DEC-16: token do ADMIN cấp, ADMIN cấu hình máy chung)
    assert trader.post("/api/accounts/default/gateway/token").status_code == 405
    assert trader.post("/api/admin/users/sub-trader/gateway-token").status_code == 403
    assert not repo.has_gateway_tokens("default")
    # Token luôn cấp cho tài khoản của chính USER đó (không nhận account_id từ ngoài)
    login_owner(app, kc, repo, "bob", account="acc_b")
    tok = rotate(admin, "sub-bob").json()
    assert tok["account_id"] == "acc_b" and not repo.has_gateway_tokens("default")
    # Người không phải USER (ADMIN) → 404, không sinh token
    sub_admin = next(u.sub for u in kc.users.values() if u.username == "admin")
    repo.create_account(TradingAccount("acc_c", "C", utcnow(), "t", price_feed=False))
    repo.set_member(Member("acc_c", sub_admin, "OWNER", utcnow(), "t"))
    assert admin.post(f"/api/admin/users/{sub_admin}/gateway-token").status_code == 404
    assert not repo.has_gateway_tokens("acc_c")


def test_gateway_of_a_cannot_write_into_b():
    """MT-C02."""
    repo, store, app, kc, admin, trader = world()
    bob = login_owner(app, kc, repo, "bob", account="acc_b")
    tok_default = rotate(admin).json()["token"]
    tok_b = rotate(admin, "sub-bob").json()["token"]

    # Token của acc_b mà khai account_id=default → 403
    r = trader.post(HB_PATH, json=HB | {"account_id": "default"}, headers=bearer(tok_b))
    assert r.status_code == 403
    r = trader.post("/api/ingest/mt5/candles", json=batch(bars(5)) | {"account_id": "default"},
                    headers=bearer(tok_b))
    assert r.status_code == 403
    # acc_b chưa được ghi nến dùng chung (tới MT-05): nến bị từ chối, nhịp tim được nhận
    r = trader.post("/api/ingest/mt5/candles", json=batch(bars(5)), headers=bearer(tok_b))
    assert r.status_code == 403
    assert store.stats("XAUUSD", Timeframe.M15, DataSource.MT5).count == 0
    assert trader.post(HB_PATH, json=HB, headers=bearer(tok_b)).status_code == 200
    # Trạng thái Gateway tách theo tài khoản
    assert bob.get("/api/accounts/acc_b/gateway/status").json()["state"] == "CONNECTED"
    assert trader.get("/api/accounts/default/gateway/status").json()["state"] == "NEVER"
    # Token đúng tài khoản + đúng account_id → được
    r = trader.post("/api/ingest/mt5/candles", json=batch(bars(5)) | {"account_id": "default"},
                    headers=bearer(tok_default))
    assert r.status_code == 200


def test_locked_user_gateway_is_refused_and_unlock_reuses_same_token():
    repo, store, _, _, admin, trader = world()
    tok = rotate(admin).json()["token"]
    assert trader.post(HB_PATH, json=HB, headers=bearer(tok)).status_code == 200
    repo.set_user_status("sub-trader", "LOCKED", utcnow())
    assert trader.post(HB_PATH, json=HB, headers=bearer(tok)).status_code == 403
    r = trader.post("/api/ingest/mt5/candles", json=batch(bars(5)), headers=bearer(tok))
    assert r.status_code == 403
    assert store.stats("XAUUSD", Timeframe.M15, DataSource.MT5).count == 0
    repo.set_user_status("sub-trader", "ACTIVE", utcnow())
    assert trader.post(HB_PATH, json=HB, headers=bearer(tok)).status_code == 200


def test_ingest_closed_when_no_token_anywhere():
    _, _, _, _, admin, trader = world(legacy=None)
    r = trader.post(HB_PATH, json=HB, headers=bearer("x" * 40))
    assert r.status_code == 503
    rotate(admin)
    r = trader.post(HB_PATH, json=HB, headers=bearer("x" * 40))
    assert r.status_code == 401
    assert trader.post(HB_PATH, json=HB).status_code == 401
