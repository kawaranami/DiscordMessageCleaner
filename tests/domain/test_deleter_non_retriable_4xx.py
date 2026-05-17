# Feature: discord-message-purger, Property 25: Non-retriable 4xx -> single attempt, ERROR entry
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


_AUTHENTICATED_USER_ID = "auth-user-4xx"

_non_retriable_4xx_st = st.integers(min_value=400, max_value=499).filter(
    lambda c: c not in {401, 403, 404, 429}
)


@settings(max_examples=100)
@given(status_code=_non_retriable_4xx_st)
def test_non_retriable_4xx_single_attempt_error_entry(status_code: int) -> None:
    call_count: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        call_count.append(1)
        return httpx.Response(status_code, text=f"Error {status_code}")

    http = _make_http_client(handler)
    log = OperationLog()
    log.found_total = 1

    message = Message(
        id="msg-4xx-test",
        channel_id="ch-4xx-test",
        author_id=_AUTHENTICATED_USER_ID,
        content="test content",
        timestamp=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
    )

    deleter = MessageDeleter(http, log, _AUTHENTICATED_USER_ID)
    entry = deleter.delete(message)

    assert len(call_count) == 1, (
        f"Ожидали ровно 1 HTTP-запрос для non-retriable {status_code}, "
        f"получили {len(call_count)}"
    )

    assert entry.status == LogEntryStatus.ERROR, (
        f"Ожидали статус ERROR для HTTP {status_code}, получили {entry.status!r}"
    )

    assert entry.http_status == status_code, (
        f"Ожидали http_status={status_code}, получили {entry.http_status}"
    )
