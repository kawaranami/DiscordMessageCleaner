# Feature: discord-message-purger, Property 41: 401 mid-operation triggers immediate cancel and token clear

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Iterator

import pytest
from hypothesis import given, settings
from hypothesis.strategies import sampled_from
from PySide6.QtWidgets import QApplication

from discord_message_purger.application.controller import (
    OperationController,
)
from discord_message_purger.application.operation_context import OperationContext
from discord_message_purger.application.session import Session
from discord_message_purger.domain.exceptions import DiscordAuthError
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


class AuthErrorScanner:

    def __init__(self, injection_point: str) -> None:
        self._injection_point = injection_point
        self._error_raised = threading.Event()

    def list_channels(self, guild_id: str) -> list[Channel]:
        if self._injection_point == "list_channels":
            self._error_raised.set()
            raise DiscordAuthError(body="401 Unauthorized")

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
        if self._injection_point == "scan_channel":
            self._error_raised.set()
            raise DiscordAuthError(body="401 Unauthorized")

        for i in range(5):
            if ctx.check_cancelled():
                return
            yield Message(
                id=f"msg_{i}",
                channel_id=channel.id,
                author_id=authenticated_user_id,
                content=f"Сообщение {i}",
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )

    @property
    def error_was_raised(self) -> bool:
        return self._error_raised.is_set()


class AuthErrorDeleter:

    def __init__(self, should_raise: bool) -> None:
        self._should_raise = should_raise
        self.delete_count: int = 0
        self.calls_after_error: int = 0
        self._error_raised = threading.Event()
        self._lock = threading.Lock()

    def delete(self, message: Message) -> OperationLogEntry:
        with self._lock:
            self.delete_count += 1
            if self._error_raised.is_set():
                self.calls_after_error += 1

        if self._should_raise and not self._error_raised.is_set():
            self._error_raised.set()
            raise DiscordAuthError(body="401 Unauthorized")

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
    def error_was_raised(self) -> bool:
        return self._error_raised.is_set()


@pytest.mark.property
@settings(max_examples=100, deadline=None)
@given(
    injection_point=sampled_from(["list_channels", "scan_channel", "delete"]),
)
def test_401_mid_operation_cancels_and_clears_token(
    qapp,
    injection_point: str,
) -> None:

    session = Session()
    session.consent_granted = True
    session.token = "secret_discord_token_12345"
    session.authenticated_user_id = "user_123"

    scanner = AuthErrorScanner(injection_point=injection_point)
    deleter = AuthErrorDeleter(should_raise=(injection_point == "delete"))
    operation_log = OperationLog()
    operation_log.found_total = 1000

    controller = OperationController(
        scanner=scanner,
        deleter=deleter,
        operation_log=operation_log,
        session=session,
    )

    state_changes: list[OperationState] = []
    state_lock = threading.Lock()
    canceled_event = threading.Event()

    def on_state_changed(new_state: OperationState) -> None:
        with state_lock:
            state_changes.append(new_state)
        if new_state == OperationState.CANCELED:
            canceled_event.set()

    auth_lost_event = threading.Event()

    def on_auth_lost() -> None:
        auth_lost_event.set()

    controller.state_changed.connect(on_state_changed)
    controller.auth_lost.connect(on_auth_lost)

    server = Server(id="guild_1", name="Тестовый сервер")
    start_time = time.monotonic()
    controller.start(server=server, user_id="user_123")

    deadline = start_time + 5.0
    while not canceled_event.is_set():
        if time.monotonic() > deadline:
            with state_lock:
                current_states = list(state_changes)
            pytest.fail(
                f"Переход в CANCELED не произошёл за 5 секунд. "
                f"Состояния: {current_states}, injection_point={injection_point}"
            )
        QApplication.processEvents()
        time.sleep(0.005)

    if controller._worker is not None:
        controller._worker.join(timeout=5.0)

    QApplication.processEvents()
    time.sleep(0.01)
    QApplication.processEvents()

    elapsed = time.monotonic() - start_time
    assert elapsed <= 5.0, (
        f"Переход в CANCELED занял {elapsed:.2f} с (ожидалось быстро)"
    )

    assert session.token is None, (
        f"session.token должен быть None после 401, но равен {session.token!r}"
    )

    assert deleter.calls_after_error == 0, (
        f"После 401 было {deleter.calls_after_error} дополнительных "
        f"вызовов delete (ожидалось 0)"
    )

    if not auth_lost_event.is_set():
        for _ in range(20):
            QApplication.processEvents()
            time.sleep(0.01)
            if auth_lost_event.is_set():
                break

    assert auth_lost_event.is_set(), (
        "Сигнал auth_lost не был эмитирован после 401"
    )

    with state_lock:
        assert OperationState.CANCELED in state_changes, (
            f"CANCELED отсутствует в списке переходов: {state_changes}"
        )
