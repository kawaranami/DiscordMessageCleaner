# Feature: discord-message-purger, Property 17: Channel type filter
from __future__ import annotations

import json

import httpx
from hypothesis import given, settings
from hypothesis import strategies as st

from discord_message_purger.domain.models import Channel, ChannelType
from discord_message_purger.domain.operation_log import OperationLog
from discord_message_purger.domain.scanner import MessageScanner
from discord_message_purger.infrastructure.http_client import DiscordHttpClient


class _NoOpRateLimiter:

    def before_request(self, route_key: str, cancel_event=None) -> None:
        pass

    def after_response(self, route_key: str, response) -> None:
        pass

    def handle_429(self, response, ctx=None) -> None:
        pass

    def _extract_retry_after(self, response) -> float:
        return 1.0


def _channel_dict(channel_type: int, index: int) -> dict:
    return {
        "id": f"ch-{index}",
        "guild_id": "guild-1",
        "name": f"channel-{index}",
        "type": channel_type,
    }


_channel_types_strategy = st.lists(
    st.integers(min_value=0, max_value=15),
    min_size=0,
    max_size=30,
)

_ALLOWED_TYPES = {ChannelType.GUILD_TEXT.value, ChannelType.GUILD_ANNOUNCEMENT.value}


@settings(max_examples=150)
@given(channel_types=_channel_types_strategy)
def test_list_channels_filters_by_supported_types(
    channel_types: list[int],
) -> None:
    raw_channels = [
        _channel_dict(ch_type, i) for i, ch_type in enumerate(channel_types)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps(raw_channels).encode(),
            headers={"content-type": "application/json"},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(
        base_url="https://discord.com/api/v10",
        transport=transport,
    )
    http = DiscordHttpClient(
        token_provider=lambda: "test-token",
        rate_limiter=_NoOpRateLimiter(),
        client=client,
    )
    log = OperationLog()
    scanner = MessageScanner(http, log)

    result = scanner.list_channels("guild-1")

    for channel in result:
        assert channel.type.value in _ALLOWED_TYPES, (
            f"Канал {channel.id} имеет недопустимый тип {channel.type.value}, "
            f"ожидались только типы из {_ALLOWED_TYPES}"
        )

    expected_ids = {
        f"ch-{i}"
        for i, ch_type in enumerate(channel_types)
        if ch_type in _ALLOWED_TYPES
    }
    result_ids = {channel.id for channel in result}
    assert result_ids == expected_ids, (
        f"Множество возвращённых каналов {result_ids} не совпадает "
        f"с ожидаемым {expected_ids}"
    )

    forbidden_ids = {
        f"ch-{i}"
        for i, ch_type in enumerate(channel_types)
        if ch_type not in _ALLOWED_TYPES
    }
    assert result_ids.isdisjoint(forbidden_ids), (
        f"В результате присутствуют каналы с запрещёнными типами: "
        f"{result_ids & forbidden_ids}"
    )
