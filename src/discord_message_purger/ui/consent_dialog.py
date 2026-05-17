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


_CHECKBOX_LABEL = "Я понимаю риски и беру ответственность на себя"

_WINDOW_TITLE = "Подтверждение рисков использования"

_WARNING_TEXT = (
    "Внимание: использование пользовательского токена для автоматизации "
    "нарушает Discord Terms of Service и может привести к блокировке "
    "аккаунта без возможности восстановления.\n\n"
    "Приложение Discord Message Purger удаляет ваши собственные сообщения "
    "от имени вашего аккаунта через ваш токен. Все риски, связанные с "
    "использованием такого режима работы, лежат на вас.\n\n"
    "Чтобы продолжить, отметьте поле ниже и нажмите «Продолжить». "
    "Если вы не готовы принять эти риски — нажмите «Отмена», и "
    "приложение завершит работу."
)

_BUTTON_CONTINUE = "Продолжить"
_BUTTON_CANCEL = "Отмена"


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
