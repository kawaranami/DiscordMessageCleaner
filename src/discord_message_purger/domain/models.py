from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, IntEnum
from typing import Literal

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:

    class StrEnum(str, Enum):

        def __str__(self) -> str:
            return str(self.value)


ErrorType = Literal["network", "api", "validation", "auth"]


class ChannelType(IntEnum):

    GUILD_TEXT = 0
    DM = 1
    GUILD_VOICE = 2
    GROUP_DM = 3
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
    guild_id: str | None
    name: str
    type: ChannelType

    @property
    def is_direct_message(self) -> bool:
        return self.type in (ChannelType.DM, ChannelType.GROUP_DM)


@dataclass(frozen=True, slots=True)
class DirectMessagesTarget:

    channels: tuple[Channel, ...]

    @property
    def id(self) -> str:
        return "@me"

    @property
    def name(self) -> str:
        count = len(self.channels)
        if count == 1:
            return f"Direct messages: {self.channels[0].name}"
        return f"Direct messages ({count} conversations)"


CleanupTarget = Server | DirectMessagesTarget


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
    "DirectMessagesTarget",
    "CleanupTarget",
    "Message",
    "OperationLogEntry",
    "OperationSummary",
    "ErrorType",
]
