from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final

from discord_message_purger.domain.models import Channel, ChannelType

if TYPE_CHECKING:
    from discord_message_purger.infrastructure.http_client import (
        DiscordHttpClient,
    )


_LIST_TIMEOUT_S: Final[float] = 10.0

_DM_TYPE_VALUES: Final[frozenset[int]] = frozenset(
    {ChannelType.DM.value, ChannelType.GROUP_DM.value}
)

_SNOWFLAKE_RE: Final = re.compile(r"^\d{15,21}$")

_ME_LINK_RE: Final = re.compile(r"channels/@me/(\d{15,21})")

_UNKNOWN_USER: Final[str] = "Unknown user"
_UNNAMED_GROUP: Final[str] = "Unnamed group"


class NotADirectMessageError(ValueError):
    pass


def parse_channel_reference(text: str) -> str | None:

    value = text.strip()
    if not value:
        return None
    if _SNOWFLAKE_RE.match(value):
        return value
    match = _ME_LINK_RE.search(value)
    if match:
        return match.group(1)
    return None


def _user_label(user: Any) -> str | None:

    if not isinstance(user, dict):
        return None
    username = user.get("username")
    global_name = user.get("global_name")
    has_username = isinstance(username, str) and username.strip() != ""
    if isinstance(global_name, str) and global_name.strip():
        if has_username and username != global_name:
            return f"{global_name} (@{username})"
        return global_name
    if has_username:
        return username
    return None


def _short_user_name(user: Any) -> str | None:

    if not isinstance(user, dict):
        return None
    for key in ("global_name", "username"):
        value = user.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def parse_dm_channel(raw: Any) -> Channel | None:

    if not isinstance(raw, dict):
        return None

    type_value = raw.get("type")
    if not isinstance(type_value, int) or type_value not in _DM_TYPE_VALUES:
        return None

    channel_id = raw.get("id")
    if not isinstance(channel_id, str) or not channel_id:
        return None

    recipients = raw.get("recipients")
    if not isinstance(recipients, list):
        recipients = []

    if type_value == ChannelType.DM.value:
        label = _user_label(recipients[0]) if recipients else None
        name = label or _UNKNOWN_USER
    else:
        group_name = raw.get("name")
        if isinstance(group_name, str) and group_name.strip():
            name = group_name
        else:
            members = [
                member
                for member in (_short_user_name(r) for r in recipients)
                if member
            ]
            name = ", ".join(members) if members else _UNNAMED_GROUP
        name = f"Group: {name}"

    return Channel(
        id=channel_id,
        guild_id=None,
        name=name,
        type=ChannelType(type_value),
    )


def _activity_key(raw: dict) -> int:

    last_message_id = raw.get("last_message_id")
    if isinstance(last_message_id, str) and last_message_id.isdigit():
        return int(last_message_id)
    return 0


def parse_dm_channels(payload: Any) -> list[Channel]:

    if not isinstance(payload, list):
        return []

    raws = [raw for raw in payload if isinstance(raw, dict)]
    raws.sort(key=_activity_key, reverse=True)

    channels: list[Channel] = []
    for raw in raws:
        channel = parse_dm_channel(raw)
        if channel is not None:
            channels.append(channel)
    return channels


class DirectMessageDirectory:

    def __init__(self, http: "DiscordHttpClient") -> None:
        self._http = http

    def list_channels(self) -> list[Channel]:

        response = self._http.get("/users/@me/channels", timeout_s=_LIST_TIMEOUT_S)
        return parse_dm_channels(response.json())

    def fetch_channel(self, channel_id: str) -> Channel:

        response = self._http.get(
            f"/channels/{channel_id}", timeout_s=_LIST_TIMEOUT_S
        )
        channel = parse_dm_channel(response.json())
        if channel is None:
            raise NotADirectMessageError(
                f"Channel {channel_id} is not a direct message conversation"
            )
        return channel


__all__ = [
    "DirectMessageDirectory",
    "NotADirectMessageError",
    "parse_channel_reference",
    "parse_dm_channel",
    "parse_dm_channels",
]
