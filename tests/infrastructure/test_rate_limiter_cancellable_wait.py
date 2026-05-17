# Feature: discord-message-purger, Property 30: Cancellable rate-limit wait

from __future__ import annotations

import threading
import time

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from discord_message_purger.infrastructure.rate_limiter import RateLimiter


_CANCEL_BUDGET_SECONDS: float = 1.0


def _schedule_cancel(
    cancel_event: threading.Event, delay_seconds: float
) -> threading.Thread:

    def _runner() -> None:
        time.sleep(delay_seconds)
        cancel_event.set()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return thread


# Feature: discord-message-purger, Property 30: Cancellable rate-limit wait
@pytest.mark.property
@given(
    duration=st.floats(
        min_value=0.5,
        max_value=2.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    cancel_fraction=st.floats(
        min_value=0.0,
        max_value=1.0,
        allow_nan=False,
        allow_infinity=False,
    ),
)
@settings(max_examples=100, deadline=None)
def test_interruptible_sleep_cancels_within_one_second(
    duration: float,
    cancel_fraction: float,
) -> None:

    cancel_at = cancel_fraction * duration

    cancel_event = threading.Event()

    limiter = RateLimiter()

    cancel_thread = _schedule_cancel(cancel_event, cancel_at)
    try:
        start = time.monotonic()
        limiter.interruptible_sleep(duration, cancel_event)
        elapsed = time.monotonic() - start
    finally:
        cancel_thread.join(timeout=duration + _CANCEL_BUDGET_SECONDS + 1.0)

    assert elapsed <= cancel_at + _CANCEL_BUDGET_SECONDS, (
        "interruptible_sleep должен завершиться не позже чем за 1 с после "
        "cancel_event.set(): "
        f"cancel_at={cancel_at!r}, elapsed={elapsed!r}, duration={duration!r}"
    )

    if cancel_at + _CANCEL_BUDGET_SECONDS < duration:
        assert elapsed < duration, (
            "При отмене, пришедшей заметно раньше окончания ожидания, "
            "interruptible_sleep должен выйти до истечения duration: "
            f"elapsed={elapsed!r}, duration={duration!r}, "
            f"cancel_at={cancel_at!r}"
        )
