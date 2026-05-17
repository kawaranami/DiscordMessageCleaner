from __future__ import annotations

from datetime import datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from discord_message_purger.domain.models import (
    LogEntryStatus,
    OperationLogEntry,
)
from discord_message_purger.domain.operation_log import OperationLog


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
        channel_id="c1" if status is LogEntryStatus.CHANNEL_SKIPPED else "c1",
        message_id=None if status is LogEntryStatus.CHANNEL_SKIPPED else "m1",
        first_visible_char="x",
        message_timestamp=None
        if status is LogEntryStatus.CHANNEL_SKIPPED
        else datetime(2024, 1, 1, 11, 59, 0),
        http_status=None,
        error_type=None,
        description="",
    )


# Feature: discord-message-purger, Property 34: processed monotonically non-decreasing
@pytest.mark.property
@given(
    events=st.lists(
        st.sampled_from(
            [
                "add_success",
                "add_not_found",
                "add_error",
                "add_rejected",
                "add_channel_skipped",
                "update_total",
            ]
        ),
        max_size=50,
    )
)
@settings(max_examples=100)
def test_processed_monotonically_non_decreasing(events: list[str]) -> None:
    log = OperationLog()

    log.update_total(1000)
    prev_processed = log.processed

    for event in events:
        if event == "update_total":
            log.update_total(max(log.found_total, log.processed))
        else:
            status = _ADD_EVENT_TO_STATUS[event]
            log.add(_make_entry(status))

        assert log.processed >= prev_processed, (
            "Счётчик processed должен быть монотонно неубывающим: "
            f"было {prev_processed}, стало {log.processed} "
            f"после события {event!r}"
        )
        prev_processed = log.processed
