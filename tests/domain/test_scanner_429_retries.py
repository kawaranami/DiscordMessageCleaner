from __future__ import annotations

import json
import time

import httpx
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from discord_message_purger.domain.exceptions import DiscordRateLimitError
from discord_message_purger.infrastructure.http_client import DiscordHttpClient
from discord_message_purger.infrastructure.rate_limiter import RateLimiter


class _TrackingSleepRateLimiter(RateLimiter):

    def __init__(self) -> None:
        self.total_slept: float = 0.0
        self._logical_time: float = 0.0
        super().__init__(
            time_source=self._get_time,
            sleep_fn=self._fake_sleep,
        )

    def _get_time(self) -> float:
        return self._logical_time

    def _fake_sleep(self, seconds: float) -> None:
        self.total_slept += seconds
        self._logical_time += seconds


def _make_http_client_with_429_sequence(
    k: int,
    retry_afters: list[float],
) -> tuple[DiscordHttpClient, _TrackingSleepRateLimiter, list[int]]:
    call_count: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        idx = len(call_count)
        call_count.append(1)

        if idx < k:
            retry_after = retry_afters[idx] if idx < len(retry_afters) else 1.0
            body = json.dumps({"retry_after": retry_after})
            return httpx.Response(
                429,
                content=body.encode(),
                headers={
                    "content-type": "application/json",
                    "Retry-After": str(int(retry_after)),
                },
            )
        return httpx.Response(
            200,
            content=b"[]",
            headers={"content-type": "application/json"},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(
        base_url="https://discord.com/api/v10",
        transport=transport,
    )
    rate_limiter = _TrackingSleepRateLimiter()
    http = DiscordHttpClient(
        token_provider=lambda: "test-token",
        rate_limiter=rate_limiter,
        client=client,
    )
    return http, rate_limiter, call_count


# Feature: discord-message-purger, Property 20: 429 retries on list and history (bounded by 5)
@pytest.mark.property
@given(
    k=st.integers(min_value=0, max_value=5),
    retry_afters=st.lists(
        st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        min_size=10,
        max_size=10,
    ),
)
@settings(max_examples=100)
def test_429_retries_within_limit_succeeds(
    k: int,
    retry_afters: list[float],
) -> None:
    http, rate_limiter, call_count = _make_http_client_with_429_sequence(k, retry_afters)

    response = http.get(
        "/channels/123/messages",
        timeout_s=30.0,
        params={"limit": 100},
        max_consecutive_429=5,
    )

    assert response.status_code == 200

    assert len(call_count) == k + 1

    expected_wait = sum(retry_afters[:k])
    assert abs(rate_limiter.total_slept - expected_wait) <= 0.1, (
        f"Ожидалось суммарное ожидание ~{expected_wait:.3f} с, "
        f"получено {rate_limiter.total_slept:.3f} с"
    )


# Feature: discord-message-purger, Property 20: 429 retries on list and history (bounded by 5)
@pytest.mark.property
@given(
    k=st.integers(min_value=6, max_value=10),
    retry_afters=st.lists(
        st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False),
        min_size=10,
        max_size=10,
    ),
)
@settings(max_examples=100)
def test_429_retries_exceeding_limit_raises(
    k: int,
    retry_afters: list[float],
) -> None:
    http, rate_limiter, call_count = _make_http_client_with_429_sequence(k, retry_afters)

    with pytest.raises(DiscordRateLimitError):
        http.get(
            "/channels/123/messages",
            timeout_s=30.0,
            params={"limit": 100},
            max_consecutive_429=5,
        )

    assert len(call_count) == 6, (
        f"Ожидалось 6 запросов (5 обработанных + 1 финальный), "
        f"получено {len(call_count)}"
    )
