# Feature: discord-message-purger, Property 1: Consent gating

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


_PROTECTED_OPERATIONS = sampled_from(["start_operation"])


@pytest.mark.property
@settings(max_examples=100)
@given(operation=_PROTECTED_OPERATIONS)
def test_consent_gating_blocks_without_consent(
    qapp,
    operation: str,
) -> None:

    session = Session()
    session.consent_granted = False

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
    controller.log_entry_added.connect(emitted_entries.append)

    server = Server(id="123456789", name="Тестовый сервер")

    if operation == "start_operation":
        controller.start(server=server, user_id="user_123")

    assert not scanner.list_channels_called, (
        "scanner.list_channels был вызван при consent_granted == False"
    )
    assert not scanner.scan_channel_called, (
        "scanner.scan_channel был вызван при consent_granted == False"
    )
    assert not deleter.delete_called, (
        "deleter.delete был вызван при consent_granted == False"
    )

    assert len(emitted_entries) >= 1, (
        "Ожидалась хотя бы одна лог-запись при отказе из-за отсутствия consent"
    )
    auth_entries = [e for e in emitted_entries if e.error_type == "auth"]
    assert len(auth_entries) >= 1, (
        "Ожидалась лог-запись с error_type='auth', "
        f"получены записи: {[e.error_type for e in emitted_entries]}"
    )
