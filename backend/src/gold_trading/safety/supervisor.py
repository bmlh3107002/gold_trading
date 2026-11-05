"""Máy trạng thái Safety: ACTIVE / PAUSED / HALTED (docs/08).

- Mọi chuyển trạng thái là một event có reason_code, actor, policy_version.
- Từ HALTED chỉ được về trạng thái khác khi có phê duyệt của người vận hành.
- Safety không tạo tín hiệu giao dịch; nó chỉ chặn hoặc hạn chế.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable

from gold_trading.common.enums import SafetyState
from gold_trading.common.ids import new_id
from gold_trading.common.time import utcnow
from gold_trading.contracts.safety import SafetyTransition


class SafetyTransitionError(RuntimeError):
    pass


class SafetySupervisor:
    def __init__(
        self,
        policy_version: str,
        initial_state: SafetyState = SafetyState.PAUSED,
        *,
        history: Iterable[SafetyTransition] = (),
        persist: Callable[[SafetyTransition], None] | None = None,
    ) -> None:
        # Khởi động ở PAUSED: chỉ mở lệnh khi đã kiểm tra hệ thống và chủ động resume.
        self._state = initial_state
        self._policy_version = policy_version
        self._history: list[SafetyTransition] = list(history)
        # persist được gọi TRƯỚC khi đổi trạng thái; nếu nó lỗi thì trạng thái giữ nguyên.
        self._persist = persist
        self._lock = threading.Lock()

    @property
    def state(self) -> SafetyState:
        return self._state

    @property
    def history(self) -> tuple[SafetyTransition, ...]:
        return tuple(self._history)

    def allows_new_orders(self) -> bool:
        return self._state is SafetyState.ACTIVE

    def allows_protective_actions(self) -> bool:
        # Hủy lệnh chờ, siết SL, đóng vị thế luôn được phép ở mọi trạng thái.
        return True

    def pause(
        self, reason_code: str, *, trigger_source: str, actor: str
    ) -> SafetyTransition | None:
        with self._lock:
            if self._state is SafetyState.HALTED:
                return None  # Không hạ mức nghiêm trọng từ HALTED xuống PAUSED.
            return self._transition(SafetyState.PAUSED, reason_code, trigger_source, actor)

    def halt(self, reason_code: str, *, trigger_source: str, actor: str) -> SafetyTransition | None:
        with self._lock:
            return self._transition(SafetyState.HALTED, reason_code, trigger_source, actor)

    def resume(
        self,
        reason_code: str,
        *,
        trigger_source: str,
        actor: str,
        operator_approved: bool = False,
    ) -> SafetyTransition | None:
        with self._lock:
            if self._state is SafetyState.HALTED and not operator_approved:
                raise SafetyTransitionError("Thoát HALTED cần phê duyệt của người vận hành")
            return self._transition(SafetyState.ACTIVE, reason_code, trigger_source, actor)

    def _transition(
        self, to: SafetyState, reason_code: str, trigger_source: str, actor: str
    ) -> SafetyTransition | None:
        if not reason_code:
            raise SafetyTransitionError("reason_code là bắt buộc")
        if to is self._state:
            return None  # Idempotent: gửi lại cùng lệnh không tạo event mới.
        event = SafetyTransition(
            transition_id=new_id("st"),
            from_state=self._state,
            to_state=to,
            reason_code=reason_code,
            trigger_source=trigger_source,
            actor=actor,
            at=utcnow(),
            policy_version=self._policy_version,
        )
        if self._persist:
            self._persist(event)
        self._state = to
        self._history.append(event)
        return event
