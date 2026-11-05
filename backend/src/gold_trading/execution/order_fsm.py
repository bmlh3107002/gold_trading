"""Vòng đời lệnh dạng finite-state machine (docs/09)."""

from __future__ import annotations

from gold_trading.common.enums import OrderState as S

TERMINAL: frozenset[S] = frozenset({S.FILLED, S.REJECTED, S.CANCELLED, S.EXPIRED})

ALLOWED: dict[S, frozenset[S]] = {
    S.REQUESTED: frozenset({S.VALIDATED, S.REJECTED, S.EXPIRED}),
    S.VALIDATED: frozenset({S.SUBMITTED, S.REJECTED, S.EXPIRED, S.CANCELLED}),
    S.SUBMITTED: frozenset({S.ACKNOWLEDGED, S.REJECTED, S.UNKNOWN}),
    S.ACKNOWLEDGED: frozenset({S.PARTIALLY_FILLED, S.FILLED, S.CANCELLED, S.EXPIRED, S.UNKNOWN}),
    S.PARTIALLY_FILLED: frozenset({S.PARTIALLY_FILLED, S.FILLED, S.CANCELLED, S.UNKNOWN}),
    # UNKNOWN chỉ thoát được sau khi truy vấn MT5 để biết trạng thái thật — không retry mù.
    S.UNKNOWN: frozenset(
        {S.ACKNOWLEDGED, S.PARTIALLY_FILLED, S.FILLED, S.REJECTED, S.CANCELLED, S.EXPIRED}
    ),
}


class InvalidOrderTransition(RuntimeError):
    pass


def transition(current: S, target: S) -> S:
    if current in TERMINAL:
        raise InvalidOrderTransition(f"{current} là trạng thái cuối")
    if target not in ALLOWED.get(current, frozenset()):
        raise InvalidOrderTransition(f"Không cho phép {current} -> {target}")
    return target
