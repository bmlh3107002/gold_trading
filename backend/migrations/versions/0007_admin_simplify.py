"""DEC-17: trang Quản trị đơn giản (một USER một tài khoản, USER xin token, ADMIN cấp, xóa USER).

1. ``users.status`` nhận thêm ``DELETED`` (ADMIN đã xóa: ẩn, không đăng nhập, token thu hồi; giữ
   dòng để còn lịch sử).
2. Bảng ``gateway_token_requests`` (chỉ thêm dòng, có trigger chặn UPDATE/DELETE): USER xin cấp
   token → ADMIN cấp / từ chối; trạng thái hiện tại = sự kiện cuối của tài khoản.
3. Dọn dữ liệu cũ: USER nào đang là chủ **nhiều** tài khoản giao dịch (do luồng cũ trước DEC-16,
   ví dụ tài khoản trống ``u-<username>`` tự tạo kèm người dùng) thì giữ **một** tài khoản: tài
   khoản cấp giá nếu có, nếu không thì tài khoản tạo sớm nhất. Tài khoản thừa: thu hồi token,
   bỏ quyền sở hữu, ghi audit. Mặc định an toàn: KHÔNG đụng tài khoản thừa nếu nó cấp giá hoặc
   chế độ cuối là SHADOW/LIVE (để người vận hành xử lý tay). Tài khoản, lịch sử Safety/Mode/audit
   giữ nguyên (không xóa dòng nào ở bảng có lịch sử).

Revision ID: 0007
Revises: 0006
"""

import json
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _dedupe_owners(conn) -> None:
    now = datetime.now(UTC)
    rows = conn.execute(sa.text(
        "SELECT m.sub, a.account_id, a.price_feed, a.created_at "
        "FROM account_members m JOIN trading_accounts a ON a.account_id = m.account_id "
        "WHERE m.role = 'OWNER' ORDER BY m.sub"
    )).mappings().all()
    by_user: dict[str, list] = {}
    for r in rows:
        by_user.setdefault(r["sub"], []).append(r)
    for sub, accs in by_user.items():
        if len(accs) < 2:
            continue
        accs.sort(key=lambda r: (not r["price_feed"], r["created_at"], r["account_id"]))
        keep = accs[0]["account_id"]
        for extra in accs[1:]:
            acc_id = extra["account_id"]
            last_mode = conn.execute(sa.text(
                "SELECT to_mode FROM mode_changes WHERE account_id = :a "
                "ORDER BY seq DESC LIMIT 1"), {"a": acc_id}).scalar()
            if extra["price_feed"] or last_mode in ("SHADOW", "LIVE"):
                continue  # không tự động; để người vận hành quyết
            revoked = conn.execute(sa.text(
                "UPDATE gateway_tokens SET revoked_at = :now "
                "WHERE account_id = :a AND revoked_at IS NULL"), {"now": now, "a": acc_id}
            ).rowcount
            conn.execute(sa.text(
                "DELETE FROM account_members WHERE account_id = :a AND sub = :s"),
                {"a": acc_id, "s": sub})
            payload = {"sub": sub, "removed_account": acc_id, "kept_account": keep,
                       "tokens_revoked": revoked}
            conn.execute(sa.text(
                "INSERT INTO audit_log (at, actor, action, outcome, payload, detail, account_id) "
                "VALUES (:at, 'migration-0007', 'account.dedupe', 'ACCEPTED', :p, :d, :a)"
            ).bindparams(sa.bindparam("p", type_=postgresql.JSONB())),
                {"at": now, "p": payload, "a": acc_id,
                 "d": "DEC-17: mỗi USER một tài khoản; bỏ tài khoản thừa (giữ lịch sử)"})
            print(f"0007: {sub}: bỏ tài khoản thừa {acc_id} (giữ {keep}), "
                  f"thu hồi {revoked} token — {json.dumps(payload)}")


def upgrade() -> None:
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.create_check_constraint("ck_users_status", "users",
                               "status IN ('ACTIVE', 'LOCKED', 'DELETED')")
    op.create_table(
        "gateway_token_requests",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("account_id", sa.String(64), sa.ForeignKey("trading_accounts.account_id"),
                  nullable=False),
        sa.Column("sub", sa.String(255), sa.ForeignKey("users.sub"), nullable=False),
        sa.Column("event", sa.String(16), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.CheckConstraint("event IN ('REQUESTED', 'APPROVED', 'REJECTED', 'CANCELLED')",
                           name="ck_gateway_token_requests_event"),
    )
    op.create_index("ix_gateway_token_requests_account", "gateway_token_requests",
                    ["account_id", "seq"])
    op.execute(
        "CREATE TRIGGER gateway_token_requests_append_only BEFORE UPDATE OR DELETE "
        "ON gateway_token_requests FOR EACH ROW EXECUTE FUNCTION forbid_mutation();"
    )
    _dedupe_owners(op.get_bind())


def downgrade() -> None:
    # Không khôi phục quyền sở hữu đã bỏ (token đã thu hồi không dùng lại được).
    op.execute("DROP TRIGGER IF EXISTS gateway_token_requests_append_only "
               "ON gateway_token_requests;")
    op.drop_index("ix_gateway_token_requests_account", "gateway_token_requests")
    op.drop_table("gateway_token_requests")
    op.execute("UPDATE users SET status = 'LOCKED' WHERE status = 'DELETED'")
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.create_check_constraint("ck_users_status", "users", "status IN ('ACTIVE', 'LOCKED')")
