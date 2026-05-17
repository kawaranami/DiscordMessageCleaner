from __future__ import annotations

import httpx
import pytest

from discord_message_purger.application.controller import OperationController
from discord_message_purger.application.session import Session
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


def _make_user_messages(channel_id: str, count: int, user_id: str):
    return [
        {
            "id": str(1000000 - i),
            "channel_id": channel_id,
            "author": {"id": user_id},
            "content": f"Сообщение #{i}",
            "timestamp": "2024-06-15T12:00:00+00:00",
        }
        for i in range(count)
    ]


def _build_components(transport, session):
    mock_client = httpx.Client(transport=transport, base_url="https://discord.com/api/v10")

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

    return controller, operation_log, http_client


@pytest.mark.integration
def test_401_mid_operation_cancels_and_clears_token(qapp):

    request_count = {"messages": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method

        if method == "GET" and f"/guilds/{_GUILD_ID}/channels" in path:
            return httpx.Response(
                200,
                json=[
                    {"id": _CHANNEL_1_ID, "guild_id": _GUILD_ID, "name": "general", "type": 0},
                ],
            )

        if method == "GET" and "/messages" in path:
            request_count["messages"] += 1
            if request_count["messages"] == 1:
                return httpx.Response(
                    200,
                    json=_make_user_messages(_CHANNEL_1_ID, 3, _USER_ID),
                )
            return httpx.Response(401, json={"message": "401: Unauthorized"})

        if method == "DELETE" and "/messages/" in path:
            return httpx.Response(204)

        return httpx.Response(404, json={"message": "Not Found"})

    transport = httpx.MockTransport(handler)

    session = Session()
    session.consent_granted = True
    session.token = _USER_TOKEN
    session.authenticated_user_id = _USER_ID

    controller, operation_log, http_client = _build_components(transport, session)

    operation_log.update_total(3)

    auth_lost_received = []
    controller.auth_lost.connect(lambda: auth_lost_received.append(True))

    server = Server(id=_GUILD_ID, name=_GUILD_NAME)
    controller.start(server, _USER_ID)

    assert controller._worker is not None
    controller._worker.join(timeout=10.0)
    qapp.processEvents()

    assert controller._ctx is not None
    assert controller._ctx.state == OperationState.CANCELED

    assert session.token is None
    assert session.authenticated_user_id is None

    assert len(auth_lost_received) > 0

    http_client.close()


@pytest.mark.integration
def test_5xx_after_retries_pauses_operation(qapp):

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method

        if method == "GET" and f"/guilds/{_GUILD_ID}/channels" in path:
            return httpx.Response(
                200,
                json=[
                    {"id": _CHANNEL_1_ID, "guild_id": _GUILD_ID, "name": "general", "type": 0},
                ],
            )

        if method == "GET" and "/messages" in path:
            return httpx.Response(500, json={"message": "Internal Server Error"})

        return httpx.Response(404, json={"message": "Not Found"})

    transport = httpx.MockTransport(handler)

    session = Session()
    session.consent_granted = True
    session.token = _USER_TOKEN
    session.authenticated_user_id = _USER_ID

    controller, operation_log, http_client = _build_components(transport, session)

    server = Server(id=_GUILD_ID, name=_GUILD_NAME)
    controller.start(server, _USER_ID)

    assert controller._worker is not None
    controller._worker.join(timeout=30.0)
    qapp.processEvents()

    assert controller._ctx is not None
    assert controller._ctx.state == OperationState.PAUSED

    assert session.token == _USER_TOKEN

    http_client.close()


@pytest.mark.integration
def test_empty_server_completes_with_zero_summary(qapp):

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method

        if method == "GET" and f"/guilds/{_GUILD_ID}/channels" in path:
            return httpx.Response(200, json=[])

        return httpx.Response(404, json={"message": "Not Found"})

    transport = httpx.MockTransport(handler)

    session = Session()
    session.consent_granted = True
    session.token = _USER_TOKEN
    session.authenticated_user_id = _USER_ID

    controller, operation_log, http_client = _build_components(transport, session)

    server = Server(id=_GUILD_ID, name=_GUILD_NAME)
    controller.start(server, _USER_ID)

    assert controller._worker is not None
    controller._worker.join(timeout=10.0)
    qapp.processEvents()

    assert controller._ctx is not None
    assert controller._ctx.state == OperationState.COMPLETED

    summary = operation_log.summary()
    assert summary.success == 0
    assert summary.not_found == 0
    assert summary.errors == 0
    assert summary.rejected_other_author == 0
    assert summary.channels_skipped == 0
    assert summary.scanned_messages == 0

    assert operation_log.processed == 0
    assert len(operation_log.entries) == 0

    http_client.close()


@pytest.mark.integration
def test_403_on_channel_skips_and_continues(qapp):

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method

        if method == "GET" and f"/guilds/{_GUILD_ID}/channels" in path:
            return httpx.Response(
                200,
                json=[
                    {"id": _CHANNEL_1_ID, "guild_id": _GUILD_ID, "name": "restricted", "type": 0},
                    {"id": _CHANNEL_2_ID, "guild_id": _GUILD_ID, "name": "open", "type": 0},
                ],
            )

        if method == "GET" and "/messages" in path:
            parts = path.split("/")
            channel_id = parts[4]

            if channel_id == _CHANNEL_1_ID:
                return httpx.Response(403, json={"message": "Missing Access"})

            if channel_id == _CHANNEL_2_ID:
                before_param = request.url.params.get("before")
                if before_param is None:
                    return httpx.Response(
                        200,
                        json=_make_user_messages(_CHANNEL_2_ID, 3, _USER_ID),
                    )
                return httpx.Response(200, json=[])

            return httpx.Response(200, json=[])

        if method == "DELETE" and "/messages/" in path:
            return httpx.Response(204)

        return httpx.Response(404, json={"message": "Not Found"})

    transport = httpx.MockTransport(handler)

    session = Session()
    session.consent_granted = True
    session.token = _USER_TOKEN
    session.authenticated_user_id = _USER_ID

    controller, operation_log, http_client = _build_components(transport, session)

    operation_log.update_total(3)

    server = Server(id=_GUILD_ID, name=_GUILD_NAME)
    controller.start(server, _USER_ID)

    assert controller._worker is not None
    controller._worker.join(timeout=10.0)
    qapp.processEvents()

    assert controller._ctx is not None
    assert controller._ctx.state == OperationState.COMPLETED

    skipped_entries = [
        e for e in operation_log.entries if e.status == LogEntryStatus.CHANNEL_SKIPPED
    ]
    assert len(skipped_entries) == 1
    assert skipped_entries[0].channel_id == _CHANNEL_1_ID
    assert "доступ запрещён" in skipped_entries[0].description

    success_entries = [e for e in operation_log.entries if e.status == LogEntryStatus.SUCCESS]
    assert len(success_entries) == 3

    summary = operation_log.summary()
    assert summary.success == 3
    assert summary.channels_skipped == 1
    assert summary.errors == 0

    http_client.close()
