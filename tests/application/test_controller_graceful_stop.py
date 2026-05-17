# Feature: discord-message-purger, Property 38: Graceful stop within 30 seconds

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Iterator

import pytest
from hypothesis import given, settings
from hypothesis.strategies import floats, sampled_from

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


class BlockingDeleter:

    def __init__(self, block_duration: float) -> None:
        self._block_duration = block_duration
        self.delete_count: int = 0
        self._lock = threading.Lock()

    def delete(self, message: Message) -> OperationLogEntry:
        if self._block_duration > 0:
            time.sleep(self._block_duration)

        with self._lock:
            self.delete_count += 1

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

    @property
    def current_count(self) -> int:
        with self._lock:
            return self.delete_count


class MultiMessageScanner:

    def __init__(self, message_count: int = 200) -> None:
        self._message_count = message_count

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
        for i in range(self._message_count):
            if ctx.check_cancelled():
                return
            if not ctx.wait_if_paused():
                return
            yield Message(
                id=f"msg_{i}",
                channel_id=channel.id,
                author_id=authenticated_user_id,
                content=f"Сообщение {i}",
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )


@pytest.mark.property
@settings(max_examples=100, deadline=None)
@given(
    command=sampled_from(["pause", "cancel"]),
    block_duration=floats(min_value=0.0, max_value=0.02),
)
def test_graceful_stop_within_30_seconds(
    qapp,
    command: str,
    block_duration: float,
) -> None:

    session = Session()
    session.consent_granted = True
    session.token = "test_token"
    session.authenticated_user_id = "user_123"

    deleter = BlockingDeleter(block_duration=block_duration)
    scanner = MultiMessageScanner(message_count=200)
    operation_log = OperationLog()

    controller = OperationController(
        scanner=scanner,
        deleter=deleter,
        operation_log=operation_log,
        session=session,
    )

    state_changes: list[OperationState] = []
    target_reached = threading.Event()

    if command == "pause":
        target_state = OperationState.PAUSED
    else:
        target_state = OperationState.CANCELED

    def on_state_changed(new_state: OperationState) -> None:
        state_changes.append(new_state)
        if new_state == target_state:
            target_reached.set()

    controller.state_changed.connect(on_state_changed)

    server = Server(id="guild_1", name="Тестовый сервер")
    controller.start(server=server, user_id="user_123")

    deadline = time.monotonic() + 5.0
    while OperationState.RUNNING not in state_changes:
        if time.monotonic() > deadline:
            if controller._worker is not None:
                controller._worker.join(timeout=1.0)
            return
        time.sleep(0.002)

    time.sleep(0.01)

    command_time = time.monotonic()

    if command == "pause":
        controller.pause()
    else:
        controller.cancel()

    reached = target_reached.wait(timeout=30.0)

    assert reached, (
        f"Переход в {target_state} не произошёл за 30 секунд после {command}. "
        f"Состояния: {state_changes}"
    )

    transition_time = time.monotonic() - command_time
    assert transition_time <= 30.0, (
        f"Переход в {target_state} занял {transition_time:.2f} с (лимит 30 с)"
    )

    deletes_at_transition = deleter.current_count

    time.sleep(block_duration + 0.05)

    deletes_after_transition = deleter.current_count - deletes_at_transition
    assert deletes_after_transition <= 1, (
        f"После перехода в {target_state} было выполнено "
        f"{deletes_after_transition} DELETE-запросов (допускается ≤1)"
    )

    if command == "pause":
        controller.cancel()
    if controller._worker is not None:
        controller._worker.join(timeout=5.0)
