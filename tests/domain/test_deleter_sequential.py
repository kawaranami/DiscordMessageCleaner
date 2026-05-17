# Feature: discord-message-purger, Property 26: Sequential delete (max one in-flight request)
from __future__ import annotations

import threading
import time
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


_AUTHENTICATED_USER_ID = "auth-user-sequential"

_message_st = st.builds(
    Message,
    id=st.text(min_size=1, max_size=20, alphabet=st.characters(categories=("L", "N"))),
    channel_id=st.text(min_size=1, max_size=15, alphabet=st.characters(categories=("L", "N"))),
    author_id=st.just(_AUTHENTICATED_USER_ID),
    content=st.text(max_size=30),
    timestamp=st.just(datetime(2024, 3, 15, 10, 0, 0, tzinfo=timezone.utc)),
)

_messages_st = st.lists(_message_st, min_size=2, max_size=20)


@settings(max_examples=100)
@given(messages=_messages_st)
def test_sequential_delete_max_one_in_flight(messages: list[Message]) -> None:
    lock = threading.Lock()
    current_in_flight = 0
    max_in_flight = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal current_in_flight, max_in_flight

        with lock:
            current_in_flight += 1
            if current_in_flight > max_in_flight:
                max_in_flight = current_in_flight

        time.sleep(0.001)

        with lock:
            current_in_flight -= 1

        return httpx.Response(204)

    http = _make_http_client(handler)
    log = OperationLog()
    log.found_total = len(messages)

    deleter = MessageDeleter(http, log, _AUTHENTICATED_USER_ID)

    for msg in messages:
        deleter.delete(msg)

    assert max_in_flight <= 1, (
        f"Обнаружено {max_in_flight} одновременных DELETE-запросов, "
        f"ожидали максимум 1 (последовательное удаление)"
    )
