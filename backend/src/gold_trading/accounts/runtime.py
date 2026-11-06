"""Safety + Mode theo từng tài khoản giao dịch (MT-06).

- Mỗi tài khoản một ``SafetySupervisor`` và một ``ModeManager``.
- Quy tắc khôi phục khi khởi động áp dụng cho MỌI tài khoản: ACTIVE→PAUSED, HALTED giữ,
  LIVE→PAPER, dữ liệu mẫu chặn SHADOW/LIVE.
- **DB là nguồn sự thật.** Mỗi lần ghi Safety kèm ``expected_last``; DB đã đổi (ví dụ HALT từ
  CLI) thì ghi bị từ chối (``StaleStateError``). Vòng nền đồng bộ trạng thái mỗi 2 giây.
- Đọc DB lỗi → ``allows_new_orders()`` = False (mặc định an toàn).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from gold_trading.common.enums import SafetyState, TradingMode
from gold_trading.common.time import utcnow
from gold_trading.modes.manager import ModeManager
from gold_trading.safety.supervisor import SafetySupervisor
from gold_trading.storage.repository import (
    AuditEntry,
    Repository,
    restore_mode,
    restore_safety_state,
)

log = logging.getLogger("gold_trading.accounts")

SYNC_INTERVAL_S = 2.0
GLOBAL_KILL_REASON = "GLOBAL_KILL_SWITCH"


@dataclass
class AccountRuntime:
    account_id: str
    safety: SafetySupervisor
    modes: ModeManager


class AccountRegistry:
    def __init__(
        self,
        repo: Repository,
        *,
        policy_version: str,
        default_mode: TradingMode,
        live_unlocked: bool,
        mode_guard: Callable[[TradingMode], str | None],
    ) -> None:
        self.repo = repo
        self._policy = policy_version
        self._default_mode = default_mode
        self._live_unlocked = live_unlocked
        self._guard = mode_guard
        self._rts: dict[str, AccountRuntime] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        for acc in repo.accounts():
            self._build(acc.account_id)

    # --- Dựng runtime + quy tắc khôi phục ---

    def _audit(self, account_id: str, action: str, payload: dict[str, Any], detail: str) -> None:
        self.repo.append_audit(
            AuditEntry(utcnow(), "system", action, "ACCEPTED", payload, detail, account_id, None)
        )

    def _build(self, account_id: str) -> AccountRuntime:
        repo = self.repo
        history = repo.safety_history(account_id)
        start_state, downgrade_reason = restore_safety_state(history)
        holder: dict[str, SafetySupervisor] = {}

        def persist(t):
            # expected_last = sự kiện mới nhất mà tiến trình này biết (trước khi thêm t).
            repo.append_safety(account_id, t, expected_last=holder["s"].last_transition_id)

        safety = SafetySupervisor(
            self._policy, initial_state=start_state, history=history, persist=persist
        )
        holder["s"] = safety
        if downgrade_reason:
            safety.pause(downgrade_reason, trigger_source="startup", actor="system")

        default_mode = self._default_mode
        if default_mode is TradingMode.LIVE or self._guard(default_mode):
            default_mode = TradingMode.PAPER
        start_mode, relocked = restore_mode(repo.last_mode(account_id), default_mode)
        if relocked:
            self._audit(account_id, "mode.startup", {"from": "LIVE", "to": "PAPER"},
                        "LIVE không được khôi phục tự động sau restart")
        if (reason := self._guard(start_mode)) is not None:
            self._audit(account_id, "mode.startup", {"from": start_mode.value, "to": "PAPER"},
                        reason)
            start_mode = TradingMode.PAPER
        modes = ModeManager(
            start_mode,
            live_unlocked=self._live_unlocked,
            on_change=lambda ch: repo.append_mode(account_id, ch),
            guard=self._guard,
        )
        rt = AccountRuntime(account_id, safety, modes)
        self._rts[account_id] = rt
        return rt

    # --- Truy cập ---

    def get(self, account_id: str) -> AccountRuntime | None:
        with self._lock:
            rt = self._rts.get(account_id)
            if rt is None and self.repo.account(account_id) is not None:
                rt = self._build(account_id)  # tài khoản tạo sau khi khởi động
            return rt

    def ids(self) -> list[str]:
        with self._lock:
            return list(self._rts)

    def add(self, account_id: str) -> AccountRuntime:
        with self._lock:
            return self._rts.get(account_id) or self._build(account_id)

    # --- Đồng bộ với DB ---

    def sync(self, account_id: str | None = None) -> list[str]:
        """Nhận các sự kiện Safety ghi từ ngoài tiến trình (CLI). Trả các tài khoản đã đổi."""
        changed = []
        for acc in [account_id] if account_id else self.ids():
            rt = self._rts.get(acc)
            if rt is None:
                continue
            if rt.safety.adopt(self.repo.safety_history(acc)):
                log.warning("Safety tài khoản %s đổi từ bên ngoài → %s", acc, rt.safety.state)
                changed.append(acc)
        return changed

    def allows_new_orders(self, account_id: str) -> bool:
        """Chỉ True khi đọc được DB và tài khoản đang ACTIVE."""
        try:
            self.sync(account_id)
        except Exception:
            log.exception("Không đọc được trạng thái Safety của %s: chặn lệnh mới", account_id)
            return False
        rt = self._rts.get(account_id)
        return bool(rt and rt.safety.allows_new_orders())

    def halt_all(self, reason_code: str, *, actor: str, trigger_source: str) -> list[str]:
        """Kill switch toàn hệ thống: HALT từng tài khoản. Trả các tài khoản vừa chuyển HALTED."""
        halted = []
        for acc in self.ids():
            rt = self._rts[acc]
            self.sync(acc)
            if rt.safety.state is SafetyState.HALTED:
                continue
            rt.safety.halt(reason_code, trigger_source=trigger_source, actor=actor)
            halted.append(acc)
        return halted

    # --- Vòng nền ---

    def _loop(self) -> None:
        while not self._stop.wait(SYNC_INTERVAL_S):
            try:
                self.sync()
            except Exception:
                log.exception("Đồng bộ Safety từ DB thất bại")

    def start(self) -> None:
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="safety-sync", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
