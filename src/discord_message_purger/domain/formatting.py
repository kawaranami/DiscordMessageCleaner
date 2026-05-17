from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import OperationLogEntry


_EMPTY_PLACEHOLDER = "·"

_TIMESTAMP_FORMAT = "%Y/%m/%d %H:%M"


def first_visible_char(content: str) -> str:
    for ch in content:
        if not ch.isspace():
            return ch
    return _EMPTY_PLACEHOLDER


def format_local(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.strftime(_TIMESTAMP_FORMAT)


def parse_local(s: str) -> datetime:
    return datetime.strptime(s, _TIMESTAMP_FORMAT)


def format_log_line(
    entry: "OperationLogEntry", processed: int, total: int
) -> str:
    timestamp_str = format_local(entry.message_timestamp)
    return (
        f"{entry.first_visible_char} - {timestamp_str} "
        f"- [{processed}/{total}]"
    )
