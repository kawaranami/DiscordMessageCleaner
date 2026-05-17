# Feature: discord-message-purger, Property 39: Resume continues from first unprocessed message

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Iterator

import pytest
from hypothesis import given, settings, assume
from hypothesis.strategies import (
    integers,
    lists,
    sampled_from,
    booleans,
    composite,
)

from discord_message_purger.application.controller import (
    OperationController,
)
from discord_message_purger.application.operation_context import OperationContext
from discord_message_purger.application.session import Session
from discord_message_purger.domain.models import (
    Channel,
    ChannelType,
    LogEntryStatus,
    Message,
    OperationLogEntry,
    OperationState,
    Server,
)
from discord_message_purger.domain.operation_log import OperationLog


_PROCESSED_STATUSES = [
    LogEntryStatus.SUCCESS,
    LogEntryStatus.NOT_FOUND,
    LogEntryStatus.ERROR,
    LogEntryStatus.REJECTED,
]


@composite
def messages_with_processed_subset(draw):
    count = draw(integers(min_value=2, max_value=15))

    messages = []
    for i in range(count):
        msg = Message(
            id=f"msg_{i:04d}",
            channel_id="ch_1",
            author_id="user_123",
            content=f"Содержимое сообщения {i}",
            timestamp=datetime(2024, 1, 1, hour=i % 24, tzinfo=timezone.utc),
        )
        messages.append(msg)

    processed_flags = draw(lists(booleans(), min_size=count, max_size=count))
    processed_ids = {
        messages[i].id for i in range(count) if processed_flags[i]
    }

    assume(len(processed_ids) < count)

    processed_statuses = {}
    for msg_id in processed_ids:
        status = draw(sampled_from(_PROCESSED_STATUSES))
        processed_statuses[msg_id] = status

    return messages, processed_ids, processed_statuses


class TrackingDeleter:

    def __init__(self) -> None:
        self.deleted_message_ids: list[str] = []
        self.first_delete_event = threading.Event()
        self._lock = threading.Lock()

    def delete(self, message: Message) -> OperationLogEntry:
        with self._lock:
            self.deleted_message_ids.append(message.id)
            if len(self.deleted_message_ids) == 1:
                self.first_delete_event.set()

        return OperationLogEntry(
            timestamp_local=datetime.now(tz=timezone.utc),
            status=LogEntryStatus.SUCCESS,
            channel_id=message.channel_id,
            message_id=message.id,
            first_visible_char=message.content[:1] if message.content else "·",
            message_timestamp=message.timestamp,
            http_status=204,
            error_type=None,
            description="",
        )


class ResumeScanner:

    def __init__(self, messages: list[Message], processed_ids: set[str]) -> None:
        self._messages = messages
        self._processed_ids = processed_ids

    def list_channels(self, guild_id: str) -> list[Channel]:
        return [
            Channel(
                id="ch_1",
                guild_id=guild_id,
                name="тестовый-канал",
                type=ChannelType.GUILD_TEXT,
            )
        ]

    def scan_channel(
        self,
        channel: Channel,
        authenticated_user_id: str,
        ctx: OperationContext,
    ) -> Iterator[Message]:
        for msg in self._messages:
            if ctx.check_cancelled():
                return
            if not ctx.wait_if_paused():
                return
            if msg.id in self._processed_ids:
                continue
            yield msg


@pytest.mark.property
@settings(max_examples=100, deadline=None)
@given(data=messages_with_processed_subset())
def test_resume_continues_from_first_unprocessed(
    qapp,
    data: tuple,
) -> None:
    messages, processed_ids, processed_statuses = data

    expected_first_unprocessed = None
    for msg in messages:
        if msg.id not in processed_ids:
            expected_first_unprocessed = msg
            break

    assert expected_first_unprocessed is not None

    session = Session()
    session.consent_granted = True
    session.token = "test_token"
    session.authenticated_user_id = "user_123"

    deleter = TrackingDeleter()
    scanner = ResumeScanner(messages=messages, processed_ids=processed_ids)
    operation_log = OperationLog()
    operation_log.found_total = 1000

    for msg_id, status in processed_statuses.items():
        entry = OperationLogEntry(
            timestamp_local=datetime.now(tz=timezone.utc),
            status=status,
            channel_id="ch_1",
            message_id=msg_id,
            first_visible_char="x",
            message_timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            http_status=204 if status == LogEntryStatus.SUCCESS else None,
            error_type=None,
            description="",
        )
        operation_log.add(entry)

    controller = OperationController(
        scanner=scanner,
        deleter=deleter,
        operation_log=operation_log,
        session=session,
    )

    state_changes: list[OperationState] = []
    controller.state_changed.connect(state_changes.append)

    server = Server(id="guild_1", name="Тестовый сервер")
    controller.start(server=server, user_id="user_123")

    got_first_delete = deleter.first_delete_event.wait(timeout=10.0)

    if got_first_delete:
        assert deleter.deleted_message_ids[0] == expected_first_unprocessed.id, (
            f"Ожидался первый delete для '{expected_first_unprocessed.id}', "
            f"но получен для '{deleter.deleted_message_ids[0]}'. "
            f"Обработанные: {processed_ids}"
        )
    else:
        pytest.fail(
            "Deleter.delete() не был вызван за 10 секунд после запуска операции"
        )

    if controller._ctx is not None and controller._ctx.state in (
        OperationState.RUNNING,
        OperationState.PAUSED,
    ):
        controller.cancel()
    if controller._worker is not None:
        controller._worker.join(timeout=5.0)
