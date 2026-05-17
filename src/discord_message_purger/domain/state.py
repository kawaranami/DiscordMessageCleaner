from __future__ import annotations

from .exceptions import IllegalStateTransition
from .models import OperationState

LEGAL_TRANSITIONS: dict[OperationState, set[OperationState]] = {
    OperationState.IDLE: {OperationState.RUNNING},
    OperationState.RUNNING: {
        OperationState.PAUSED,
        OperationState.CANCELED,
        OperationState.COMPLETED,
        OperationState.ERROR,
    },
    OperationState.PAUSED: {
        OperationState.RUNNING,
        OperationState.CANCELED,
        OperationState.ERROR,
    },
    OperationState.COMPLETED: set(),
    OperationState.CANCELED: set(),
    OperationState.ERROR: set(),
}


def transition(
    current: OperationState,
    target: OperationState,
) -> OperationState:

    allowed = LEGAL_TRANSITIONS.get(current, set())
    if target in allowed:
        return target
    raise IllegalStateTransition(current, target)


__all__ = [
    "LEGAL_TRANSITIONS",
    "transition",
]
