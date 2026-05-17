from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from discord_message_purger.ui.consent_dialog import ConsentDialog


@pytest.fixture()
def dialog(qtbot):

    widget = ConsentDialog()
    qtbot.addWidget(widget)
    return widget


def test_initial_state_continue_disabled_and_cancel_enabled(dialog: ConsentDialog) -> None:

    assert dialog._checkbox.isChecked() is False
    assert dialog._continue_button.isEnabled() is False
    assert dialog._cancel_button.isEnabled() is True


def test_continue_button_enabled_after_checkbox_checked(dialog: ConsentDialog) -> None:

    dialog._checkbox.setChecked(True)

    assert dialog._continue_button.isEnabled() is True


def test_continue_button_disabled_when_checkbox_unchecked_again(
    dialog: ConsentDialog,
) -> None:

    dialog._checkbox.setChecked(True)
    assert dialog._continue_button.isEnabled() is True

    dialog._checkbox.setChecked(False)

    assert dialog._continue_button.isEnabled() is False


def test_cancel_button_click_rejects_dialog(dialog: ConsentDialog, qtbot) -> None:

    with qtbot.waitExposed(dialog):
        dialog.show()

    qtbot.mouseClick(dialog._cancel_button, Qt.MouseButton.LeftButton)

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.consent_given is False


def test_escape_key_rejects_dialog(dialog: ConsentDialog, qtbot) -> None:

    with qtbot.waitExposed(dialog):
        dialog.show()

    qtbot.keyClick(dialog, Qt.Key.Key_Escape)

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.consent_given is False


def test_programmatic_accept_without_checkbox_falls_back_to_reject(
    dialog: ConsentDialog,
) -> None:

    assert dialog._continue_button.isEnabled() is False

    dialog.accept()

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.consent_given is False


def test_continue_button_click_with_checked_checkbox_accepts_dialog(
    dialog: ConsentDialog, qtbot
) -> None:

    with qtbot.waitExposed(dialog):
        dialog.show()

    dialog._checkbox.setChecked(True)
    assert dialog._continue_button.isEnabled() is True

    qtbot.mouseClick(dialog._continue_button, Qt.MouseButton.LeftButton)

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.consent_given is True
