from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from discord_message_purger.application.controller import OperationController
from discord_message_purger.application.session import Session
from discord_message_purger.domain.models import (
    Channel,
    ChannelType,
    DirectMessagesTarget,
    OperationState,
)
from discord_message_purger.ui.main_window import MainWindow


class _FakeTokenManager:

    def validate_and_store(self, token: str) -> object:
        return MagicMock(status="ok", user_id="123456")


class _FakeResponse:

    def __init__(self, data: object) -> None:
        self._data = data

    def json(self) -> object:
        return self._data


class _FakeHttpClient:

    def __init__(self) -> None:
        self.paths: list[str] = []

    def get(self, path: str, *, timeout_s: float, **_kwargs: object) -> _FakeResponse:
        self.paths.append(path)
        if path == "/users/@me/channels":
            return _FakeResponse(
                [{"id": "900", "type": 1, "recipients": [{"id": "1", "username": "friend"}]}]
            )
        return _FakeResponse([])


_TARGET = DirectMessagesTarget(
    channels=(Channel(id="900", guild_id=None, name="friend", type=ChannelType.DM),)
)


@pytest.fixture()
def session() -> Session:
    session = Session()
    session.consent_granted = True
    return session


@pytest.fixture()
def controller(session: Session) -> OperationController:
    return OperationController(
        scanner=MagicMock(),
        deleter=MagicMock(),
        operation_log=MagicMock(),
        session=session,
    )


@pytest.fixture()
def http_client() -> _FakeHttpClient:
    return _FakeHttpClient()


@pytest.fixture()
def window(qtbot, session, controller, http_client) -> MainWindow:
    main_window = MainWindow(
        controller=controller,
        session=session,
        token_manager=_FakeTokenManager(),
        http_client=http_client,
        show_consent=False,
    )
    qtbot.addWidget(main_window)
    return main_window


def test_selector_page_has_servers_and_dm_tabs(window: MainWindow) -> None:
    tabs = window.selector_tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "Servers",
        "Direct messages",
    ]
    assert tabs.widget(0) is window.server_selector
    assert tabs.widget(1) is window.dm_selector


def test_token_validated_loads_servers_and_dms(
    window: MainWindow, http_client: _FakeHttpClient, qtbot
) -> None:
    window._on_token_validated("token", "123456")
    qtbot.waitUntil(lambda: not window.dm_selector.is_loading, timeout=3000)
    qtbot.waitUntil(lambda: window.server_selector._worker is None, timeout=3000)

    assert "/users/@me/guilds" in http_client.paths
    assert "/users/@me/channels" in http_client.paths
    assert [c.id for c in window.dm_selector.channels()] == ["900"]


def test_dm_start_goes_through_confirmation(
    window: MainWindow, session: Session, controller: OperationController
) -> None:
    session.authenticated_user_id = "123456"
    window.progress_display.update_total(5)

    with patch("discord_message_purger.ui.main_window.ConfirmationDialog") as dialog_cls:
        dialog_cls.return_value = MagicMock(confirmed=True)
        with patch.object(controller, "start") as start:
            window.dm_selector.start_requested.emit(_TARGET)

    dialog_cls.assert_called_once_with(_TARGET, window)
    start.assert_called_once_with(_TARGET, "123456")
    assert window.stack.currentIndex() == 2
    assert window.progress_display.total == 0


def test_dm_start_rejected_dialog_does_not_start(
    window: MainWindow, session: Session, controller: OperationController
) -> None:
    session.authenticated_user_id = "123456"
    window.stack.setCurrentIndex(1)

    with patch("discord_message_purger.ui.main_window.ConfirmationDialog") as dialog_cls:
        dialog_cls.return_value = MagicMock(confirmed=False)
        with patch.object(controller, "start") as start:
            window.dm_selector.start_requested.emit(_TARGET)

    start.assert_not_called()
    assert window.stack.currentIndex() == 1


@pytest.mark.parametrize(
    "state",
    [OperationState.COMPLETED, OperationState.CANCELED, OperationState.ERROR],
)
def test_new_cleanup_button_after_operation(window: MainWindow, session: Session, state) -> None:
    session.token = "token"
    window.stack.setCurrentIndex(2)

    window._update_buttons(state)

    assert window.new_button.isVisibleTo(window)
    assert window.new_button.isEnabled()

    window.new_button.click()

    assert window.stack.currentIndex() == 1
    assert not window.new_button.isVisibleTo(window)


@pytest.mark.parametrize(
    "state",
    [OperationState.IDLE, OperationState.RUNNING, OperationState.PAUSED],
)
def test_new_cleanup_button_hidden_while_active(window: MainWindow, state) -> None:
    window.stack.setCurrentIndex(2)

    window._update_buttons(state)

    assert not window.new_button.isVisibleTo(window)


def test_new_cleanup_disabled_until_worker_finishes(
    window: MainWindow, controller: OperationController
) -> None:
    window.stack.setCurrentIndex(2)
    controller._worker_running = True

    window._update_buttons(OperationState.CANCELED)
    assert window.new_button.isVisibleTo(window)
    assert not window.new_button.isEnabled()

    controller._worker_running = False
    controller.operation_finished.emit()
    assert window.new_button.isEnabled()


def test_new_cleanup_without_token_returns_to_login(window: MainWindow, session: Session) -> None:
    session.token = None
    window.stack.setCurrentIndex(2)
    window._update_buttons(OperationState.CANCELED)

    window.new_button.click()

    assert window.stack.currentIndex() == 0
