"""OPS-15: dừng khẩn cấp bằng CLI khi Keycloak hỏng. Case 0-C11."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from gold_trading.common.enums import SafetyState
from gold_trading.common.time import utcnow
from gold_trading.contracts.candle import DataSource
from gold_trading.safety import break_glass
from gold_trading.storage.repository import SqlRepository, TradingAccount
from tests.auth_helpers import client, login_owner, make_app


@pytest.fixture
def repo(tmp_path) -> SqlRepository:
    r = SqlRepository.from_url(f"sqlite:///{tmp_path / 'gt.db'}")
    r.create_all()
    r.create_account(TradingAccount("acc_b", "B", utcnow(), "t", False))
    return r


def last_state(repo, acc):
    h = repo.safety_history(acc, limit=1)
    return h[-1].to_state if h else SafetyState.PAUSED


def test_halt_single_account(repo, capsys):
    assert break_glass.main(["halt", "--account", "default", "--reason", "KC_DOWN"], repo) == 0
    t = repo.safety_history("default")[-1]
    assert t.to_state is SafetyState.HALTED and t.actor == "break-glass"
    assert t.trigger_source == "cli" and t.reason_code == "BREAK_GLASS:KC_DOWN"
    assert last_state(repo, "acc_b") is SafetyState.PAUSED  # tài khoản khác không đổi
    audit = repo.audit(account_id="default")
    assert audit[0].action == "safety.halt" and audit[0].actor == "break-glass"
    assert "đã HALTED" in capsys.readouterr().out


def test_halt_all_and_idempotent(repo, capsys):
    break_glass.main(["halt", "--account", "acc_b"], repo)
    assert break_glass.main(["halt", "--all"], repo) == 0
    out = capsys.readouterr().out
    assert "default: đã HALTED" in out and "acc_b: vẫn HALTED" in out
    assert last_state(repo, "default") is SafetyState.HALTED
    assert len(repo.safety_history("acc_b")) == 1  # không ghi thêm khi đã HALTED
    assert any(e.action == "system.kill_switch" for e in repo.audit(system=True))


def test_unknown_account_and_missing_db(repo, monkeypatch, capsys):
    assert break_glass.main(["halt", "--account", "ghost"], repo) == 1
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert break_glass.main(["status"]) == 2


def test_status_lists_accounts(repo, capsys):
    break_glass.main(["halt", "--account", "default"], repo)
    capsys.readouterr()
    assert break_glass.main(["status"], repo) == 0
    out = capsys.readouterr().out
    assert "default" in out and "HALTED" in out and "acc_b" in out and "PAUSED" in out


def test_cli_has_no_way_to_resume_or_change_mode(repo):
    for cmd in (["resume", "--account", "default"], ["mode", "LIVE"], ["unlock"]):
        with pytest.raises(SystemExit):
            break_glass.main(cmd, repo)


def test_source_contains_no_unsafe_calls():
    """Quét mã (không tính docstring/chú thích): không resume, không đổi Mode, không ACTIVE."""
    src = Path(break_glass.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for forbidden in ("resume", "set_mode", "ACTIVE", "TradingMode", "live_unlocked",
                      "ModeManager", "append_mode"):
        assert forbidden not in names, forbidden
    to_states = [
        kw.value for n in ast.walk(tree) if isinstance(n, ast.Call)
        for kw in n.keywords if kw.arg == "to_state"
    ]
    assert len(to_states) == 1 and ast.unparse(to_states[0]) == "SafetyState.HALTED"


def test_halt_works_while_keycloak_is_down_and_running_app_sees_it(repo):
    """0-C11: Keycloak chết → không đăng nhập mới được, nhưng HALT qua CLI vẫn được; backend
    đang chạy nhận HALTED; khởi động lại vẫn HALTED (không bao giờ tự ACTIVE)."""
    app, kc = make_app(repo, data_source=DataSource.MT5, run_analysts=False)
    c = login_owner(app, kc, repo)
    r = c.post("/api/accounts/default/safety", json={"action": "resume", "reason_code": "OK"})
    assert r.json()["safety_state"] == "ACTIVE"

    kc.down = True
    c2 = client(app)
    q = kc.start_login(c2)
    r = c2.get("/api/auth/callback", params={"code": "x", "state": q["state"]},
               follow_redirects=False)
    assert r.headers["location"] == "/?auth_error=unavailable"

    assert break_glass.main(["halt", "--all", "--reason", "KEYCLOAK_DOWN"], repo) == 0
    registry = app.state.registry
    registry.sync()  # vòng nền chạy mỗi 2 giây; gọi trực tiếp trong test
    assert registry.get("default").safety.state is SafetyState.HALTED
    assert registry.allows_new_orders("default") is False
    # Phiên cũ (đang còn hạn) xem được trạng thái mới
    assert c.get("/api/accounts/default/status").json()["safety_state"] == "HALTED"

    app2, _ = make_app(repo, data_source=DataSource.MT5, run_analysts=False)  # khởi động lại
    assert app2.state.registry.get("default").safety.state is SafetyState.HALTED
    assert app2.state.registry.get("acc_b").safety.state is SafetyState.HALTED
