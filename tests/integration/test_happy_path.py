from __future__ import annotations

import time

import httpx
import pytest

from discord_message_purger.application.controller import OperationController
from discord_message_purger.application.session import Session
from discord_message_purger.application.token_manager import TokenManager
from discord_message_purger.domain.deleter import MessageDeleter
from discord_message_purger.domain.models import (
    LogEntryStatus,
    OperationState,
    Server,
)
from discord_message_purger.domain.operation_log import OperationLog
from discord_message_purger.domain.scanner import MessageScanner
from discord_message_purger.infrastructure.http_client import DiscordHttpClient
from discord_message_purger.infrastructure.rate_limiter import RateLimiter


_USER_ID = "123456789"
_USER_TOKEN = "test-token-abc"
_GUILD_ID = "999000111"
_GUILD_NAME = "Test Server"
_CHANNEL_1_ID = "100001"
_CHANNEL_2_ID = "100002"


def _make_messages(channel_id: str, count: int, user_id: str, other_user_id: str = "999999"):
    messages = []
    for i in range(count):
        author_id = user_id if i % 2 == 0 else other_user_id
        messages.append({
            "id": str(1000000 - i),
            "channel_id": channel_id,
            "author": {"id": author_id},
            "content": f"Сообщение #{i} от {'user' if author_id == user_id else 'other'}",
            "timestamp": "2024-06-15T12:00:00+00:00",
        })
    return messages


class _MockState:

    def __init__(self):
        self.deleted_message_ids: list[str] = []
        self.channel_messages: dict[str, list[dict]] = {
            _CHANNEL_1_ID: _make_messages(_CHANNEL_1_ID, 10, _USER_ID),
            _CHANNEL_2_ID: _make_messages(_CHANNEL_2_ID, 6, _USER_ID),
        }


def _build_mock_transport(state: _MockState) -> httpx.MockTransport:

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method

        if method == "GET" and path == "/api/v10/users/@me":
            return httpx.Response(
                200,
                json={"id": _USER_ID, "username": "testuser", "discriminator": "0001"},
            )

        if method == "GET" and path == "/api/v10/users/@me/guilds":
            return httpx.Response(
                200,
                json=[{"id": _GUILD_ID, "name": _GUILD_NAME, "icon": None}],
            )

        if method == "GET" and path == f"/api/v10/guilds/{_GUILD_ID}/channels":
            return httpx.Response(
                200,
                json=[
                    {"id": _CHANNEL_1_ID, "guild_id": _GUILD_ID, "name": "general", "type": 0},
                    {"id": _CHANNEL_2_ID, "guild_id": _GUILD_ID, "name": "announcements", "type": 5},
                    {"id": "100003", "guild_id": _GUILD_ID, "name": "voice", "type": 2},
                ],
            )

        if method == "GET" and "/messages" in path:
            parts = path.split("/")
            channel_id = parts[4]
            messages = state.channel_messages.get(channel_id, [])

            before_param = request.url.params.get("before")
            if before_param:
                before_int = int(before_param)
                messages = [m for m in messages if int(m["id"]) < before_int]

            limit = int(request.url.params.get("limit", "100"))
            page = messages[:limit]

            return httpx.Response(200, json=page)

        if method == "DELETE" and "/messages/" in path:
            parts = path.split("/")
            message_id = parts[6]
            state.deleted_message_ids.append(message_id)
            return httpx.Response(204)

        return httpx.Response(404, json={"message": "Not Found"})

    return httpx.MockTransport(handler)


@pytest.mark.integration
def test_happy_path_full_cycle(qapp):

    state = _MockState()
    transport = _build_mock_transport(state)
    mock_client = httpx.Client(transport=transport, base_url="https://discord.com/api/v10")

    session = Session()
    session.consent_granted = True

    rate_limiter = RateLimiter(
        time_source=time.monotonic,
        sleep_fn=lambda s: None,
    )

    http_client = DiscordHttpClient(
        token_provider=lambda: session.token,
        rate_limiter=rate_limiter,
        client=mock_client,
    )

    token_manager = TokenManager(http=http_client, session=session)
    result = token_manager.validate_and_store(_USER_TOKEN)

    assert result.status == "ok"
    assert result.user_id == _USER_ID
    assert session.token == _USER_TOKEN
    assert session.authenticated_user_id == _USER_ID

    operation_log = OperationLog()
    operation_log.update_total(8)

    scanner = MessageScanner(http=http_client, operation_log=operation_log)
    deleter = MessageDeleter(
        http=http_client,
        operation_log=operation_log,
        authenticated_user_id=_USER_ID,
        rate_limiter=rate_limiter,
    )

    controller = OperationController(
        scanner=scanner,
        deleter=deleter,
        operation_log=operation_log,
        session=session,
    )

    states_received: list[OperationState] = []
    summaries_received = []

    controller.state_changed.connect(lambda s: states_received.append(s))
    controller.summary_ready.connect(lambda s: summaries_received.append(s))

    server = Server(id=_GUILD_ID, name=_GUILD_NAME)
    controller.start(server, _USER_ID)

    assert controller._worker is not None
    controller._worker.join(timeout=10.0)
    assert not controller._worker.is_alive(), "Worker-поток не завершился за 10 секунд"

    qapp.processEvents()


    assert controller._ctx is not None
    assert controller._ctx.state == OperationState.COMPLETED

    assert OperationState.RUNNING in states_received
    assert OperationState.COMPLETED in states_received

    expected_user_messages = 5 + 3

    assert len(state.deleted_message_ids) == expected_user_messages

    assert operation_log.processed == expected_user_messages

    success_entries = [e for e in operation_log.entries if e.status == LogEntryStatus.SUCCESS]
    assert len(success_entries) == expected_user_messages

    expected_skipped = 5 + 3
    assert operation_log.skipped_other_authors == expected_skipped

    summary = operation_log.summary()
    assert summary.success == expected_user_messages
    assert summary.not_found == 0
    assert summary.errors == 0
    assert summary.rejected_other_author == expected_skipped
    assert summary.channels_skipped == 0

    assert operation_log.scanned_messages == 16

    assert session.token == _USER_TOKEN

    http_client.close()


@pytest.mark.integration
def test_happy_path_found_total_updated(qapp):

    state = _MockState()
    transport = _build_mock_transport(state)
    mock_client = httpx.Client(transport=transport, base_url="https://discord.com/api/v10")

    session = Session()
    session.consent_granted = True
    session.token = _USER_TOKEN
    session.authenticated_user_id = _USER_ID

    rate_limiter = RateLimiter(sleep_fn=lambda s: None)

    http_client = DiscordHttpClient(
        token_provider=lambda: session.token,
        rate_limiter=rate_limiter,
        client=mock_client,
    )

    operation_log = OperationLog()
    scanner = MessageScanner(http=http_client, operation_log=operation_log)
    deleter = MessageDeleter(
        http=http_client,
        operation_log=operation_log,
        authenticated_user_id=_USER_ID,
        rate_limiter=rate_limiter,
    )

    controller = OperationController(
        scanner=scanner,
        deleter=deleter,
        operation_log=operation_log,
        session=session,
    )

    server = Server(id=_GUILD_ID, name=_GUILD_NAME)
    controller.start(server, _USER_ID)

    assert controller._worker is not None
    controller._worker.join(timeout=10.0)
    qapp.processEvents()

    assert operation_log.processed <= operation_log.found_total

    http_client.close()
