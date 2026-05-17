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
    OperationState,
)
from discord_message_purger.domain.operation_log import OperationLog
from discord_message_purger.domain.scanner import MessageScanner
from discord_message_purger.infrastructure.http_client import DiscordHttpClient


class _NoOpRateLimiter:

    def before_request(self, route_key, cancel_event=None):
        pass

    def after_response(self, route_key, response):
        pass

    def handle_429(self, response, ctx=None):
        pass


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
        min_size=0,
        max_size=30,
        unique_by=lambda ch: ch.id,
    )


def _make_scanner_with_mask(
    channels: list[Channel],
    forbidden_mask: list[bool],
) -> tuple[MessageScanner, OperationLog]:
    forbidden_ids: set[str] = set()
    for ch, is_forbidden in zip(channels, forbidden_mask):
        if is_forbidden:
            forbidden_ids.add(ch.id)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/channels/" in path and "/messages" in path:
            parts = path.split("/")
            ch_idx = parts.index("channels") + 1
            channel_id = parts[ch_idx]

            if channel_id in forbidden_ids:
                return httpx.Response(403, text="Forbidden")
            return httpx.Response(
                200,
                content=b"[]",
                headers={"content-type": "application/json"},
            )

        return httpx.Response(
            200,
            content=b"[]",
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
    return scanner, log


# Feature: discord-message-purger, Property 21: Completion accounts for every channel
@pytest.mark.property
@given(
    channels=_channels_strategy(),
    data=st.data(),
)
@settings(max_examples=100)
def test_completion_accounts_for_every_channel(
    channels: list[Channel],
    data: st.DataObject,
) -> None:
    n = len(channels)

    forbidden_mask = data.draw(
        st.lists(
            st.booleans(),
            min_size=n,
            max_size=n,
        )
    )

    scanner, log = _make_scanner_with_mask(channels, forbidden_mask)
    ctx = OperationContext()
    ctx.state = OperationState.RUNNING

    channels_processed = 0
    for ch in channels:
        messages = list(scanner.scan_channel(ch, "user-1", ctx))
        channels_processed += 1

    channels_skipped = log.channels_skipped

    channels_completed_normally = n - channels_skipped

    assert channels_completed_normally + channels_skipped == n, (
        f"Уравнение учёта нарушено: "
        f"обработано_нормально({channels_completed_normally}) + "
        f"пропущено({channels_skipped}) != {n}"
    )

    expected_skipped = sum(1 for m in forbidden_mask if m)
    assert channels_skipped == expected_skipped, (
        f"Ожидалось {expected_skipped} пропущенных каналов, "
        f"получено {channels_skipped}"
    )

    assert channels_processed == n, (
        f"Не все каналы были обработаны: ожидалось {n}, "
        f"обработано {channels_processed}"
    )

    ctx.state = OperationState.COMPLETED
    assert ctx.state == OperationState.COMPLETED, (
        f"Финальное состояние должно быть COMPLETED, получено {ctx.state}"
    )
