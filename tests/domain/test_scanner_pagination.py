# Feature: discord-message-purger, Property 18: Pagination correctness
from __future__ import annotations

import json
import math
from urllib.parse import parse_qs, urlparse

import httpx
from hypothesis import given, settings
from hypothesis import strategies as st

from discord_message_purger.application.operation_context import OperationContext
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


_USER_ID = "user-123"
_CHANNEL_ID = "ch-1"
_GUILD_ID = "guild-1"


def _make_message_dict(msg_id: int, author_id: str = _USER_ID) -> dict:
    return {
        "id": str(msg_id),
        "channel_id": _CHANNEL_ID,
        "author": {"id": author_id},
        "content": f"Message {msg_id}",
        "timestamp": "2024-01-15T12:00:00+00:00",
    }


def _make_channel() -> Channel:
    return Channel(
        id=_CHANNEL_ID,
        guild_id=_GUILD_ID,
        name="test-channel",
        type=ChannelType.GUILD_TEXT,
    )


def _make_context() -> OperationContext:
    return OperationContext()


_n_messages_strategy = st.integers(min_value=0, max_value=300)


@settings(max_examples=150, deadline=None)
@given(n_messages=_n_messages_strategy)
def test_pagination_correctness(n_messages: int) -> None:
    start_id = 1000000 + n_messages
    all_messages = [
        _make_message_dict(start_id - i) for i in range(n_messages)
    ]

    request_log: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        before_param = params.get("before", [None])[0]
        limit_param = int(params.get("limit", ["100"])[0])

        request_log.append({
            "before": before_param,
            "limit": limit_param,
        })

        if before_param is not None:
            before_int = int(before_param)
            filtered = [
                m for m in all_messages if int(m["id"]) < before_int
            ]
        else:
            filtered = list(all_messages)

        page = filtered[:limit_param]

        return httpx.Response(
            200,
            content=json.dumps(page).encode(),
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

    channel = _make_channel()
    ctx = _make_context()

    yielded_messages = list(scanner.scan_channel(channel, _USER_ID, ctx))

    expected_requests = math.ceil(n_messages / 100) + 1 if n_messages > 0 else 1
    assert len(request_log) == expected_requests, (
        f"Ожидалось {expected_requests} запросов для {n_messages} сообщений, "
        f"получено {len(request_log)}"
    )

    if len(request_log) > 1:
        assert request_log[0]["before"] is None, (
            "Первый запрос не должен иметь параметр `before`"
        )

        for i in range(1, len(request_log)):
            before_value = request_log[i]["before"]
            assert before_value is not None, (
                f"Запрос #{i+1} должен иметь параметр `before`"
            )

            prev_before = request_log[i - 1]["before"]
            if prev_before is not None:
                prev_before_int = int(prev_before)
                prev_page = [
                    m for m in all_messages if int(m["id"]) < prev_before_int
                ][:100]
            else:
                prev_page = all_messages[:100]

            if prev_page:
                min_id_prev_page = min(int(m["id"]) for m in prev_page)
                before_int = int(before_value)
                assert before_int <= min_id_prev_page, (
                    f"Запрос #{i+1}: before={before_int} должен быть "
                    f"≤ min(id) предыдущей страницы={min_id_prev_page}"
                )

    yielded_ids = [m.id for m in yielded_messages]
    expected_ids = [m["id"] for m in all_messages]

    assert len(yielded_ids) == len(set(yielded_ids)), (
        f"Обнаружены дубликаты в выданных сообщениях: "
        f"{len(yielded_ids)} выдано, {len(set(yielded_ids))} уникальных"
    )

    assert set(yielded_ids) == set(expected_ids), (
        f"Множество выданных id ({len(yielded_ids)}) не совпадает "
        f"с ожидаемым ({len(expected_ids)}). "
        f"Пропущены: {set(expected_ids) - set(yielded_ids)}, "
        f"Лишние: {set(yielded_ids) - set(expected_ids)}"
    )

    if n_messages > 0:
        last_before = request_log[-1]["before"]
        if last_before is not None:
            last_before_int = int(last_before)
            remaining = [
                m for m in all_messages if int(m["id"]) < last_before_int
            ]
            assert len(remaining) == 0, (
                f"Последний запрос (before={last_before}) должен получить "
                f"пустую страницу, но осталось {len(remaining)} сообщений"
            )
