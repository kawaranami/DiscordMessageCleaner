# Feature: discord-message-purger, Property 4: Successful auth round trip

from __future__ import annotations

import httpx
import pytest
from hypothesis import given, settings
from hypothesis.strategies import characters, text

from discord_message_purger.application.session import Session
from discord_message_purger.application.token_manager import TokenManager
from discord_message_purger.infrastructure.http_client import DiscordHttpClient
from discord_message_purger.infrastructure.rate_limiter import RateLimiter


_ascii_printable = characters(min_codepoint=33, max_codepoint=126)


@pytest.mark.property
@settings(max_examples=100)
@given(
    token=text(alphabet=_ascii_printable, min_size=1, max_size=100),
    user_id=text(min_size=1, max_size=20),
)
def test_successful_auth_round_trip(token: str, user_id: str) -> None:

    session = Session()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": user_id})

    transport = httpx.MockTransport(handler)
    httpx_client = httpx.Client(
        base_url="https://discord.com/api/v10", transport=transport
    )

    rate_limiter = RateLimiter(sleep_fn=lambda _s: None)

    discord_client = DiscordHttpClient(
        token_provider=lambda: session.token,
        rate_limiter=rate_limiter,
        client=httpx_client,
    )

    manager = TokenManager(http=discord_client, session=session)

    result = manager.validate_and_store(token)

    assert session.token == token, (
        f"Ожидали session.token == {token!r}, получили {session.token!r}"
    )
    assert session.authenticated_user_id == user_id, (
        f"Ожидали session.authenticated_user_id == {user_id!r}, "
        f"получили {session.authenticated_user_id!r}"
    )
    assert result.status == "ok"
    assert result.user_id == user_id
