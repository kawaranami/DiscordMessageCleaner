# Feature: discord-message-purger, Property 15: Missing user_id aborts before any HTTP call

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis.strategies import sampled_from

from discord_message_purger.application.controller import (
    DeleterProtocol,
    OperationController,
    ScannerProtocol,
)
from discord_message_purger.application.operation_context import OperationContext
from discord_message_purger.application.session import Session
from discord_message_purger.domain.exceptions import MissingAuthenticatedUserError
from discord_message_purger.domain.models import (
    Channel,
    ChannelType,
    Message,
    OperationLogEntry,
    OperationState,
    Server,
)
from discord_message_purger.domain.operation_log import OperationLog


class MockScanner:

    def __init__(self) -> None:
        self.list_channels_called: bool = False
        self.scan_channel_called: bool = False

    def list_channels(self, guild_id: str) -> list[Channel]:
        self.list_channels_called = True
        return []

    def scan_channel(
        self,
        channel: Channel,
        authenticated_user_id: str,
        ctx: OperationContext,
    ) -> Iterator[Message]:
        self.scan_channel_called = True
        return iter([])


class MockDeleter:

    def __init__(self) -> None:
        self.delete_called: bool = False

    def delete(self, message: Message) -> OperationLogEntry:
        self.delete_called = True
        return OperationLogEntry(
            timestamp_local=datetime.now(tz=timezone.utc),
            status="Успех",
            channel_id=message.channel_id,
            message_id=message.id,
            first_visible_char="x",
            message_timestamp=message.timestamp,
            http_status=204,
            error_type=None,
            description="",
        )


_INVALID_USER_IDS = sampled_from([None, "", " ", "\t", "\n  "])


@pytest.mark.property
@settings(max_examples=100)
@given(user_id=_INVALID_USER_IDS)
def test_missing_user_id_aborts_before_http(
    qapp,
    user_id: str | None,
) -> None:

    session = Session()
    session.consent_granted = True

    scanner = MockScanner()
    deleter = MockDeleter()
    operation_log = OperationLog()

    controller = OperationController(
        scanner=scanner,
        deleter=deleter,
        operation_log=operation_log,
        session=session,
    )

    emitted_entries: list[OperationLogEntry] = []
    emitted_states: list[OperationState] = []
    controller.log_entry_added.connect(emitted_entries.append)
    controller.state_changed.connect(emitted_states.append)

    server = Server(id="987654321", name="Тестовый сервер")

    with pytest.raises(MissingAuthenticatedUserError):
        controller.start(server=server, user_id=user_id)

    assert not scanner.list_channels_called, (
        f"scanner.list_channels был вызван при user_id={user_id!r}"
    )
    assert not scanner.scan_channel_called, (
        f"scanner.scan_channel был вызван при user_id={user_id!r}"
    )
    assert not deleter.delete_called, (
        f"deleter.delete был вызван при user_id={user_id!r}"
    )

    assert len(emitted_entries) >= 1, (
        "Ожидалась хотя бы одна лог-запись при невалидном user_id"
    )
    auth_entries = [e for e in emitted_entries if e.error_type == "auth"]
    assert len(auth_entries) >= 1, (
        "Ожидалась лог-запись с error_type='auth', "
        f"получены записи: {[e.error_type for e in emitted_entries]}"
    )

    assert OperationState.ERROR in emitted_states, (
        f"Ожидался переход в ERROR, получены состояния: {emitted_states}"
    )
