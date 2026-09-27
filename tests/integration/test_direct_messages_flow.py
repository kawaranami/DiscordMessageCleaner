from __future__ import annotations

import httpx
import pytest

from discord_message_purger.application.controller import OperationController
from discord_message_purger.application.session import Session
from discord_message_purger.domain.deleter import MessageDeleter
from discord_message_purger.domain.direct_messages import DirectMessageDirectory
from discord_message_purger.domain.models import (
    DirectMessagesTarget,
    LogEntryStatus,
    OperationState,
)
from discord_message_purger.domain.operation_log import OperationLog
from discord_message_purger.domain.scanner import MessageScanner
from discord_message_purger.infrastructure.http_client import DiscordHttpClient
from discord_message_purger.infrastructure.rate_limiter import RateLimiter


_USER_ID = "123456789"
_FRIEND_ID = "555555555"
_DM_ID = "700000000000000001"
_GROUP_ID = "700000000000000002"
_OTHER_DM_ID = "700000000000000003"


def _msg(msg_id: str, channel_id: str, author_id: str, msg_type: int = 0) -> dict:
    return {
        "id": msg_id,
        "type": msg_type,
        "channel_id": channel_id,
        "author": {"id": author_id},
        "content": f"message {msg_id}",
        "timestamp": "2024-06-15T12:00:00+00:00",
    }


_HISTORY: dict[str, list[dict]] = {
    _DM_ID: [
        _msg("1009", _DM_ID, _USER_ID),
        _msg("1008", _DM_ID, _FRIEND_ID),
        _msg("1007", _DM_ID, _USER_ID, msg_type=3),
        _msg("1006", _DM_ID, _USER_ID, msg_type=19),
        _msg("1005", _DM_ID, _FRIEND_ID),
    ],
    _GROUP_ID: [
        _msg("2003", _GROUP_ID, _USER_ID),
        _msg("2002", _GROUP_ID, _USER_ID, msg_type=1),
        _msg("2001", _GROUP_ID, _FRIEND_ID),
    ],
    _OTHER_DM_ID: [
        _msg("3001", _OTHER_DM_ID, _USER_ID),
    ],
}

_OPEN_CHANNELS = [
    {
        "id": _DM_ID,
        "type": 1,
        "last_message_id": "1009",
        "recipients": [{"id": _FRIEND_ID, "username": "friend", "global_name": "Friend"}],
    },
    {
        "id": _GROUP_ID,
        "type": 3,
        "name": "Squad",
        "last_message_id": "2003",
        "recipients": [{"id": _FRIEND_ID, "username": "friend"}],
    },
    {
        "id": _OTHER_DM_ID,
        "type": 1,
        "last_message_id": "3001",
        "recipients": [{"id": "777", "username": "someone"}],
    },
]


class _Recorder:

    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []
        self.paths: list[str] = []


def _handler(recorder: _Recorder):

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v10")
        recorder.paths.append(f"{request.method} {path}")

        if request.method == "GET" and path == "/users/@me/channels":
            return httpx.Response(200, json=_OPEN_CHANNELS)

        parts = path.strip("/").split("/")
        if parts[0] == "channels" and parts[2:] == ["messages"]:
            channel_id = parts[1]
            if request.url.params.get("before"):
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=_HISTORY.get(channel_id, []))

        if request.method == "DELETE" and parts[0] == "channels" and len(parts) == 4:
            recorder.deleted.append((parts[1], parts[3]))
            return httpx.Response(204)

        return httpx.Response(404, json={"message": "Unknown"})

    return handler


@pytest.mark.integration
def test_direct_messages_cleanup_deletes_only_own_deletable_messages(qapp):

    recorder = _Recorder()
    session = Session()
    session.consent_granted = True
    session.token = "token"
    session.authenticated_user_id = _USER_ID

    rate_limiter = RateLimiter(sleep_fn=lambda s: None)
    http_client = DiscordHttpClient(
        token_provider=lambda: session.token,
        rate_limiter=rate_limiter,
        client=httpx.Client(
            transport=httpx.MockTransport(_handler(recorder)),
            base_url="https://discord.com/api/v10",
        ),
    )
    operation_log = OperationLog()
    controller = OperationController(
        scanner=MessageScanner(http=http_client, operation_log=operation_log),
        deleter=MessageDeleter(
            http=http_client,
            operation_log=operation_log,
            authenticated_user_id=_USER_ID,
            rate_limiter=rate_limiter,
        ),
        operation_log=operation_log,
        session=session,
    )

    open_channels = DirectMessageDirectory(http_client).list_channels()
    selected = tuple(c for c in open_channels if c.id in {_DM_ID, _GROUP_ID})
    assert [c.name for c in selected] == ["Group: Squad", "Friend (@friend)"]

    controller.start(DirectMessagesTarget(channels=selected), _USER_ID)
    assert controller._worker is not None
    controller._worker.join(timeout=15.0)
    qapp.processEvents()

    assert controller._ctx is not None
    assert controller._ctx.state == OperationState.COMPLETED
    assert not controller.is_busy

    assert sorted(recorder.deleted) == sorted(
        [(_DM_ID, "1009"), (_DM_ID, "1006"), (_GROUP_ID, "2003")]
    )
    assert not any(_OTHER_DM_ID in p for p in recorder.paths)
    assert not any("/guilds/" in p for p in recorder.paths)

    summary = operation_log.summary()
    assert summary.success == 3
    assert summary.found_for_user == 3
    assert summary.errors == 0
    assert all(
        e.status is LogEntryStatus.SUCCESS
        for e in operation_log.entries
    )

    http_client.close()
