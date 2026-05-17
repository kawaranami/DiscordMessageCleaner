# Feature: discord-message-purger, Property 23: Generic transient retry policy

from __future__ import annotations

import threading
from collections.abc import Callable

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from discord_message_purger.domain.exceptions import (
    DiscordNetworkError,
    DiscordServerError,
    DiscordTimeoutError,
)
from discord_message_purger.infrastructure.retry import with_retry_policy


_OUTCOME_5XX: str = "5xx"
_OUTCOME_NETWORK: str = "network"
_OUTCOME_TIMEOUT: str = "timeout"
_OUTCOME_OK: str = "ok"

_OUTCOMES: tuple[str, ...] = (
    _OUTCOME_5XX,
    _OUTCOME_NETWORK,
    _OUTCOME_TIMEOUT,
    _OUTCOME_OK,
)

_TRANSIENT_OUTCOMES: frozenset[str] = frozenset(
    {_OUTCOME_5XX, _OUTCOME_NETWORK, _OUTCOME_TIMEOUT}
)

_EXPECTED_RETRIES: tuple[float, ...] = (1.0, 2.0, 4.0)
_MAX_TOTAL_ATTEMPTS: int = len(_EXPECTED_RETRIES) + 1

_TOLERANCE_SECONDS: float = 0.1

_SUCCESS_VALUE: object = object()


def _outcome_to_exception_type(outcome: str) -> type[BaseException]:

    if outcome == _OUTCOME_5XX:
        return DiscordServerError
    if outcome == _OUTCOME_NETWORK:
        return DiscordNetworkError
    if outcome == _OUTCOME_TIMEOUT:
        return DiscordTimeoutError
    raise AssertionError(f"Не транзитный исход: {outcome!r}")


def _raise_for_outcome(outcome: str) -> None:

    if outcome == _OUTCOME_5XX:
        raise DiscordServerError(status=503, body="")
    if outcome == _OUTCOME_NETWORK:
        raise DiscordNetworkError("simulated network error")
    if outcome == _OUTCOME_TIMEOUT:
        raise DiscordTimeoutError("simulated timeout")
    raise AssertionError(f"Неожиданный transient-исход: {outcome!r}")


def _make_fake_call(
    outcomes: list[str],
    call_log: list[str],
) -> Callable[[], object]:

    cursor: list[int] = [0]

    def call() -> object:
        i = cursor[0]
        cursor[0] += 1
        if i < len(outcomes):
            outcome = outcomes[i]
        else:
            outcome = _OUTCOME_OK
        call_log.append(outcome)
        if outcome == _OUTCOME_OK:
            return _SUCCESS_VALUE
        _raise_for_outcome(outcome)
        raise AssertionError("unreachable")

    return call


# Feature: discord-message-purger, Property 23: Generic transient retry policy
@pytest.mark.property
@given(
    outcomes=st.lists(
        st.sampled_from(_OUTCOMES),
        min_size=0,
        max_size=10,
    ),
)
@settings(max_examples=200, deadline=None)
def test_generic_transient_retry_policy(outcomes: list[str]) -> None:

    leading_failures = 0
    for outcome in outcomes:
        if outcome in _TRANSIENT_OUTCOMES:
            leading_failures += 1
        else:
            break

    expected_failed_calls = min(leading_failures, _MAX_TOTAL_ATTEMPTS)
    expected_propagates = expected_failed_calls == _MAX_TOTAL_ATTEMPTS

    if expected_propagates:
        expected_sleeps: list[float] = list(_EXPECTED_RETRIES)
    else:
        expected_sleeps = list(_EXPECTED_RETRIES[:leading_failures])

    sleep_calls: list[tuple[float, threading.Event | None]] = []

    def fake_sleep(seconds: float, cancel_event: threading.Event | None) -> None:
        sleep_calls.append((seconds, cancel_event))

    call_log: list[str] = []
    fake_call = _make_fake_call(list(outcomes), call_log)

    if expected_propagates:
        last_failure_outcome = outcomes[_MAX_TOTAL_ATTEMPTS - 1]
        expected_exc_type = _outcome_to_exception_type(last_failure_outcome)
        with pytest.raises(expected_exc_type):
            with_retry_policy(fake_call, ctx=None, sleep_fn=fake_sleep)
    else:
        result = with_retry_policy(fake_call, ctx=None, sleep_fn=fake_sleep)
        assert result is _SUCCESS_VALUE, (
            "При успехе SHALL возвращаться значение из call(); "
            f"получено {result!r}"
        )

    total_attempts = len(call_log)
    assert total_attempts <= _MAX_TOTAL_ATTEMPTS, (
        f"Общее число попыток должно быть не больше {_MAX_TOTAL_ATTEMPTS}, "
        f"фактически выполнено {total_attempts} (call_log={call_log!r})"
    )

    expected_total_attempts = expected_failed_calls + (
        0 if expected_propagates else 1
    )
    assert total_attempts == expected_total_attempts, (
        f"Ожидалось ровно {expected_total_attempts} попыток, "
        f"фактически {total_attempts} "
        f"(call_log={call_log!r}, outcomes={outcomes!r})"
    )

    actual_sleep_seconds = [s for s, _ in sleep_calls]
    assert len(actual_sleep_seconds) == len(expected_sleeps), (
        f"Число задержек должно быть {len(expected_sleeps)} "
        f"(префикс [1, 2, 4]), фактически {len(actual_sleep_seconds)}: "
        f"{actual_sleep_seconds!r} (outcomes={outcomes!r})"
    )
    for i, (actual, expected) in enumerate(
        zip(actual_sleep_seconds, expected_sleeps, strict=True)
    ):
        assert abs(actual - expected) <= _TOLERANCE_SECONDS, (
            f"Задержка #{i} должна быть {expected:.3f} с с точностью "
            f"100 мс, фактически {actual:.6f} с "
            f"(actual_sleeps={actual_sleep_seconds!r})"
        )

    for i, (_, cancel_event) in enumerate(sleep_calls):
        assert cancel_event is None, (
            f"Задержка #{i}: при ctx=None ожидался cancel_event=None, "
            f"получено {cancel_event!r}"
        )
