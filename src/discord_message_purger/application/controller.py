from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import TYPE_CHECKING, Iterator, Protocol, runtime_checkable

from PySide6.QtCore import QObject, Signal

from ..domain.exceptions import (
    DiscordAuthError,
    DiscordNetworkError,
    DiscordPurgerError,
    DiscordServerError,
    DiscordTimeoutError,
    IllegalStateTransition,
    MissingAuthenticatedUserError,
    RateLimitTooLongError,
)
from ..domain.models import (
    Channel,
    LogEntryStatus,
    Message,
    OperationLogEntry,
    OperationState,
    OperationSummary,
    Server,
)
from ..domain.state import transition
from .operation_context import OperationContext

if TYPE_CHECKING:
    from .session import Session
    from ..domain.operation_log import OperationLog


logger = logging.getLogger(__name__)


@runtime_checkable
class ScannerProtocol(Protocol):

    def list_channels(self, guild_id: str) -> list[Channel]: ...

    def scan_channel(
        self,
        channel: Channel,
        authenticated_user_id: str,
        ctx: OperationContext,
    ) -> Iterator[Message]: ...


@runtime_checkable
class DeleterProtocol(Protocol):

    def delete(self, message: Message) -> OperationLogEntry: ...


class OperationController(QObject):

    state_changed = Signal(object)
    progress_changed = Signal(int, int)
    log_entry_added = Signal(object)
    rate_limit_wait_started = Signal(float, str)
    rate_limit_wait_ended = Signal()
    summary_ready = Signal(object)
    auth_lost = Signal()

    def __init__(
        self,
        scanner: ScannerProtocol,
        deleter: DeleterProtocol,
        operation_log: "OperationLog",
        session: "Session",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._scanner = scanner
        self._deleter = deleter
        self._operation_log = operation_log
        self._session = session

        self._ctx: OperationContext | None = None
        self._worker: threading.Thread | None = None


    def start(self, server: Server, user_id: str) -> None:
        if not self._session.consent_granted:
            entry = OperationLogEntry(
                timestamp_local=datetime.now().astimezone(),
                status=LogEntryStatus.ERROR,
                channel_id=None,
                message_id=None,
                first_visible_char="·",
                message_timestamp=None,
                http_status=None,
                error_type="auth",
                description="no consent",
            )
            self._emit_log_entry(entry)
            return

        if user_id is None or not isinstance(user_id, str) or user_id.strip() == "":
            entry = OperationLogEntry(
                timestamp_local=datetime.now().astimezone(),
                status=LogEntryStatus.ERROR,
                channel_id=None,
                message_id=None,
                first_visible_char="·",
                message_timestamp=None,
                http_status=None,
                error_type="auth",
                description="Идентификатор пользователя отсутствует или пуст",
            )
            self._emit_log_entry(entry)
            self._set_state_force(OperationState.ERROR)
            raise MissingAuthenticatedUserError(
                "authenticated_user_id отсутствует или пуст"
            )

        self._ctx = OperationContext(
            state=OperationState.IDLE,
            server=server,
            authenticated_user_id=user_id,
        )

        self._worker = threading.Thread(
            target=self._worker_run,
            name="OperationWorker",
            daemon=True,
        )
        self._worker.start()

    def pause(self) -> None:
        if self._ctx is None:
            return
        self._ctx.pause_event.set()
        self._transition_state(OperationState.PAUSED)

    def resume(self) -> None:
        if self._ctx is None:
            return
        self._ctx.pause_event.clear()
        self._ctx.resume_event.set()
        self._transition_state(OperationState.RUNNING)

    def cancel(self) -> None:
        if self._ctx is None:
            return
        self._ctx.cancel_event.set()
        self._ctx.resume_event.set()
        self._transition_state(OperationState.CANCELED)

    def shutdown(self, timeout_s: float) -> bool:
        self.cancel()
        if self._worker is not None and self._worker.is_alive():
            self._worker.join(timeout=timeout_s)
            return not self._worker.is_alive()
        return True


    def _worker_run(self) -> None:
        assert self._ctx is not None  # noqa: S101

        try:
            logger.info("Worker стартовал")
            self._transition_state(OperationState.RUNNING)

            server = self._ctx.server
            assert server is not None  # noqa: S101
            logger.info("Запрашиваем список каналов сервера %s (%s)", server.name, server.id)
            channels = self._scanner.list_channels(server.id)
            logger.info("Получено каналов: %d", len(channels))
            for ch in channels:
                logger.debug("  Канал %s (%s, type=%s)", ch.name, ch.id, ch.type)

            all_messages: list[Message] = []
            for channel in channels:
                if self._ctx.check_cancelled():
                    logger.info("Сканирование отменено пользователем")
                    return

                logger.info("Сканирование канала %s (%s)", channel.name, channel.id)
                channel_msg_count = 0
                for message in self._scanner.scan_channel(
                    channel, self._ctx.authenticated_user_id, self._ctx
                ):
                    if self._ctx.check_cancelled():
                        logger.info("Сканирование отменено пользователем")
                        return
                    all_messages.append(message)
                    channel_msg_count += 1
                    self._operation_log.update_total(len(all_messages))
                    self.progress_changed.emit(0, len(all_messages))
                logger.info("В канале %s найдено сообщений пользователя: %d", channel.name, channel_msg_count)

            logger.info("ФАЗА 1 завершена. Всего найдено: %d", len(all_messages))

            self._operation_log.update_total(len(all_messages))
            self.progress_changed.emit(0, len(all_messages))

            for message in all_messages:
                if self._ctx.check_cancelled():
                    return
                if not self._ctx.wait_if_paused():
                    return

                log_entry = self._deleter.delete(message)
                self._emit_log_entry(log_entry)
                self.progress_changed.emit(
                    self._operation_log.processed,
                    self._operation_log.found_total,
                )

            self._transition_state(OperationState.COMPLETED)
            summary = self._operation_log.summary()
            self.summary_ready.emit(summary)

        except DiscordAuthError:
            self._handle_auth_error()
        except (DiscordServerError, DiscordNetworkError, DiscordTimeoutError) as exc:
            self._handle_transient_error(exc)
        except RateLimitTooLongError as exc:
            self._handle_fatal_error(str(exc))
        except MissingAuthenticatedUserError as exc:
            self._handle_fatal_error(str(exc))
        except IllegalStateTransition:
            logger.exception("Нелегальный переход состояния в worker-потоке")
        except Exception:
            logger.exception("Непредвиденная ошибка в worker-потоке")
            import traceback
            traceback.print_exc()
            self._handle_fatal_error("Непредвиденная ошибка")


    def _handle_auth_error(self) -> None:
        self._session.clear_token()
        self._transition_state(OperationState.CANCELED)
        self.auth_lost.emit()

    def _handle_transient_error(self, exc: Exception) -> None:
        description = str(exc)[:500]
        entry = OperationLogEntry(
            timestamp_local=datetime.now().astimezone(),
            status=LogEntryStatus.ERROR,
            channel_id=None,
            message_id=None,
            first_visible_char="·",
            message_timestamp=None,
            http_status=getattr(exc, "status", None),
            error_type="network",
            description=description,
        )
        self._emit_log_entry(entry)
        self._transition_state(OperationState.PAUSED)

    def _handle_fatal_error(self, description: str) -> None:
        entry = OperationLogEntry(
            timestamp_local=datetime.now().astimezone(),
            status=LogEntryStatus.ERROR,
            channel_id=None,
            message_id=None,
            first_visible_char="·",
            message_timestamp=None,
            http_status=None,
            error_type="network",
            description=description[:500],
        )
        self._emit_log_entry(entry)
        self._transition_state(OperationState.ERROR)


    def _transition_state(self, target: OperationState) -> None:
        if self._ctx is None:
            return
        new_state = transition(self._ctx.state, target)
        self._ctx.state = new_state
        self.state_changed.emit(new_state)

    def _set_state_force(self, target: OperationState) -> None:
        if self._ctx is not None:
            self._ctx.state = target
        self.state_changed.emit(target)

    def _emit_log_entry(self, entry: OperationLogEntry) -> None:
        self.log_entry_added.emit(entry)


__all__ = [
    "OperationController",
    "ScannerProtocol",
    "DeleterProtocol",
]
