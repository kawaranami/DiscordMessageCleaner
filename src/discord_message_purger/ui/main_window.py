from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from discord_message_purger.domain.models import (
    DirectMessagesTarget,
    OperationState,
    Server,
)
from discord_message_purger.ui.cancel_confirm_dialog import CancelConfirmDialog
from discord_message_purger.ui.confirmation_dialog import ConfirmationDialog
from discord_message_purger.ui.consent_dialog import ConsentDialog
from discord_message_purger.ui.dm_selector import DirectMessagesScreen
from discord_message_purger.ui.login_screen import LoginScreen
from discord_message_purger.ui.progress_display import ProgressDisplay
from discord_message_purger.ui.server_selector import ServerSelectorScreen

if TYPE_CHECKING:
    from discord_message_purger.application.controller import OperationController
    from discord_message_purger.application.session import Session
    from discord_message_purger.ui.login_screen import TokenValidator
    from discord_message_purger.ui.server_selector import HttpClient


_PAGE_LOGIN = 0
_PAGE_SERVER_SELECTOR = 1
_PAGE_PROGRESS = 2

_TAB_SERVERS = "Servers"
_TAB_DIRECT_MESSAGES = "Direct messages"

_BUTTON_PAUSE = "Pause"
_BUTTON_RESUME = "Resume"
_BUTTON_CANCEL = "Cancel"
_BUTTON_NEW = "New cleanup"

_TERMINAL_STATES = (
    OperationState.COMPLETED,
    OperationState.CANCELED,
    OperationState.ERROR,
)

_MSG_AUTH_LOST = "Invalid token"

_WINDOW_TITLE = "Discord Message Purger"

_DISCORD_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #313338;
    color: #dbdee1;
    font-family: 'Segoe UI', 'Whitney', sans-serif;
    font-size: 14px;
}
QPlainTextEdit {
    background-color: #2b2d31;
    color: #dbdee1;
    border: 1px solid #1e1f22;
    border-radius: 8px;
    padding: 8px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 13px;
}
QPushButton {
    background-color: #5865f2;
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-weight: bold;
    font-size: 14px;
    min-height: 32px;
}
QPushButton:hover {
    background-color: #4752c4;
}
QPushButton:pressed {
    background-color: #3c45a5;
}
QPushButton:disabled {
    background-color: #4e5058;
    color: #80848e;
}
QPushButton#dangerButton {
    background-color: #da373c;
}
QPushButton#dangerButton:hover {
    background-color: #a12828;
}
QPushButton#dangerButton:disabled {
    background-color: #4e5058;
    color: #80848e;
}
QLineEdit {
    background-color: #1e1f22;
    color: #dbdee1;
    border: 1px solid #1e1f22;
    border-radius: 4px;
    padding: 8px 12px;
    font-size: 14px;
    min-height: 28px;
}
QLineEdit:focus {
    border-color: #5865f2;
}
QListWidget {
    background-color: #2b2d31;
    color: #dbdee1;
    border: 1px solid #1e1f22;
    border-radius: 8px;
    padding: 4px;
    font-size: 14px;
}
QListWidget::item {
    padding: 8px 12px;
    border-radius: 4px;
}
QListWidget::item:selected {
    background-color: #404249;
    color: #ffffff;
}
QListWidget::item:hover {
    background-color: #35373c;
}
QListWidget::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 2px solid #80848e;
    background-color: #1e1f22;
}
QListWidget::indicator:checked {
    background-color: #5865f2;
    border-color: #5865f2;
}
QTabWidget::pane {
    border: none;
}
QTabBar::tab {
    background-color: #2b2d31;
    color: #949ba4;
    padding: 8px 18px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-weight: bold;
}
QTabBar::tab:selected {
    background-color: #404249;
    color: #ffffff;
}
QTabBar::tab:hover {
    color: #dbdee1;
}
QLabel {
    color: #dbdee1;
    font-size: 14px;
}
QLabel#loginErrorLabel, QLabel#serverSelectorErrorLabel,
QLabel#dmSelectorErrorLabel {
    color: #f23f43;
    font-size: 13px;
}
QLabel#rate_limit_label {
    color: #f0b232;
    font-size: 13px;
    padding: 4px 8px;
}
QLabel#statsHeader {
    color: #ffffff;
    font-size: 13px;
    font-weight: bold;
    padding: 4px 8px;
}
QLabel#etaLabel, QLabel#hintLabel {
    color: #949ba4;
    font-size: 13px;
}
QCheckBox {
    color: #dbdee1;
    font-size: 14px;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 2px solid #80848e;
    background-color: #1e1f22;
}
QCheckBox::indicator:checked {
    background-color: #5865f2;
    border-color: #5865f2;
}
QDialog {
    background-color: #313338;
    color: #dbdee1;
}
QMessageBox {
    background-color: #313338;
    color: #dbdee1;
}
"""


class MainWindow(QMainWindow):

    def __init__(
        self,
        controller: "OperationController",
        session: "Session",
        token_manager: "TokenValidator",
        http_client: "HttpClient",
        *,
        show_consent: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._session = session
        self._state: OperationState = OperationState.IDLE

        self.setWindowTitle(_WINDOW_TITLE)
        self.setMinimumSize(900, 600)
        self.resize(960, 680)

        self._login_screen = LoginScreen(token_manager, self)
        self._server_selector = ServerSelectorScreen(http_client, self)
        self._dm_selector = DirectMessagesScreen(http_client, self)
        self._progress_display = ProgressDisplay(self)

        self._build_ui()

        self._connect_screen_signals()

        self._connect_controller_signals()

        self._update_buttons(OperationState.IDLE)

        if show_consent:
            self._show_consent_dialog()


    def _build_ui(self) -> None:

        self.setStyleSheet(_DISCORD_STYLESHEET)

        self._selector_tabs = QTabWidget(self)
        self._selector_tabs.addTab(self._server_selector, _TAB_SERVERS)
        self._selector_tabs.addTab(self._dm_selector, _TAB_DIRECT_MESSAGES)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._login_screen)
        self._stack.addWidget(self._selector_tabs)
        self._stack.addWidget(self._progress_display)

        self._pause_button = QPushButton(_BUTTON_PAUSE, self)
        self._resume_button = QPushButton(_BUTTON_RESUME, self)
        self._cancel_button = QPushButton(_BUTTON_CANCEL, self)
        self._new_button = QPushButton(_BUTTON_NEW, self)

        self._pause_button.setAutoDefault(False)
        self._resume_button.setAutoDefault(False)
        self._cancel_button.setAutoDefault(False)
        self._new_button.setAutoDefault(False)

        self._pause_button.clicked.connect(self._on_pause_clicked)
        self._resume_button.clicked.connect(self._on_resume_clicked)
        self._cancel_button.clicked.connect(self._on_cancel_clicked)
        self._new_button.clicked.connect(self._on_new_clicked)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self._pause_button)
        button_row.addWidget(self._resume_button)
        button_row.addWidget(self._cancel_button)
        button_row.addWidget(self._new_button)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.addWidget(self._stack, stretch=1)
        layout.addLayout(button_row)
        self.setCentralWidget(central)


    def _connect_screen_signals(self) -> None:

        self._login_screen.token_validated.connect(self._on_token_validated)

        self._server_selector.start_requested.connect(
            self._on_start_requested
        )
        self._dm_selector.start_requested.connect(self._on_start_requested)

        self._stack.currentChanged.connect(self._refresh_new_button)

    def _connect_controller_signals(self) -> None:

        self._controller.state_changed.connect(self._on_state_changed)

        self._controller.log_entry_added.connect(
            self._progress_display.append_log_entry
        )

        self._controller.progress_changed.connect(self._on_progress_changed)

        self._controller.summary_ready.connect(self._on_summary_ready)

        self._controller.rate_limit_wait_started.connect(
            self._progress_display.show_rate_limit_wait
        )
        self._controller.rate_limit_wait_ended.connect(
            self._progress_display.hide_rate_limit_wait
        )

        self._controller.auth_lost.connect(self._on_auth_lost)

        self._controller.operation_finished.connect(self._refresh_new_button)


    def _show_consent_dialog(self) -> None:

        dialog = ConsentDialog(self)
        result = dialog.exec()

        if result == ConsentDialog.DialogCode.Rejected or not dialog.consent_given:
            QTimer.singleShot(0, QApplication.quit)
            return

        self._session.consent_granted = True


    def closeEvent(self, event: QCloseEvent) -> None:
        ctx = self._controller._ctx
        state = ctx.state if ctx else OperationState.IDLE

        if state in (OperationState.RUNNING, OperationState.PAUSED):
            dialog = CancelConfirmDialog.for_close_app(self)
            result = dialog.exec()

            if result == QDialog.DialogCode.Accepted:
                success = self._controller.shutdown(timeout_s=5.0)
                if not success:
                    import os

                    os._exit(0)
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


    @Slot(str, str)
    def _on_token_validated(self, token: str, user_id: str) -> None:

        self._session.authenticated_user_id = user_id
        self._session.token = token

        self._stack.setCurrentIndex(_PAGE_SERVER_SELECTOR)
        self._server_selector.load_servers()
        self._dm_selector.clear()
        self._dm_selector.load_channels()

    @Slot(object)
    def _on_start_requested(self, server: object) -> None:

        if not isinstance(server, (Server, DirectMessagesTarget)):
            return

        if self._controller.is_busy:
            return

        dialog = ConfirmationDialog(server, self)
        dialog.exec()

        if not dialog.confirmed:
            return

        self._progress_display.reset()
        self._stack.setCurrentIndex(_PAGE_PROGRESS)
        self._controller.start(server, self._session.authenticated_user_id or "")


    @Slot(object)
    def _on_state_changed(self, state: object) -> None:

        if isinstance(state, OperationState):
            self._update_buttons(state)

    @Slot(int, int)
    def _on_progress_changed(self, processed: int, total: int) -> None:

        if total != self._progress_display.total:
            self._progress_display.update_total(total)
        self._progress_display._update_stats_header()

    @Slot(object)
    def _on_summary_ready(self, summary: object) -> None:

        success = getattr(summary, "success", 0)
        not_found = getattr(summary, "not_found", 0)
        errors = getattr(summary, "errors", 0)
        self._progress_display.show_summary(success, not_found, errors)

    @Slot()
    def _on_auth_lost(self) -> None:

        self._stack.setCurrentIndex(_PAGE_LOGIN)

        QMessageBox.warning(self, _WINDOW_TITLE, _MSG_AUTH_LOST)


    @Slot()
    def _on_pause_clicked(self) -> None:
        self._controller.pause()

    @Slot()
    def _on_resume_clicked(self) -> None:
        self._controller.resume()

    @Slot()
    def _on_cancel_clicked(self) -> None:
        self._controller.cancel()

    @Slot()
    def _on_new_clicked(self) -> None:
        if self._controller.is_busy:
            return
        if self._session.token is None:
            self._stack.setCurrentIndex(_PAGE_LOGIN)
            return
        self._stack.setCurrentIndex(_PAGE_SERVER_SELECTOR)


    def _update_buttons(self, state: OperationState) -> None:

        if state == OperationState.RUNNING:
            self._pause_button.setEnabled(True)
            self._pause_button.setVisible(True)
            self._resume_button.setEnabled(False)
            self._resume_button.setVisible(False)
            self._cancel_button.setEnabled(True)
            self._cancel_button.setVisible(True)
        elif state == OperationState.PAUSED:
            self._pause_button.setEnabled(False)
            self._pause_button.setVisible(False)
            self._resume_button.setEnabled(True)
            self._resume_button.setVisible(True)
            self._cancel_button.setEnabled(True)
            self._cancel_button.setVisible(True)
        else:
            self._pause_button.setEnabled(False)
            self._pause_button.setVisible(False)
            self._resume_button.setEnabled(False)
            self._resume_button.setVisible(False)
            self._cancel_button.setEnabled(False)
            self._cancel_button.setVisible(False)

        self._state = state
        self._refresh_new_button()

    @Slot()
    def _refresh_new_button(self) -> None:

        visible = (
            self._state in _TERMINAL_STATES
            and self._stack.currentIndex() == _PAGE_PROGRESS
        )
        self._new_button.setVisible(visible)
        self._new_button.setEnabled(visible and not self._controller.is_busy)

    @property
    def stack(self) -> QStackedWidget:
        return self._stack

    @property
    def login_screen(self) -> LoginScreen:
        return self._login_screen

    @property
    def server_selector(self) -> ServerSelectorScreen:
        return self._server_selector

    @property
    def dm_selector(self) -> DirectMessagesScreen:
        return self._dm_selector

    @property
    def selector_tabs(self) -> QTabWidget:
        return self._selector_tabs

    @property
    def progress_display(self) -> ProgressDisplay:
        return self._progress_display

    @property
    def pause_button(self) -> QPushButton:
        return self._pause_button

    @property
    def resume_button(self) -> QPushButton:
        return self._resume_button

    @property
    def cancel_button(self) -> QPushButton:
        return self._cancel_button

    @property
    def new_button(self) -> QPushButton:
        return self._new_button


__all__ = ["MainWindow"]
