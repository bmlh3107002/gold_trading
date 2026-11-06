"""OPS-17, MT-03, MT-06: phân quyền theo tài khoản, cách ly giữa tài khoản, Safety/Mode riêng.

Case: 0-C13, 0-C15, 0-C16, MT-C01, MT-C03, MT-C04, MT-C06.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gold_trading.accounts.access import ADMIN_PERMS, MIN_ROLE, Perm, decide
from gold_trading.common.enums import SafetyState, TradingMode
from gold_trading.common.ids import new_id
from gold_trading.common.time import utcnow
from gold_trading.contracts.candle import DataSource
from gold_trading.contracts.safety import SafetyTransition
from gold_trading.modes.manager import LIVE_CHECKLIST
from gold_trading.storage.repository import InMemoryRepository, Member, StaleStateError
from tests.auth_helpers import FakeKeycloak, client, make_app

DOC = Path(__file__).resolve().parents[2] / "docs/thiet-ke/00-xac-thuc-phan-quyen.md"
FULL_CHECKLIST = {k: True for k in LIVE_CHECKLIST}


class World:
    """Một app + Keycloak giả + nhiều người dùng đã đăng nhập."""

    def __init__(self, **kw) -> None:
        self.repo = kw.pop("repo", None) or InMemoryRepository()
        kw.setdefault("data_source", DataSource.MT5)
        kw.setdefault("run_analysts", False)
        self.kc = FakeKeycloak()
        self.app, _ = make_app(self.repo, self.kc, **kw)
        self.clients = {}
        # admin đăng nhập đầu tiên → OWNER tài khoản default
        self.user("admin", admin=True)

    def user(self, name: str, *, admin: bool = False):
        c = client(self.app)
        self.kc.login(c, name, admin=admin)
        self.clients[name] = c
        return c

    def grant(self, name: str, role: str, account: str = "default") -> None:
        self.repo.set_member(Member(account, f"sub-{name}", role, utcnow(), "test"))

    def create_account(self, account_id: str) -> None:
        r = self.clients["admin"].post("/api/accounts", json={"account_id": account_id,
                                                              "name": account_id})
        assert r.status_code == 201, r.text

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


# ---------- Ma trận quyền khớp tài liệu ----------

DOC_ROWS = {
    "Xem trạng thái, lịch sử Safety/Mode, audit, Gateway **của tài khoản**": Perm.VIEW,
    "PAUSE / HALT tài khoản": Perm.PAUSE_HALT,
    "Resume PAUSED → ACTIVE": Perm.RESUME,
    "Thoát HALTED (cần tick xác nhận)": Perm.EXIT_HALTED,
    "Đổi Mode BACKTEST/PAPER/SHADOW": Perm.SET_MODE,
    "Yêu cầu bật LIVE": Perm.REQUEST_LIVE,
    "**Duyệt** LIVE (người khác người yêu cầu)": Perm.APPROVE_LIVE,
    "Xoay token Gateway": Perm.ROTATE_TOKEN,
    "Thêm/đổi vai trò/gỡ thành viên": Perm.MANAGE_MEMBERS,
}


def test_permission_matrix_matches_design_doc():
    text = DOC.read_text(encoding="utf-8")
    seen = set()
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 5 or cells[0] not in DOC_ROWS:
            continue
        perm = DOC_ROWS[cells[0]]
        expected = [c.startswith("✓") for c in cells[1:]]
        actual = [
            decide(perm, "VIEWER", False) == "ok",
            decide(perm, "OPERATOR", False) == "ok",
            decide(perm, "OWNER", False) == "ok",
            decide(perm, None, True) == "ok",
        ]
        assert actual == expected, (perm, actual, expected)
        seen.add(perm)
    assert seen == set(Perm), set(Perm) - seen
    assert set(MIN_ROLE) == set(Perm)
    assert Perm.RESUME not in ADMIN_PERMS and Perm.SET_MODE not in ADMIN_PERMS


def test_non_member_non_admin_gets_not_found():
    assert decide(Perm.VIEW, None, False) == "not_found"
    assert decide(Perm.PAUSE_HALT, "VIEWER", False) == "forbidden"


# ---------- Cách ly tài khoản (MT-C01, MT-C03) ----------


def test_user_cannot_see_or_touch_other_account():
    """MT-C01: A gọi API với id tài khoản của B → 404, ghi audit; B không bị ảnh hưởng."""
    w = World()
    w.create_account("acc_b")
    a = w.user("alice")
    w.grant("alice", "OWNER", "default")
    b = w.user("bob")
    w.grant("bob", "OWNER", "acc_b")
    for method, path, body in [
        ("GET", "/api/accounts/acc_b/status", None),
        ("GET", "/api/accounts/acc_b/audit", None),
        ("POST", "/api/accounts/acc_b/safety", {"action": "halt", "reason_code": "X"}),
        ("POST", "/api/accounts/acc_b/mode", {"mode": "BACKTEST"}),
        ("POST", "/api/accounts/acc_b/mode/live-requests", {"checklist": {}}),
    ]:
        r = a.request(method, path, json=body)
        assert r.status_code == 404, (path, r.status_code)
    # Tài khoản không tồn tại trả đúng cùng mã → không dò được tài khoản nào có thật
    assert a.get("/api/accounts/does-not-exist/status").status_code == 404
    assert len(w.denied()) >= 6
    assert all(e.account_id is None for e in w.denied())  # audit hệ thống, không lộ
    assert state(b, "acc_b") == "PAUSED"
    assert [x["account_id"] for x in a.get("/api/accounts").json()] == ["default"]
    assert [x["account_id"] for x in b.get("/api/accounts").json()] == ["acc_b"]


def test_halt_of_one_account_does_not_affect_other():
    """MT-C03."""
    w = World()
    w.create_account("acc_b")
    w.user("bob")
    w.grant("bob", "OWNER", "acc_b")
    admin, bob = w.clients["admin"], w.clients["bob"]
    assert resume(bob, "acc_b").status_code == 200
    assert halt(admin, "default").status_code == 200
    assert state(admin, "default") == "HALTED"
    assert state(bob, "acc_b") == "ACTIVE"
    hist = w.repo.safety_history("acc_b")
    assert [t.to_state for t in hist] == [SafetyState.ACTIVE]


def test_global_kill_switch_halts_every_account_admin_only():
    """MT-C04."""
    w = World()
    for acc in ("acc_b", "acc_c"):
        w.create_account(acc)
    w.user("bob")
    for acc in ("default", "acc_b", "acc_c"):
        w.grant("bob", "OWNER", acc)
    bob = w.clients["bob"]
    resume(bob, "acc_b")
    halt(bob, "acc_c")
    r = bob.post("/api/admin/kill-switch", json={"reason_code": "TEST"})
    assert r.status_code == 403
    assert state(bob, "acc_b") == "ACTIVE"
    r = w.clients["admin"].post("/api/admin/kill-switch", json={"reason_code": "TEST"})
    assert r.status_code == 200
    body = r.json()
    assert set(body["halted"]) == {"default", "acc_b"} and body["already_halted"] == ["acc_c"]
    for acc in ("default", "acc_b", "acc_c"):
        assert state(bob, acc) == "HALTED"
    assert w.repo.safety_history("acc_b")[-1].reason_code.startswith("GLOBAL_KILL_SWITCH")
    assert any(e.action == "system.kill_switch" and e.outcome == "ACCEPTED"
               for e in w.repo.audit(system=True))


# ---------- Vai trò (0-C13, 0-C15) ----------


def test_viewer_write_is_forbidden_and_audited():
    """0-C15."""
    w = World()
    v = w.user("vera")
    w.grant("vera", "VIEWER")
    assert v.get("/api/accounts/default/status").status_code == 200
    assert halt(v).status_code == 403
    assert resume(v).status_code == 403
    assert v.post("/api/accounts/default/mode", json={"mode": "BACKTEST"}).status_code == 403
    assert state(v) == "PAUSED"
    denied = w.denied()
    assert len(denied) == 3 and all(e.account_id == "default" for e in denied)
    assert all(e.actor == "vera" and e.actor_sub == "sub-vera" for e in denied)


def test_role_revocation_takes_effect_on_next_request():
    """0-C13: quyền đọc từ DB mỗi request, không cache trong phiên."""
    w = World()
    o = w.user("oscar")
    w.grant("oscar", "OPERATOR")
    assert halt(o).status_code == 200
    w.grant("oscar", "VIEWER")  # hạ quyền
    assert resume(o, approved=True).status_code == 403
    w.repo.remove_member("default", "sub-oscar")  # gỡ hẳn
    assert o.get("/api/accounts/default/status").status_code == 404
    assert o.get("/api/accounts").json() == []


def test_operator_can_resume_paused_but_not_exit_halted():
    w = World()
    o = w.user("olga")
    w.grant("olga", "OPERATOR")
    assert resume(o).status_code == 200 and state(o) == "ACTIVE"
    assert halt(o).status_code == 200
    assert resume(o, approved=True).status_code == 403  # thoát HALTED cần OWNER
    assert state(o) == "HALTED"
    assert resume(w.clients["admin"], approved=True).status_code == 200  # admin là OWNER


def test_admin_non_member_can_view_and_halt_but_not_resume_or_set_mode():
    w = World()
    w.create_account("acc_b")
    admin = w.clients["admin"]  # ADMIN nhưng không là thành viên acc_b
    assert admin.get("/api/accounts/acc_b/status").json()["role"] is None
    assert halt(admin, "acc_b").status_code == 200
    assert resume(admin, "acc_b", approved=True).status_code == 403
    assert admin.post("/api/accounts/acc_b/mode", json={"mode": "BACKTEST"}).status_code == 403
    assert "acc_b" in [x["account_id"] for x in admin.get("/api/accounts").json()]


def test_removed_user_cannot_act_but_safety_state_is_kept():
    """MT-C06: người dùng bị khóa → không thao tác được; trạng thái bảo vệ vẫn giữ."""
    w = World()
    u = w.user("uma")
    w.grant("uma", "OWNER")
    halt(u)
    w.repo.remove_member("default", "sub-uma")
    assert resume(u, approved=True).status_code == 404
    assert state(w.clients["admin"]) == "HALTED"
    # Bị vô hiệu hóa trên Keycloak → phiên chết ở lần làm mới kế tiếp (xem test_auth.py)


def test_status_lists_permissions_for_ui():
    w = World()
    v = w.user("vic")
    w.grant("vic", "VIEWER")
    assert v.get("/api/accounts/default/status").json()["permissions"] == ["VIEW"]
    perms = w.clients["admin"].get("/api/accounts/default/status").json()["permissions"]
    assert set(perms) == {p.value for p in Perm}


# ---------- Tạo tài khoản ----------


def test_create_account_admin_only_validated():
    w = World()
    n = w.user("nina")
    r = n.post("/api/accounts", json={"account_id": "acc_x", "name": "X"})
    assert r.status_code == 403
    admin = w.clients["admin"]
    assert admin.post("/api/accounts", json={"account_id": "acc_x", "name": "X"}).status_code == 201
    assert admin.post("/api/accounts", json={"account_id": "acc_x", "name": "X"}).status_code == 409
    for bad in ("A", "has space", "../etc", "x" * 40, "UPPER"):
        r = admin.post("/api/accounts", json={"account_id": bad, "name": "X"})
        assert r.status_code == 422, bad
    acc = w.repo.account("acc_x")
    assert acc.price_feed is False  # chỉ tài khoản mặc định được ghi nến dùng chung
    assert state(admin, "acc_x") == "PAUSED"


# ---------- Bật LIVE hai bước (0-C16) ----------


def live_world(**kw):
    w = World(live_unlocked=True, **kw)
    w.user("owner2")
    w.grant("owner2", "OWNER")
    return w


def test_live_request_same_person_cannot_approve():
    w = live_world()
    admin = w.clients["admin"]
    req = admin.post("/api/accounts/default/mode/live-requests",
                     json={"checklist": FULL_CHECKLIST}).json()
    r = admin.post(f"/api/accounts/default/mode/live-requests/{req['request_id']}/approve")
    assert r.status_code == 409
    rejected = [e for e in w.repo.audit(50) if e.action == "mode.live_approve"]
    assert rejected[0].outcome == "REJECTED" and "trùng" in rejected[0].detail
    assert admin.get("/api/accounts/default/status").json()["mode"] == "PAPER"


def test_live_approved_by_second_authenticated_owner():
    w = live_world()
    admin, o2 = w.clients["admin"], w.clients["owner2"]
    req = admin.post("/api/accounts/default/mode/live-requests",
                     json={"checklist": FULL_CHECKLIST}).json()
    assert [x["request_id"] for x in
            o2.get("/api/accounts/default/mode/live-requests").json()] == [req["request_id"]]
    r = o2.post(f"/api/accounts/default/mode/live-requests/{req['request_id']}/approve")
    assert r.status_code == 200 and r.json()["mode"] == "LIVE"
    # Dùng lại yêu cầu đã duyệt → từ chối
    r = o2.post(f"/api/accounts/default/mode/live-requests/{req['request_id']}/approve")
    assert r.status_code == 409


def test_live_cannot_be_set_directly():
    w = live_world()
    r = w.clients["admin"].post("/api/accounts/default/mode",
                                json={"mode": "LIVE", "checklist": FULL_CHECKLIST})
    assert r.status_code == 409


def test_live_approval_rules():
    w = live_world()
    admin, o2 = w.clients["admin"], w.clients["owner2"]
    v = w.user("viewer")
    w.grant("viewer", "VIEWER")
    # VIEWER không yêu cầu, không duyệt được
    assert v.post("/api/accounts/default/mode/live-requests", json={}).status_code == 403
    req = admin.post("/api/accounts/default/mode/live-requests",
                     json={"checklist": FULL_CHECKLIST}).json()
    assert v.post(
        f"/api/accounts/default/mode/live-requests/{req['request_id']}/approve"
    ).status_code == 403
    # Checklist thiếu → ModeManager từ chối dù người duyệt hợp lệ
    req = o2.post("/api/accounts/default/mode/live-requests", json={"checklist": {}}).json()
    r = admin.post(f"/api/accounts/default/mode/live-requests/{req['request_id']}/approve")
    assert r.status_code == 409
    # Người yêu cầu bị gỡ quyền trước khi được duyệt → từ chối
    req = o2.post("/api/accounts/default/mode/live-requests",
                  json={"checklist": FULL_CHECKLIST}).json()
    w.grant("owner2", "VIEWER")
    r = admin.post(f"/api/accounts/default/mode/live-requests/{req['request_id']}/approve")
    assert r.status_code == 409
    assert admin.get("/api/accounts/default/status").json()["mode"] == "PAPER"


def test_live_locked_by_config_still_refused():
    w = World(live_unlocked=False)
    w.user("o2")
    w.grant("o2", "OWNER")
    req = w.clients["admin"].post("/api/accounts/default/mode/live-requests",
                                  json={"checklist": FULL_CHECKLIST}).json()
    r = w.clients["o2"].post(
        f"/api/accounts/default/mode/live-requests/{req['request_id']}/approve"
    )
    assert r.status_code == 409


def test_live_request_expires(monkeypatch):
    from datetime import timedelta

    from gold_trading.api import accounts as accounts_api

    w = live_world()
    req = w.clients["admin"].post("/api/accounts/default/mode/live-requests",
                                  json={"checklist": FULL_CHECKLIST}).json()
    base = utcnow()
    monkeypatch.setattr(accounts_api, "utcnow", lambda: base + timedelta(minutes=16))
    r = w.clients["owner2"].post(
        f"/api/accounts/default/mode/live-requests/{req['request_id']}/approve"
    )
    assert r.status_code == 409


def test_sample_data_blocks_live_even_with_two_people():
    w = live_world(data_source=DataSource.SAMPLE, run_sample_feed=False)
    req = w.clients["admin"].post("/api/accounts/default/mode/live-requests",
                                  json={"checklist": FULL_CHECKLIST}).json()
    r = w.clients["owner2"].post(
        f"/api/accounts/default/mode/live-requests/{req['request_id']}/approve"
    )
    assert r.status_code == 409


# ---------- Safety theo tài khoản: DB là nguồn sự thật (MT-06, chuẩn bị cho OPS-15) ----------


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
    admin = w.clients["admin"]
    assert resume(admin).status_code == 200
    _external_halt(w.repo)  # như CLI ghi thẳng vào DB
    assert state(admin) == "HALTED"
    # Tiến trình chưa đồng bộ cố ghi PAUSE từ trạng thái ACTIVE cũ → bị từ chối ở tầng repository
    w2 = World(repo=w.repo)
    rt = w2.app.state.registry.get("default")
    _external_halt(w.repo)  # thêm một HALT nữa sau khi w2 đã dựng
    rt.safety._state = SafetyState.ACTIVE  # giả lập trạng thái cũ trong bộ nhớ
    with pytest.raises(StaleStateError):
        rt.safety.pause("X", trigger_source="t", actor="t")
    assert w.repo.safety_history("default")[-1].to_state is SafetyState.HALTED


def test_allows_new_orders_false_when_db_unreadable():
    w = World()
    reg = w.app.state.registry
    resume(w.clients["admin"])
    assert reg.allows_new_orders("default") is True

    def boom(*a, **k):
        raise RuntimeError("db down")

    w.repo.safety_history = boom  # type: ignore[method-assign]
    assert reg.allows_new_orders("default") is False


def test_startup_rules_apply_to_every_account():
    repo = InMemoryRepository()
    w = World(repo=repo, live_unlocked=True)
    w.create_account("acc_b")
    w.user("bob")
    w.grant("bob", "OWNER", "acc_b")
    resume(w.clients["admin"], "default")
    resume(w.clients["bob"], "acc_b")
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
    r = w.clients["admin"].post(
        "/api/accounts/default/safety",
        json={"action": "halt", "reason_code": "X", "account_id": "acc_b"},
    )
    assert r.status_code == 422
