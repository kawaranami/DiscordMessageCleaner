from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from PySide6.QtCore import QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from discord_message_purger.application.token_manager import AuthResult


@runtime_checkable
class TokenValidator(Protocol):

    def validate_and_store(self, token: str) -> "AuthResult": ...


_STATUS_OK: Final[str] = "ok"
_STATUS_INVALID_TOKEN: Final[str] = "invalid_token"
_STATUS_NETWORK_ERROR: Final[str] = "network_error"
_STATUS_STORAGE_ERROR: Final[str] = "storage_error"

_MAX_TOKEN_LENGTH: Final[int] = 100

_BUTTON_CONNECT: Final[str] = "Подключиться"
_PLACEHOLDER: Final[str] = "Введите токен Discord"

_MSG_EMPTY_TOKEN: Final[str] = "Введите токен"
_MSG_INVALID_TOKEN: Final[str] = "Токен недействителен"
_MSG_NETWORK_ERROR: Final[str] = (
    "Ошибка соединения с Discord. Попробуйте ещё раз."
)
_MSG_STORAGE_ERROR: Final[str] = (
    "Не удалось сохранить токен. Перезапустите приложение."
)


class _ValidationWorker(QThread):

    def __init__(self, token_manager: TokenValidator, token: str) -> None:
        super().__init__()
        self._token_manager = token_manager
        self._token = token
        self.result: object | None = None
        self.error: BaseException | None = None

    def run(self) -> None:  # noqa: D401 - переопределение QThread.run

        try:
            self.result = self._token_manager.validate_and_store(self._token)
        except BaseException as exc:  # noqa: BLE001 — намеренно широко
            self.error = exc


class LoginScreen(QWidget):

    token_validated = Signal(str, str)
    validation_failed = Signal(str)

    def __init__(
        self,
        token_manager: TokenValidator,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._token_manager = token_manager

        self._worker: _ValidationWorker | None = None
        self._pending_token: str | None = None

        self._build_ui()


    def _build_ui(self) -> None:

        self._token_input = QLineEdit(self)
        self._token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._token_input.setMaxLength(_MAX_TOKEN_LENGTH)
        self._token_input.setPlaceholderText(_PLACEHOLDER)
        self._token_input.returnPressed.connect(self._on_connect_clicked)

        self._connect_button = QPushButton(_BUTTON_CONNECT, self)
        self._connect_button.setAutoDefault(False)
        self._connect_button.setDefault(False)
        self._connect_button.clicked.connect(self._on_connect_clicked)

        self._error_label = QLabel("", self)
        self._error_label.setWordWrap(True)
        self._error_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._error_label.setObjectName("loginErrorLabel")

        layout = QVBoxLayout(self)
        layout.addWidget(self._token_input)
        layout.addWidget(self._connect_button)
        layout.addWidget(self._error_label)


    @property
    def error_text(self) -> str:

        return self._error_label.text()


    @Slot()
    def _on_connect_clicked(self) -> None:

        if self._worker is not None:
            return

        raw_token = self._token_input.text()
        token = raw_token.strip()
        if token == "":
            self._set_error(_MSG_EMPTY_TOKEN)
            self.validation_failed.emit(_MSG_EMPTY_TOKEN)
            return

        self._set_error("")
        self._token_input.setEnabled(False)
        self._connect_button.setEnabled(False)

        worker = _ValidationWorker(self._token_manager, token)
        worker.finished.connect(self._on_worker_done)
        worker.finished.connect(worker.deleteLater)

        self._worker = worker
        self._pending_token = token

        worker.start()


    @Slot()
    def _on_worker_done(self) -> None:

        worker = self._worker
        token = self._pending_token

        self._worker = None
        self._pending_token = None

        self._restore_inputs()

        if worker is None or token is None:
            return

        if worker.error is not None:
            self._set_error(_MSG_NETWORK_ERROR)
            self.validation_failed.emit(_MSG_NETWORK_ERROR)
            return

        result = worker.result
        status = getattr(result, "status", None)

        if status == _STATUS_OK:
            user_id = getattr(result, "user_id", None) or ""
            self._set_error("")
            self.token_validated.emit(token, user_id)
            return

        if status == _STATUS_INVALID_TOKEN:
            message = _MSG_INVALID_TOKEN
        elif status == _STATUS_STORAGE_ERROR:
            message = _MSG_STORAGE_ERROR
        else:
            message = _MSG_NETWORK_ERROR

        self._set_error(message)
        self.validation_failed.emit(message)


    def _restore_inputs(self) -> None:

        self._token_input.setEnabled(True)
        self._connect_button.setEnabled(True)

    def _set_error(self, message: str) -> None:

        self._error_label.setText(message)


__all__ = ["LoginScreen", "TokenValidator"]
