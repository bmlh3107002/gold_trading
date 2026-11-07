"""MT-12 + GW-09: nhịp tim mang danh tính MT5 (login, server…), số liệu tài khoản, thông số symbol.

Trường hợp xấu: Gateway cũ (không có trường mới), NaN/Inf, số âm, login 0, danh tính mâu thuẫn
với trường cũ, có số liệu tài khoản mà không có danh tính, chuỗi quá dài.
"""

import json

import pytest

from tests.test_ingest_api import AUTH, HB, client

PATH = "/api/ingest/mt5/heartbeat"
STATUS = "/api/accounts/default/gateway/status"

IDENT = {
    "login": 51234567,
    "server": "Broker-Demo",
    "company": "Demo Broker Ltd",
    "account_type": "DEMO",
    "terminal_name": "MetaTrader 5",
    "terminal_path": r"C:\Program Files\MetaTrader 5",
}
ACC = {
    "currency": "USD",
    "balance": 10000.0,
    "equity": 10012.5,
    "margin": 0.0,
    "margin_free": 10012.5,
    "margin_level": None,
    "leverage": 100,
    "trade_allowed": True,
}
SYM_EXTRA = {
    "stops_level": 10,
    "freeze_level": 5,
    "swap_mode": 1,
    "swap_long": -25.3,
    "swap_short": 8.1,
    "swap_rollover3days": 3,
}
FULL = HB | {
    "gateway_version": "0.3.0",
    "company": "Demo Broker Ltd",
    "identity": IDENT,
    "account": ACC,
    "symbol": HB["symbol"] | SYM_EXTRA,
}


def test_full_heartbeat_is_stored_and_shown_to_owner():
    c, _ = client()
    assert c.post(PATH, json=FULL, headers=AUTH).status_code == 200
    hb = c.get(STATUS).json()["heartbeat"]
    assert hb["identity"] == IDENT
    assert hb["account"]["equity"] == 10012.5 and hb["account"]["leverage"] == 100
    assert hb["account"]["margin_level"] is None
    assert hb["symbol"]["stops_level"] == 10 and hb["symbol"]["swap_long"] == -25.3
    assert "commission" not in hb["symbol"]


def test_old_gateway_without_new_fields_still_accepted():
    c, _ = client()
    assert c.post(PATH, json=HB, headers=AUTH).status_code == 200
    hb = c.get(STATUS).json()["heartbeat"]
    assert hb["identity"] is None and hb["account"] is None
    assert hb["symbol"]["stops_level"] is None and hb["symbol"]["swap_long"] is None


def test_logged_out_terminal_no_identity_no_account():
    c, _ = client()
    body = HB | {"account_type": "UNKNOWN", "server": None, "identity": None, "account": None}
    assert c.post(PATH, json=body, headers=AUTH).status_code == 200
    assert c.get(STATUS).json()["heartbeat"]["identity"] is None


def _raw(c, body: str):
    return c.post(PATH, content=body, headers=AUTH | {"Content-Type": "application/json"})


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_rejected(bad):
    c, _ = client()
    for path in (("account", "equity"), ("symbol", "swap_long"), ("symbol", "point")):
        body = json.loads(json.dumps(FULL))
        body[path[0]][path[1]] = "__X__"
        r = _raw(c, json.dumps(body).replace('"__X__"', bad))
        assert r.status_code == 422, (path, bad)
    assert c.get(STATUS).json()["state"] == "NEVER"  # không ghi nhịp tim hỏng


@pytest.mark.parametrize(
    "patch",
    [
        {"identity": IDENT | {"login": 0}},
        {"identity": IDENT | {"login": -5}},
        {"identity": IDENT | {"login": 2**63}},
        {"identity": IDENT | {"server": ""}},
        {"identity": IDENT | {"server": "x" * 257}},
        {"identity": IDENT | {"account_type": "LIVE"}},
        {"account": ACC | {"leverage": 0}},
        {"account": ACC | {"margin": -1.0}},
        {"symbol": HB["symbol"] | {"stops_level": -1}},
        {"symbol": HB["symbol"] | {"swap_rollover3days": 7}},
        {"symbol": HB["symbol"] | {"point": 0}},
        {"symbol": HB["symbol"] | {"volume_step": -0.01}},
    ],
)
def test_bad_values_rejected(patch):
    c, _ = client()
    assert c.post(PATH, json=FULL | patch, headers=AUTH).status_code == 422


def test_identity_must_match_legacy_fields():
    """Trường cũ và ``identity`` đến từ một lần đọc; lệch → từ chối, không chọn bừa một bên."""
    c, _ = client()
    for patch in (
        {"server": "Other-Server"},
        {"account_type": "REAL"},
        {"identity": IDENT | {"server": "Other-Server"}},
    ):
        assert c.post(PATH, json=FULL | patch, headers=AUTH).status_code == 422, patch


def test_account_without_identity_rejected():
    c, _ = client()
    assert c.post(PATH, json=FULL | {"identity": None}, headers=AUTH).status_code == 422


def test_login_change_between_heartbeats_is_reported_as_is():
    """MT-12 chỉ báo; MT-14 (bước sau) mới chuyển MISMATCH. Ở đây: trạng thái hiện login mới,
    không giữ login cũ."""
    c, _ = client()
    assert c.post(PATH, json=FULL, headers=AUTH).status_code == 200
    new = IDENT | {"login": 99887766, "server": "Other-Live", "account_type": "REAL"}
    body = FULL | {"identity": new, "server": "Other-Live", "account_type": "REAL"}
    assert c.post(PATH, json=body, headers=AUTH).status_code == 200
    hb = c.get(STATUS).json()["heartbeat"]
    assert hb["identity"]["login"] == 99887766 and hb["account_type"] == "REAL"


def test_identity_not_visible_to_anon_admin_or_other_user():
    """Login MT5, số dư chỉ chủ tài khoản thấy. ADMIN chỉ thấy trạng thái kết nối (DEC-15/16)."""
    from tests.auth_helpers import client as web_client
    from tests.test_admin_users import URL, create, issue
    from tests.test_admin_users_dec17 import bearer, lan_world

    repo, app, kc, admin, me, sub = lan_world()
    tok = issue(admin, sub)
    gw = web_client(app)
    assert gw.post(PATH, json=FULL, headers=bearer(tok)).status_code == 200
    own = "/api/accounts/u-lanng/gateway/status"
    assert me.get(own).json()["heartbeat"]["identity"]["login"] == 51234567
    # ẩn danh
    assert web_client(app).get(own).status_code == 401
    # ADMIN: không vào được trạng thái chi tiết, danh sách không lộ login/số dư
    assert admin.get(own).status_code in (403, 404)
    listing = json.dumps(admin.get(URL).json())
    assert "51234567" not in listing and "10012.5" not in listing
    # USER khác
    create(admin, username="minhtv", email="minh@example.com")
    other = web_client(app)
    kc.login(other, "minhtv")
    assert other.get(own).status_code in (403, 404)
