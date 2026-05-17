# Feature: discord-message-purger, Property 7: Token never appears in repr/str

from __future__ import annotations

import httpx
import pytest
from hypothesis import given, settings
from hypothesis.strategies import characters, text

from discord_message_purger.application.session import Session
from discord_message_purger.application.token_manager import TokenManager
from discord_message_purger.domain.exceptions import DiscordHttpError
from discord_message_purger.infrastructure.http_client import DiscordHttpClient
from discord_message_purger.infrastructure.rate_limiter import RateLimiter


_token_strategy = text(
    alphabet=characters(min_codepoint=33, max_codepoint=126),
    min_size=8,
    max_size=100,
)


@pytest.mark.property
@settings(max_examples=100)
@given(token=_token_strategy)
def test_token_not_in_session_repr_str(token: str) -> None:

    session = Session()
    session.token = token

    session_repr = repr(session)
    assert token not in session_repr, (
        f"Токен обнаружен в repr(Session): {session_repr!r}"
    )

    session_str = str(session)
    assert token not in session_str, (
        f"Токен обнаружен в str(Session): {session_str!r}"
    )


@pytest.mark.property
@settings(max_examples=100)
@given(token=_token_strategy)
def test_token_not_in_token_manager_repr(token: str) -> None:

    session = Session()
    session.token = token

    rate_limiter = RateLimiter(sleep_fn=lambda _s: None)

    transport = httpx.MockTransport(
        lambda _req: httpx.Response(200, json={"id": "test"})
    )
    httpx_client = httpx.Client(
        base_url="https://discord.com/api/v10", transport=transport
    )

    discord_client = DiscordHttpClient(
        token_provider=lambda: session.token,
        rate_limiter=rate_limiter,
        client=httpx_client,
    )

    manager = TokenManager(http=discord_client, session=session)

    manager_repr = repr(manager)
    assert token not in manager_repr, (
        f"Токен обнаружен в repr(TokenManager): {manager_repr!r}"
    )

    manager_str = str(manager)
    assert token not in manager_str, (
        f"Токен обнаружен в str(TokenManager): {manager_str!r}"
    )


@pytest.mark.property
@settings(max_examples=100)
@given(token=_token_strategy)
def test_token_not_in_discord_http_error_repr(token: str) -> None:

    from hypothesis import assume

    repr_structure = "DiscordHttpError(status=500, body='Authorization: ***')"
    assume(token not in repr_structure)

    body_with_token = f"Authorization: {token}"
    error = DiscordHttpError(status=500, body=body_with_token)

    error_repr = repr(error)
    assert token not in error_repr, (
        f"Токен обнаружен в repr(DiscordHttpError): {error_repr!r}"
    )

    error_str = str(error)
    assert token not in error_str, (
        f"Токен обнаружен в str(DiscordHttpError): {error_str!r}"
    )
