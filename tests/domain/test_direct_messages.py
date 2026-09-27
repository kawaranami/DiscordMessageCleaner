from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from discord_message_purger.domain.direct_messages import (
    DirectMessageDirectory,
    NotADirectMessageError,
    parse_channel_reference,
    parse_dm_channel,
    parse_dm_channels,
)
from discord_message_purger.domain.models import ChannelType


@dataclass
class _FakeResponse:

    _data: Any

    def json(self) -> Any:
        return self._data


class _FakeHttp:

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    def get(self, path: str, *, timeout_s: float, **_kwargs: Any) -> _FakeResponse:
        self.calls.append(path)
        return _FakeResponse(self._responses[path])


def _dm(channel_id: str, last_message_id: str | None = None, **user: Any) -> dict:
    return {
        "id": channel_id,
        "type": 1,
        "last_message_id": last_message_id,
        "recipients": [{"id": "42", **user}],
    }


def test_dm_uses_global_name_and_username() -> None:
    channel = parse_dm_channel(_dm("100", username="alice", global_name="Alice"))

    assert channel is not None
    assert channel.id == "100"
    assert channel.guild_id is None
    assert channel.type is ChannelType.DM
    assert channel.name == "Alice (@alice)"
    assert channel.is_direct_message


def test_dm_without_global_name_uses_username() -> None:
    channel = parse_dm_channel(_dm("100", username="bob", global_name=None))

    assert channel is not None
    assert channel.name == "bob"


def test_dm_without_recipients_is_unknown_user() -> None:
    channel = parse_dm_channel({"id": "100", "type": 1, "recipients": []})

    assert channel is not None
    assert channel.name == "Unknown user"


def test_group_dm_uses_explicit_name() -> None:
    channel = parse_dm_channel(
        {"id": "200", "type": 3, "name": "Weekend plans", "recipients": []}
    )

    assert channel is not None
    assert channel.type is ChannelType.GROUP_DM
    assert channel.name == "Group: Weekend plans"


def test_unnamed_group_dm_lists_members() -> None:
    channel = parse_dm_channel(
        {
            "id": "200",
            "type": 3,
            "name": None,
            "recipients": [
                {"id": "1", "username": "alice", "global_name": "Alice"},
                {"id": "2", "username": "bob", "global_name": None},
            ],
        }
    )

    assert channel is not None
    assert channel.name == "Group: Alice, bob"


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "not a dict",
        {"id": "1", "type": 0, "name": "general"},
        {"id": 123, "type": 1},
        {"type": 1},
    ],
)
def test_non_dm_payloads_are_rejected(raw: Any) -> None:
    assert parse_dm_channel(raw) is None


def test_channels_sorted_by_recent_activity() -> None:
    payload = [
        _dm("1", last_message_id="1000", username="old"),
        _dm("2", last_message_id=None, username="never"),
        _dm("3", last_message_id="99999999999999999999", username="newest"),
        {"id": "4", "type": 0, "name": "guild channel"},
    ]

    channels = parse_dm_channels(payload)

    assert [c.id for c in channels] == ["3", "1", "2"]


def test_parse_dm_channels_handles_garbage() -> None:
    assert parse_dm_channels({"message": "error"}) == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("123456789012345678", "123456789012345678"),
        ("  123456789012345678  ", "123456789012345678"),
        (
            "https://discord.com/channels/@me/123456789012345678",
            "123456789012345678",
        ),
        (
            "https://discord.com/channels/@me/123456789012345678/876543210987654321",
            "123456789012345678",
        ),
        (
            "https://ptb.discord.com/channels/@me/123456789012345678",
            "123456789012345678",
        ),
        ("", None),
        ("hello", None),
        ("12345", None),
        ("https://discord.com/channels/111111111111111111/222222222222222222", None),
    ],
)
def test_parse_channel_reference(text: str, expected: str | None) -> None:
    assert parse_channel_reference(text) == expected


def test_directory_lists_open_conversations() -> None:
    http = _FakeHttp({"/users/@me/channels": [_dm("1", username="alice")]})

    channels = DirectMessageDirectory(http).list_channels()  # type: ignore[arg-type]

    assert http.calls == ["/users/@me/channels"]
    assert [c.id for c in channels] == ["1"]


def test_directory_fetches_closed_conversation_by_id() -> None:
    http = _FakeHttp({"/channels/555": _dm("555", username="carol")})

    channel = DirectMessageDirectory(http).fetch_channel("555")  # type: ignore[arg-type]

    assert channel.id == "555"
    assert channel.name == "carol"


def test_directory_rejects_guild_channel_id() -> None:
    http = _FakeHttp(
        {"/channels/777": {"id": "777", "type": 0, "guild_id": "1", "name": "general"}}
    )

    with pytest.raises(NotADirectMessageError):
        DirectMessageDirectory(http).fetch_channel("777")  # type: ignore[arg-type]
