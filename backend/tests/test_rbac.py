"""DEC-16 (thay OPS-17): chỉ ADMIN | USER. Cách ly tài khoản, Safety/Mode riêng, duyệt LIVE.

Case: 0-C13, 0-C16, MT-C01, MT-C03, MT-C06 + case DEC-16 (ADMIN không vào tài khoản giao dịch,
vai trò cũ OPERATOR/VIEWER không cho quyền gì, USER bị khóa không có lệnh mới).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from gold_trading.accounts.access import decide
from gold_trading.common.enums import SafetyState, TradingMode
from gold_trading.common.ids import new_id
from gold_trading.common.time import utcnow
from gold_trading.contracts.candle import DataSource
from gold_trading.contracts.safety import SafetyTransition
from gold_trading.modes.manager import LIVE_CHECKLIST
from gold_trading.storage.repository import (
    InMemoryRepository,
    Member,
    StaleStateError,
    TradingAccount,
)
from tests.auth_helpers import FakeKeycloak, client, make_app

FULL_CHECKLIST = {k: True for k in LIVE_CHECKLIST}

ACCOUNT_ROUTES = [
    ("GET", "/api/accounts/{a}/status", None),
    ("GET", "/api/accounts/{a}/audit", None),
    ("POST", "/api/accounts/{a}/safety", {"action": "halt", "reason_code": "X"}),
    ("POST", "/api/accounts/{a}/mode", {"mode": "BACKTEST"}),
    ("GET", "/api/accounts/{a}/mode/live-requests", None),
    ("POST", "/api/accounts/{a}/mode/live-requests", {"checklist": {}}),
    ("GET", "/api/accounts/{a}/gateway/status", None),
    ("GET", "/api/accounts/{a}/gateway/token", None),
]


class World:
    """Một app + Keycloak giả: ``admin`` (ADMIN) và ``trader`` (USER, chủ ``default``)."""

    def __init__(self, **kw) -> None:
        self.repo = kw.pop("repo", None) or InMemoryRepository()
        kw.setdefault("data_source", DataSource.MT5)
        kw.setdefault("run_analysts", False)
        self.kc = FakeKeycloak()
        self.app, _ = make_app(self.repo, self.kc, **kw)
        self.clients = {}
        self.user("admin", admin=True)
        self.user("trader")
        self.grant("trader", "default")

    def user(self, name: str, *, admin: bool = False):
        c = client(self.app)
        self.kc.login(c, name, admin=admin)
        self.clients[name] = c
        return c

    def grant(self, name: str, account: str = "default", role: str = "OWNER") -> None:
        self.repo.set_member(Member(account, f"sub-{name}", role, utcnow(), "test"))

    def create_account(self, account_id: str) -> None:
        self.repo.create_account(TradingAccount(account_id, account_id, utcnow(), "test",
                                                price_feed=False))
        self.app.state.registry.add(account_id)

    def lock(self, name: str) -> None:
        self.repo.set_user_status(f"sub-{name}", "LOCKED", utcnow())

    def denied(self, action: str | None = None):
        return [e for e in self.repo.audit(500) if e.action == "access.denied"
                and (action is None or e.payload.get("action") == action)]


def halt(c, acc="default", reason="X"):
    return c.post(f"/api/accounts/{acc}/safety", json={"action": "halt", "reason_code": reason})


def resume(c, acc="default", approved=False):
    return c.post(f"/api/accounts/{acc}/safety",
                  json={"action": "resume", "reason_code": "R", "operator_approved": approved})


def state(c, acc="default"):
    return c.get(f"/api/accounts/{acc}/status").json()["safety_state"]


# ---------- Quy tắc ----------


def test_decide_rules():
    assert decide(is_admin=False, owns=True, status="ACTIVE") == "ok"
    assert decide(is_admin=False, owns=True, status="LOCKED") == "locked"
    assert decide(is_admin=False, owns=True, status=None) == "locked"  # thiếu hồ sơ → chặn
    assert decide(is_admin=False, owns=False, status="ACTIVE") == "not_found"
    # ADMIN không bao giờ vào tài khoản giao dịch, kể cả khi có dòng sở hữu (dữ liệu cũ)
    assert decide(is_admin=True, owns=True, status="ACTIVE") == "not_found"


def test_admin_cannot_touch_any_trading_account_even_with_legacy_membership():
    w = World()
    admin = w.clients["admin"]
    w.grant("admin", "default")  # dòng OWNER cũ từ trước DEC-16
    for method, path, body in ACCOUNT_ROUTES:
        r = admin.request(method, path.format(a="default"), json=body)
        assert r.status_code == 404, (path, r.status_code)
    assert admin.get("/api/accounts").json() == []
    assert len(w.denied()) == len(ACCOUNT_ROUTES)
    assert all("ADMIN" in (e.detail or "") for e in w.denied())
    assert state(w.clients["trader"]) == "PAUSED"  # không đổi gì
    # Kill switch toàn hệ thống trên Dashboard đã bỏ (DEC-16; break-glass CLI vẫn còn)
    assert admin.post("/api/admin/kill-switch", json={"reason_code": "X"}).status_code == 404


def test_legacy_operator_and_viewer_rows_grant_nothing():
    """Bỏ vai trò trung gian không được vô tình mở rộng quyền: dòng cũ ≠ OWNER → không quyền."""
    w = World()
    for name, role in (("olga", "OPERATOR"), ("vera", "VIEWER")):
        c = w.user(name)
        w.grant(name, "default", role)
        for method, path, body in ACCOUNT_ROUTES:
            assert c.request(method, path.format(a="default"), json=body).status_code == 404
        assert c.get("/api/accounts").json() == []
    assert state(w.clients["trader"]) == "PAUSED"


# ---------- Cách ly tài khoản (MT-C01, MT-C03) ----------


def test_user_cannot_see_or_touch_other_account():
    """MT-C01: A gọi API với id tài khoản của B → 404, ghi audit; B không bị ảnh hưởng."""
    w = World()
    w.create_account("acc_b")
    a = w.clients["trader"]
    b = w.user("bob")
    w.grant("bob", "acc_b")
    for method, path, body in ACCOUNT_ROUTES:
        r = a.request(method, path.format(a="acc_b"), json=body)
        assert r.status_code == 404, (path, r.status_code)
    # Tài khoản không tồn tại trả đúng cùng mã → không dò được tài khoản nào có thật
    assert a.get("/api/accounts/does-not-exist/status").status_code == 404
    assert len(w.denied()) >= len(ACCOUNT_ROUTES) + 1
    assert all(e.account_id is None for e in w.denied())  # audit hệ thống, không lộ
    assert state(b, "acc_b") == "PAUSED"
    assert [x["account_id"] for x in a.get("/api/accounts").json()] == ["default"]
    assert [x["account_id"] for x in b.get("/api/accounts").json()] == ["acc_b"]
    assert set(a.get("/api/accounts").json()[0]) == {"account_id", "name", "safety_state",
                                                       "mode"}


def test_halt_of_one_account_does_not_affect_other():
    """MT-C03."""
    w = World()
    w.create_account("acc_b")
    bob = w.user("bob")
    w.grant("bob", "acc_b")
    trader = w.clients["trader"]
    assert resume(bob, "acc_b").status_code == 200
    assert halt(trader, "default").status_code == 200
    assert state(trader, "default") == "HALTED"
    assert state(bob, "acc_b") == "ACTIVE"
    assert [t.to_state for t in w.repo.safety_history("acc_b")] == [SafetyState.ACTIVE]


def test_owner_has_every_trading_action_on_own_account():
    """Một vai trò USER: tạm dừng, dừng khẩn cấp, mở lại (thoát HALTED cần tick), đổi Mode."""
    w = World()
    t = w.clients["trader"]
    assert resume(t).status_code == 200
    assert halt(t).status_code == 200
    assert resume(t).status_code == 409  # thoát HALTED phải tick xác nhận
    assert resume(t, approved=True).json()["safety_state"] == "ACTIVE"
    assert t.post("/api/accounts/default/mode", json={"mode": "BACKTEST"}).status_code == 200


def test_ownership_revocation_takes_effect_on_next_request():
    """0-C13: quyền đọc từ DB mỗi request, không cache trong phiên."""
    w = World()
    t = w.clients["trader"]
    assert halt(t).status_code == 200
    w.repo.remove_member("default", "sub-trader")
    assert t.get("/api/accounts/default/status").status_code == 404
    assert t.get("/api/accounts").json() == []


def test_locked_user_cannot_act_but_safety_state_is_kept():
    """MT-C06 + DEC-16: USER bị khóa → phiên bị thu hồi, không lệnh mới; Safety giữ nguyên."""
    w = World()
    t = w.clients["trader"]
    assert resume(t).status_code == 200
    reg = w.app.state.registry
    assert reg.allows_new_orders("default") is True
    w.lock("trader")
    assert reg.allows_new_orders("default") is False  # Trading Engine chặn lệnh mới
    assert t.get("/api/accounts/default/status").status_code == 401  # phiên bị thu hồi
    assert reg.get("default").safety.state is SafetyState.ACTIVE  # không tự đổi trạng thái
    assert any(e.action == "auth.session_revoked" and e.detail == "tài khoản bị khóa"
               for e in w.repo.audit(50))
    # Đăng nhập lại cũng bị chặn ở backend (kể cả khi Keycloak vẫn cấp code)
    c = client(w.app)
    q = w.kc.start_login(c)
    w.kc.codes["c1"] = ("sub-trader", q["nonce"], q["code_challenge"])
    r = c.get("/api/auth/callback", params={"code": "c1", "state": q["state"]},
              follow_redirects=False)
    assert r.headers["location"] == "/?auth_error=locked"
    assert "__Host-gt_session" not in c.cookies
    # Mở khóa: được dùng lại nhưng KHÔNG tự chạy lại / tự đổi gì
    w.repo.set_user_status("sub-trader", "ACTIVE", utcnow())
    assert reg.allows_new_orders("default") is True
    assert reg.get("default").safety.state is SafetyState.ACTIVE


def test_allows_new_orders_false_when_user_record_missing_or_db_unreadable():
    w = World()
    reg = w.app.state.registry
    resume(w.clients["trader"])
    assert reg.allows_new_orders("default") is True

    def boom(*a, **k):
        raise RuntimeError("db down")

    w.repo.user = boom  # type: ignore[method-assign]
    assert reg.allows_new_orders("default") is False


# ---------- LIVE: USER xin, ADMIN duyệt/từ chối (0-C16, DEC-16) ----------


def live_world(**kw):
    return World(live_unlocked=True, **kw)


def request_live(w, checklist=FULL_CHECKLIST):
    r = w.clients["trader"].post("/api/accounts/default/mode/live-requests",
                                 json={"checklist": checklist})
    assert r.status_code == 201, r.text
    return r.json()


def test_live_requested_by_user_approved_by_admin():
    w = live_world()
    admin, trader = w.clients["admin"], w.clients["trader"]
    req = request_live(w)
    pending = admin.get("/api/admin/live-requests").json()
    assert [(x["request_id"], x["account_name"], x["requested_by"]) for x in pending] == [
        (req["request_id"], "Tài khoản chính", "trader")
    ]
    r = admin.post(f"/api/admin/live-requests/{req['request_id']}/approve")
    assert r.status_code == 200
    assert trader.get("/api/accounts/default/status").json()["mode"] == "LIVE"
    ok = [e for e in w.repo.audit(50) if e.action == "mode.live_approve"]
    assert ok[0].outcome == "ACCEPTED" and ok[0].actor == "admin"
    assert ok[0].payload["requester"] == "trader"
    # Dùng lại yêu cầu đã duyệt → từ chối
    assert admin.post(f"/api/admin/live-requests/{req['request_id']}/approve").status_code == 409


def test_live_rejected_by_admin_stays_paper():
    w = live_world()
    admin = w.clients["admin"]
    req = request_live(w)
    assert admin.post(f"/api/admin/live-requests/{req['request_id']}/reject").status_code == 200
    assert admin.get("/api/admin/live-requests").json() == []
    assert admin.post(f"/api/admin/live-requests/{req['request_id']}/approve").status_code == 409
    assert w.clients["trader"].get("/api/accounts/default/status").json()["mode"] == "PAPER"
    assert any(e.action == "mode.live_reject" for e in w.repo.audit(50))


def test_only_admin_approves_or_rejects_live():
    w = live_world()
    trader = w.clients["trader"]
    req = request_live(w)
    assert trader.get("/api/admin/live-requests").status_code == 403
    for verb in ("approve", "reject"):
        assert trader.post(f"/api/admin/live-requests/{req['request_id']}/{verb}"
                           ).status_code == 403
    # Đường cũ (người thứ hai trong tài khoản duyệt) không còn
    assert trader.post(f"/api/accounts/default/mode/live-requests/{req['request_id']}/approve"
                       ).status_code in (404, 405)
    assert trader.get("/api/accounts/default/status").json()["mode"] == "PAPER"


def test_live_cannot_be_set_directly():
    w = live_world()
    r = w.clients["trader"].post("/api/accounts/default/mode",
                                 json={"mode": "LIVE", "checklist": FULL_CHECKLIST})
    assert r.status_code == 409


def test_live_approval_rules():
    w = live_world()
    admin = w.clients["admin"]
    # Checklist thiếu → ModeManager từ chối dù ADMIN duyệt
    req = request_live(w, checklist={})
    assert admin.post(f"/api/admin/live-requests/{req['request_id']}/approve").status_code == 409
    # Người yêu cầu bị khóa trước khi được duyệt → từ chối
    req = request_live(w)
    w.lock("trader")
    assert admin.post(f"/api/admin/live-requests/{req['request_id']}/approve").status_code == 409
    w.repo.set_user_status("sub-trader", "ACTIVE", utcnow())
    # Người yêu cầu không còn là chủ → từ chối
    w2 = live_world()
    req = request_live(w2)
    w2.repo.remove_member("default", "sub-trader")
    r = w2.clients["admin"].post(f"/api/admin/live-requests/{req['request_id']}/approve")
    assert r.status_code == 409
    assert w.app.state.registry.get("default").modes.mode is TradingMode.PAPER
    assert w2.app.state.registry.get("default").modes.mode is TradingMode.PAPER


def test_live_locked_by_config_still_refused():
    w = World(live_unlocked=False)
    req = request_live(w)
    r = w.clients["admin"].post(f"/api/admin/live-requests/{req['request_id']}/approve")
    assert r.status_code == 409


def test_live_request_expires(monkeypatch):
    from gold_trading.api import accounts as accounts_api

    w = live_world()
    req = request_live(w)
    base = utcnow()
    monkeypatch.setattr(accounts_api, "utcnow", lambda: base + timedelta(minutes=16))
    assert w.clients["admin"].get("/api/admin/live-requests").json() == []
    r = w.clients["admin"].post(f"/api/admin/live-requests/{req['request_id']}/approve")
    assert r.status_code == 409


def test_sample_data_blocks_live_even_when_admin_approves():
    w = live_world(data_source=DataSource.SAMPLE, run_sample_feed=False)
    req = request_live(w)
    r = w.clients["admin"].post(f"/api/admin/live-requests/{req['request_id']}/approve")
    assert r.status_code == 409


# ---------- Safety theo tài khoản: DB là nguồn sự thật (MT-06, OPS-15) ----------


def _external_halt(repo, acc="default"):
    last = repo.safety_history(acc)
    frm = last[-1].to_state if last else SafetyState.PAUSED
    repo.append_safety(acc, SafetyTransition(
        transition_id=new_id("st"), from_state=frm, to_state=SafetyState.HALTED,
        reason_code="BREAK_GLASS", trigger_source="cli", actor="break-glass", at=utcnow(),
        policy_version="p",
    ))


def test_external_halt_is_seen_and_cannot_be_overwritten():
    w = World()
    t = w.clients["trader"]
    assert resume(t).status_code == 200
    _external_halt(w.repo)  # như CLI ghi thẳng vào DB
    assert state(t) == "HALTED"
    w2 = World(repo=w.repo)
    rt = w2.app.state.registry.get("default")
    _external_halt(w.repo)
    rt.safety._state = SafetyState.ACTIVE  # giả lập trạng thái cũ trong bộ nhớ
    with pytest.raises(StaleStateError):
        rt.safety.pause("X", trigger_source="t", actor="t")
    assert w.repo.safety_history("default")[-1].to_state is SafetyState.HALTED


def test_allows_new_orders_false_when_db_unreadable():
    w = World()
    reg = w.app.state.registry
    resume(w.clients["trader"])
    assert reg.allows_new_orders("default") is True

    def boom(*a, **k):
        raise RuntimeError("db down")

    w.repo.safety_history = boom  # type: ignore[method-assign]
    assert reg.allows_new_orders("default") is False


def test_startup_rules_apply_to_every_account():
    repo = InMemoryRepository()
    w = World(repo=repo, live_unlocked=True)
    w.create_account("acc_b")
    bob = w.user("bob")
    w.grant("bob", "acc_b")
    resume(w.clients["trader"], "default")
    resume(bob, "acc_b")
    from gold_trading.modes.manager import ModeChange

    repo.append_mode("acc_b", ModeChange("PAPER", "LIVE", "a", "b"))
    w2 = World(repo=repo)  # "khởi động lại"
    reg = w2.app.state.registry
    for acc in ("default", "acc_b"):
        rt = reg.get(acc)
        assert rt.safety.state is SafetyState.PAUSED
        assert rt.safety.history[-1].reason_code == "STARTUP_REQUIRES_REVIEW"
    assert reg.get("acc_b").modes.mode is TradingMode.PAPER


def test_route_param_account_id_is_never_trusted_from_body():
    w = World()
    r = w.clients["trader"].post(
        "/api/accounts/default/safety",
        json={"action": "halt", "reason_code": "X", "account_id": "acc_b"},
    )
    assert r.status_code == 422
