from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Callable,
    Iterator,
    Protocol,
    runtime_checkable,
)

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
    CleanupTarget,
    DirectMessagesTarget,
    LogEntryStatus,
    Message,
    OperationLogEntry,
    OperationState,
    OperationSummary,
)
from ..domain.state import transition
from .operation_context import OperationContext

if TYPE_CHECKING:
    from .session import Session
    from ..domain.operation_log import OperationLog


logger = logging.getLogger(__name__)

_ACTIVE_STATES = frozenset({OperationState.RUNNING, OperationState.PAUSED})


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
    operation_finished = Signal()

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
        self._worker_running: bool = False
        self._restart_on_resume: bool = False
        self._state_lock = threading.Lock()

    @property
    def is_busy(self) -> bool:
        return self._worker_running


    def start(self, server: CleanupTarget, user_id: str) -> None:
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
                description="User ID is missing or empty",
            )
            self._emit_log_entry(entry)
            self._set_state_force(OperationState.ERROR)
            raise MissingAuthenticatedUserError(
                "authenticated_user_id is missing or empty"
            )

        if self._worker_running:
            logger.warning("Start ignored: previous operation is still stopping")
            return

        if self._ctx is not None:
            self._operation_log.reset()

        self._ctx = OperationContext(
            state=OperationState.IDLE,
            server=server,
            authenticated_user_id=user_id,
        )

        self._launch_worker()

    def _launch_worker(self) -> None:
        self._restart_on_resume = False
        self._worker_running = True
        self._worker = threading.Thread(
            target=self._worker_run,
            name="OperationWorker",
            daemon=True,
        )
        self._worker.start()

    def pause(self) -> None:
        ctx = self._ctx
        if ctx is None:
            return
        self._transition_if(
            {OperationState.RUNNING},
            OperationState.PAUSED,
            before=ctx.pause_event.set,
        )

    def resume(self) -> None:
        ctx = self._ctx
        if ctx is None:
            return

        def _wake() -> None:
            ctx.pause_event.clear()
            ctx.resume_event.set()

        if not self._transition_if(
            {OperationState.PAUSED}, OperationState.RUNNING, before=_wake
        ):
            return

        if self._restart_on_resume:
            if self._worker is not None:
                self._worker.join(timeout=5.0)
            self._ctx.resume_event.clear()
            logger.info("Restarting operation after transient error")
            self._launch_worker()

    def cancel(self) -> None:
        ctx = self._ctx
        if ctx is None:
            return
        self._restart_on_resume = False

        def _stop() -> None:
            ctx.cancel_event.set()
            ctx.resume_event.set()

        if not self._transition_if(
            {OperationState.RUNNING, OperationState.PAUSED},
            OperationState.CANCELED,
            before=_stop,
        ) and ctx.state is OperationState.IDLE:
            _stop()

    def shutdown(self, timeout_s: float) -> bool:
        self.cancel()
        if self._worker is not None and self._worker.is_alive():
            self._worker.join(timeout=timeout_s)
            return not self._worker.is_alive()
        return True


    def _worker_run(self) -> None:
        assert self._ctx is not None  # noqa: S101

        try:
            logger.info("Worker started")
            self._transition_if({OperationState.IDLE}, OperationState.RUNNING)
            if self._ctx.check_cancelled():
                self._transition_if(
                    {OperationState.RUNNING}, OperationState.CANCELED
                )
                return

            target = self._ctx.server
            assert target is not None  # noqa: S101
            channels = self._resolve_channels(target)
            logger.info("Channels received: %d", len(channels))
            for ch in channels:
                logger.debug("  Channel %s (%s, type=%s)", ch.name, ch.id, ch.type)

            base_processed = self._operation_log.processed
            all_messages: list[Message] = []
            for channel in channels:
                if self._ctx.check_cancelled():
                    logger.info("Scan canceled by user")
                    return

                logger.info("Scanning channel %s (%s)", channel.name, channel.id)
                channel_msg_count = 0
                for message in self._scanner.scan_channel(
                    channel, self._ctx.authenticated_user_id, self._ctx
                ):
                    if self._ctx.check_cancelled():
                        logger.info("Scan canceled by user")
                        return
                    all_messages.append(message)
                    channel_msg_count += 1
                    self._update_total(base_processed + len(all_messages))
                logger.info("Channel %s: %d user messages found", channel.name, channel_msg_count)

            logger.info("Phase 1 complete. Total found: %d", len(all_messages))

            self._update_total(base_processed + len(all_messages))

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

            if not self._ctx.wait_if_paused():
                return
            if self._transition_if(
                {OperationState.RUNNING}, OperationState.COMPLETED
            ):
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
            logger.exception("Illegal state transition in worker thread")
        except Exception:
            logger.exception("Unexpected error in worker thread")
            import traceback
            traceback.print_exc()
            self._handle_fatal_error("Unexpected error")
        finally:
            self._worker_running = False
            self.operation_finished.emit()

    def _resolve_channels(self, target: CleanupTarget) -> list[Channel]:
        if isinstance(target, DirectMessagesTarget):
            logger.info(
                "Using %d selected direct message conversation(s)",
                len(target.channels),
            )
            return list(target.channels)
        logger.info("Fetching channels for guild %s (%s)", target.name, target.id)
        return self._scanner.list_channels(target.id)

    def _update_total(self, total: int) -> None:
        self._operation_log.update_total(total)
        self.progress_changed.emit(self._operation_log.processed, total)

    def _handle_auth_error(self) -> None:
        self._session.clear_token()
        self._transition_if(_ACTIVE_STATES, OperationState.CANCELED)
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
        if self._ctx is None or self._ctx.check_cancelled():
            return
        self._restart_on_resume = True
        self._transition_if({OperationState.RUNNING}, OperationState.PAUSED)
        if self._ctx.state is not OperationState.PAUSED:
            self._restart_on_resume = False

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
        self._transition_if(_ACTIVE_STATES, OperationState.ERROR)


    def _transition_if(
        self,
        allowed_from: set[OperationState] | frozenset[OperationState],
        target: OperationState,
        *,
        before: Callable[[], None] | None = None,
    ) -> bool:
        ctx = self._ctx
        if ctx is None:
            return False
        with self._state_lock:
            if ctx.state not in allowed_from:
                return False
            if before is not None:
                before()
            ctx.state = transition(ctx.state, target)
        self.state_changed.emit(target)
        return True

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
