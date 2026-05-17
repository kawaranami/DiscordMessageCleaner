from __future__ import annotations

import threading
import time
from typing import Any, Callable, Final, TypeVar

from discord_message_purger.domain.exceptions import (
    DiscordNetworkError,
    DiscordRateLimitError,
    DiscordServerError,
    DiscordTimeoutError,
    RateLimitTooLongError,
)


__all__ = ["with_retry_policy"]


T = TypeVar("T")

SleepFn = Callable[[float, "threading.Event | None"], None]


_RATE_LIMIT_MIN_WAIT: Final[float] = 0.0
_RATE_LIMIT_MAX_WAIT: Final[float] = 60.0
_RATE_LIMIT_HARD_CAP: Final[float] = 600.0
_DEFAULT_SLEEP_CHUNK_S: Final[float] = 0.1


def _clamp(value: float, lower: float, upper: float) -> float:

    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


def _default_sleep(seconds: float, cancel_event: "threading.Event | None") -> None:

    if seconds <= 0:
        return
    if cancel_event is None:
        time.sleep(seconds)
        return
    remaining = seconds
    while remaining > 0:
        chunk = remaining if remaining < _DEFAULT_SLEEP_CHUNK_S else _DEFAULT_SLEEP_CHUNK_S
        if cancel_event.wait(timeout=chunk):
            return
        remaining -= chunk


def _extract_cancel_event(ctx: Any) -> "threading.Event | None":

    if ctx is None:
        return None
    return getattr(ctx, "cancel_event", None)


def with_retry_policy(
    call: Callable[[], T],
    ctx: Any | None,
    *,
    retries: tuple[float, ...] = (1.0, 2.0, 4.0),
    sleep_fn: SleepFn | None = None,
) -> T:

    sleep = sleep_fn if sleep_fn is not None else _default_sleep
    cancel_event = _extract_cancel_event(ctx)

    attempt = 0
    while True:
        try:
            return call()
        except DiscordRateLimitError as exc:
            if exc.retry_after_seconds > _RATE_LIMIT_HARD_CAP:
                raise RateLimitTooLongError(exc.retry_after_seconds) from exc
            wait_s = _clamp(
                exc.retry_after_seconds,
                _RATE_LIMIT_MIN_WAIT,
                _RATE_LIMIT_MAX_WAIT,
            )
            sleep(wait_s, cancel_event)
            continue
        except (DiscordServerError, DiscordNetworkError, DiscordTimeoutError):
            if attempt >= len(retries):
                raise
            sleep(retries[attempt], cancel_event)
            attempt += 1
            continue
