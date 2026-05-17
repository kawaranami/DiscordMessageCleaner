# Feature: discord-message-purger, Property 22: Successful delete log entry has correct identifiers
from __future__ import annotations

from datetime import datetime, timezone

import httpx
from hypothesis import given, settings
from hypothesis import strategies as st

from discord_message_purger.domain.deleter import MessageDeleter
from discord_message_purger.domain.models import (
    LogEntryStatus,
    Message,
)
from discord_message_purger.domain.operation_log import OperationLog
from discord_message_purger.infrastructure.http_client import DiscordHttpClient


class _NoOpRateLimiter:

    def before_request(self, route_key: str, cancel_event=None) -> None:
        pass

    def after_response(self, route_key: str, response) -> None:
        pass

    def handle_429(self, response, ctx=None) -> None:
        pass


def _make_http_client(handler, token: str = "test-token") -> DiscordHttpClient:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(
        base_url="https://discord.com/api/v10",
        transport=transport,
    )
    return DiscordHttpClient(
        token_provider=lambda: token,
        rate_limiter=_NoOpRateLimiter(),
        client=client,
    )


_AUTHENTICATED_USER_ID = "auth-user-correct-ids"

_message_st = st.builds(
    Message,
    id=st.text(min_size=1, max_size=30, alphabet=st.characters(categories=("L", "N"))),
    channel_id=st.text(min_size=1, max_size=20, alphabet=st.characters(categories=("L", "N"))),
    author_id=st.just(_AUTHENTICATED_USER_ID),
    content=st.text(max_size=50),
    timestamp=st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2025, 12, 31),
        timezones=st.just(timezone.utc),
    ),
)

_status_code_st = st.sampled_from([204, 404])


@settings(max_examples=100)
@given(message=_message_st, status_code=_status_code_st)
def test_correct_ids_in_log_entry(message: Message, status_code: int) -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        if status_code == 404:
            return httpx.Response(404, text="Not Found")
        return httpx.Response(204)

    http = _make_http_client(handler)
    log = OperationLog()
    log.found_total = 1

    deleter = MessageDeleter(http, log, _AUTHENTICATED_USER_ID)
    entry = deleter.delete(message)

    assert entry.message_id == message.id, (
        f"message_id не совпадает: ожидали {message.id!r}, получили {entry.message_id!r}"
    )
    assert entry.channel_id == message.channel_id, (
        f"channel_id не совпадает: ожидали {message.channel_id!r}, получили {entry.channel_id!r}"
    )

    expected_status = LogEntryStatus.SUCCESS if status_code == 204 else LogEntryStatus.NOT_FOUND
    assert entry.status == expected_status, (
        f"Статус не совпадает: HTTP {status_code} -> ожидали {expected_status!r}, "
        f"получили {entry.status!r}"
    )
