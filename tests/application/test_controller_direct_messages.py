from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Iterator

from discord_message_purger.application.controller import OperationController
from discord_message_purger.application.operation_context import OperationContext
from discord_message_purger.application.session import Session
from discord_message_purger.domain.exceptions import DiscordServerError
from discord_message_purger.domain.models import (
    Channel,
    ChannelType,
    DirectMessagesTarget,
    LogEntryStatus,
    Message,
    OperationLogEntry,
    OperationState,
    Server,
)
from discord_message_purger.domain.operation_log import OperationLog


_USER_ID = "user_123"


def _dm_channel(channel_id: str) -> Channel:
    return Channel(id=channel_id, guild_id=None, name=f"dm {channel_id}", type=ChannelType.DM)


def _message(msg_id: str, channel_id: str) -> Message:
    return Message(
        id=msg_id,
        channel_id=channel_id,
        author_id=_USER_ID,
        content=f"text {msg_id}",
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


class _Scanner:

    def __init__(
        self,
        messages: dict[str, list[Message]],
        fail_first_scans: int = 0,
    ) -> None:
        self.messages = messages
        self.fail_first_scans = fail_first_scans
        self.scanned: list[str] = []
        self.list_channels_calls: list[str] = []
        self.release = threading.Event()
        self.release.set()

    def list_channels(self, guild_id: str) -> list[Channel]:
        self.list_channels_calls.append(guild_id)
        return [
            Channel(id=cid, guild_id=guild_id, name=cid, type=ChannelType.GUILD_TEXT)
            for cid in self.messages
        ]

    def scan_channel(
        self,
        channel: Channel,
        authenticated_user_id: str,
        ctx: OperationContext,
    ) -> Iterator[Message]:
        self.release.wait(timeout=5.0)
        self.scanned.append(channel.id)
        if self.fail_first_scans > 0:
            self.fail_first_scans -= 1
            raise DiscordServerError(status=502, body="Bad Gateway")
        yield from self.messages.get(channel.id, [])


class _Deleter:

    def __init__(self, operation_log: OperationLog) -> None:
        self._operation_log = operation_log
        self.deleted: list[str] = []

    def delete(self, message: Message) -> OperationLogEntry:
        self.deleted.append(message.id)
        entry = OperationLogEntry(
            timestamp_local=datetime.now(),
            status=LogEntryStatus.SUCCESS,
            channel_id=message.channel_id,
            message_id=message.id,
            first_visible_char="t",
            message_timestamp=message.timestamp,
            http_status=204,
            error_type=None,
            description="",
        )
        self._operation_log.add(entry)
        return entry


def _build(scanner: _Scanner) -> tuple[OperationController, _Deleter, OperationLog]:
    session = Session()
    session.consent_granted = True
    session.token = "token"
    session.authenticated_user_id = _USER_ID
    operation_log = OperationLog()
    deleter = _Deleter(operation_log)
    controller = OperationController(
        scanner=scanner,
        deleter=deleter,
        operation_log=operation_log,
        session=session,
    )
    return controller, deleter, operation_log


def _wait_worker(controller: OperationController) -> None:
    assert controller._worker is not None
    controller._worker.join(timeout=10.0)
    assert not controller._worker.is_alive()


def test_direct_messages_target_scans_only_selected_channels(qapp) -> None:
    scanner = _Scanner(
        {
            "dm1": [_message("1", "dm1"), _message("2", "dm1")],
            "dm2": [_message("3", "dm2")],
            "dm3": [_message("4", "dm3")],
        }
    )
    controller, deleter, operation_log = _build(scanner)

    target = DirectMessagesTarget(channels=(_dm_channel("dm1"), _dm_channel("dm2")))
    controller.start(target, _USER_ID)
    _wait_worker(controller)

    assert scanner.list_channels_calls == []
    assert scanner.scanned == ["dm1", "dm2"]
    assert deleter.deleted == ["1", "2", "3"]
    assert controller._ctx is not None
    assert controller._ctx.state == OperationState.COMPLETED
    assert operation_log.summary().success == 3
    assert not controller.is_busy


def test_operation_finished_emitted(qapp, qtbot) -> None:
    scanner = _Scanner({"dm1": [_message("1", "dm1")]})
    controller, _deleter, _log = _build(scanner)

    with qtbot.waitSignal(controller.operation_finished, timeout=5000):
        controller.start(DirectMessagesTarget(channels=(_dm_channel("dm1"),)), _USER_ID)


def test_resume_after_transient_error_restarts_and_completes(qapp) -> None:
    scanner = _Scanner(
        {"dm1": [_message("1", "dm1"), _message("2", "dm1")]},
        fail_first_scans=1,
    )
    controller, deleter, operation_log = _build(scanner)

    controller.start(DirectMessagesTarget(channels=(_dm_channel("dm1"),)), _USER_ID)
    _wait_worker(controller)

    assert controller._ctx is not None
    assert controller._ctx.state == OperationState.PAUSED
    assert deleter.deleted == []
    assert not controller.is_busy

    controller.resume()
    _wait_worker(controller)

    assert controller._ctx.state == OperationState.COMPLETED
    assert deleter.deleted == ["1", "2"]
    assert operation_log.processed == 2
    assert operation_log.found_total == 2


def test_cancel_after_transient_error_does_not_restart(qapp) -> None:
    scanner = _Scanner({"dm1": [_message("1", "dm1")]}, fail_first_scans=1)
    controller, deleter, _log = _build(scanner)

    controller.start(DirectMessagesTarget(channels=(_dm_channel("dm1"),)), _USER_ID)
    _wait_worker(controller)
    worker = controller._worker

    controller.cancel()

    assert controller._ctx is not None
    assert controller._ctx.state == OperationState.CANCELED
    assert controller._worker is worker
    assert deleter.deleted == []


def test_second_operation_starts_with_clean_log(qapp) -> None:
    scanner = _Scanner(
        {
            "g1": [_message("1", "g1"), _message("2", "g1"), _message("3", "g1")],
            "dm1": [_message("10", "dm1")],
        }
    )
    controller, deleter, operation_log = _build(scanner)

    controller.start(Server(id="guild", name="Guild"), _USER_ID)
    _wait_worker(controller)
    assert operation_log.processed == 4

    scanner.messages = {"dm1": [_message("10", "dm1")]}
    controller.start(DirectMessagesTarget(channels=(_dm_channel("dm1"),)), _USER_ID)
    _wait_worker(controller)

    assert controller._ctx is not None
    assert controller._ctx.state == OperationState.COMPLETED
    assert operation_log.processed == 1
    assert operation_log.found_total == 1
    assert len(operation_log.entries) == 1
    assert deleter.deleted[-1] == "10"


def test_start_ignored_while_previous_worker_running(qapp) -> None:
    scanner = _Scanner({"dm1": [_message("1", "dm1")]})
    scanner.release.clear()
    controller, _deleter, _log = _build(scanner)

    controller.start(DirectMessagesTarget(channels=(_dm_channel("dm1"),)), _USER_ID)
    first_worker = controller._worker
    first_ctx = controller._ctx
    assert controller.is_busy

    controller.start(Server(id="guild", name="Guild"), _USER_ID)

    assert controller._worker is first_worker
    assert controller._ctx is first_ctx

    scanner.release.set()
    _wait_worker(controller)
