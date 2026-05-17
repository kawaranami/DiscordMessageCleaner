from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from discord_message_purger.application.operation_context import OperationContext
from discord_message_purger.domain.models import (
    Channel,
    ChannelType,
    LogEntryStatus,
)
from discord_message_purger.domain.operation_log import OperationLog
from discord_message_purger.domain.scanner import MessageScanner
from discord_message_purger.infrastructure.http_client import DiscordHttpClient
from discord_message_purger.infrastructure.rate_limiter import RateLimiter


def _channels_strategy() -> st.SearchStrategy[list[Channel]]:
    return st.lists(
        st.integers(min_value=1, max_value=9999).map(
            lambda i: Channel(
                id=str(i),
                guild_id="guild-1",
                name=f"канал-{i}",
                type=ChannelType.GUILD_TEXT,
            )
        ),
        min_size=1,
        max_size=10,
        unique_by=lambda ch: ch.id,
    )


class _NoOpRateLimiter:

    def before_request(self, route_key, cancel_event=None):
        pass

    def after_response(self, route_key, response):
        pass

    def handle_429(self, response, ctx=None):
        pass


def _make_scanner(
    channels: list[Channel],
    forbidden_mask: list[bool],
) -> tuple[MessageScanner, OperationLog, list[str]]:
    forbidden_ids: set[str] = set()
    for ch, is_forbidden in zip(channels, forbidden_mask):
        if is_forbidden:
            forbidden_ids.add(ch.id)

    visited: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/channels/" in path and "/messages" in path:
            parts = path.split("/")
            ch_idx = parts.index("channels") + 1
            channel_id = parts[ch_idx]
            visited.append(channel_id)

            if channel_id in forbidden_ids:
                return httpx.Response(403, text="Forbidden")
            return httpx.Response(200, content=b"[]", headers={"content-type": "application/json"})

        return httpx.Response(200, content=b"[]", headers={"content-type": "application/json"})

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
    return scanner, log, visited


# Feature: discord-message-purger, Property 19: HTTP 403 channel skip and log
@pytest.mark.property
@given(
    channels=_channels_strategy(),
    data=st.data(),
)
@settings(max_examples=100)
def test_http_403_channel_skip_and_log(
    channels: list[Channel],
    data: st.DataObject,
) -> None:
    forbidden_mask = data.draw(
        st.lists(
            st.booleans(),
            min_size=len(channels),
            max_size=len(channels),
        )
    )

    scanner, log, visited = _make_scanner(channels, forbidden_mask)
    ctx = OperationContext()

    for ch in channels:
        list(scanner.scan_channel(ch, "user-1", ctx))

    skipped_entries = [
        e for e in log.entries if e.status == LogEntryStatus.CHANNEL_SKIPPED
    ]
    expected_skipped_ids = {
        ch.id for ch, is_forbidden in zip(channels, forbidden_mask) if is_forbidden
    }
    actual_skipped_ids = {e.channel_id for e in skipped_entries}

    assert actual_skipped_ids == expected_skipped_ids, (
        f"Ожидались пропущенные каналы {expected_skipped_ids}, "
        f"получены {actual_skipped_ids}"
    )

    assert len(skipped_entries) == len(expected_skipped_ids), (
        f"Ожидалось {len(expected_skipped_ids)} записей CHANNEL_SKIPPED, "
        f"получено {len(skipped_entries)}"
    )

    visited_set = set(visited)
    all_channel_ids = {ch.id for ch in channels}
    assert visited_set == all_channel_ids, (
        f"Не все каналы были посещены: ожидались {all_channel_ids}, "
        f"посещены {visited_set}"
    )
