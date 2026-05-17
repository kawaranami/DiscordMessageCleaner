# Feature: discord-message-purger, Property 5: Non-success HTTP/network errors classified consistently

from __future__ import annotations

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from discord_message_purger.application.session import Session
from discord_message_purger.application.token_manager import TokenManager
from discord_message_purger.infrastructure.http_client import DiscordHttpClient
from discord_message_purger.infrastructure.rate_limiter import RateLimiter


_http_status_not_2xx_401_429 = st.integers(min_value=100, max_value=599).filter(
    lambda c: c not in {401, 429} and not (200 <= c <= 299)
)

_error_scenario = st.one_of(
    _http_status_not_2xx_401_429,
    st.just(401),
    st.sampled_from(["NETWORK", "TIMEOUT"]),
)


def _build_manager_for_scenario(scenario) -> tuple[TokenManager, Session]:

    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(scenario, str):
            if scenario == "NETWORK":
                raise httpx.ConnectError("симуляция сетевой ошибки")
            elif scenario == "TIMEOUT":
                raise httpx.ReadTimeout("симуляция таймаута")
        return httpx.Response(scenario, text="error body")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(
        base_url="https://discord.com/api/v10",
        transport=transport,
    )
    session = Session()
    rate_limiter = RateLimiter(sleep_fn=lambda _s: None)
    http = DiscordHttpClient(
        token_provider=lambda: session.token,
        rate_limiter=rate_limiter,
        client=client,
    )
    manager = TokenManager(http=http, session=session)
    return manager, session


@pytest.mark.property
@settings(max_examples=150)
@given(scenario=_error_scenario)
def test_error_classification(scenario) -> None:

    manager, session = _build_manager_for_scenario(scenario)

    result = manager.validate_and_store("test-token-value")

    if scenario == 401:
        assert result.status == "invalid_token", (
            f"Ожидался статус 'invalid_token' для HTTP 401, "
            f"получен '{result.status}'"
        )
    else:
        assert result.status == "network_error", (
            f"Ожидался статус 'network_error' для сценария {scenario!r}, "
            f"получен '{result.status}'"
        )

    assert session.token is None, (
        f"session.token должен быть None после ошибки (сценарий {scenario!r}), "
        f"но равен {session.token!r}"
    )
    assert session.authenticated_user_id is None, (
        f"session.authenticated_user_id должен быть None после ошибки "
        f"(сценарий {scenario!r}), но равен {session.authenticated_user_id!r}"
    )
