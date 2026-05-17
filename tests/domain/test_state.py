from __future__ import annotations

import itertools

import pytest

from discord_message_purger.domain.exceptions import IllegalStateTransition
from discord_message_purger.domain.models import OperationState
from discord_message_purger.domain.state import LEGAL_TRANSITIONS, transition


EXPECTED_LEGAL_TRANSITIONS: dict[OperationState, set[OperationState]] = {
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


def _all_state_pairs() -> list[tuple[OperationState, OperationState]]:

    return list(itertools.product(OperationState, OperationState))


def test_legal_transitions_matches_design_document() -> None:

    assert LEGAL_TRANSITIONS == EXPECTED_LEGAL_TRANSITIONS, (
        "LEGAL_TRANSITIONS должен в точности соответствовать диаграмме "
        f"состояний из design.md. Ожидалось: {EXPECTED_LEGAL_TRANSITIONS!r}, "
        f"получено: {LEGAL_TRANSITIONS!r}"
    )

    for state in OperationState:
        assert state in LEGAL_TRANSITIONS, (
            f"В LEGAL_TRANSITIONS отсутствует запись для состояния {state!r}; "
            "таблица должна покрывать все элементы OperationState."
        )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        pytest.param(current, target, id=f"{current.name}->{target.name}")
        for current, target in _all_state_pairs()
        if target in EXPECTED_LEGAL_TRANSITIONS[current]
    ],
)
def test_transition_returns_target_for_legal_edges(
    current: OperationState,
    target: OperationState,
) -> None:

    result = transition(current, target)

    assert result == target, (
        f"transition({current!r}, {target!r}) должен вернуть target={target!r}, "
        f"получено: {result!r}"
    )
    assert isinstance(result, OperationState), (
        "transition() должен возвращать значение типа OperationState, "
        f"получено: {type(result).__name__}"
    )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        pytest.param(current, target, id=f"{current.name}->{target.name}")
        for current, target in _all_state_pairs()
        if target not in EXPECTED_LEGAL_TRANSITIONS[current]
    ],
)
def test_transition_raises_for_illegal_edges(
    current: OperationState,
    target: OperationState,
) -> None:

    with pytest.raises(IllegalStateTransition) as excinfo:
        transition(current, target)

    err = excinfo.value
    assert err.current == current, (
        f"IllegalStateTransition.current должен быть {current!r}, "
        f"получено: {err.current!r}"
    )
    assert err.target == target, (
        f"IllegalStateTransition.target должен быть {target!r}, "
        f"получено: {err.target!r}"
    )
