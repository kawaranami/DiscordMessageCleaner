# Feature: discord-message-purger, Property 29: Excessive wait → operation ERROR, prior progress preserved

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from discord_message_purger.application.operation_context import OperationContext
from discord_message_purger.domain.exceptions import RateLimitTooLongError
from discord_message_purger.domain.models import (
    LogEntryStatus,
    OperationLogEntry,
)
from discord_message_purger.domain.operation_log import OperationLog
from discord_message_purger.infrastructure.rate_limiter import RateLimiter


_ADD_EVENT_TO_STATUS: dict[str, LogEntryStatus] = {
    "add_success": LogEntryStatus.SUCCESS,
    "add_not_found": LogEntryStatus.NOT_FOUND,
    "add_error": LogEntryStatus.ERROR,
    "add_rejected": LogEntryStatus.REJECTED,
    "add_channel_skipped": LogEntryStatus.CHANNEL_SKIPPED,
}


def _make_entry(status: LogEntryStatus) -> OperationLogEntry:
    return OperationLogEntry(
        timestamp_local=datetime(2024, 1, 1, 12, 0, 0),
        status=status,
        channel_id="c1",
        message_id=None if status is LogEntryStatus.CHANNEL_SKIPPED else "m1",
        first_visible_char="x",
        message_timestamp=None
        if status is LogEntryStatus.CHANNEL_SKIPPED
        else datetime(2024, 1, 1, 11, 59, 0),
        http_status=None,
        error_type=None,
        description="",
    )


def _populate_log(events: list[str]) -> OperationLog:
    log = OperationLog()
    log.update_total(1000)
    for event in events:
        log.add(_make_entry(_ADD_EVENT_TO_STATUS[event]))
    return log


def _snapshot_log(log: OperationLog) -> tuple[Any, ...]:
    return (
        list(log.entries),
        list(log._processed_snapshots),
        log.scanned_messages,
        log.found_total,
        log.processed,
        log.skipped_other_authors,
        log.channels_skipped,
    )


def _build_429_response(retry_after: float, source: str) -> dict[str, Any]:
    if source == "body":
        return {"json": {"retry_after": retry_after}, "headers": {}}
    if source == "header":
        return {"headers": {"Retry-After": str(retry_after)}}
    return {
        "json": {"retry_after": retry_after},
        "headers": {"Retry-After": str(retry_after)},
    }


# Feature: discord-message-purger, Property 29: Excessive wait → operation ERROR, prior progress preserved
@pytest.mark.property
@given(
    events=st.lists(
        st.sampled_from(list(_ADD_EVENT_TO_STATUS.keys())),
        max_size=30,
    ),
    retry_after=st.floats(
        min_value=601.0,
        max_value=86400.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    source=st.sampled_from(["body", "header", "both"]),
)
@settings(max_examples=100, deadline=None)
def test_excessive_wait_raises_and_preserves_log(
    events: list[str],
    retry_after: float,
    source: str,
) -> None:
    log = _populate_log(events)
    pre_snapshot = _snapshot_log(log)

    sleep_calls: list[float] = []
    wait_started_calls: list[tuple[float, str]] = []
    wait_ended_calls: list[None] = []

    rate_limiter = RateLimiter(
        on_wait_started=lambda s, r: wait_started_calls.append((s, r)),
        on_wait_ended=lambda: wait_ended_calls.append(None),
        sleep_fn=lambda seconds: sleep_calls.append(seconds),
    )

    ctx = OperationContext()
    response = _build_429_response(retry_after, source)

    with pytest.raises(RateLimitTooLongError) as exc_info:
        rate_limiter.handle_429(response, ctx)

    assert exc_info.value.retry_after_seconds == retry_after, (
        "RateLimitTooLongError должен сохранять переданное значение "
        f"retry_after; ожидалось {retry_after!r}, получено "
        f"{exc_info.value.retry_after_seconds!r}"
    )

    assert sleep_calls == [], (
        "При retry_after > 600 RateLimiter не должен вызывать sleep_fn; "
        f"зафиксированы вызовы со значениями {sleep_calls!r}"
    )
    assert wait_started_calls == [], (
        "При retry_after > 600 не должен подниматься on_wait_started; "
        f"зафиксированы вызовы {wait_started_calls!r}"
    )
    assert wait_ended_calls == [], (
        "При retry_after > 600 не должен подниматься on_wait_ended; "
        f"зафиксировано {len(wait_ended_calls)} вызов(ов)"
    )

    post_snapshot = _snapshot_log(log)
    assert post_snapshot == pre_snapshot, (
        "OperationLog не должен изменяться после RateLimitTooLongError;"
        f" до: {pre_snapshot!r}, после: {post_snapshot!r}"
    )
