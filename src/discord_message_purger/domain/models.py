from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Literal

ErrorType = Literal["network", "api", "validation", "auth"]


class ChannelType(IntEnum):

    GUILD_TEXT = 0
    GUILD_VOICE = 2
    GUILD_ANNOUNCEMENT = 5
    ANNOUNCEMENT_THREAD = 10
    PUBLIC_THREAD = 11
    PRIVATE_THREAD = 12
    GUILD_STAGE_VOICE = 13


class LogEntryStatus(StrEnum):

    SUCCESS = "Success"
    NOT_FOUND = "Not found"
    ERROR = "Error"
    REJECTED = "Rejected"
    CHANNEL_SKIPPED = "Channel skipped"


class OperationState(StrEnum):

    IDLE = "Idle"
    RUNNING = "Running"
    PAUSED = "Paused"
    COMPLETED = "Completed"
    CANCELED = "Canceled"
    ERROR = "Error"


@dataclass(frozen=True, slots=True)
class Server:

    id: str
    name: str
    icon_url: str | None = None


@dataclass(frozen=True, slots=True)
class Channel:

    id: str
    guild_id: str
    name: str
    type: ChannelType


@dataclass(frozen=True, slots=True)
class Message:

    id: str
    channel_id: str
    author_id: str
    content: str
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class OperationLogEntry:

    timestamp_local: datetime
    status: LogEntryStatus
    channel_id: str | None
    message_id: str | None
    first_visible_char: str
    message_timestamp: datetime | None
    http_status: int | None
    error_type: ErrorType | None
    description: str


@dataclass(frozen=True, slots=True)
class OperationSummary:

    success: int
    not_found: int
    errors: int
    rejected_other_author: int
    channels_skipped: int
    scanned_messages: int
    found_for_user: int


__all__ = [
    "ChannelType",
    "LogEntryStatus",
    "OperationState",
    "Server",
    "Channel",
    "Message",
    "OperationLogEntry",
    "OperationSummary",
    "ErrorType",
]
