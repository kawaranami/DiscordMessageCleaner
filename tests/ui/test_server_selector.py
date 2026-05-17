from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Final

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget

from discord_message_purger.domain.exceptions import (
    DiscordAuthError,
    DiscordForbiddenError,
    DiscordNetworkError,
    DiscordServerError,
    DiscordTimeoutError,
)
from discord_message_purger.domain.models import Server
from discord_message_purger.ui.server_selector import ServerSelectorScreen


@dataclass
class _FakeResponse:

    _data: Any

    def json(self) -> Any:
        return self._data


class _SyncHttpClient:

    def __init__(
        self,
        guilds: list[dict] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.guilds = guilds if guilds is not None else []
        self.error = error
        self.calls: list[tuple[str, float]] = []

    def get(
        self,
        path: str,
        *,
        timeout_s: float,
        params: object = None,
        max_consecutive_429: int | None = None,
    ) -> _FakeResponse:
        self.calls.append((path, timeout_s))
        if self.error is not None:
            raise self.error
        return _FakeResponse(_data=self.guilds)


class _BlockingHttpClient:

    def __init__(self, guilds: list[dict] | None = None) -> None:
        self.guilds = guilds if guilds is not None else []
        self.release = threading.Event()
        self.entered = threading.Event()
        self.calls: list[tuple[str, float]] = []

    def get(
        self,
        path: str,
        *,
        timeout_s: float,
        params: object = None,
        max_consecutive_429: int | None = None,
    ) -> _FakeResponse:
        self.calls.append((path, timeout_s))
        self.entered.set()
        self.release.wait(timeout=5.0)
        return _FakeResponse(_data=self.guilds)


_SAMPLE_GUILDS: Final[list[dict]] = [
    {"id": "111222333", "name": "Test Server Alpha"},
    {"id": "444555666", "name": "Сервер Бета"},
    {"id": "777888999", "name": "Gaming Guild"},
]


@pytest.fixture()
def http_client() -> _SyncHttpClient:
    return _SyncHttpClient(guilds=_SAMPLE_GUILDS)


@pytest.fixture()
def screen(qtbot, http_client: _SyncHttpClient) -> ServerSelectorScreen:
    widget = ServerSelectorScreen(http=http_client)
    qtbot.addWidget(widget)
    return widget


def test_load_servers_calls_correct_endpoint(
    screen: ServerSelectorScreen,
    http_client: _SyncHttpClient,
    qtbot,
) -> None:
    screen.load_servers()
    qtbot.waitUntil(lambda: screen._worker is None, timeout=3000)

    assert len(http_client.calls) == 1
    path, timeout = http_client.calls[0]
    assert path == "/users/@me/guilds"
    assert timeout == 10.0


def test_load_servers_runs_in_background_thread(qtbot) -> None:
    client = _BlockingHttpClient(guilds=_SAMPLE_GUILDS)
    screen = ServerSelectorScreen(http=client)
    qtbot.addWidget(screen)

    screen.load_servers()

    qtbot.waitUntil(client.entered.is_set, timeout=3000)

    client.release.set()
    qtbot.waitUntil(lambda: screen._worker is None, timeout=3000)

    assert screen._list_widget.count() == 3


def test_servers_displayed_with_name_and_id(
    screen: ServerSelectorScreen,
    http_client: _SyncHttpClient,
    qtbot,
) -> None:
    screen.load_servers()
    qtbot.waitUntil(lambda: screen._worker is None, timeout=3000)

    assert screen._list_widget.count() == 3
    assert screen._list_widget.item(0).text() == "Test Server Alpha (111222333)"
    assert screen._list_widget.item(1).text() == "Сервер Бета (444555666)"
    assert screen._list_widget.item(2).text() == "Gaming Guild (777888999)"


def test_list_widget_no_text_eliding(
    screen: ServerSelectorScreen,
) -> None:
    assert screen._list_widget.textElideMode() == Qt.TextElideMode.ElideNone


def test_server_items_store_server_in_user_role(
    screen: ServerSelectorScreen,
    http_client: _SyncHttpClient,
    qtbot,
) -> None:
    screen.load_servers()
    qtbot.waitUntil(lambda: screen._worker is None, timeout=3000)

    item = screen._list_widget.item(0)
    server = item.data(Qt.ItemDataRole.UserRole)
    assert isinstance(server, Server)
    assert server.id == "111222333"
    assert server.name == "Test Server Alpha"


def test_list_widget_single_selection_mode(
    screen: ServerSelectorScreen,
) -> None:
    assert (
        screen._list_widget.selectionMode()
        == QListWidget.SelectionMode.SingleSelection
    )


def test_start_button_disabled_by_default(
    screen: ServerSelectorScreen,
) -> None:
    assert screen._start_button.isEnabled() is False


def test_start_button_disabled_when_list_empty(
    qtbot,
) -> None:
    client = _SyncHttpClient(guilds=[])
    screen = ServerSelectorScreen(http=client)
    qtbot.addWidget(screen)

    screen.load_servers()
    qtbot.waitUntil(lambda: screen._worker is None, timeout=3000)

    assert screen._start_button.isEnabled() is False


def test_start_button_enabled_when_server_selected(
    screen: ServerSelectorScreen,
    http_client: _SyncHttpClient,
    qtbot,
) -> None:
    screen.load_servers()
    qtbot.waitUntil(lambda: screen._worker is None, timeout=3000)

    screen._list_widget.setCurrentRow(0)

    assert screen._start_button.isEnabled() is True


def test_start_button_disabled_after_deselection(
    screen: ServerSelectorScreen,
    http_client: _SyncHttpClient,
    qtbot,
) -> None:
    screen.load_servers()
    qtbot.waitUntil(lambda: screen._worker is None, timeout=3000)

    screen._list_widget.setCurrentRow(0)
    assert screen._start_button.isEnabled() is True

    screen._list_widget.setCurrentRow(-1)
    assert screen._start_button.isEnabled() is False


def test_empty_server_list_shows_no_servers_message(
    qtbot,
) -> None:
    client = _SyncHttpClient(guilds=[])
    screen = ServerSelectorScreen(http=client)
    qtbot.addWidget(screen)

    screen.load_servers()
    qtbot.waitUntil(lambda: screen._worker is None, timeout=3000)

    assert screen.error_text == "Доступных серверов нет"
    assert screen._start_button.isEnabled() is False


@pytest.mark.parametrize(
    "error,expected_substring",
    [
        (DiscordAuthError(body=""), "авторизации"),
        (DiscordForbiddenError(body=""), "запрещён"),
        (DiscordServerError(status=500, body=""), "сервера discord"),
        (DiscordTimeoutError("timeout"), "время ожидания"),
        (DiscordNetworkError("network"), "сети"),
    ],
)
def test_error_shows_message_and_retry_button(
    qtbot,
    error: BaseException,
    expected_substring: str,
) -> None:
    client = _SyncHttpClient(error=error)
    screen = ServerSelectorScreen(http=client)
    qtbot.addWidget(screen)

    screen.load_servers()
    qtbot.waitUntil(lambda: screen._worker is None, timeout=3000)

    assert expected_substring in screen.error_text.lower()
    assert screen._retry_button.isVisibleTo(screen) is True


def test_retry_button_hidden_by_default(
    screen: ServerSelectorScreen,
) -> None:
    assert screen._retry_button.isVisibleTo(screen) is False


def test_retry_button_triggers_reload(
    qtbot,
) -> None:
    client = _SyncHttpClient(error=DiscordNetworkError("fail"))
    screen = ServerSelectorScreen(http=client)
    qtbot.addWidget(screen)

    screen.load_servers()
    qtbot.waitUntil(lambda: screen._worker is None, timeout=3000)
    assert screen._retry_button.isVisibleTo(screen) is True

    client.error = None
    client.guilds = _SAMPLE_GUILDS

    screen.show()
    qtbot.mouseClick(screen._retry_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: screen._worker is None, timeout=3000)

    assert screen._list_widget.count() == 3
    assert screen._retry_button.isVisibleTo(screen) is False
    assert screen.error_text == ""


def test_token_preserved_on_error(
    qtbot,
) -> None:
    client = _SyncHttpClient(error=DiscordNetworkError("fail"))
    screen = ServerSelectorScreen(http=client)
    qtbot.addWidget(screen)

    screen.load_servers()
    qtbot.waitUntil(lambda: screen._worker is None, timeout=3000)

    assert screen._http is client


def test_server_selected_signal_emitted_on_selection(
    screen: ServerSelectorScreen,
    http_client: _SyncHttpClient,
    qtbot,
) -> None:
    screen.load_servers()
    qtbot.waitUntil(lambda: screen._worker is None, timeout=3000)

    with qtbot.waitSignal(screen.server_selected, timeout=1000) as blocker:
        screen._list_widget.setCurrentRow(1)

    server = blocker.args[0]
    assert isinstance(server, Server)
    assert server.id == "444555666"
    assert server.name == "Сервер Бета"


def test_start_requested_signal_emitted_on_button_click(
    screen: ServerSelectorScreen,
    http_client: _SyncHttpClient,
    qtbot,
) -> None:
    screen.load_servers()
    qtbot.waitUntil(lambda: screen._worker is None, timeout=3000)

    screen._list_widget.setCurrentRow(2)

    with qtbot.waitSignal(screen.start_requested, timeout=1000) as blocker:
        qtbot.mouseClick(screen._start_button, Qt.MouseButton.LeftButton)

    server = blocker.args[0]
    assert isinstance(server, Server)
    assert server.id == "777888999"
    assert server.name == "Gaming Guild"


def test_duplicate_load_servers_ignored(
    qtbot,
) -> None:
    client = _BlockingHttpClient(guilds=_SAMPLE_GUILDS)
    screen = ServerSelectorScreen(http=client)
    qtbot.addWidget(screen)

    screen.load_servers()
    qtbot.waitUntil(client.entered.is_set, timeout=3000)

    screen.load_servers()

    assert len(client.calls) == 1

    client.release.set()
    qtbot.waitUntil(lambda: screen._worker is None, timeout=3000)
