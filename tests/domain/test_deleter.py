from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from discord_message_purger.domain.deleter import MessageDeleter
from discord_message_purger.domain.models import (
    LogEntryStatus,
    Message,
)
from discord_message_purger.domain.operation_log import OperationLog
from discord_message_purger.infrastructure.http_client import DiscordHttpClient


class _NoOpRateLimiter:

    def before_request(self, route_key: str, cancel_event=None) -> None:
        pass

    def after_response(self, route_key: str, response) -> None:
        pass

    def handle_429(self, response, ctx=None) -> None:
        pass


def _make_http_client(
    handler,
    token: str = "test-token",
) -> DiscordHttpClient:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(
        base_url="https://discord.com/api/v10",
        transport=transport,
    )
    return DiscordHttpClient(
        token_provider=lambda: token,
        rate_limiter=_NoOpRateLimiter(),
        client=client,
    )


def _make_message(
    *,
    msg_id: str = "msg-1",
    channel_id: str = "ch-1",
    author_id: str = "user-1",
    content: str = "Hello world",
    timestamp: datetime | None = None,
) -> Message:
    if timestamp is None:
        timestamp = datetime(2024, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    return Message(
        id=msg_id,
        channel_id=channel_id,
        author_id=author_id,
        content=content,
        timestamp=timestamp,
    )


def _make_deleter(
    handler,
    authenticated_user_id: str = "user-1",
) -> tuple[MessageDeleter, OperationLog]:
    http = _make_http_client(handler)
    log = OperationLog()
    log.found_total = 1
    deleter = MessageDeleter(http, log, authenticated_user_id)
    return deleter, log


class TestDefenseInDepth:

    def test_mismatch_returns_rejected_entry(self) -> None:
        http_called = []

        def handler(request: httpx.Request) -> httpx.Response:
            http_called.append(request.url.path)
            return httpx.Response(204)

        deleter, log = _make_deleter(handler, authenticated_user_id="user-1")
        message = _make_message(author_id="other-user")

        entry = deleter.delete(message)

        assert entry.status == LogEntryStatus.REJECTED
        assert entry.description == "author_id mismatch"
        assert entry.http_status is None
        assert entry.error_type == "validation"
        assert http_called == []

    def test_mismatch_entry_has_correct_ids(self) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        deleter, log = _make_deleter(handler, authenticated_user_id="user-1")
        message = _make_message(
            msg_id="msg-42", channel_id="ch-99", author_id="intruder"
        )

        entry = deleter.delete(message)

        assert entry.channel_id == "ch-99"
        assert entry.message_id == "msg-42"

    def test_mismatch_entry_has_first_visible_char(self) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        deleter, log = _make_deleter(handler, authenticated_user_id="user-1")
        message = _make_message(author_id="other", content="Привет мир")

        entry = deleter.delete(message)

        assert entry.first_visible_char == "П"

    def test_mismatch_entry_added_to_log(self) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        deleter, log = _make_deleter(handler, authenticated_user_id="user-1")
        message = _make_message(author_id="other")

        deleter.delete(message)

        assert len(log.entries) == 1
        assert log.entries[0].status == LogEntryStatus.REJECTED


class TestDeleteSuccess:

    def test_204_returns_success_entry(self) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        deleter, log = _make_deleter(handler)
        message = _make_message()

        entry = deleter.delete(message)

        assert entry.status == LogEntryStatus.SUCCESS
        assert entry.http_status == 204
        assert entry.error_type is None

    def test_204_entry_has_correct_ids(self) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        deleter, log = _make_deleter(handler)
        message = _make_message(msg_id="msg-77", channel_id="ch-55")

        entry = deleter.delete(message)

        assert entry.channel_id == "ch-55"
        assert entry.message_id == "msg-77"

    def test_204_sends_correct_delete_request(self) -> None:
        seen_requests: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_requests.append((request.method, request.url.path))
            return httpx.Response(204)

        deleter, log = _make_deleter(handler)
        message = _make_message(msg_id="msg-123", channel_id="ch-456")

        deleter.delete(message)

        assert len(seen_requests) == 1
        method, path = seen_requests[0]
        assert method == "DELETE"
        assert path == "/api/v10/channels/ch-456/messages/msg-123"

    def test_204_entry_has_first_visible_char(self) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        deleter, log = _make_deleter(handler)
        message = _make_message(content="  \t\nTest content")

        entry = deleter.delete(message)

        assert entry.first_visible_char == "T"

    def test_204_entry_has_message_timestamp(self) -> None:
        ts = datetime(2023, 12, 25, 10, 30, 0, tzinfo=timezone.utc)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        deleter, log = _make_deleter(handler)
        message = _make_message(timestamp=ts)

        entry = deleter.delete(message)

        assert entry.message_timestamp == ts

    def test_204_entry_added_to_log(self) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        deleter, log = _make_deleter(handler)
        message = _make_message()

        deleter.delete(message)

        assert len(log.entries) == 1
        assert log.entries[0].status == LogEntryStatus.SUCCESS


class TestDeleteNotFound:

    def test_404_returns_not_found_entry(self) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Not Found")

        deleter, log = _make_deleter(handler)
        message = _make_message()

        entry = deleter.delete(message)

        assert entry.status == LogEntryStatus.NOT_FOUND
        assert entry.http_status == 404
        assert entry.error_type is None

    def test_404_entry_has_correct_ids(self) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Not Found")

        deleter, log = _make_deleter(handler)
        message = _make_message(msg_id="msg-gone", channel_id="ch-old")

        entry = deleter.delete(message)

        assert entry.channel_id == "ch-old"
        assert entry.message_id == "msg-gone"

    def test_404_entry_added_to_log(self) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Not Found")

        deleter, log = _make_deleter(handler)
        message = _make_message()

        deleter.delete(message)

        assert len(log.entries) == 1
        assert log.entries[0].status == LogEntryStatus.NOT_FOUND


class TestEmptyContent:

    def test_empty_content_uses_placeholder(self) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        deleter, log = _make_deleter(handler)
        message = _make_message(content="")

        entry = deleter.delete(message)

        assert entry.first_visible_char == "·"

    def test_whitespace_only_content_uses_placeholder(self) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        deleter, log = _make_deleter(handler)
        message = _make_message(content="   \t\n  ")

        entry = deleter.delete(message)

        assert entry.first_visible_char == "·"


class TestRetryPolicyExhausted:

    def test_500_after_retries_returns_error_entry(self) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        deleter, log = _make_deleter(handler)
        message = _make_message()

        entry = deleter.delete(message)

        assert entry.status == LogEntryStatus.ERROR
        assert entry.http_status == 500
        assert entry.error_type == "api"
        assert "500" in entry.description
        assert len(log.entries) == 1

    def test_timeout_after_retries_returns_error_entry(self) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("simulated timeout")

        deleter, log = _make_deleter(handler)
        message = _make_message()

        entry = deleter.delete(message)

        assert entry.status == LogEntryStatus.ERROR
        assert entry.http_status is None
        assert entry.error_type == "network"
        assert "аймаут" in entry.description or "timeout" in entry.description.lower()
        assert len(log.entries) == 1


class TestForbiddenError:

    def test_403_returns_error_entry_forbidden(self) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="Forbidden")

        deleter, log = _make_deleter(handler)
        message = _make_message()

        entry = deleter.delete(message)

        assert entry.status == LogEntryStatus.ERROR
        assert entry.http_status == 403
        assert entry.error_type == "api"
        assert entry.description == "Forbidden"
        assert len(log.entries) == 1

    def test_403_single_attempt_only(self) -> None:
        call_count = []

        def handler(request: httpx.Request) -> httpx.Response:
            call_count.append(1)
            return httpx.Response(403, text="Forbidden")

        deleter, log = _make_deleter(handler)
        message = _make_message()

        deleter.delete(message)

        assert len(call_count) == 1


class TestOtherClientErrors:

    def test_400_returns_error_entry(self) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text="Bad Request")

        deleter, log = _make_deleter(handler)
        message = _make_message()

        entry = deleter.delete(message)

        assert entry.status == LogEntryStatus.ERROR
        assert entry.http_status == 400
        assert entry.error_type == "api"
        assert "400" in entry.description
        assert len(log.entries) == 1

    def test_410_returns_error_entry(self) -> None:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(410, text="Gone")

        deleter, log = _make_deleter(handler)
        message = _make_message()

        entry = deleter.delete(message)

        assert entry.status == LogEntryStatus.ERROR
        assert entry.http_status == 410
        assert entry.error_type == "api"
        assert "410" in entry.description


class TestRetryAttemptCount:

    def test_500_makes_4_attempts(self) -> None:
        call_count = []

        def handler(request: httpx.Request) -> httpx.Response:
            call_count.append(1)
            return httpx.Response(500, text="Internal Server Error")

        deleter, log = _make_deleter(handler)
        message = _make_message()

        deleter.delete(message)

        assert len(call_count) == 4

    def test_network_error_makes_4_attempts(self) -> None:
        call_count = []

        def handler(request: httpx.Request) -> httpx.Response:
            call_count.append(1)
            raise httpx.ConnectError("simulated network error")

        deleter, log = _make_deleter(handler)
        message = _make_message()

        deleter.delete(message)

        assert len(call_count) == 4

    def test_success_after_transient_failure(self) -> None:
        call_count = []

        def handler(request: httpx.Request) -> httpx.Response:
            call_count.append(1)
            if len(call_count) <= 2:
                return httpx.Response(500, text="Server Error")
            return httpx.Response(204)

        deleter, log = _make_deleter(handler)
        message = _make_message()

        entry = deleter.delete(message)

        assert entry.status == LogEntryStatus.SUCCESS
        assert len(call_count) == 3


class TestRateLimiterIntegration:

    def test_enforce_min_delete_interval_called(self) -> None:
        enforce_calls = []

        class _TrackingRateLimiter:
            def enforce_min_delete_interval(self, cancel_event=None):
                enforce_calls.append(cancel_event)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        http = _make_http_client(handler)
        log = OperationLog()
        log.found_total = 1
        rate_limiter = _TrackingRateLimiter()
        deleter = MessageDeleter(http, log, "user-1", rate_limiter=rate_limiter)
        message = _make_message()

        deleter.delete(message)

        assert len(enforce_calls) == 1

    def test_enforce_not_called_for_rejected(self) -> None:
        enforce_calls = []

        class _TrackingRateLimiter:
            def enforce_min_delete_interval(self, cancel_event=None):
                enforce_calls.append(1)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        http = _make_http_client(handler)
        log = OperationLog()
        log.found_total = 1
        rate_limiter = _TrackingRateLimiter()
        deleter = MessageDeleter(http, log, "user-1", rate_limiter=rate_limiter)
        message = _make_message(author_id="other-user")

        deleter.delete(message)

        assert len(enforce_calls) == 0

    def test_cancel_event_passed_to_enforce(self) -> None:
        import threading

        enforce_calls = []

        class _TrackingRateLimiter:
            def enforce_min_delete_interval(self, cancel_event=None):
                enforce_calls.append(cancel_event)

        class _FakeCtx:
            def __init__(self):
                self.cancel_event = threading.Event()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        http = _make_http_client(handler)
        log = OperationLog()
        log.found_total = 1
        rate_limiter = _TrackingRateLimiter()
        ctx = _FakeCtx()
        deleter = MessageDeleter(
            http, log, "user-1", rate_limiter=rate_limiter, ctx=ctx
        )
        message = _make_message()

        deleter.delete(message)

        assert len(enforce_calls) == 1
        assert enforce_calls[0] is ctx.cancel_event
