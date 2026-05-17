from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Final

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit

from discord_message_purger.ui.login_screen import LoginScreen


@dataclass(frozen=True)
class _FakeAuthResult:
    status: str
    user_id: str | None = None
    error_message: str | None = None


_OK: Final[str] = "ok"
_INVALID: Final[str] = "invalid_token"
_NETWORK: Final[str] = "network_error"
_STORAGE: Final[str] = "storage_error"


class _SyncTokenManager:

    def __init__(self, result: _FakeAuthResult | None = None) -> None:
        self.result = result or _FakeAuthResult(status=_OK, user_id="42")
        self.calls: list[str] = []

    def validate_and_store(self, token: str) -> _FakeAuthResult:
        self.calls.append(token)
        return self.result


@pytest.fixture()
def token_manager() -> _SyncTokenManager:

    return _SyncTokenManager()


@pytest.fixture()
def screen(qtbot, token_manager: _SyncTokenManager) -> LoginScreen:

    widget = LoginScreen(token_manager=token_manager)
    qtbot.addWidget(widget)
    return widget


def test_token_input_uses_password_echo_mode(screen: LoginScreen) -> None:

    assert screen._token_input.echoMode() == QLineEdit.EchoMode.Password


def test_token_input_max_length_is_100(screen: LoginScreen) -> None:

    assert screen._token_input.maxLength() == 100


def test_token_input_clamps_long_paste_to_100(
    screen: LoginScreen, qtbot
) -> None:

    long_value = "x" * 250
    screen._token_input.setText(long_value)

    assert len(screen._token_input.text()) == 100


@pytest.mark.parametrize("raw_value", ["", "   ", "\t\t", "\n  \t"])
def test_empty_or_whitespace_token_shows_error_without_request(
    screen: LoginScreen,
    token_manager: _SyncTokenManager,
    qtbot,
    raw_value: str,
) -> None:

    screen._token_input.setText(raw_value)

    with qtbot.waitSignal(screen.validation_failed, timeout=1000) as blocker:
        qtbot.mouseClick(screen._connect_button, Qt.MouseButton.LeftButton)

    assert blocker.args == ["Введите токен"]
    assert screen.error_text == "Введите токен"
    assert token_manager.calls == [], "HTTP-запрос не должен отправляться"


def test_successful_validation_emits_token_validated(
    qtbot, token_manager: _SyncTokenManager
) -> None:

    token_manager.result = _FakeAuthResult(status=_OK, user_id="user-123")
    screen = LoginScreen(token_manager=token_manager)
    qtbot.addWidget(screen)

    screen._token_input.setText("my-secret-token")

    with qtbot.waitSignal(screen.token_validated, timeout=2000) as blocker:
        qtbot.mouseClick(screen._connect_button, Qt.MouseButton.LeftButton)

    assert blocker.args == ["my-secret-token", "user-123"]
    assert screen.error_text == ""
    assert token_manager.calls == ["my-secret-token"]


def test_successful_validation_strips_token_before_sending(
    qtbot, token_manager: _SyncTokenManager
) -> None:

    token_manager.result = _FakeAuthResult(status=_OK, user_id="abc")
    screen = LoginScreen(token_manager=token_manager)
    qtbot.addWidget(screen)

    screen._token_input.setText("   trimmed-token   ")

    with qtbot.waitSignal(screen.token_validated, timeout=2000):
        qtbot.mouseClick(screen._connect_button, Qt.MouseButton.LeftButton)

    assert token_manager.calls == ["trimmed-token"]


@pytest.mark.parametrize(
    "status,expected_message",
    [
        (_INVALID, "Токен недействителен"),
        (_NETWORK, "Ошибка соединения с Discord. Попробуйте ещё раз."),
        (_STORAGE, "Не удалось сохранить токен. Перезапустите приложение."),
    ],
)
def test_error_status_mapping(
    qtbot,
    token_manager: _SyncTokenManager,
    status: str,
    expected_message: str,
) -> None:

    token_manager.result = _FakeAuthResult(status=status)
    screen = LoginScreen(token_manager=token_manager)
    qtbot.addWidget(screen)

    screen._token_input.setText("any-non-empty-token")

    with qtbot.waitSignal(screen.validation_failed, timeout=2000) as blocker:
        qtbot.mouseClick(screen._connect_button, Qt.MouseButton.LeftButton)

    assert blocker.args == [expected_message]
    assert screen.error_text == expected_message


def test_error_keeps_inputs_enabled_for_retry(
    qtbot, token_manager: _SyncTokenManager
) -> None:

    token_manager.result = _FakeAuthResult(status=_INVALID)
    screen = LoginScreen(token_manager=token_manager)
    qtbot.addWidget(screen)

    screen._token_input.setText("bad-token")

    with qtbot.waitSignal(screen.validation_failed, timeout=2000):
        qtbot.mouseClick(screen._connect_button, Qt.MouseButton.LeftButton)

    assert screen._token_input.isEnabled() is True
    assert screen._connect_button.isEnabled() is True


class _BlockingTokenManager:

    def __init__(self) -> None:
        self.release = threading.Event()
        self.entered = threading.Event()
        self.calls: list[str] = []

    def validate_and_store(self, token: str) -> _FakeAuthResult:
        self.calls.append(token)
        self.entered.set()
        self.release.wait(timeout=5.0)
        return _FakeAuthResult(status=_OK, user_id="late-user")


def test_validation_runs_in_background_thread(qtbot) -> None:

    manager = _BlockingTokenManager()
    screen = LoginScreen(token_manager=manager)
    qtbot.addWidget(screen)

    screen._token_input.setText("token-async")
    qtbot.mouseClick(screen._connect_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(manager.entered.is_set, timeout=3000)
    assert screen._connect_button.isEnabled() is False
    assert screen._token_input.isEnabled() is False

    with qtbot.waitSignal(screen.token_validated, timeout=3000) as blocker:
        manager.release.set()

    assert blocker.args == ["token-async", "late-user"]
    assert screen._connect_button.isEnabled() is True
    assert screen._token_input.isEnabled() is True
