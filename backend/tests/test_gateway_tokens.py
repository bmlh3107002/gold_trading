"""MT-04, MT-11: token Gateway riêng từng tài khoản, lưu băm, xoay vòng. Case MT-C02."""

from __future__ import annotations

import json

from gold_trading.common.time import utcnow
from gold_trading.contracts.candle import DataSource
from gold_trading.storage.candles import InMemoryCandleStore
from gold_trading.storage.repository import InMemoryRepository, Member
from tests.auth_helpers import client, make_app
from tests.test_ingest_api import HB, bars, batch

LEGACY = "L" * 32


def world(legacy: str | None = LEGACY):
    repo = InMemoryRepository()
    store = InMemoryCandleStore()
    app, kc = make_app(repo, candle_store=store, data_source=DataSource.MT5,
                       run_analysts=False, ingest_token=legacy)
    admin = client(app)
    kc.login(admin, "admin", admin=True)
    return repo, store, app, kc, admin


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def rotate(c, acc="default"):
    r = c.post(f"/api/accounts/{acc}/gateway/token")
    assert r.status_code == 200, r.text
    return r


def test_rotation_issues_token_once_and_disables_legacy():
    repo, store, _, _, admin = world()
    hb = "/api/ingest/mt5/heartbeat"
    assert admin.post(hb, json=HB, headers=bearer(LEGACY)).status_code == 200
    info = admin.get("/api/accounts/default/gateway/token").json()
    assert info == {"has_token": False, "legacy_token_active": True, "price_feed": True}

    r = rotate(admin)
    tok = r.json()["token"]
    assert tok.startswith("gtk_") and len(tok) >= 40
    assert r.headers["cache-control"] == "no-store"
    # Token cũ trong .env hết hiệu lực NGAY khi đã có token trên giao diện
    assert admin.post(hb, json=HB, headers=bearer(LEGACY)).status_code == 401
    assert admin.post(hb, json=HB, headers=bearer(tok)).status_code == 200
    info = admin.get("/api/accounts/default/gateway/token").json()
    assert info["has_token"] is True and info["legacy_token_active"] is False

    tok2 = rotate(admin).json()["token"]
    assert admin.post(hb, json=HB, headers=bearer(tok)).status_code == 401  # token cũ chết ngay
    r = admin.post("/api/ingest/mt5/candles", json=batch(bars(50)), headers=bearer(tok2))
    assert r.status_code == 200 and r.json()["accepted"] == 50


def test_token_never_stored_or_audited_in_clear():
    repo, _, _, _, admin = world()
    tok = rotate(admin).json()["token"]
    dumped = json.dumps([e.__dict__ for e in repo.audit(500)], default=str)
    assert tok not in dumped
    assert tok not in json.dumps(repo._tokens, default=str)  # chỉ băm
    for path in ("/api/accounts/default/gateway/token", "/api/accounts/default/status",
                 "/api/accounts/default/audit", "/api/accounts"):
        assert tok not in admin.get(path).text


def test_rotate_requires_owner_or_admin():
    repo, _, app, kc, admin = world()
    v = client(app)
    kc.login(v, "vera")
    assert v.post("/api/accounts/default/gateway/token").status_code == 404  # không thành viên
    repo.set_member(Member("default", "sub-vera", "OPERATOR", utcnow(), "t"))
    assert v.post("/api/accounts/default/gateway/token").status_code == 403
    assert v.get("/api/accounts/default/gateway/status").status_code == 200
    # ADMIN không là thành viên vẫn xoay được (ma trận quyền)
    admin.post("/api/accounts", json={"account_id": "acc_b", "name": "B"})
    assert admin.post("/api/accounts/acc_b/gateway/token").status_code == 200


def test_gateway_of_a_cannot_write_into_b():
    """MT-C02."""
    repo, store, _, _, admin = world()
    admin.post("/api/accounts", json={"account_id": "acc_b", "name": "B"})
    tok_default = rotate(admin).json()["token"]
    tok_b = rotate(admin, "acc_b").json()["token"]

    # Token của acc_b mà khai account_id=default → 403
    r = admin.post("/api/ingest/mt5/heartbeat", json=HB | {"account_id": "default"},
                   headers=bearer(tok_b))
    assert r.status_code == 403
    r = admin.post("/api/ingest/mt5/candles", json=batch(bars(5)) | {"account_id": "default"},
                   headers=bearer(tok_b))
    assert r.status_code == 403
    # acc_b chưa được ghi nến dùng chung (tới MT-05): nến bị từ chối, nhịp tim được nhận
    r = admin.post("/api/ingest/mt5/candles", json=batch(bars(5)), headers=bearer(tok_b))
    assert r.status_code == 403
    assert store.stats("XAUUSD", "M15", DataSource.MT5).count == 0
    assert admin.post("/api/ingest/mt5/heartbeat", json=HB,
                      headers=bearer(tok_b)).status_code == 200
    # Trạng thái Gateway tách theo tài khoản
    assert admin.get("/api/accounts/acc_b/gateway/status").json()["state"] == "CONNECTED"
    assert admin.get("/api/accounts/default/gateway/status").json()["state"] == "NEVER"
    # Token đúng tài khoản + đúng account_id → được
    r = admin.post("/api/ingest/mt5/candles", json=batch(bars(5)) | {"account_id": "default"},
                   headers=bearer(tok_default))
    assert r.status_code == 200


def test_ingest_closed_when_no_token_anywhere():
    _, _, _, _, admin = world(legacy=None)
    r = admin.post("/api/ingest/mt5/heartbeat", json=HB, headers=bearer("x" * 40))
    assert r.status_code == 503
    rotate(admin)
    r = admin.post("/api/ingest/mt5/heartbeat", json=HB, headers=bearer("x" * 40))
    assert r.status_code == 401
    assert admin.post("/api/ingest/mt5/heartbeat", json=HB).status_code == 401
