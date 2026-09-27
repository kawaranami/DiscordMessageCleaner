from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from discord_message_purger.domain.models import (
    CleanupTarget,
    DirectMessagesTarget,
)


_BUTTON_CONFIRM = "Confirm"
_BUTTON_CANCEL = "Cancel"

_INPUT_MAX_LENGTH = 100

_MESSAGE_TEMPLATE = (
    "All messages from your account in all accessible channels of "
    "'{name}' will be deleted. This action cannot be undone."
)

_TITLE_TEMPLATE = "Confirm operation on server '{name}'"

_INPUT_PLACEHOLDER = "Type the server name to confirm"

_DM_CONFIRM_WORD = "DELETE"

_DM_MESSAGE_TEMPLATE = (
    "All messages from your account in {count} selected direct message "
    "{noun} will be deleted:\n\n{names}\n\n"
    "Messages from other participants are not affected. "
    "This action cannot be undone."
)

_DM_TITLE = "Confirm deletion in direct messages"

_DM_INPUT_PLACEHOLDER = f"Type {_DM_CONFIRM_WORD} to confirm"

_DM_MAX_LISTED = 10


class ConfirmationDialog(QDialog):

    def __init__(
        self, server: CleanupTarget, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)

        self._server: CleanupTarget = server
        self._confirmed: bool = False

        if isinstance(server, DirectMessagesTarget):
            self._expected_name: str = _DM_CONFIRM_WORD
            self._message_text = self._dm_message(server)
            self._placeholder = _DM_INPUT_PLACEHOLDER
            title = _DM_TITLE
        else:
            self._expected_name = server.name
            self._message_text = _MESSAGE_TEMPLATE.format(name=server.name)
            self._placeholder = _INPUT_PLACEHOLDER
            title = _TITLE_TEMPLATE.format(name=server.name)

        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        self.setWindowTitle(title)

        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        self._build_ui()


    @property
    def server(self) -> CleanupTarget:

        return self._server

    @property
    def confirmed(self) -> bool:

        return self._confirmed

    @property
    def confirm_button(self) -> QPushButton:

        return self._confirm_button

    @property
    def cancel_button(self) -> QPushButton:

        return self._cancel_button

    @property
    def input_field(self) -> QLineEdit:

        return self._input


    def _build_ui(self) -> None:

        self._message_label = QLabel(self._message_text, self)
        self._message_label.setWordWrap(True)
        self._message_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self._input = QLineEdit(self)
        self._input.setMaxLength(_INPUT_MAX_LENGTH)
        self._input.setPlaceholderText(self._placeholder)

        self._button_box = QDialogButtonBox(self)
        self._confirm_button = QPushButton(_BUTTON_CONFIRM, self)
        self._cancel_button = QPushButton(_BUTTON_CANCEL, self)

        self._button_box.addButton(
            self._confirm_button, QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._button_box.addButton(
            self._cancel_button, QDialogButtonBox.ButtonRole.RejectRole
        )

        self._cancel_button.setEnabled(True)

        self._cancel_button.setDefault(True)
        self._cancel_button.setAutoDefault(True)
        self._confirm_button.setDefault(False)
        self._confirm_button.setAutoDefault(False)

        self._input.textChanged.connect(self._on_text_changed)
        self._button_box.accepted.connect(self._on_accepted)
        self._button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._message_label)
        layout.addWidget(self._input)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self._button_box)
        layout.addLayout(button_row)

        self.setLayout(layout)

        self._recompute_confirm_enabled()


    @staticmethod
    def _dm_message(target: DirectMessagesTarget) -> str:

        names = [f"  • {channel.name}" for channel in target.channels]
        if len(names) > _DM_MAX_LISTED:
            hidden = len(names) - _DM_MAX_LISTED
            names = names[:_DM_MAX_LISTED] + [f"  … and {hidden} more"]
        count = len(target.channels)
        return _DM_MESSAGE_TEMPLATE.format(
            count=count,
            noun="conversation" if count == 1 else "conversations",
            names="\n".join(names),
        )

    def _on_text_changed(self, _text: str) -> None:

        self._recompute_confirm_enabled()

    def _on_accepted(self) -> None:

        if self._input.text() != self._expected_name:
            self.reject()
            return
        self._confirmed = True
        self.accept()


    def _recompute_confirm_enabled(self) -> None:

        is_match = self._input.text() == self._expected_name
        self._confirm_button.setEnabled(is_match)


__all__ = ["ConfirmationDialog"]
