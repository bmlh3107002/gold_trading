"""Mode Manager (docs/12). LIVE bị khóa mặc định."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from gold_trading.common.enums import TradingMode


class ModeChangeError(RuntimeError):
    pass


LIVE_CHECKLIST: tuple[str, ...] = (
    "reconciliation_clean",
    "required_sources_healthy",
    "kill_switch_tested",
    "guardian_ea_tested",
    "risk_limits_approved",
    "model_versions_approved",
    "on_call_ready",
)


@dataclass(frozen=True)
class ModeChange:
    from_mode: TradingMode
    to_mode: TradingMode
    actor: str
    approver: str | None


class ModeManager:
    def __init__(
        self,
        initial: TradingMode = TradingMode.PAPER,
        *,
        live_unlocked: bool = False,
        on_change: Callable[[ModeChange], None] | None = None,
    ) -> None:
        if initial is TradingMode.LIVE:
            raise ModeChangeError("Không được khởi động trực tiếp ở LIVE")
        self._mode = initial
        self._live_unlocked = live_unlocked
        self._on_change = on_change

    @property
    def mode(self) -> TradingMode:
        return self._mode

    @property
    def live_unlocked(self) -> bool:
        return self._live_unlocked

    def set_mode(
        self,
        to: TradingMode,
        *,
        actor: str,
        approver: str | None = None,
        checklist: Mapping[str, bool] | None = None,
    ) -> ModeChange | None:
        if to is self._mode:
            return None
        if to is TradingMode.LIVE:
            self._check_live(actor, approver, checklist or {})
        change = ModeChange(self._mode, to, actor, approver)
        # Ghi lại trước khi đổi; nếu ghi lỗi thì mode giữ nguyên.
        if self._on_change:
            self._on_change(change)
        self._mode = to
        return change

    def _check_live(self, actor: str, approver: str | None, checklist: Mapping[str, bool]) -> None:
        if not self._live_unlocked:
            raise ModeChangeError("LIVE đang bị khóa bằng cấu hình")
        if not approver or approver == actor:
            raise ModeChangeError("Bật LIVE cần người phê duyệt thứ hai khác người yêu cầu")
        missing = [item for item in LIVE_CHECKLIST if not checklist.get(item)]
        if missing:
            raise ModeChangeError(f"Checklist LIVE chưa đạt: {', '.join(missing)}")
