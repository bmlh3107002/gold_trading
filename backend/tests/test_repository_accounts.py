"""MT-01/MT-02/MT-04: repository theo tài khoản. Chạy cho cả bản bộ nhớ và SQL (SQLite)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from gold_trading.common.enums import SafetyState, TradingMode
from gold_trading.common.ids import new_id
from gold_trading.common.time import utcnow
from gold_trading.contracts.safety import SafetyTransition
from gold_trading.modes.manager import ModeChange
from gold_trading.storage.repository import (
    AuditEntry,
    ConflictError,
    InMemoryRepository,
    Member,
    SqlRepository,
    StaleStateError,
    TradingAccount,
    token_hash,
)


@pytest.fixture(params=["memory", "sqlite"])
def repo(request, tmp_path):
    if request.param == "memory":
        return InMemoryRepository()
    r = SqlRepository.from_url(f"sqlite:///{tmp_path / 'gt.db'}")
    r.create_all()
    return r


def tr(frm, to, reason="R"):
    return SafetyTransition(
        transition_id=new_id("st"), from_state=frm, to_state=to, reason_code=reason,
        trigger_source="t", actor="t", at=utcnow(), policy_version="p",
    )


def add_account(repo, acc_id="acc_b", price_feed=False):
    repo.create_account(TradingAccount(acc_id, f"Tài khoản {acc_id}", utcnow(), "admin",
                                       price_feed))


def test_default_account_exists_and_is_price_feed(repo):
    accs = repo.accounts()
    assert [a.account_id for a in accs] == ["default"]
    assert accs[0].price_feed is True
    repo.ensure_default_account()  # idempotent
    assert len(repo.accounts()) == 1


def test_create_duplicate_account_conflicts(repo):
    add_account(repo)
    with pytest.raises(ConflictError):
        add_account(repo)


def test_safety_and_mode_are_isolated_per_account(repo):
    add_account(repo)
    repo.append_safety("default", tr(SafetyState.PAUSED, SafetyState.HALTED))
    repo.append_mode("acc_b", ModeChange(TradingMode.PAPER, TradingMode.SHADOW, "a", None))
    assert [t.to_state for t in repo.safety_history("default")] == [SafetyState.HALTED]
    assert repo.safety_history("acc_b") == []
    assert repo.last_mode("default") is None
    assert repo.last_mode("acc_b") is TradingMode.SHADOW


def test_unknown_account_cannot_receive_events(repo):
    with pytest.raises(KeyError):
        repo.append_safety("nope", tr(SafetyState.PAUSED, SafetyState.HALTED))
    with pytest.raises(KeyError):
        repo.append_mode("nope", ModeChange(TradingMode.PAPER, TradingMode.SHADOW, "a", None))


def test_optimistic_safety_write_detects_external_change(repo):
    first = tr(SafetyState.PAUSED, SafetyState.ACTIVE)
    repo.append_safety("default", first, expected_last=None)
    # Ai đó (CLI break-glass) ghi HALT trong lúc tiến trình khác còn giữ trạng thái cũ
    repo.append_safety("default", tr(SafetyState.ACTIVE, SafetyState.HALTED))
    with pytest.raises(StaleStateError):
        repo.append_safety("default", tr(SafetyState.ACTIVE, SafetyState.PAUSED),
                           expected_last=first.transition_id)
    assert repo.safety_history("default")[-1].to_state is SafetyState.HALTED


def test_audit_filters_by_account_and_system(repo):
    now = utcnow()
    repo.append_audit(AuditEntry(now, "a", "x", "ACCEPTED", {}, None, "default", "sub-a"))
    repo.append_audit(AuditEntry(now, "b", "y", "ACCEPTED", {}, None, "acc_b", "sub-b"))
    repo.append_audit(AuditEntry(now, "c", "auth.login", "ACCEPTED", {}, None, None, "sub-c"))
    assert [e.actor for e in repo.audit(account_id="default")] == ["a"]
    assert [e.actor for e in repo.audit(system=True)] == ["c"]
    assert len(repo.audit()) == 3
    assert repo.audit(account_id="default")[0].actor_sub == "sub-a"


def test_users_upsert_keeps_first_login(repo):
    t1 = utcnow()
    repo.upsert_user("s1", "alice", "Alice@Example.com", None, t1)
    repo.upsert_user("s1", "alice", "alice@example.com", "Alice", t1 + timedelta(hours=1))
    u = repo.user("s1")
    assert u.first_login_at == t1 and u.last_login_at == t1 + timedelta(hours=1)
    assert u.display_name == "Alice"
    assert repo.find_user("ALICE").sub == "s1"
    assert repo.find_user("alice@example.com").sub == "s1"
    assert repo.find_user("bob") is None


def test_members_roles(repo):
    add_account(repo)
    now = utcnow()
    repo.upsert_user("s1", "alice", None, None, now)
    repo.upsert_user("s2", "bob", None, None, now)
    repo.set_member(Member("default", "s1", "OWNER", now, "boot"))
    repo.set_member(Member("default", "s2", "VIEWER", now, "s1"))
    repo.set_member(Member("acc_b", "s2", "OWNER", now, "s1"))
    assert repo.role("default", "s1") == "OWNER"
    assert repo.role("acc_b", "s1") is None
    assert [m.sub for m in repo.members("default")] == ["s1", "s2"]  # OWNER trước
    repo.set_member(Member("default", "s2", "OPERATOR", now, "s1"))  # đổi vai trò
    assert repo.role("default", "s2") == "OPERATOR"
    assert {m.account_id for m in repo.memberships("s2")} == {"default", "acc_b"}
    assert repo.remove_member("default", "s2") is True
    assert repo.remove_member("default", "s2") is False
    assert repo.role("default", "s2") is None


def test_member_requires_known_user_and_valid_role(repo):
    now = utcnow()
    with pytest.raises(KeyError):
        repo.set_member(Member("default", "ghost", "VIEWER", now, "x"))
    repo.upsert_user("s1", "alice", None, None, now)
    with pytest.raises(ValueError):
        repo.set_member(Member("default", "s1", "ADMIN", now, "x"))


def test_gateway_token_rotation_revokes_old_immediately(repo):
    add_account(repo)
    now = utcnow()
    assert repo.has_gateway_tokens("default") is False
    repo.rotate_gateway_token("default", "gtk_old", "alice", now)
    assert repo.account_for_token("gtk_old") == "default"
    repo.rotate_gateway_token("default", "gtk_new", "alice", now)
    assert repo.account_for_token("gtk_old") is None
    assert repo.account_for_token("gtk_new") == "default"
    repo.rotate_gateway_token("acc_b", "gtk_b", "bob", now)
    assert repo.account_for_token("gtk_b") == "acc_b"
    assert repo.account_for_token("gtk_new") == "default"  # token của tài khoản khác không đổi
    assert repo.account_for_token("") is None
    assert repo.has_gateway_tokens("default") is True


def test_token_stored_only_as_hash(tmp_path):
    from sqlalchemy import select

    from gold_trading.storage.schema import gateway_tokens

    r = SqlRepository.from_url(f"sqlite:///{tmp_path / 'gt.db'}")
    r.create_all()
    r.rotate_gateway_token("default", "gtk_supersecret", "alice", utcnow())
    with r.engine.connect() as conn:
        rows = conn.execute(select(gateway_tokens)).mappings().all()
    dumped = repr([dict(x) for x in rows])
    assert "gtk_supersecret" not in dumped
    assert token_hash("gtk_supersecret") in dumped
