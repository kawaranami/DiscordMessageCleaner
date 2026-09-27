from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from discord_message_purger.domain.direct_messages import NotADirectMessageError
from discord_message_purger.domain.exceptions import (
    DiscordNetworkError,
    DiscordNotFoundError,
)
from discord_message_purger.domain.models import (
    Channel,
    ChannelType,
    DirectMessagesTarget,
)
from discord_message_purger.ui.confirmation_dialog import ConfirmationDialog
from discord_message_purger.ui.dm_selector import DirectMessagesScreen


_ALICE = Channel(id="111111111111111111", guild_id=None, name="Alice (@alice)", type=ChannelType.DM)
_BOB = Channel(id="222222222222222222", guild_id=None, name="bob", type=ChannelType.DM)
_GROUP = Channel(id="333333333333333333", guild_id=None, name="Group: Squad", type=ChannelType.GROUP_DM)
_CLOSED = Channel(id="444444444444444444", guild_id=None, name="carol", type=ChannelType.DM)


class _FakeSource:

    def __init__(self, channels: list[Channel] | None = None) -> None:
        self.channels = list(channels or [])
        self.list_error: BaseException | None = None
        self.fetch_results: dict[str, Channel | BaseException] = {}
        self.list_calls = 0
        self.fetch_calls: list[str] = []

    def list_channels(self) -> list[Channel]:
        self.list_calls += 1
        if self.list_error is not None:
            raise self.list_error
        return list(self.channels)

    def fetch_channel(self, channel_id: str) -> Channel:
        self.fetch_calls.append(channel_id)
        result = self.fetch_results.get(channel_id)
        if isinstance(result, BaseException):
            raise result
        if result is None:
            raise DiscordNotFoundError(body="")
        return result


@pytest.fixture()
def source() -> _FakeSource:
    return _FakeSource([_ALICE, _BOB, _GROUP])


@pytest.fixture()
def screen(qtbot, source: _FakeSource) -> DirectMessagesScreen:
    widget = DirectMessagesScreen(source=source)
    qtbot.addWidget(widget)
    return widget


def _load(screen: DirectMessagesScreen, qtbot) -> None:
    screen.load_channels()
    qtbot.waitUntil(lambda: not screen.is_loading, timeout=3000)


def _item_for(screen: DirectMessagesScreen, channel: Channel):
    for index in range(screen.list_widget.count()):
        item = screen.list_widget.item(index)
        if item.data(Qt.ItemDataRole.UserRole) == channel:
            return item
    raise AssertionError(f"{channel} not in list")


def test_requires_http_or_source() -> None:
    with pytest.raises(ValueError):
        DirectMessagesScreen()


def test_loads_conversations_unchecked(screen, source, qtbot) -> None:
    _load(screen, qtbot)

    assert source.list_calls == 1
    assert screen.channels() == [_ALICE, _BOB, _GROUP]
    assert screen.selected_channels() == []
    assert not screen.start_button.isEnabled()
    assert screen.error_text == ""


def test_empty_list_shows_message(qtbot) -> None:
    screen = DirectMessagesScreen(source=_FakeSource([]))
    qtbot.addWidget(screen)
    _load(screen, qtbot)

    assert "No open direct message" in screen.error_text
    assert not screen.start_button.isEnabled()


def test_load_error_is_reported(qtbot) -> None:
    source = _FakeSource()
    source.list_error = DiscordNetworkError("down")
    screen = DirectMessagesScreen(source=source)
    qtbot.addWidget(screen)
    _load(screen, qtbot)

    assert "Network error" in screen.error_text


def test_clicking_row_toggles_selection_and_updates_button(screen, qtbot) -> None:
    _load(screen, qtbot)

    item = _item_for(screen, _BOB)
    screen.list_widget.itemClicked.emit(item)

    assert screen.selected_channels() == [_BOB]
    assert screen.start_button.isEnabled()
    assert "1 conversation" in screen.start_button.text()

    screen.list_widget.itemClicked.emit(item)
    assert screen.selected_channels() == []
    assert not screen.start_button.isEnabled()


def test_filter_and_select_all_visible(screen, qtbot) -> None:
    _load(screen, qtbot)

    screen._search_input.setText("ALI")
    assert not _item_for(screen, _ALICE).isHidden()
    assert _item_for(screen, _BOB).isHidden()
    assert _item_for(screen, _GROUP).isHidden()

    screen.select_all_visible()
    assert screen.selected_channels() == [_ALICE]

    screen._search_input.setText("")
    screen.select_all_visible()
    assert screen.selected_channels() == [_ALICE, _BOB, _GROUP]
    assert "3 conversations" in screen.start_button.text()

    screen.select_none()
    assert screen.selected_channels() == []


def test_start_emits_target_with_selected_channels(screen, qtbot) -> None:
    _load(screen, qtbot)
    _item_for(screen, _ALICE).setCheckState(Qt.CheckState.Checked)
    _item_for(screen, _GROUP).setCheckState(Qt.CheckState.Checked)

    with qtbot.waitSignal(screen.start_requested, timeout=1000) as blocker:
        screen.start_button.click()

    target = blocker.args[0]
    assert isinstance(target, DirectMessagesTarget)
    assert target.channels == (_ALICE, _GROUP)


def test_refresh_keeps_selection_and_manually_added(screen, source, qtbot) -> None:
    _load(screen, qtbot)
    _item_for(screen, _BOB).setCheckState(Qt.CheckState.Checked)

    source.fetch_results[_CLOSED.id] = _CLOSED
    screen.add_channel_reference(_CLOSED.id)
    qtbot.waitUntil(lambda: not screen.is_loading, timeout=3000)

    _load(screen, qtbot)

    assert set(screen.selected_channels()) == {_BOB, _CLOSED}
    assert _CLOSED in screen.channels()


def test_add_closed_conversation_by_link(screen, source, qtbot) -> None:
    _load(screen, qtbot)
    source.fetch_results[_CLOSED.id] = _CLOSED

    screen.add_channel_reference(
        f"https://discord.com/channels/@me/{_CLOSED.id}"
    )
    qtbot.waitUntil(lambda: not screen.is_loading, timeout=3000)

    assert source.fetch_calls == [_CLOSED.id]
    assert screen.channels()[0] == _CLOSED
    assert screen.selected_channels() == [_CLOSED]
    assert screen.error_text == ""


def test_add_existing_conversation_just_selects_it(screen, source, qtbot) -> None:
    _load(screen, qtbot)

    screen.add_channel_reference(_BOB.id)

    assert source.fetch_calls == []
    assert screen.selected_channels() == [_BOB]


@pytest.mark.parametrize(
    "error,expected",
    [
        (NotADirectMessageError("guild"), "not a direct message"),
        (DiscordNotFoundError(body=""), "not found"),
    ],
)
def test_add_reports_errors(screen, source, qtbot, error, expected) -> None:
    _load(screen, qtbot)
    source.fetch_results[_CLOSED.id] = error

    screen.add_channel_reference(_CLOSED.id)
    qtbot.waitUntil(lambda: not screen.is_loading, timeout=3000)

    assert expected in screen.error_text.lower()
    assert _CLOSED not in screen.channels()


def test_add_rejects_garbage_without_request(screen, source) -> None:
    screen.add_channel_reference("not a channel")

    assert source.fetch_calls == []
    assert "channel ID" in screen.error_text


def test_confirmation_dialog_for_direct_messages_requires_delete_word(qtbot) -> None:
    target = DirectMessagesTarget(channels=(_ALICE, _GROUP))
    dialog = ConfirmationDialog(target)
    qtbot.addWidget(dialog)

    assert "2 selected direct message conversations" in dialog._message_label.text()
    assert "Alice (@alice)" in dialog._message_label.text()
    assert not dialog.confirm_button.isEnabled()

    dialog.input_field.setText(_ALICE.name)
    assert not dialog.confirm_button.isEnabled()

    dialog.input_field.setText("DELETE")
    assert dialog.confirm_button.isEnabled()
    dialog.confirm_button.click()
    assert dialog.confirmed


def test_confirmation_dialog_truncates_long_lists(qtbot) -> None:
    channels = tuple(
        Channel(id=str(10**17 + i), guild_id=None, name=f"user{i}", type=ChannelType.DM)
        for i in range(15)
    )
    dialog = ConfirmationDialog(DirectMessagesTarget(channels=channels))
    qtbot.addWidget(dialog)

    text = dialog._message_label.text()
    assert "user9" in text
    assert "user10" not in text
    assert "and 5 more" in text
