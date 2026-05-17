from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


_CHECKBOX_LABEL = "I understand the risks and accept responsibility"

_WINDOW_TITLE = "Disclaimer"

_WARNING_TEXT = (
    "Discord's Terms of Service prohibit automating actions on user "
    "accounts via user tokens (so-called self-bots). Using this "
    "application may result in your Discord account being permanently "
    "banned. By proceeding, you accept full responsibility for any "
    "consequences."
)

_BUTTON_CONTINUE = "Continue"
_BUTTON_CANCEL = "Cancel"


class ConsentDialog(QDialog):

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowTitle(_WINDOW_TITLE)

        warning_label = QLabel(_WARNING_TEXT, self)
        warning_label.setWordWrap(True)
        warning_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self._checkbox = QCheckBox(_CHECKBOX_LABEL, self)
        self._checkbox.setChecked(False)

        self._button_box = QDialogButtonBox(self)
        self._continue_button: QPushButton = self._button_box.addButton(
            _BUTTON_CONTINUE, QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._cancel_button: QPushButton = self._button_box.addButton(
            _BUTTON_CANCEL, QDialogButtonBox.ButtonRole.RejectRole
        )

        self._continue_button.setEnabled(False)
        self._cancel_button.setDefault(False)
        self._cancel_button.setAutoDefault(False)
        self._continue_button.setDefault(False)
        self._continue_button.setAutoDefault(False)

        layout = QVBoxLayout(self)
        layout.addWidget(warning_label)
        layout.addWidget(self._checkbox)
        layout.addWidget(self._button_box)

        self._checkbox.toggled.connect(self._on_checkbox_toggled)
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)


    @property
    def consent_given(self) -> bool:

        return (
            self.result() == QDialog.DialogCode.Accepted
            and self._checkbox.isChecked()
        )


    def _on_checkbox_toggled(self, checked: bool) -> None:

        self._continue_button.setEnabled(checked)


    def accept(self) -> None:

        if not self._checkbox.isChecked():
            super().reject()
            return
        super().accept()


__all__ = ["ConsentDialog"]
