from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis.strategies import sampled_from
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from discord_message_purger.application.controller import OperationController
from discord_message_purger.application.session import Session
from discord_message_purger.domain.models import OperationState, Server
from discord_message_purger.ui.main_window import MainWindow


@dataclass(frozen=True)
class FakeAuthResult:

    status: Literal["ok", "invalid_token", "network_error", "storage_error"]
    user_id: str | None = None


class FakeTokenManager:

    def validate_and_store(self, token: str) -> FakeAuthResult:
        return FakeAuthResult(status="ok", user_id="123456")


class FakeHttpClient:

    def get(
        self,
        path: str,
        *,
        timeout_s: float,
        params: object = None,
        max_consecutive_429: int | None = None,
    ) -> object:
        return FakeResponse([])


class FakeResponse:

    def __init__(self, data: list) -> None:
        self._data = data

    def json(self) -> list:
        return self._data


@pytest.fixture()
def session() -> Session:
    return Session()


@pytest.fixture()
def controller(session: Session) -> OperationController:
    scanner = MagicMock()
    deleter = MagicMock()
    operation_log = MagicMock()
    return OperationController(
        scanner=scanner,
        deleter=deleter,
        operation_log=operation_log,
        session=session,
    )


@pytest.fixture()
def main_window(
    qtbot, session: Session, controller: OperationController
) -> MainWindow:
    token_manager = FakeTokenManager()
    http_client = FakeHttpClient()
    window = MainWindow(
        controller=controller,
        session=session,
        token_manager=token_manager,
        http_client=http_client,
        show_consent=False,
    )
    qtbot.addWidget(window)
    return window


class TestInitialState:

    def test_initial_page_is_login(self, main_window: MainWindow) -> None:
        assert main_window.stack.currentIndex() == 0

    def test_initial_buttons_hidden(self, main_window: MainWindow) -> None:
        assert not main_window.pause_button.isVisible()
        assert not main_window.pause_button.isEnabled()
        assert not main_window.resume_button.isVisible()
        assert not main_window.resume_button.isEnabled()
        assert not main_window.cancel_button.isVisible()
        assert not main_window.cancel_button.isEnabled()


class TestButtonStates:

    def test_running_state_buttons(self, main_window: MainWindow) -> None:
        main_window._update_buttons(OperationState.RUNNING)

        assert main_window.pause_button.isVisibleTo(main_window)
        assert main_window.pause_button.isEnabled()
        assert not main_window.resume_button.isVisibleTo(main_window)
        assert not main_window.resume_button.isEnabled()
        assert main_window.cancel_button.isVisibleTo(main_window)
        assert main_window.cancel_button.isEnabled()

    def test_paused_state_buttons(self, main_window: MainWindow) -> None:
        main_window._update_buttons(OperationState.PAUSED)

        assert not main_window.pause_button.isVisibleTo(main_window)
        assert not main_window.pause_button.isEnabled()
        assert main_window.resume_button.isVisibleTo(main_window)
        assert main_window.resume_button.isEnabled()
        assert main_window.cancel_button.isVisibleTo(main_window)
        assert main_window.cancel_button.isEnabled()

    def test_idle_state_buttons(self, main_window: MainWindow) -> None:
        main_window._update_buttons(OperationState.IDLE)

        assert not main_window.pause_button.isVisibleTo(main_window)
        assert not main_window.pause_button.isEnabled()
        assert not main_window.resume_button.isVisibleTo(main_window)
        assert not main_window.resume_button.isEnabled()
        assert not main_window.cancel_button.isVisibleTo(main_window)
        assert not main_window.cancel_button.isEnabled()

    def test_completed_state_buttons(self, main_window: MainWindow) -> None:
        main_window._update_buttons(OperationState.COMPLETED)

        assert not main_window.pause_button.isVisibleTo(main_window)
        assert not main_window.cancel_button.isVisibleTo(main_window)
        assert not main_window.resume_button.isVisibleTo(main_window)

    def test_canceled_state_buttons(self, main_window: MainWindow) -> None:
        main_window._update_buttons(OperationState.CANCELED)

        assert not main_window.pause_button.isVisibleTo(main_window)
        assert not main_window.cancel_button.isVisibleTo(main_window)
        assert not main_window.resume_button.isVisibleTo(main_window)

    def test_error_state_buttons(self, main_window: MainWindow) -> None:
        main_window._update_buttons(OperationState.ERROR)

        assert not main_window.pause_button.isVisibleTo(main_window)
        assert not main_window.cancel_button.isVisibleTo(main_window)
        assert not main_window.resume_button.isVisibleTo(main_window)

    def test_state_changed_signal_updates_buttons(
        self, main_window: MainWindow, controller: OperationController
    ) -> None:
        controller.state_changed.emit(OperationState.RUNNING)

        assert main_window.pause_button.isVisibleTo(main_window)
        assert main_window.pause_button.isEnabled()
        assert not main_window.resume_button.isVisibleTo(main_window)


class TestScreenRouting:

    def test_token_validated_switches_to_server_selector(
        self, main_window: MainWindow, session: Session
    ) -> None:
        main_window._on_token_validated("test_token", "user_123")

        assert main_window.stack.currentIndex() == 1
        assert session.authenticated_user_id == "user_123"
        assert session.token == "test_token"

    def test_auth_lost_switches_to_login(
        self, main_window: MainWindow, qtbot
    ) -> None:
        main_window.stack.setCurrentIndex(2)

        with patch.object(QMessageBox, "warning", return_value=None) as mock_warn:
            main_window._on_auth_lost()

        assert main_window.stack.currentIndex() == 0
        mock_warn.assert_called_once()
        call_args = mock_warn.call_args
        assert "Токен недействителен" in call_args[0][2]

    def test_start_requested_with_confirmed_dialog(
        self, main_window: MainWindow, session: Session, controller: OperationController
    ) -> None:
        session.consent_granted = True
        session.authenticated_user_id = "user_123"
        server = Server(id="guild_1", name="Test Server")

        with patch(
            "discord_message_purger.ui.main_window.ConfirmationDialog"
        ) as MockDialog:
            mock_instance = MagicMock()
            mock_instance.confirmed = True
            mock_instance.exec.return_value = None
            MockDialog.return_value = mock_instance

            with patch.object(controller, "start") as mock_start:
                main_window._on_start_requested(server)

        assert main_window.stack.currentIndex() == 2
        mock_start.assert_called_once_with(server, "user_123")

    def test_start_requested_with_rejected_dialog(
        self, main_window: MainWindow, session: Session
    ) -> None:
        session.authenticated_user_id = "user_123"
        server = Server(id="guild_1", name="Test Server")

        main_window.stack.setCurrentIndex(1)

        with patch(
            "discord_message_purger.ui.main_window.ConfirmationDialog"
        ) as MockDialog:
            mock_instance = MagicMock()
            mock_instance.confirmed = False
            mock_instance.exec.return_value = None
            MockDialog.return_value = mock_instance

            main_window._on_start_requested(server)

        assert main_window.stack.currentIndex() == 1


class TestConsentHandling:

    def test_consent_rejected_calls_quit(
        self, qtbot, session: Session, controller: OperationController
    ) -> None:
        token_manager = FakeTokenManager()
        http_client = FakeHttpClient()

        with patch(
            "discord_message_purger.ui.main_window.ConsentDialog"
        ) as MockDialog:
            mock_instance = MagicMock()
            mock_instance.exec.return_value = MagicMock()
            mock_instance.consent_given = False
            mock_instance.DialogCode = MagicMock()
            MockDialog.return_value = mock_instance
            MockDialog.DialogCode = MagicMock()
            MockDialog.DialogCode.Rejected = 0
            mock_instance.exec.return_value = 0

            with patch.object(QApplication, "quit") as mock_quit:
                with patch.object(QTimer, "singleShot") as mock_timer:
                    window = MainWindow(
                        controller=controller,
                        session=session,
                        token_manager=token_manager,
                        http_client=http_client,
                        show_consent=True,
                    )
                    qtbot.addWidget(window)

                mock_timer.assert_called_once()
                args = mock_timer.call_args[0]
                assert args[0] == 0


class TestControllerSignals:

    def test_progress_changed_updates_total(
        self, main_window: MainWindow, controller: OperationController
    ) -> None:
        controller.progress_changed.emit(0, 10)
        assert main_window.progress_display.total == 10

    def test_pause_button_calls_controller_pause(
        self, main_window: MainWindow, controller: OperationController
    ) -> None:
        with patch.object(controller, "pause") as mock_pause:
            main_window._on_pause_clicked()
        mock_pause.assert_called_once()

    def test_resume_button_calls_controller_resume(
        self, main_window: MainWindow, controller: OperationController
    ) -> None:
        with patch.object(controller, "resume") as mock_resume:
            main_window._on_resume_clicked()
        mock_resume.assert_called_once()

    def test_cancel_button_calls_controller_cancel(
        self, main_window: MainWindow, controller: OperationController
    ) -> None:
        with patch.object(controller, "cancel") as mock_cancel:
            main_window._on_cancel_clicked()
        mock_cancel.assert_called_once()


class TestCloseEvent:

    def test_idle_state_accepts_without_dialog(
        self, main_window: MainWindow, controller: OperationController
    ) -> None:
        from PySide6.QtGui import QCloseEvent

        assert controller._ctx is None

        event = QCloseEvent()
        main_window.closeEvent(event)
        assert event.isAccepted()

    def test_completed_state_accepts_without_dialog(
        self, main_window: MainWindow, controller: OperationController
    ) -> None:
        from PySide6.QtGui import QCloseEvent
        from discord_message_purger.application.operation_context import OperationContext
        from discord_message_purger.domain.models import Server

        controller._ctx = OperationContext(
            state=OperationState.COMPLETED,
            server=Server(id="g1", name="S"),
            authenticated_user_id="u1",
        )

        event = QCloseEvent()
        main_window.closeEvent(event)
        assert event.isAccepted()

    def test_canceled_state_accepts_without_dialog(
        self, main_window: MainWindow, controller: OperationController
    ) -> None:
        from PySide6.QtGui import QCloseEvent
        from discord_message_purger.application.operation_context import OperationContext
        from discord_message_purger.domain.models import Server

        controller._ctx = OperationContext(
            state=OperationState.CANCELED,
            server=Server(id="g1", name="S"),
            authenticated_user_id="u1",
        )

        event = QCloseEvent()
        main_window.closeEvent(event)
        assert event.isAccepted()

    def test_error_state_accepts_without_dialog(
        self, main_window: MainWindow, controller: OperationController
    ) -> None:
        from PySide6.QtGui import QCloseEvent
        from discord_message_purger.application.operation_context import OperationContext
        from discord_message_purger.domain.models import Server

        controller._ctx = OperationContext(
            state=OperationState.ERROR,
            server=Server(id="g1", name="S"),
            authenticated_user_id="u1",
        )

        event = QCloseEvent()
        main_window.closeEvent(event)
        assert event.isAccepted()

    def test_running_state_shows_dialog_and_cancel_ignores(
        self, main_window: MainWindow, controller: OperationController
    ) -> None:
        from PySide6.QtGui import QCloseEvent
        from PySide6.QtWidgets import QDialog
        from discord_message_purger.application.operation_context import OperationContext
        from discord_message_purger.domain.models import Server

        controller._ctx = OperationContext(
            state=OperationState.RUNNING,
            server=Server(id="g1", name="S"),
            authenticated_user_id="u1",
        )

        event = QCloseEvent()

        with patch(
            "discord_message_purger.ui.main_window.CancelConfirmDialog"
        ) as MockDialog:
            mock_instance = MagicMock()
            mock_instance.exec.return_value = QDialog.DialogCode.Rejected
            MockDialog.for_close_app.return_value = mock_instance

            main_window.closeEvent(event)

        assert not event.isAccepted()

        controller._ctx.state = OperationState.IDLE

    def test_paused_state_shows_dialog_and_cancel_ignores(
        self, main_window: MainWindow, controller: OperationController
    ) -> None:
        from PySide6.QtGui import QCloseEvent
        from PySide6.QtWidgets import QDialog
        from discord_message_purger.application.operation_context import OperationContext
        from discord_message_purger.domain.models import Server

        controller._ctx = OperationContext(
            state=OperationState.PAUSED,
            server=Server(id="g1", name="S"),
            authenticated_user_id="u1",
        )

        event = QCloseEvent()

        with patch(
            "discord_message_purger.ui.main_window.CancelConfirmDialog"
        ) as MockDialog:
            mock_instance = MagicMock()
            mock_instance.exec.return_value = QDialog.DialogCode.Rejected
            MockDialog.for_close_app.return_value = mock_instance

            main_window.closeEvent(event)

        assert not event.isAccepted()

        controller._ctx.state = OperationState.IDLE

    def test_running_state_close_confirmed_shutdown_success(
        self, main_window: MainWindow, controller: OperationController
    ) -> None:
        from PySide6.QtGui import QCloseEvent
        from PySide6.QtWidgets import QDialog
        from discord_message_purger.application.operation_context import OperationContext
        from discord_message_purger.domain.models import Server

        controller._ctx = OperationContext(
            state=OperationState.RUNNING,
            server=Server(id="g1", name="S"),
            authenticated_user_id="u1",
        )

        event = QCloseEvent()

        with patch(
            "discord_message_purger.ui.main_window.CancelConfirmDialog"
        ) as MockDialog:
            mock_instance = MagicMock()
            mock_instance.exec.return_value = QDialog.DialogCode.Accepted
            MockDialog.for_close_app.return_value = mock_instance

            with patch.object(controller, "shutdown", return_value=True) as mock_shutdown:
                main_window.closeEvent(event)

        mock_shutdown.assert_called_once_with(timeout_s=5.0)
        assert event.isAccepted()

        controller._ctx.state = OperationState.IDLE

    def test_running_state_close_confirmed_shutdown_timeout_exits(
        self, main_window: MainWindow, controller: OperationController
    ) -> None:
        from PySide6.QtGui import QCloseEvent
        from PySide6.QtWidgets import QDialog
        from discord_message_purger.application.operation_context import OperationContext
        from discord_message_purger.domain.models import Server

        controller._ctx = OperationContext(
            state=OperationState.RUNNING,
            server=Server(id="g1", name="S"),
            authenticated_user_id="u1",
        )

        event = QCloseEvent()

        with patch(
            "discord_message_purger.ui.main_window.CancelConfirmDialog"
        ) as MockDialog:
            mock_instance = MagicMock()
            mock_instance.exec.return_value = QDialog.DialogCode.Accepted
            MockDialog.for_close_app.return_value = mock_instance

            with patch.object(controller, "shutdown", return_value=False):
                with patch("os._exit") as mock_exit:
                    main_window.closeEvent(event)

        mock_exit.assert_called_once_with(0)

        controller._ctx.state = OperationState.IDLE


_ALL_STATES = sampled_from(list(OperationState))


class TestButtonStatesProperty:
    # Feature: discord-message-purger, Property 37: UI buttons state matches operation state

    @given(state=_ALL_STATES)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_buttons_match_state_table(
        self, state: OperationState, main_window: MainWindow
    ) -> None:
        main_window._update_buttons(state)

        if state == OperationState.RUNNING:
            assert main_window.pause_button.isVisibleTo(main_window)
            assert main_window.pause_button.isEnabled()
            assert not main_window.resume_button.isVisibleTo(main_window)
            assert not main_window.resume_button.isEnabled()
            assert main_window.cancel_button.isVisibleTo(main_window)
            assert main_window.cancel_button.isEnabled()
        elif state == OperationState.PAUSED:
            assert not main_window.pause_button.isVisibleTo(main_window)
            assert not main_window.pause_button.isEnabled()
            assert main_window.resume_button.isVisibleTo(main_window)
            assert main_window.resume_button.isEnabled()
            assert main_window.cancel_button.isVisibleTo(main_window)
            assert main_window.cancel_button.isEnabled()
        else:
            assert not main_window.pause_button.isVisibleTo(main_window)
            assert not main_window.pause_button.isEnabled()
            assert not main_window.resume_button.isVisibleTo(main_window)
            assert not main_window.resume_button.isEnabled()
            assert not main_window.cancel_button.isVisibleTo(main_window)
            assert not main_window.cancel_button.isEnabled()


class TestCloseEventProperty:
    # Feature: discord-message-purger, Property 43: Close-during-active-op gating

    @given(state=_ALL_STATES)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_close_gating_by_state(
        self, state: OperationState, main_window: MainWindow, controller: OperationController
    ) -> None:
        from PySide6.QtGui import QCloseEvent
        from PySide6.QtWidgets import QDialog
        from discord_message_purger.application.operation_context import OperationContext

        if state == OperationState.IDLE:
            controller._ctx = None
        else:
            controller._ctx = OperationContext(
                state=state,
                server=Server(id="g1", name="S"),
                authenticated_user_id="u1",
            )

        event = QCloseEvent()

        if state in (OperationState.RUNNING, OperationState.PAUSED):
            with patch(
                "discord_message_purger.ui.main_window.CancelConfirmDialog"
            ) as MockDialog:
                mock_instance = MagicMock()
                mock_instance.exec.return_value = QDialog.DialogCode.Rejected
                MockDialog.for_close_app.return_value = mock_instance

                main_window.closeEvent(event)

            MockDialog.for_close_app.assert_called_once()
            assert not event.isAccepted()

            if controller._ctx is not None:
                controller._ctx.state = OperationState.IDLE
        else:
            with patch(
                "discord_message_purger.ui.main_window.CancelConfirmDialog"
            ) as MockDialog:
                main_window.closeEvent(event)

            MockDialog.for_close_app.assert_not_called()
            assert event.isAccepted()
