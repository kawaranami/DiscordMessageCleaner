from __future__ import annotations

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from discord_message_purger.infrastructure.rate_limiter import RateLimiter


_TOLERANCE_SECONDS: float = 0.1

_CLAMP_MAX: float = 60.0
_CLAMP_MIN: float = 0.0
_HARD_LIMIT_SECONDS: float = 600.0


_RETRY_AFTER_STRATEGY = st.one_of(
    st.floats(
        min_value=-10.0,
        max_value=120.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    st.floats(
        min_value=120.0,
        max_value=_HARD_LIMIT_SECONDS,
        allow_nan=False,
        allow_infinity=False,
    ),
)


class _FakeClock:

    def __init__(self) -> None:
        self._now: float = 0.0
        self.total_slept: float = 0.0
        self.sleep_calls: int = 0

    def time(self) -> float:

        return self._now

    def sleep(self, seconds: float) -> None:

        if seconds <= 0:
            return
        self.sleep_calls += 1
        self.total_slept += seconds
        self._now += seconds


# Feature: discord-message-purger, Property 24: 429 wait clamped to [0..60] and not counted in retries
@pytest.mark.property
@given(retry_after=_RETRY_AFTER_STRATEGY)
@settings(max_examples=200, deadline=None)
def test_handle_429_clamps_wait_and_does_not_count_retry(
    retry_after: float,
) -> None:

    clock = _FakeClock()
    rate_limiter = RateLimiter(
        time_source=clock.time,
        sleep_fn=clock.sleep,
    )

    retries_counter: int = 0

    response = httpx.Response(
        status_code=429,
        json={"retry_after": retry_after},
        headers={"Retry-After": repr(retry_after)},
    )

    rate_limiter.handle_429(response, ctx=None)

    expected_wait = max(_CLAMP_MIN, min(retry_after, _CLAMP_MAX))
    actual_wait = clock.total_slept

    assert abs(actual_wait - expected_wait) <= _TOLERANCE_SECONDS, (
        "Фактическое ожидание после 429 должно равняться "
        "clamp(Retry-After, 0, 60) с точностью не хуже 100 мс: "
        f"ожидалось {expected_wait:.6f} с, проспано {actual_wait:.6f} с "
        f"(retry_after={retry_after!r})"
    )

    assert _CLAMP_MIN <= actual_wait <= _CLAMP_MAX + _TOLERANCE_SECONDS, (
        "Ожидание после 429 должно лежать в диапазоне [0, 60] секунд, "
        f"получено {actual_wait:.6f} с (retry_after={retry_after!r})"
    )

    assert retries_counter == 0, (
        "handle_429 не должен инкрементировать счётчик повторов из "
        f"общей retry-policy: ожидалось 0, фактически {retries_counter}"
    )
