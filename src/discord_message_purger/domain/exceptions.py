from __future__ import annotations

import re
from typing import Final


_AUTH_HEADER_PATTERN: Final = re.compile(
    r"(?i)(authorization)\s*[:=]\s*\S+",
)
_AUTH_HEADER_MASK: Final = r"\1: ***"


def _mask_authorization(text: str) -> str:

    return _AUTH_HEADER_PATTERN.sub(_AUTH_HEADER_MASK, text)


class DiscordPurgerError(Exception):
    pass


class DiscordHttpError(DiscordPurgerError):

    def __init__(
        self,
        status: int,
        body: str = "",
        message: str | None = None,
    ) -> None:
        self.status: int = status
        self.body: str = body
        rendered = message if message is not None else f"HTTP {status}"
        super().__init__(rendered)

    def __repr__(self) -> str:
        safe_body = _mask_authorization(self.body)
        return (
            f"{type(self).__name__}(status={self.status!r}, "
            f"body={safe_body!r})"
        )


class DiscordAuthError(DiscordHttpError):

    def __init__(self, body: str = "", message: str | None = None) -> None:
        super().__init__(status=401, body=body, message=message)


class DiscordForbiddenError(DiscordHttpError):

    def __init__(self, body: str = "", message: str | None = None) -> None:
        super().__init__(status=403, body=body, message=message)


class DiscordNotFoundError(DiscordHttpError):

    def __init__(self, body: str = "", message: str | None = None) -> None:
        super().__init__(status=404, body=body, message=message)


class DiscordRateLimitError(DiscordHttpError):

    def __init__(
        self,
        retry_after_seconds: float,
        body: str = "",
        message: str | None = None,
    ) -> None:
        self.retry_after_seconds: float = retry_after_seconds
        rendered = (
            message
            if message is not None
            else f"HTTP 429 (retry_after={retry_after_seconds:.3f}s)"
        )
        super().__init__(status=429, body=body, message=rendered)

    def __repr__(self) -> str:
        safe_body = _mask_authorization(self.body)
        return (
            f"{type(self).__name__}("
            f"retry_after_seconds={self.retry_after_seconds!r}, "
            f"status={self.status!r}, body={safe_body!r})"
        )


class DiscordServerError(DiscordHttpError):

    def __init__(self, status: int, body: str = "", message: str | None = None) -> None:
        if not 500 <= status <= 599:
            raise ValueError(
                f"DiscordServerError is only valid for 5xx statuses, got {status}"
            )
        super().__init__(status=status, body=body, message=message)


class DiscordOtherClientError(DiscordHttpError):

    def __init__(self, status: int, body: str = "", message: str | None = None) -> None:
        if not 400 <= status <= 499:
            raise ValueError(
                f"DiscordOtherClientError is only valid for 4xx statuses, got {status}"
            )
        if status in {401, 403, 404, 429}:
            raise ValueError(
                "Use specialized subclasses for 401/403/404/429 statuses"
            )
        super().__init__(status=status, body=body, message=message)


class DiscordNetworkError(DiscordPurgerError):
    pass


class DiscordTimeoutError(DiscordPurgerError):
    pass


class RateLimitTooLongError(DiscordPurgerError):

    def __init__(self, retry_after_seconds: float, message: str | None = None) -> None:
        self.retry_after_seconds: float = retry_after_seconds
        rendered = (
            message
            if message is not None
            else (
                f"Discord requested wait of {retry_after_seconds:.3f}s, "
                "which exceeds the allowed threshold"
            )
        )
        super().__init__(rendered)


class MissingAuthenticatedUserError(DiscordPurgerError):
    pass


class IllegalStateTransition(DiscordPurgerError):

    def __init__(self, current: object, target: object, message: str | None = None) -> None:
        self.current = current
        self.target = target
        rendered = (
            message
            if message is not None
            else f"Illegal state transition: {current!r} -> {target!r}"
        )
        super().__init__(rendered)


__all__ = [
    "DiscordPurgerError",
    "DiscordHttpError",
    "DiscordAuthError",
    "DiscordForbiddenError",
    "DiscordNotFoundError",
    "DiscordRateLimitError",
    "DiscordServerError",
    "DiscordOtherClientError",
    "DiscordNetworkError",
    "DiscordTimeoutError",
    "RateLimitTooLongError",
    "MissingAuthenticatedUserError",
    "IllegalStateTransition",
]
