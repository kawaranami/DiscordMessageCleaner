# Feature: discord-message-purger, Property 14: Scanner and Deleter forward only own messages (defense-in-depth)
from __future__ import annotations

from datetime import datetime, timezone

import httpx
from hypothesis import given, settings
from hypothesis import strategies as st

from discord_message_purger.domain.deleter import MessageDeleter
from discord_message_purger.domain.models import Message
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


_AUTHENTICATED_USER_ID = "auth-user-42"

_author_id_st = st.one_of(
    st.just(_AUTHENTICATED_USER_ID),
    st.text(min_size=1, max_size=20).filter(lambda s: s != _AUTHENTICATED_USER_ID),
)

_message_st = st.builds(
    Message,
    id=st.text(min_size=1, max_size=30, alphabet=st.characters(categories=("L", "N"))),
    channel_id=st.text(min_size=1, max_size=20, alphabet=st.characters(categories=("L", "N"))),
    author_id=_author_id_st,
    content=st.text(max_size=50),
    timestamp=st.just(datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)),
)

_messages_st = st.lists(_message_st, min_size=0, max_size=20)


@settings(max_examples=100)
@given(messages=_messages_st)
def test_defense_in_depth_only_own_messages_deleted(messages: list[Message]) -> None:
    deleted_message_ids: set[str] = set()

    def handler(request: httpx.Request) -> httpx.Response:
        parts = request.url.path.split("/")
        if len(parts) >= 7 and parts[5] == "messages":
            deleted_message_ids.add(parts[6])
        return httpx.Response(204)

    http = _make_http_client(handler)
    log = OperationLog()
    log.found_total = max(len(messages), 1)

    deleter = MessageDeleter(http, log, _AUTHENTICATED_USER_ID)

    for msg in messages:
        deleter.delete(msg)

    own_message_ids = {m.id for m in messages if m.author_id == _AUTHENTICATED_USER_ID}

    assert deleted_message_ids <= own_message_ids, (
        f"HTTP DELETE отправлен для чужих сообщений! "
        f"Удалено: {deleted_message_ids}, Свои: {own_message_ids}, "
        f"Лишние: {deleted_message_ids - own_message_ids}"
    )
