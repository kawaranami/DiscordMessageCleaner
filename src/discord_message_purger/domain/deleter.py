from __future__ import annotations

from datetime import datetime
from typing import Any

from discord_message_purger.domain.exceptions import (
    DiscordForbiddenError,
    DiscordNetworkError,
    DiscordNotFoundError,
    DiscordOtherClientError,
    DiscordServerError,
    DiscordTimeoutError,
)
from discord_message_purger.domain.models import (
    LogEntryStatus,
    Message,
    OperationLogEntry,
)
from discord_message_purger.domain.operation_log import OperationLog
from discord_message_purger.infrastructure.http_client import DiscordHttpClient
from discord_message_purger.infrastructure.rate_limiter import RateLimiter
from discord_message_purger.infrastructure.retry import with_retry_policy


class MessageDeleter:

    __slots__ = (
        "_http",
        "_operation_log",
        "_authenticated_user_id",
        "_rate_limiter",
        "_ctx",
    )

    def __init__(
        self,
        http: DiscordHttpClient,
        operation_log: OperationLog,
        authenticated_user_id: str,
        rate_limiter: RateLimiter | None = None,
        ctx: Any | None = None,
    ) -> None:
        self._http = http
        self._operation_log = operation_log
        self._authenticated_user_id = authenticated_user_id
        self._rate_limiter = rate_limiter
        self._ctx = ctx

    def delete(self, message: Message) -> OperationLogEntry:
        content_stripped = message.content.strip()
        if not content_stripped:
            fvc = "·"
        elif len(content_stripped) <= 30:
            fvc = content_stripped
        else:
            fvc = content_stripped[:27] + "..."
        timestamp_local = datetime.now()

        if message.author_id != self._authenticated_user_id:
            entry = OperationLogEntry(
                timestamp_local=timestamp_local,
                status=LogEntryStatus.REJECTED,
                channel_id=message.channel_id,
                message_id=message.id,
                first_visible_char=fvc,
                message_timestamp=message.timestamp,
                http_status=None,
                error_type="validation",
                description="author_id mismatch",
            )
            self._operation_log.add(entry)
            return entry

        if self._rate_limiter is not None:
            cancel_event = getattr(self._ctx, "cancel_event", None)
            self._rate_limiter.enforce_min_delete_interval(cancel_event)

        try:
            with_retry_policy(
                lambda: self._http.delete(
                    f"/channels/{message.channel_id}/messages/{message.id}",
                    timeout_s=10.0,
                ),
                self._ctx,
            )
            entry = OperationLogEntry(
                timestamp_local=timestamp_local,
                status=LogEntryStatus.SUCCESS,
                channel_id=message.channel_id,
                message_id=message.id,
                first_visible_char=fvc,
                message_timestamp=message.timestamp,
                http_status=204,
                error_type=None,
                description="",
            )
        except DiscordNotFoundError:
            entry = OperationLogEntry(
                timestamp_local=timestamp_local,
                status=LogEntryStatus.NOT_FOUND,
                channel_id=message.channel_id,
                message_id=message.id,
                first_visible_char=fvc,
                message_timestamp=message.timestamp,
                http_status=404,
                error_type=None,
                description="",
            )
        except DiscordForbiddenError:
            entry = OperationLogEntry(
                timestamp_local=timestamp_local,
                status=LogEntryStatus.ERROR,
                channel_id=message.channel_id,
                message_id=message.id,
                first_visible_char=fvc,
                message_timestamp=message.timestamp,
                http_status=403,
                error_type="api",
                description="Forbidden",
            )
        except DiscordOtherClientError as exc:
            entry = OperationLogEntry(
                timestamp_local=timestamp_local,
                status=LogEntryStatus.ERROR,
                channel_id=message.channel_id,
                message_id=message.id,
                first_visible_char=fvc,
                message_timestamp=message.timestamp,
                http_status=exc.status,
                error_type="api",
                description=f"HTTP {exc.status}",
            )
        except (DiscordServerError, DiscordNetworkError, DiscordTimeoutError) as exc:
            if isinstance(exc, DiscordServerError):
                error_type = "api"
                description = f"HTTP {exc.status} after retry exhaustion"
                http_status = exc.status
            elif isinstance(exc, DiscordNetworkError):
                error_type = "network"
                description = f"Network error after retry exhaustion: {exc!s}"[:500]
                http_status = None
            else:
                error_type = "network"
                description = f"Timeout after retry exhaustion: {exc!s}"[:500]
                http_status = None

            entry = OperationLogEntry(
                timestamp_local=timestamp_local,
                status=LogEntryStatus.ERROR,
                channel_id=message.channel_id,
                message_id=message.id,
                first_visible_char=fvc,
                message_timestamp=message.timestamp,
                http_status=http_status,
                error_type=error_type,
                description=description,
            )

        self._operation_log.add(entry)
        return entry


__all__ = ["MessageDeleter"]
