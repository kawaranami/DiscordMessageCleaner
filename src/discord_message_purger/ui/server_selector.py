from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from PySide6.QtCore import QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from discord_message_purger.domain.exceptions import (
    DiscordAuthError,
    DiscordForbiddenError,
    DiscordHttpError,
    DiscordNetworkError,
    DiscordPurgerError,
    DiscordServerError,
    DiscordTimeoutError,
)
from discord_message_purger.domain.models import Server

if TYPE_CHECKING:
    from discord_message_purger.infrastructure.http_client import DiscordHttpClient


@runtime_checkable
class HttpClient(Protocol):

    def get(
        self,
        path: str,
        *,
        timeout_s: float,
        params: object = None,
        max_consecutive_429: int | None = None,
    ) -> object: ...


_BUTTON_START: Final[str] = "Запустить операцию"
_BUTTON_RETRY: Final[str] = "Повторить"
_MSG_NO_SERVERS: Final[str] = "Доступных серверов нет"
_MSG_AUTH_ERROR: Final[str] = "Ошибка авторизации. Токен недействителен или истёк."
_MSG_FORBIDDEN_ERROR: Final[str] = "Доступ запрещён. Недостаточно прав."
_MSG_SERVER_ERROR: Final[str] = "Ошибка сервера Discord. Попробуйте позже."
_MSG_NETWORK_ERROR: Final[str] = "Ошибка сети. Проверьте подключение к интернету."
_MSG_TIMEOUT_ERROR: Final[str] = "Превышено время ожидания ответа от Discord."
_MSG_UNKNOWN_ERROR: Final[str] = "Произошла непредвиденная ошибка."


class _LoadServersWorker(QThread):

    def __init__(self, http: HttpClient) -> None:
        super().__init__()
        self._http = http
        self.servers: list[dict] | None = None
        self.error: BaseException | None = None

    def run(self) -> None:  # noqa: D401 - переопределение QThread.run
        try:
            response = self._http.get("/users/@me/guilds", timeout_s=10.0)
            self.servers = response.json()
        except BaseException as exc:  # noqa: BLE001 — намеренно широко
            self.error = exc


class ServerSelectorScreen(QWidget):

    server_selected = Signal(object)
    start_requested = Signal(object)

    def __init__(
        self,
        http: "HttpClient | DiscordHttpClient",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._http = http

        self._worker: _LoadServersWorker | None = None

        self._build_ui()


    def _build_ui(self) -> None:

        self._list_widget = QListWidget(self)
        self._list_widget.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
        )
        self._list_widget.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._list_widget.currentRowChanged.connect(self._on_selection_changed)

        self._start_button = QPushButton(_BUTTON_START, self)
        self._start_button.setEnabled(False)
        self._start_button.setAutoDefault(False)
        self._start_button.setDefault(False)
        self._start_button.clicked.connect(self._on_start_clicked)

        self._retry_button = QPushButton(_BUTTON_RETRY, self)
        self._retry_button.setVisible(False)
        self._retry_button.setAutoDefault(False)
        self._retry_button.setDefault(False)
        self._retry_button.clicked.connect(self.load_servers)

        self._error_label = QLabel("", self)
        self._error_label.setWordWrap(True)
        self._error_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._error_label.setObjectName("serverSelectorErrorLabel")

        layout = QVBoxLayout(self)
        layout.addWidget(self._list_widget)
        layout.addWidget(self._start_button)
        layout.addWidget(self._retry_button)
        layout.addWidget(self._error_label)


    @property
    def error_text(self) -> str:
        return self._error_label.text()


    def load_servers(self) -> None:
        if self._worker is not None:
            return

        self._set_error("")
        self._retry_button.setVisible(False)

        worker = _LoadServersWorker(self._http)
        worker.finished.connect(self._on_load_done)
        worker.finished.connect(worker.deleteLater)

        self._worker = worker
        worker.start()


    @Slot(int)
    def _on_selection_changed(self, current_row: int) -> None:
        has_selection = current_row >= 0 and self._list_widget.count() > 0
        self._start_button.setEnabled(has_selection)

        if has_selection:
            item = self._list_widget.item(current_row)
            if item is not None:
                server = item.data(Qt.ItemDataRole.UserRole)
                if server is not None:
                    self.server_selected.emit(server)

    @Slot()
    def _on_start_clicked(self) -> None:
        current_item = self._list_widget.currentItem()
        if current_item is None:
            return

        server = current_item.data(Qt.ItemDataRole.UserRole)
        if server is not None:
            self.start_requested.emit(server)

    @Slot()
    def _on_load_done(self) -> None:
        worker = self._worker
        self._worker = None

        if worker is None:
            return

        if worker.error is not None:
            self._handle_load_error(worker.error)
            return

        servers_data = worker.servers
        if servers_data is None:
            servers_data = []

        self._list_widget.clear()

        if not servers_data:
            self._set_error(_MSG_NO_SERVERS)
            self._start_button.setEnabled(False)
            return

        for guild_data in servers_data:
            server = Server(
                id=str(guild_data.get("id", "")),
                name=str(guild_data.get("name", "")),
                icon_url=guild_data.get("icon"),
            )
            item = QListWidgetItem(f"{server.name} ({server.id})")
            item.setData(Qt.ItemDataRole.UserRole, server)
            self._list_widget.addItem(item)

        self._start_button.setEnabled(False)


    def _handle_load_error(self, error: BaseException) -> None:
        if isinstance(error, DiscordAuthError):
            self.show_error(_MSG_AUTH_ERROR, retryable=True)
        elif isinstance(error, DiscordForbiddenError):
            self.show_error(_MSG_FORBIDDEN_ERROR, retryable=True)
        elif isinstance(error, DiscordServerError):
            self.show_error(_MSG_SERVER_ERROR, retryable=True)
        elif isinstance(error, DiscordTimeoutError):
            self.show_error(_MSG_TIMEOUT_ERROR, retryable=True)
        elif isinstance(error, DiscordNetworkError):
            self.show_error(_MSG_NETWORK_ERROR, retryable=True)
        elif isinstance(error, DiscordHttpError):
            self.show_error(_MSG_UNKNOWN_ERROR, retryable=True)
        elif isinstance(error, DiscordPurgerError):
            self.show_error(_MSG_UNKNOWN_ERROR, retryable=True)
        else:
            self.show_error(_MSG_UNKNOWN_ERROR, retryable=True)

    def show_error(self, message: str, *, retryable: bool = False) -> None:
        self._set_error(message)
        if retryable:
            self._retry_button.setVisible(True)


    def _set_error(self, message: str) -> None:
        self._error_label.setText(message)


__all__ = ["ServerSelectorScreen", "HttpClient"]
