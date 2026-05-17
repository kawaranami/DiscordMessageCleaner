from __future__ import annotations

from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

DialogMode = Literal["cancel_operation", "close_app"]


_TEXTS: dict[DialogMode, dict[str, str]] = {
    "cancel_operation": {
        "title": "Confirm",
        "message": "Cancel the running operation?",
        "accept": "Yes, cancel",
        "reject": "No",
    },
    "close_app": {
        "title": "Confirm",
        "message": "The deletion operation is still running. Close the application?",
        "accept": "Close",
        "reject": "Cancel",
    },
}


class CancelConfirmDialog(QDialog):

    def __init__(
        self,
        mode: DialogMode,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        if mode not in _TEXTS:
            raise ValueError(
                f"Invalid CancelConfirmDialog mode: {mode!r}. "
                f"Expected one of: {tuple(_TEXTS)}"
            )

        self._mode: DialogMode = mode
        self._confirmed: bool = False

        texts = _TEXTS[mode]

        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setModal(True)
        self.setWindowTitle(texts["title"])

        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        self._build_ui(texts)


    @classmethod
    def for_cancel_operation(
        cls, parent: QWidget | None = None
    ) -> "CancelConfirmDialog":

        return cls(mode="cancel_operation", parent=parent)

    @classmethod
    def for_close_app(cls, parent: QWidget | None = None) -> "CancelConfirmDialog":

        return cls(mode="close_app", parent=parent)


    @property
    def mode(self) -> DialogMode:

        return self._mode

    @property
    def confirmed(self) -> bool:

        return self._confirmed

    @property
    def accept_button(self) -> QPushButton:

        return self._accept_button

    @property
    def reject_button(self) -> QPushButton:

        return self._reject_button


    def _build_ui(self, texts: dict[str, str]) -> None:

        self._message_label = QLabel(texts["message"], self)
        self._message_label.setWordWrap(True)
        self._message_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self._button_box = QDialogButtonBox(self)

        self._accept_button = QPushButton(texts["accept"], self)
        self._reject_button = QPushButton(texts["reject"], self)

        self._button_box.addButton(
            self._accept_button, QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._button_box.addButton(
            self._reject_button, QDialogButtonBox.ButtonRole.RejectRole
        )

        self._reject_button.setDefault(True)
        self._reject_button.setAutoDefault(True)
        self._accept_button.setDefault(False)
        self._accept_button.setAutoDefault(False)

        self._button_box.accepted.connect(self._on_accepted)
        self._button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._message_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self._button_box)
        layout.addLayout(button_row)

        self.setLayout(layout)


    def _on_accepted(self) -> None:

        self._confirmed = True
        self.accept()


__all__ = ["CancelConfirmDialog", "DialogMode"]
