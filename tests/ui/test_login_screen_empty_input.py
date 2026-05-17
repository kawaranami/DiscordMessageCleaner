# Feature: discord-message-purger, Property 3: Empty-input rejection on login

from __future__ import annotations

from dataclasses import dataclass

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from PySide6.QtCore import Qt

from discord_message_purger.ui.login_screen import LoginScreen


@dataclass(frozen=True)
class _FakeAuthResult:

    status: str
    user_id: str | None = None
    error_message: str | None = None


class _RecordingTokenManager:

    def __init__(self) -> None:
        self.calls: list[str] = []

    def validate_and_store(self, token: str) -> _FakeAuthResult:
        self.calls.append(token)
        return _FakeAuthResult(status="ok", user_id="should-not-reach")


_whitespace_strategy = st.text(
    alphabet=st.sampled_from([" ", "\t", "\n", "\r"]),
    min_size=0,
    max_size=50,
)


@pytest.mark.property
@given(whitespace_input=_whitespace_strategy)
@settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_empty_input_rejects_without_http_request(
    whitespace_input: str, qtbot
) -> None:

    manager = _RecordingTokenManager()
    screen = LoginScreen(token_manager=manager)
    qtbot.addWidget(screen)

    screen._token_input.setText(whitespace_input)

    with qtbot.waitSignal(screen.validation_failed, timeout=1000) as blocker:
        qtbot.mouseClick(screen._connect_button, Qt.MouseButton.LeftButton)

    assert manager.calls == [], (
        f"validate_and_store вызван для whitespace-only ввода: {whitespace_input!r}"
    )

    assert screen.error_text == "Введите токен", (
        f"Ожидался текст ошибки 'Введите токен', получено: {screen.error_text!r}"
    )

    assert blocker.args == ["Введите токен"], (
        f"Сигнал validation_failed содержит неверные аргументы: {blocker.args}"
    )
