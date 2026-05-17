# Feature: discord-message-purger, Property 8: Server list rendering preserves order and data
# Feature: discord-message-purger, Property 9: Single-server selection invariant
# Feature: discord-message-purger, Property 10: Start button enabled iff selection valid
# Feature: discord-message-purger, Property 11: Server-load failure preserves token and allows retry

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import pytest
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st
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


_server_name_strategy = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
    min_size=1,
    max_size=100,
)

_server_id_strategy = st.text(
    alphabet="0123456789",
    min_size=1,
    max_size=20,
)

_server_dict_strategy = st.builds(
    lambda name, sid: {"id": sid, "name": name},
    name=_server_name_strategy,
    sid=_server_id_strategy,
)

_server_list_strategy = st.lists(
    _server_dict_strategy,
    min_size=0,
    max_size=50,
)

_error_strategy = st.sampled_from([
    DiscordAuthError(body=""),
    DiscordForbiddenError(body=""),
    DiscordServerError(status=500, body=""),
    DiscordServerError(status=502, body=""),
    DiscordServerError(status=503, body=""),
    DiscordServerError(status=504, body=""),
    DiscordNetworkError("connection refused"),
    DiscordTimeoutError("timeout"),
])


@pytest.mark.property
@given(servers=_server_list_strategy)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_server_list_rendering_preserves_order_and_data(
    servers: list[dict], qtbot
) -> None:
    client = _SyncHttpClient(guilds=servers)
    screen = ServerSelectorScreen(http=client)
    qtbot.addWidget(screen)

    screen.load_servers()
    qtbot.waitUntil(lambda: screen._worker is None, timeout=5000)

    n = len(servers)
    assert screen._list_widget.count() == n, (
        f"Ожидалось {n} строк, получено {screen._list_widget.count()}"
    )

    for i, server_dict in enumerate(servers):
        item = screen._list_widget.item(i)
        assert item is not None, f"Элемент с индексом {i} отсутствует"

        text = item.text()
        name = server_dict["name"]
        sid = server_dict["id"]

        assert name in text, (
            f"Имя сервера {name!r} не найдено в строке {text!r} (индекс {i})"
        )
        assert sid in text, (
            f"ID сервера {sid!r} не найден в строке {text!r} (индекс {i})"
        )

        expected = f"{name} ({sid})"
        assert text == expected, (
            f"Строка {i}: ожидалось {expected!r}, получено {text!r}"
        )


@pytest.mark.property
@given(
    servers=st.lists(_server_dict_strategy, min_size=2, max_size=20),
    click_indices=st.lists(st.integers(min_value=0, max_value=100), min_size=1, max_size=30),
)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_single_server_selection_invariant(
    servers: list[dict], click_indices: list[int], qtbot
) -> None:
    client = _SyncHttpClient(guilds=servers)
    screen = ServerSelectorScreen(http=client)
    qtbot.addWidget(screen)

    screen.load_servers()
    qtbot.waitUntil(lambda: screen._worker is None, timeout=5000)

    n = screen._list_widget.count()
    assert n == len(servers)

    for raw_idx in click_indices:
        idx = raw_idx % n
        screen._list_widget.setCurrentRow(idx)

        selected = screen._list_widget.selectedItems()
        assert len(selected) <= 1, (
            f"После клика по индексу {idx} выбрано {len(selected)} элементов "
            f"(ожидалось ≤ 1)"
        )


@pytest.mark.property
@given(
    servers=st.lists(_server_dict_strategy, min_size=0, max_size=30),
    selected_index=st.one_of(st.none(), st.integers(min_value=0, max_value=29)),
)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_start_button_enabled_iff_selection_valid(
    servers: list[dict], selected_index: int | None, qtbot
) -> None:
    client = _SyncHttpClient(guilds=servers)
    screen = ServerSelectorScreen(http=client)
    qtbot.addWidget(screen)

    screen.load_servers()
    qtbot.waitUntil(lambda: screen._worker is None, timeout=5000)

    n = len(servers)

    if selected_index is not None and n > 0:
        actual_index = selected_index % n
        screen._list_widget.setCurrentRow(actual_index)
        expected_enabled = True
    else:
        screen._list_widget.setCurrentRow(-1)
        expected_enabled = False

    assert screen._start_button.isEnabled() == expected_enabled, (
        f"servers={n}, selected_index={selected_index}: "
        f"ожидалось isEnabled()={expected_enabled}, "
        f"получено {screen._start_button.isEnabled()}"
    )


@pytest.mark.property
@given(error=_error_strategy)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_server_load_failure_preserves_token_and_allows_retry(
    error: BaseException, qtbot
) -> None:
    client = _SyncHttpClient(error=error)
    screen = ServerSelectorScreen(http=client)
    qtbot.addWidget(screen)

    original_http = screen._http

    screen.load_servers()
    qtbot.waitUntil(lambda: screen._worker is None, timeout=5000)

    assert screen._http is original_http, (
        "HTTP-клиент был заменён после ошибки загрузки"
    )

    assert screen._retry_button.isVisibleTo(screen) is True, (
        f"Кнопка «Повторить» не видима после ошибки: {error!r}"
    )

    assert screen.error_text != "", (
        f"Текст ошибки пуст после ошибки: {error!r}"
    )
