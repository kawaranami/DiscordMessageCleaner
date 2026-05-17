from __future__ import annotations

import re
from datetime import datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from discord_message_purger.domain.formatting import format_local, parse_local


_TIMESTAMP_RE = re.compile(r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}$")


# Feature: discord-message-purger, Property 33: Date format and round-trip
@pytest.mark.property
@given(
    dt=st.datetimes(
        min_value=datetime(1, 1, 1, 0, 0),
        max_value=datetime(9999, 12, 31, 23, 59),
    )
)
@settings(max_examples=100)
def test_format_local_parse_local_roundtrip(dt: datetime) -> None:
    formatted = format_local(dt)

    assert _TIMESTAMP_RE.fullmatch(formatted) is not None, (
        "format_local должен возвращать строку формата YYYY/MM/DD HH:MM "
        f"с ведущими нулями, получено: {formatted!r} (вход: {dt!r})"
    )

    parsed = parse_local(formatted)
    expected = dt.replace(second=0, microsecond=0)
    assert parsed == expected, (
        "parse_local(format_local(dt)) должен совпадать с "
        "dt.replace(second=0, microsecond=0); "
        f"ожидалось {expected!r}, получено {parsed!r} "
        f"(вход: {dt!r}, промежуточная строка: {formatted!r})"
    )
