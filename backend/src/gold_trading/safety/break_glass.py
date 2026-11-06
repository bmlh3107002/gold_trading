"""Lối dừng khẩn cấp khi Keycloak (hoặc giao diện) hỏng — OPS-15.

    docker compose exec backend gt-break-glass status
    docker compose exec backend gt-break-glass halt --account default --reason KEYCLOAK_DOWN
    docker compose exec backend gt-break-glass halt --all --reason KEYCLOAK_DOWN

CHỈ có ``halt`` và ``status``. Không bao giờ mở lại giao dịch, đổi Mode hay mở khóa LIVE
(test quét mã nguồn file này để giữ điều đó). Ghi thẳng vào DB với ``actor=break-glass``;
backend đang chạy nhận trạng thái mới trong vòng ~2 giây (đồng bộ từ DB).
Không cần đăng nhập: ai chạy được ``docker compose exec`` trên máy là người có quyền với máy.
"""

from __future__ import annotations

import argparse
import os
import sys

from gold_trading.common.enums import SafetyState
from gold_trading.common.ids import new_id
from gold_trading.common.time import utcnow
from gold_trading.contracts.safety import SafetyTransition
from gold_trading.storage.repository import (
    AuditEntry,
    Repository,
    SqlRepository,
    StaleStateError,
)

ACTOR = "break-glass"
TRIGGER = "cli"
POLICY = "break-glass-1"
MAX_ATTEMPTS = 5


def halt_account(repo: Repository, account_id: str, reason: str) -> str:
    """HALT một tài khoản. Trả 'HALTED' (vừa chuyển) hoặc 'ALREADY' (đã HALTED từ trước)."""
    if repo.account(account_id) is None:
        raise KeyError(account_id)
    for _ in range(MAX_ATTEMPTS):
        hist = repo.safety_history(account_id, limit=1)
        last = hist[-1] if hist else None
        current = last.to_state if last else SafetyState.PAUSED
        if current is SafetyState.HALTED:
            return "ALREADY"
        t = SafetyTransition(
            transition_id=new_id("st"),
            from_state=current,
            to_state=SafetyState.HALTED,
            reason_code=reason,
            trigger_source=TRIGGER,
            actor=ACTOR,
            at=utcnow(),
            policy_version=POLICY,
        )
        try:
            repo.append_safety(account_id, t,
                               expected_last=last.transition_id if last else None)
        except StaleStateError:
            continue  # có người vừa ghi trạng thái mới: đọc lại và thử tiếp
        repo.append_audit(AuditEntry(utcnow(), ACTOR, "safety.halt", "ACCEPTED",
                                     {"reason_code": reason, "via": "cli"}, None, account_id))
        return "HALTED"
    raise RuntimeError(f"Không ghi được HALT cho {account_id} sau {MAX_ATTEMPTS} lần thử")


def main(argv: list[str] | None = None, repo: Repository | None = None) -> int:
    p = argparse.ArgumentParser(prog="gt-break-glass", description="Dừng khẩn cấp (chỉ HALT)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="Xem trạng thái Safety của mọi tài khoản")
    h = sub.add_parser("halt", help="HALT một tài khoản hoặc toàn bộ")
    target = h.add_mutually_exclusive_group(required=True)
    target.add_argument("--account", help="Mã tài khoản, ví dụ default")
    target.add_argument("--all", action="store_true", help="HALT mọi tài khoản")
    h.add_argument("--reason", default="BREAK_GLASS", help="Mã lý do (mặc định BREAK_GLASS)")
    args = p.parse_args(argv)

    if repo is None:
        url = os.environ.get("DATABASE_URL")
        if not url:
            print("Thiếu DATABASE_URL: chạy lệnh này bên trong container backend.",
                  file=sys.stderr)
            return 2
        repo = SqlRepository.from_url(url)

    if args.cmd == "status":
        for acc in repo.accounts():
            hist = repo.safety_history(acc.account_id, limit=1)
            st = hist[-1].to_state.value if hist else "PAUSED"
            print(f"{acc.account_id:<24} {st:<8} {acc.name}")
        return 0

    reason = (args.reason or "BREAK_GLASS").strip()[:100] or "BREAK_GLASS"
    reason = f"BREAK_GLASS:{reason}" if not reason.startswith("BREAK_GLASS") else reason
    ids = [a.account_id for a in repo.accounts()] if args.all else [args.account]
    failed = 0
    for acc in ids:
        try:
            result = halt_account(repo, acc, reason)
        except KeyError:
            print(f"{acc}: KHÔNG TỒN TẠI", file=sys.stderr)
            failed += 1
            continue
        except Exception as e:  # DB lỗi: báo rõ, không nuốt lỗi
            print(f"{acc}: LỖI {type(e).__name__}: {e}", file=sys.stderr)
            failed += 1
            continue
        print(f"{acc}: {'đã HALTED' if result == 'HALTED' else 'vẫn HALTED (từ trước)'}")
    if args.all:
        repo.append_audit(AuditEntry(utcnow(), ACTOR, "system.kill_switch", "ACCEPTED",
                                     {"reason_code": reason, "via": "cli", "accounts": ids},
                                     None, None))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
