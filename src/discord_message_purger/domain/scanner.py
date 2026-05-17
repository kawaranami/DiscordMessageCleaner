from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterator

from discord_message_purger.domain.exceptions import (
    DiscordForbiddenError,
    DiscordNetworkError,
    DiscordServerError,
    DiscordTimeoutError,
    MissingAuthenticatedUserError,
)
from discord_message_purger.domain.models import (
    Channel,
    ChannelType,
    LogEntryStatus,
    Message,
    OperationLogEntry,
)
from discord_message_purger.infrastructure.retry import with_retry_policy

if TYPE_CHECKING:
    from discord_message_purger.application.operation_context import (
        OperationContext,
    )
    from discord_message_purger.domain.operation_log import OperationLog
    from discord_message_purger.infrastructure.http_client import (
        DiscordHttpClient,
    )


_LIST_CHANNELS_TIMEOUT_S: float = 30.0

_FETCH_HISTORY_TIMEOUT_S: float = 30.0

_HISTORY_PAGE_SIZE: int = 100

_HISTORY_MAX_CONSECUTIVE_429: int = 5

_SUPPORTED_CHANNEL_TYPE_VALUES: frozenset[int] = frozenset(
    {
        ChannelType.GUILD_TEXT.value,
        ChannelType.GUILD_VOICE.value,
        ChannelType.GUILD_ANNOUNCEMENT.value,
        ChannelType.ANNOUNCEMENT_THREAD.value,
        ChannelType.PUBLIC_THREAD.value,
        ChannelType.PRIVATE_THREAD.value,
        ChannelType.GUILD_STAGE_VOICE.value,
    }
)

_HISTORY_TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    DiscordServerError,
    DiscordNetworkError,
    DiscordTimeoutError,
)


class MessageScanner:

    def __init__(
        self,
        http: "DiscordHttpClient",
        operation_log: "OperationLog",
    ) -> None:
        self._http = http
        self._operation_log = operation_log


    def list_channels(self, guild_id: str) -> list[Channel]:

        def _do_list() -> list[Channel]:
            response = self._http.get(
                f"/guilds/{guild_id}/channels",
                timeout_s=_LIST_CHANNELS_TIMEOUT_S,
            )
            payload = response.json()
            return self._parse_and_filter_channels(payload, guild_id)

        regular_channels = with_retry_policy(_do_list, None)

        active_threads = self._list_active_threads(guild_id)

        return regular_channels + active_threads

    def _list_active_threads(self, guild_id: str) -> list[Channel]:

        def _do_list() -> list[Channel]:
            response = self._http.get(
                f"/guilds/{guild_id}/threads/active",
                timeout_s=_LIST_CHANNELS_TIMEOUT_S,
            )
            payload = response.json()
            if isinstance(payload, dict):
                threads_payload = payload.get("threads", [])
            else:
                threads_payload = []
            return self._parse_and_filter_channels(threads_payload, guild_id)

        try:
            return with_retry_policy(_do_list, None)
        except Exception:
            return []

    def scan_channel(
        self,
        channel: "Channel",
        authenticated_user_id: str,
        ctx: "OperationContext",
    ) -> Iterator[Message]:

        if (
            authenticated_user_id is None
            or not isinstance(authenticated_user_id, str)
            or authenticated_user_id.strip() == ""
        ):
            raise MissingAuthenticatedUserError(
                "Authenticated user ID is missing or empty; "
                "channel scan will not run"
            )

        before: str | None = None

        while True:
            if ctx.check_cancelled():
                return
            if not ctx.wait_if_paused():
                return

            try:
                page = self._fetch_history_page(channel.id, before, ctx)
            except DiscordForbiddenError:
                self._operation_log.add(
                    OperationLogEntry(
                        timestamp_local=datetime.now().astimezone(),
                        status=LogEntryStatus.CHANNEL_SKIPPED,
                        channel_id=channel.id,
                        message_id=None,
                        first_visible_char="·",
                        message_timestamp=None,
                        http_status=403,
                        error_type=None,
                        description="access forbidden",
                    )
                )
                return

            if not page:
                return

            min_id_str: str | None = None
            for raw in page:
                message = self._parse_message(raw, channel.id)
                if message is None:
                    raw_id = raw.get("id") if isinstance(raw, dict) else None
                    if isinstance(raw_id, str):
                        min_id_str = self._smaller_snowflake(min_id_str, raw_id)
                    continue

                self._operation_log.scanned_messages += 1

                if message.author_id == authenticated_user_id:
                    yield message
                else:
                    self._operation_log.skipped_other_authors += 1

                min_id_str = self._smaller_snowflake(min_id_str, message.id)

            if min_id_str is None:
                return

            before = min_id_str


    def _fetch_history_page(
        self,
        channel_id: str,
        before: str | None,
        ctx: "OperationContext",
    ) -> list[dict]:

        params: dict[str, str | int] = {"limit": _HISTORY_PAGE_SIZE}
        if before is not None:
            params["before"] = before

        def _do_fetch() -> list[dict]:
            response = self._http.get(
                f"/channels/{channel_id}/messages",
                timeout_s=_FETCH_HISTORY_TIMEOUT_S,
                params=params,
                max_consecutive_429=_HISTORY_MAX_CONSECUTIVE_429,
            )
            payload = response.json()
            if not isinstance(payload, list):
                return []
            return [item for item in payload if isinstance(item, dict)]

        return with_retry_policy(_do_fetch, ctx)

    @staticmethod
    def _parse_message(raw: dict, channel_id: str) -> Message | None:

        msg_id = raw.get("id")
        if not isinstance(msg_id, str):
            return None

        author = raw.get("author")
        if not isinstance(author, dict):
            return None
        author_id = author.get("id")
        if not isinstance(author_id, str):
            return None

        content = raw.get("content")
        if not isinstance(content, str):
            content = ""

        raw_channel_id = raw.get("channel_id")
        msg_channel_id = (
            raw_channel_id if isinstance(raw_channel_id, str) else channel_id
        )

        timestamp_raw = raw.get("timestamp")
        timestamp_value: datetime
        if isinstance(timestamp_raw, str):
            try:
                timestamp_value = datetime.fromisoformat(
                    timestamp_raw.replace("Z", "+00:00")
                )
            except ValueError:
                timestamp_value = datetime.now(timezone.utc)
        else:
            timestamp_value = datetime.now(timezone.utc)

        return Message(
            id=msg_id,
            channel_id=msg_channel_id,
            author_id=author_id,
            content=content,
            timestamp=timestamp_value,
        )

    @staticmethod
    def _smaller_snowflake(current: str | None, candidate: str) -> str:

        if current is None:
            return candidate
        try:
            current_int = int(current)
            candidate_int = int(candidate)
        except (TypeError, ValueError):
            return candidate if candidate < current else current
        return candidate if candidate_int < current_int else current

    @staticmethod
    def _parse_and_filter_channels(
        payload: object,
        guild_id: str,
    ) -> list[Channel]:

        if not isinstance(payload, list):
            return []

        channels: list[Channel] = []
        for raw in payload:
            if not isinstance(raw, dict):
                continue

            type_value = raw.get("type")
            if not isinstance(type_value, int):
                continue
            if type_value not in _SUPPORTED_CHANNEL_TYPE_VALUES:
                continue

            channel_id = raw.get("id")
            name = raw.get("name")
            if not isinstance(channel_id, str) or not isinstance(name, str):
                continue

            raw_guild_id = raw.get("guild_id")
            channel_guild_id = (
                raw_guild_id if isinstance(raw_guild_id, str) else guild_id
            )

            channels.append(
                Channel(
                    id=channel_id,
                    guild_id=channel_guild_id,
                    name=name,
                    type=ChannelType(type_value),
                )
            )
        return channels


__all__ = ["MessageScanner"]
