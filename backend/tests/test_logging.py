"""OPS-11, MT-11: log JSON + correlation id; case 0-C18 — bí mật không xuất hiện trong log."""

from __future__ import annotations

import io
import json
import logging
from urllib.parse import parse_qs, urlsplit

import pytest

from gold_trading.contracts.candle import DataSource
from gold_trading.ops.logging import JsonFormatter, configure_logging, redact
from gold_trading.storage.repository import InMemoryRepository
from tests.auth_helpers import CLIENT_SECRET, client, make_app
from tests.test_ingest_api import HB, bars, batch

LEGACY = "legacy-ingest-token-ABCDEFGHIJ0123"


@pytest.fixture
def captured():
    buf = io.StringIO()
    root = logging.getLogger()
    old_handlers, old_level = list(root.handlers), root.level
    configure_logging("DEBUG", stream=buf)
    yield buf
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in old_handlers:
        root.addHandler(h)
    root.setLevel(old_level)


@pytest.mark.parametrize(
    "raw,secret",
    [
        ("Authorization: Bearer abc.DEF-123_xyz", "abc.DEF-123_xyz"),
        ("token gtk_AbCdEfGhIjKlMnOpQrStUv0123456789", "gtk_AbCdEfGhIjKlMnOp"),
        ("GET /api/auth/callback?code=SECRETCODE&state=SECRETSTATE", "SECRETCODE"),
        ("GET /api/auth/callback?code=SECRETCODE&state=SECRETSTATE", "SECRETSTATE"),
        ("cookie: __Host-gt_session=sessvalue123; other=1", "sessvalue123"),
        ('{"client_secret": "topsecret", "x": 1}', "topsecret"),
        ("password=hunter2&user=a", "hunter2"),
        ("postgresql+psycopg://gold:dbpass@db:5432/gold", "dbpass"),
        ("id eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl", "eyJzdWIiOiJ4In0"),
        ("refresh_token='rt_value'", "rt_value"),
    ],
)
def test_redact_patterns(raw, secret):
    assert secret not in redact(raw)


def test_json_format_and_correlation_id(captured):
    app, kc = make_app(InMemoryRepository(), data_source=None)
    c = client(app)
    r = c.get("/api/health", headers={"X-Request-ID": "req-123"})
    assert r.headers["x-request-id"] == "req-123"
    r = c.get("/api/auth/me", headers={"X-Request-ID": "bad id with spaces"})
    rid = r.headers["x-request-id"]
    assert rid != "bad id with spaces" and len(rid) == 32
    lines = [json.loads(x) for x in captured.getvalue().splitlines() if x.strip()]
    access = [x for x in lines if x["logger"] == "gold_trading.access"]
    assert access and access[-1]["correlation_id"] == rid and access[-1]["status"] == 401
    assert access[-1]["path"] == "/api/auth/me"
    assert all({"ts", "level", "logger", "msg", "correlation_id"} <= set(x) for x in lines)


def test_no_secret_in_logs_after_full_flow(captured, caplog):
    """0-C18: đăng nhập, callback, làm mới, ingest có token, xoay token, đăng xuất, lỗi cố ý."""
    repo = InMemoryRepository()
    app, kc = make_app(repo, data_source=DataSource.MT5, run_analysts=False,
                       ingest_token=LEGACY, auth_cfg={"multi_user_enabled": True})
    c = client(app)
    secrets: set[str] = {CLIENT_SECRET, LEGACY}

    # Đăng nhập: thu lại state, nonce, code, cookie, token do Keycloak giả cấp
    user = kc.add_user("alice", admin=True)
    r = c.get("/api/auth/login", follow_redirects=False)
    q = {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}
    secrets |= {q["state"], q["nonce"], q["code_challenge"]}
    kc.codes["SECRETAUTHCODE123"] = (user.sub, q["nonce"], q["code_challenge"])
    secrets.add("SECRETAUTHCODE123")
    c.get("/api/auth/callback", params={"code": "SECRETAUTHCODE123", "state": q["state"]},
          follow_redirects=False)
    secrets.add(c.cookies.get("__Host-gt_session"))
    for form in kc.token_requests:
        secrets |= {v for k, v in form.items() if k in ("code_verifier", "refresh_token")}
    secrets |= set(kc.refresh_tokens)

    # Ingest có token, xoay token, dùng token mới, token sai
    auth = {"Authorization": f"Bearer {LEGACY}"}
    c.post("/api/ingest/mt5/heartbeat", json=HB, headers=auth)
    # ADMIN tạo USER (mật khẩu tạm tự sinh)
    created = c.post("/api/admin/users", json={
        "username": "bob", "email": "bob@example.com", "first_name": "B", "last_name": "C",
    }).json()
    # DEC-17: token do ADMIN cấp sau khi tạo
    tok = c.post(f"/api/admin/users/{created['sub']}/gateway-token").json()["token"]
    secrets |= {tok, created["temporary_password"]}
    reset = c.post(f"/api/admin/users/{created['sub']}/reset-password").json()
    secrets.add(reset["temporary_password"])
    c.post("/api/ingest/mt5/candles", json=batch(bars(10)),
           headers={"Authorization": f"Bearer {tok}"})
    c.post("/api/ingest/mt5/heartbeat", json=HB, headers={"Authorization": "Bearer wrongtoken"})

    # Một module vô ý log bí mật → vẫn bị che
    logging.getLogger("gold_trading.test").warning(
        "debug dump: token=%s cookie=__Host-gt_session=%s secret=%s",
        tok, c.cookies.get("__Host-gt_session"), CLIENT_SECRET,
    )
    try:
        raise RuntimeError(f"boom Bearer {tok}")
    except RuntimeError:
        logging.getLogger("gold_trading.test").exception("lỗi có bí mật")

    r = c.post("/api/auth/logout")
    secrets.add(parse_qs(urlsplit(r.json()["logout_url"]).query)["id_token_hint"][0])

    out = captured.getvalue()
    secrets.discard(None)  # type: ignore[arg-type]
    leaked = [s for s in secrets if s and s in out]
    assert leaked == [], f"lộ trong log: {[s[:6] + '…' for s in leaked]}"
    access = [json.loads(x) for x in out.splitlines() if '"gold_trading.access"' in x]
    assert access and all("?" not in a["path"] for a in access)  # không có query string


def test_formatter_survives_bad_args():
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "a %s %s", ("only-one",), None)
    out = json.loads(JsonFormatter().format(rec))
    assert out["msg"] == "a %s %s"
