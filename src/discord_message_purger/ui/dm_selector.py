from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Final, Protocol, runtime_checkable

from PySide6.QtCore import QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from discord_message_purger.domain.direct_messages import (
    DirectMessageDirectory,
    NotADirectMessageError,
    parse_channel_reference,
)
from discord_message_purger.domain.exceptions import (
    DiscordAuthError,
    DiscordForbiddenError,
    DiscordNetworkError,
    DiscordNotFoundError,
    DiscordServerError,
    DiscordTimeoutError,
)
from discord_message_purger.domain.models import Channel, DirectMessagesTarget

if TYPE_CHECKING:
    from discord_message_purger.ui.server_selector import HttpClient


@runtime_checkable
class DmChannelSource(Protocol):

    def list_channels(self) -> list[Channel]: ...

    def fetch_channel(self, channel_id: str) -> Channel: ...


_HINT_TEXT: Final[str] = (
    "Only open conversations are listed. To clean a closed DM, open it in "
    "Discord and press Refresh, or paste its channel ID or link below."
)
_SEARCH_PLACEHOLDER: Final[str] = "Search conversations"
_ADD_PLACEHOLDER: Final[str] = (
    "Channel ID or link (https://discord.com/channels/@me/...)"
)

_BUTTON_SELECT_ALL: Final[str] = "Select all"
_BUTTON_SELECT_NONE: Final[str] = "Select none"
_BUTTON_REFRESH: Final[str] = "Refresh"
_BUTTON_ADD: Final[str] = "Add"
_BUTTON_START_NONE: Final[str] = "Select conversations to clean"
_BUTTON_START_TEMPLATE: Final[str] = "Delete my messages in {count} {noun}"

_MSG_LOADING: Final[str] = "Loading conversations..."
_MSG_NO_CHANNELS: Final[str] = "No open direct message conversations"
_MSG_BAD_REFERENCE: Final[str] = (
    "Enter a channel ID or a discord.com/channels/@me/... link"
)
_MSG_NOT_DM: Final[str] = "This channel is not a direct message conversation."
_MSG_NOT_FOUND: Final[str] = "Conversation not found or not accessible."
_MSG_AUTH_ERROR: Final[str] = "Authorization error. The token is invalid or expired."
_MSG_SERVER_ERROR: Final[str] = "Discord server error. Please try again later."
_MSG_NETWORK_ERROR: Final[str] = "Network error. Check your internet connection."
_MSG_TIMEOUT_ERROR: Final[str] = "Request to Discord timed out."
_MSG_UNKNOWN_ERROR: Final[str] = "An unexpected error occurred."


def _describe_error(error: BaseException) -> str:

    if isinstance(error, NotADirectMessageError):
        return _MSG_NOT_DM
    if isinstance(error, (DiscordNotFoundError, DiscordForbiddenError)):
        return _MSG_NOT_FOUND
    if isinstance(error, DiscordAuthError):
        return _MSG_AUTH_ERROR
    if isinstance(error, DiscordServerError):
        return _MSG_SERVER_ERROR
    if isinstance(error, DiscordTimeoutError):
        return _MSG_TIMEOUT_ERROR
    if isinstance(error, DiscordNetworkError):
        return _MSG_NETWORK_ERROR
    return _MSG_UNKNOWN_ERROR


class _CallWorker(QThread):

    def __init__(self, call: Callable[[], object]) -> None:
        super().__init__()
        self._call = call
        self.result: object | None = None
        self.error: BaseException | None = None

    def run(self) -> None:  # noqa: D401 - overrides QThread.run
        try:
            self.result = self._call()
        except BaseException as exc:  # noqa: BLE001 - intentionally broad
            self.error = exc


class DirectMessagesScreen(QWidget):

    start_requested = Signal(object)

    def __init__(
        self,
        http: "HttpClient | None" = None,
        parent: QWidget | None = None,
        *,
        source: DmChannelSource | None = None,
    ) -> None:
        super().__init__(parent)
        if source is None:
            if http is None:
                raise ValueError("Either http or source must be provided")
            source = DirectMessageDirectory(http)  # type: ignore[arg-type]
        self._source: DmChannelSource = source

        self._worker: _CallWorker | None = None
        self._on_worker_result: Callable[[object], None] | None = None

        self._build_ui()
        self._update_start_button()


    def _build_ui(self) -> None:

        self._hint_label = QLabel(_HINT_TEXT, self)
        self._hint_label.setWordWrap(True)
        self._hint_label.setObjectName("hintLabel")

        self._search_input = QLineEdit(self)
        self._search_input.setPlaceholderText(_SEARCH_PLACEHOLDER)
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._apply_filter)

        self._list_widget = QListWidget(self)
        self._list_widget.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._list_widget.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._list_widget.itemChanged.connect(self._on_item_changed)
        self._list_widget.itemClicked.connect(self._on_item_clicked)

        self._select_all_button = QPushButton(_BUTTON_SELECT_ALL, self)
        self._select_none_button = QPushButton(_BUTTON_SELECT_NONE, self)
        self._refresh_button = QPushButton(_BUTTON_REFRESH, self)
        self._select_all_button.clicked.connect(self.select_all_visible)
        self._select_none_button.clicked.connect(self.select_none)
        self._refresh_button.clicked.connect(self.load_channels)

        selection_row = QHBoxLayout()
        selection_row.addWidget(self._select_all_button)
        selection_row.addWidget(self._select_none_button)
        selection_row.addStretch(1)
        selection_row.addWidget(self._refresh_button)

        self._add_input = QLineEdit(self)
        self._add_input.setPlaceholderText(_ADD_PLACEHOLDER)
        self._add_input.returnPressed.connect(self._on_add_clicked)
        self._add_button = QPushButton(_BUTTON_ADD, self)
        self._add_button.clicked.connect(self._on_add_clicked)

        add_row = QHBoxLayout()
        add_row.addWidget(self._add_input, stretch=1)
        add_row.addWidget(self._add_button)

        self._start_button = QPushButton(_BUTTON_START_NONE, self)
        self._start_button.setObjectName("dangerButton")
        self._start_button.clicked.connect(self._on_start_clicked)

        self._error_label = QLabel("", self)
        self._error_label.setWordWrap(True)
        self._error_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._error_label.setObjectName("dmSelectorErrorLabel")

        for button in (
            self._select_all_button,
            self._select_none_button,
            self._refresh_button,
            self._add_button,
            self._start_button,
        ):
            button.setAutoDefault(False)
            button.setDefault(False)

        layout = QVBoxLayout(self)
        layout.addWidget(self._hint_label)
        layout.addWidget(self._search_input)
        layout.addWidget(self._list_widget, stretch=1)
        layout.addLayout(selection_row)
        layout.addLayout(add_row)
        layout.addWidget(self._start_button)
        layout.addWidget(self._error_label)


    @property
    def error_text(self) -> str:
        return self._error_label.text()

    @property
    def is_loading(self) -> bool:
        return self._worker is not None

    @property
    def list_widget(self) -> QListWidget:
        return self._list_widget

    @property
    def start_button(self) -> QPushButton:
        return self._start_button

    def channels(self) -> list[Channel]:
        return [channel for channel, _checked in self._iter_items()]

    def selected_channels(self) -> list[Channel]:
        return [channel for channel, checked in self._iter_items() if checked]


    def clear(self) -> None:

        self._list_widget.clear()
        self._search_input.clear()
        self._add_input.clear()
        self._set_error("")
        self._update_start_button()

    def load_channels(self) -> None:

        if self._run_in_background(
            self._source.list_channels, self._on_channels_loaded
        ):
            self._set_error(_MSG_LOADING)

    def add_channel_reference(self, text: str) -> None:

        channel_id = parse_channel_reference(text)
        if channel_id is None:
            self._set_error(_MSG_BAD_REFERENCE)
            return

        existing = self._find_item(channel_id)
        if existing is not None:
            existing.setHidden(False)
            existing.setCheckState(Qt.CheckState.Checked)
            self._list_widget.scrollToItem(existing)
            self._add_input.clear()
            self._set_error("")
            return

        self._run_in_background(
            lambda: self._source.fetch_channel(channel_id),
            self._on_channel_fetched,
        )

    @Slot()
    def select_all_visible(self) -> None:

        self._list_widget.blockSignals(True)
        for index in range(self._list_widget.count()):
            item = self._list_widget.item(index)
            if not item.isHidden():
                item.setCheckState(Qt.CheckState.Checked)
        self._list_widget.blockSignals(False)
        self._update_start_button()

    @Slot()
    def select_none(self) -> None:

        self._list_widget.blockSignals(True)
        for index in range(self._list_widget.count()):
            self._list_widget.item(index).setCheckState(Qt.CheckState.Unchecked)
        self._list_widget.blockSignals(False)
        self._update_start_button()


    def _run_in_background(
        self,
        call: Callable[[], object],
        on_result: Callable[[object], None],
    ) -> bool:

        if self._worker is not None:
            return False

        self._set_busy(True)
        worker = _CallWorker(call)
        worker.finished.connect(self._on_worker_done)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        self._on_worker_result = on_result
        worker.start()
        return True

    @Slot()
    def _on_worker_done(self) -> None:

        worker = self._worker
        on_result = self._on_worker_result
        self._worker = None
        self._on_worker_result = None
        self._set_busy(False)

        if worker is None or on_result is None:
            return

        if worker.error is not None:
            self._set_error(_describe_error(worker.error))
            return

        on_result(worker.result)

    def _on_channels_loaded(self, result: object) -> None:

        channels = [c for c in (result or []) if isinstance(c, Channel)]  # type: ignore[union-attr]

        previous = {channel.id: checked for channel, checked in self._iter_items()}
        manual = [
            channel
            for channel, _checked in self._iter_items()
            if channel.id not in {c.id for c in channels}
        ]

        self._list_widget.blockSignals(True)
        self._list_widget.clear()
        for channel in manual + channels:
            self._add_item(channel, checked=previous.get(channel.id, False))
        self._list_widget.blockSignals(False)

        self._apply_filter(self._search_input.text())
        self._update_start_button()
        self._set_error("" if self._list_widget.count() else _MSG_NO_CHANNELS)

    def _on_channel_fetched(self, result: object) -> None:

        if not isinstance(result, Channel):
            self._set_error(_MSG_UNKNOWN_ERROR)
            return

        existing = self._find_item(result.id)
        if existing is None:
            self._list_widget.blockSignals(True)
            existing = self._add_item(result, checked=True, row=0)
            self._list_widget.blockSignals(False)
        else:
            existing.setCheckState(Qt.CheckState.Checked)
        existing.setHidden(False)
        self._list_widget.scrollToItem(existing)
        self._add_input.clear()
        self._set_error("")
        self._update_start_button()


    def _add_item(
        self, channel: Channel, *, checked: bool, row: int | None = None
    ) -> QListWidgetItem:

        item = QListWidgetItem(channel.name)
        item.setData(Qt.ItemDataRole.UserRole, channel)
        item.setToolTip(f"Channel ID: {channel.id}")
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setCheckState(
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        )
        if row is None:
            self._list_widget.addItem(item)
        else:
            self._list_widget.insertItem(row, item)
        return item

    def _find_item(self, channel_id: str) -> QListWidgetItem | None:

        for index in range(self._list_widget.count()):
            item = self._list_widget.item(index)
            channel = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(channel, Channel) and channel.id == channel_id:
                return item
        return None

    def _iter_items(self) -> list[tuple[Channel, bool]]:

        result: list[tuple[Channel, bool]] = []
        for index in range(self._list_widget.count()):
            item = self._list_widget.item(index)
            channel = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(channel, Channel):
                result.append(
                    (channel, item.checkState() == Qt.CheckState.Checked)
                )
        return result

    @Slot(str)
    def _apply_filter(self, text: str) -> None:

        needle = text.strip().casefold()
        for index in range(self._list_widget.count()):
            item = self._list_widget.item(index)
            item.setHidden(bool(needle) and needle not in item.text().casefold())

    @Slot(QListWidgetItem)
    def _on_item_changed(self, _item: QListWidgetItem) -> None:
        self._update_start_button()

    @Slot(QListWidgetItem)
    def _on_item_clicked(self, item: QListWidgetItem) -> None:

        item.setCheckState(
            Qt.CheckState.Unchecked
            if item.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )

    @Slot()
    def _on_add_clicked(self) -> None:
        self.add_channel_reference(self._add_input.text())

    @Slot()
    def _on_start_clicked(self) -> None:

        selected = self.selected_channels()
        if not selected:
            return
        self.start_requested.emit(DirectMessagesTarget(channels=tuple(selected)))


    def _update_start_button(self) -> None:

        count = len(self.selected_channels())
        if count == 0:
            self._start_button.setText(_BUTTON_START_NONE)
        else:
            noun = "conversation" if count == 1 else "conversations"
            self._start_button.setText(
                _BUTTON_START_TEMPLATE.format(count=count, noun=noun)
            )
        self._start_button.setEnabled(count > 0 and self._worker is None)

    def _set_busy(self, busy: bool) -> None:

        self._refresh_button.setEnabled(not busy)
        self._add_button.setEnabled(not busy)
        self._add_input.setEnabled(not busy)
        self._update_start_button()

    def _set_error(self, message: str) -> None:
        self._error_label.setText(message)


__all__ = ["DirectMessagesScreen", "DmChannelSource"]
