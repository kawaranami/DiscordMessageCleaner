# Feature: discord-message-purger, Property 31: Log entry latency ≤ 200 ms

from __future__ import annotations

from datetime import datetime
from time import monotonic
from typing import Final

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from discord_message_purger.domain.models import (
    LogEntryStatus,
    OperationLogEntry,
)
from discord_message_purger.ui.progress_display import ProgressDisplay


_LATENCY_BUDGET_S: Final[float] = 0.2

_TOTAL_HEADROOM: Final[int] = 100_000


@st.composite
def operation_log_entries(draw: st.DrawFn) -> OperationLogEntry:

    status = draw(st.sampled_from(list(LogEntryStatus)))

    if draw(st.booleans()):
        message_timestamp: datetime | None = draw(
            st.datetimes(
                min_value=datetime(2020, 1, 1),
                max_value=datetime(2030, 1, 1),
            )
        )
    else:
        message_timestamp = None

    description = draw(
        st.text(
            alphabet=st.characters(
                min_codepoint=32,
                max_codepoint=126,
            ),
            max_size=100,
        )
    )

    return OperationLogEntry(
        timestamp_local=draw(
            st.datetimes(
                min_value=datetime(2020, 1, 1),
                max_value=datetime(2030, 1, 1),
            )
        ),
        status=status,
        channel_id=draw(
            st.one_of(st.none(), st.text(min_size=1, max_size=10))
        ),
        message_id=draw(
            st.one_of(st.none(), st.text(min_size=1, max_size=10))
        ),
        first_visible_char=draw(
            st.characters(min_codepoint=33, max_codepoint=126)
        ),
        message_timestamp=message_timestamp,
        http_status=draw(
            st.one_of(st.none(), st.integers(min_value=100, max_value=599))
        ),
        error_type=draw(
            st.one_of(
                st.none(),
                st.sampled_from(["network", "api", "validation", "auth"]),
            )
        ),
        description=description,
    )


# Feature: discord-message-purger, Property 31: Log entry latency ≤ 200 ms
@pytest.mark.property
@given(entries=st.lists(operation_log_entries(), min_size=1, max_size=50))
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_log_entry_latency_under_200ms(
    qtbot, entries: list[OperationLogEntry]
) -> None:

    widget = ProgressDisplay()
    qtbot.addWidget(widget)

    widget.update_total(_TOTAL_HEADROOM)

    text_before = widget.log_view.toPlainText()
    initial_line_count = (
        text_before.count("\n") + 1 if text_before else 0
    )

    for index, entry in enumerate(entries, start=1):
        t_signal = monotonic()
        widget.log_entry_signal.emit(entry)
        text_after = widget.log_view.toPlainText()
        t_visible = monotonic()

        latency = t_visible - t_signal

        current_line_count = (
            text_after.count("\n") + 1 if text_after else 0
        )
        expected_line_count = initial_line_count + index

        assert current_line_count == expected_line_count, (
            "После эмиссии записи журнал должен содержать "
            f"{expected_line_count} строк, фактически {current_line_count} "
            f"(итерация {index} из {len(entries)})"
        )

        assert latency <= _LATENCY_BUDGET_S, (
            "Задержка появления строки журнала превысила 200 мс: "
            f"{latency * 1000:.2f} мс на записи #{index} из "
            f"{len(entries)} (статус={entry.status.name}, "
            f"message_timestamp={'есть' if entry.message_timestamp else 'нет'})"
        )
