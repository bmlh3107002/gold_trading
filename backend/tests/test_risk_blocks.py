"""GĐ2 bước 4a — lệnh cấm mở lệnh mới có hạn của làn nhanh (FAST-03, DEC-20 câu 5)."""

from datetime import UTC, datetime, timedelta

import pytest

from gold_trading.risk.blocks import ALL, Block, BlockKind, BlockStore, Lift, block_id_for
from gold_trading.storage.repository import SqlRepository
from gold_trading.storage.risk_blocks import SqlBlockStore

T = datetime(2026, 12, 4, 13, 30, tzinfo=UTC)
M = timedelta(minutes=1)


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return BlockStore()
    repo = SqlRepository.from_url(f"sqlite:///{tmp_path / 'b.db'}")
    repo.create_all()
    return SqlBlockStore(repo.engine)


def rel(start=T, end=T + 15 * M, created=T + M, cause="bls_values:EMPSIT:2026-11", scope=ALL):
    return Block(BlockKind.RELEASE, scope, "HIGH_RELEASE", start, end, cause, created,
                 "fast-lane-1")


def spread(feed="pf_a", created=T, cause="pf_a@2026-12-04T13:30:00"):
    return Block(BlockKind.SPREAD, feed, "SPREAD_WIDE", created, None, cause, created,
                 "fast-lane-1")


def test_identity_and_idempotent(store):
    b = rel()
    assert b.block_id == block_id_for("RELEASE", ALL, "bls_values:EMPSIT:2026-11")
    assert store.add(b) is True and store.add(b) is False
    assert store.get(b.block_id)[0] == b and store.get("x") is None


def test_active_window_point_in_time(store):
    b = rel()
    store.add(b)
    # bắt đầu 13:30 nhưng hệ thống biết lúc 13:31 → trước 13:31 không có hiệu lực (point-in-time)
    assert store.active(T + 30 * timedelta(seconds=1)) == []
    assert store.active(T + M) == [b]
    assert store.active(T + 15 * M - timedelta(seconds=1)) == [b]
    assert store.active(T + 15 * M) == []                       # hết hạn đúng end_at


def test_scope_feed(store):
    s = spread()
    store.add(s)
    store.add(rel())
    t = T + 2 * M
    assert [b.kind for b in store.active(t, "pf_a")] == ["SPREAD", "RELEASE"]
    assert [b.kind for b in store.active(t, "pf_b")] == ["RELEASE"]
    assert [b.kind for b in store.active(t)] == ["RELEASE"]


def test_open_ended_until_lift(store):
    s = spread()
    store.add(s)
    assert store.active(T + timedelta(hours=5), "pf_a") == [s]
    assert [b.block_id for b in store.open_spread(T + M)] == [s.block_id]
    lift_at = T + 10 * M
    assert store.lift(Lift(s.block_id, lift_at, "SPREAD_NORMAL")) is True
    assert store.lift(Lift(s.block_id, lift_at + M, "SPREAD_NORMAL")) is False
    assert store.active(lift_at - timedelta(seconds=1), "pf_a") == [s]   # quá khứ giữ nguyên
    assert store.active(lift_at, "pf_a") == []
    assert store.open_spread(lift_at) == []
    assert [b.block_id for b in store.open_spread(lift_at - M)] == [s.block_id]
    with pytest.raises(ValueError):
        store.lift(Lift("khong-co", lift_at, "X"))


@pytest.mark.parametrize("kw", [
    {"reason_code": "high release"}, {"scope": ""}, {"end_at": T}, {"cause_ref": ""},
    {"start_at": datetime(2026, 12, 4, 13, 30)},
])
def test_validation(kw):
    base = dict(kind=BlockKind.RELEASE, scope=ALL, reason_code="HIGH_RELEASE", start_at=T,
                end_at=T + 15 * M, cause_ref="c", created_at=T, policy_version="p")
    with pytest.raises(ValueError):
        Block(**(base | kw))


# ------------------------------------------------------------------ nối Safety (API tài khoản)

def _active_client():
    from tests.auth_helpers import user_client
    c = user_client()
    r = c.post("/api/accounts/default/safety", json={"action": "resume", "reason_code": "OK"})
    assert r.json()["safety_state"] == "ACTIVE"
    return c


def test_safety_blocks_new_orders_but_keeps_switch():
    """DEC-20 câu 5: lệnh cấm còn hạn → không mở lệnh mới; công tắc Safety vẫn ACTIVE; hết hạn
    → mở lại tự động."""
    from gold_trading.common.time import utcnow
    c = _active_client()
    store = c.app.state.block_store
    assert c.get("/api/accounts/default/status").json()["allows_new_orders"] is True
    now = utcnow()
    b = Block(BlockKind.RELEASE, ALL, "HIGH_RELEASE", now - M, now + 15 * M,
              "bls_values:EMPSIT:2026-11", now - timedelta(seconds=5), "fast-lane-1")
    store.add(b)
    body = c.get("/api/accounts/default/status").json()
    assert body["allows_new_orders"] is False and body["safety_state"] == "ACTIVE"
    assert body["entry_blocks"][0]["kind"] == "RELEASE"
    assert body["entry_blocks"][0]["reason_code"] == "HIGH_RELEASE"
    # lệnh cấm đã hết hạn → không còn tác dụng
    old = Block(BlockKind.NEWS, ALL, "FED_UNSCHEDULED", now - 30 * M, now - 15 * M, "fed:x",
                now - 30 * M, "fast-lane-1")
    c2 = _active_client()
    c2.app.state.block_store.add(old)
    body = c2.get("/api/accounts/default/status").json()
    assert body["allows_new_orders"] is True and body["entry_blocks"] == []


def test_spread_block_of_other_feed_does_not_apply():
    """Lệnh cấm spread gắn với một nguồn giá — nguồn khác (tài khoản dữ liệu mẫu) không bị chặn."""
    from gold_trading.common.time import utcnow
    c = _active_client()
    now = utcnow()
    c.app.state.block_store.add(Block(BlockKind.SPREAD, "pf_khac", "SPREAD_WIDE", now - M, None,
                                      "pf_khac@x", now - M, "fast-lane-1"))
    assert c.get("/api/accounts/default/status").json()["allows_new_orders"] is True


def test_block_read_error_blocks():
    """Đọc lệnh cấm lỗi → mặc định chặn (an toàn)."""
    c = _active_client()

    def boom(*a, **k):
        raise RuntimeError("db down")
    c.app.state.block_store.active = boom
    body = c.get("/api/accounts/default/status").json()
    assert body["allows_new_orders"] is False and body["safety_state"] == "ACTIVE"
