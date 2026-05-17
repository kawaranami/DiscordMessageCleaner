# Feature: discord-message-purger, Property 28: Rate-limit waits respect remaining=0 reset

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from discord_message_purger.infrastructure.rate_limiter import RateLimiter


_TOLERANCE_SECONDS: float = 0.1


@dataclass
class _FakeResponse:

    headers: dict[str, str] = field(default_factory=dict)


class _FakeClock:

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def time(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        if seconds is None or seconds < 0.0:
            return
        self._now += seconds

    def advance(self, seconds: float) -> None:
        self._now += seconds


# Feature: discord-message-purger, Property 28: Rate-limit waits respect remaining=0 reset
@pytest.mark.property
@given(
    reset_after=st.floats(
        min_value=0.0,
        max_value=60.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    pre_response_offset=st.floats(
        min_value=0.0,
        max_value=10.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    bucket=st.text(
        alphabet=st.characters(
            min_codepoint=33,
            max_codepoint=126,
            blacklist_categories=("Cs",),
        ),
        min_size=1,
        max_size=16,
    ),
)
@settings(max_examples=100, deadline=None)
def test_remaining_zero_blocks_until_reset(
    reset_after: float,
    pre_response_offset: float,
    bucket: str,
) -> None:
    clock = _FakeClock(start=0.0)
    rate_limiter = RateLimiter(
        time_source=clock.time,
        sleep_fn=clock.sleep,
    )

    clock.advance(pre_response_offset)

    t_response = clock.time()
    response = _FakeResponse(
        headers={
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset-After": repr(reset_after),
            "X-RateLimit-Bucket": bucket,
        }
    )
    route_key = f"GET /channels/{bucket}/messages"
    rate_limiter.after_response(route_key, response)

    rate_limiter.before_request(route_key)
    t_next = clock.time()

    expected_release = t_response + reset_after
    assert t_next + _TOLERANCE_SECONDS >= expected_release, (
        "Следующий запрос отправлен слишком рано: "
        f"t_next={t_next!r}, ожидалось >= {expected_release!r} "
        f"(t_response={t_response!r}, reset_after={reset_after!r})"
    )
