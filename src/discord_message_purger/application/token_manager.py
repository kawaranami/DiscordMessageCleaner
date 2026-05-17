from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from discord_message_purger.application.session import Session
from discord_message_purger.domain.exceptions import (
    DiscordAuthError,
    DiscordHttpError,
    DiscordNetworkError,
    DiscordTimeoutError,
    RateLimitTooLongError,
)
from discord_message_purger.infrastructure.http_client import DiscordHttpClient


__all__ = ["AuthResult", "AuthStatus", "TokenManager"]


AuthStatus = Literal["ok", "invalid_token", "network_error", "storage_error"]


_VALIDATE_TIMEOUT_S: Final[float] = 10.0


_VALIDATE_PATH: Final[str] = "/users/@me"


@dataclass(frozen=True)
class AuthResult:

    status: AuthStatus
    user_id: str | None = None
    error_message: str | None = None


    @classmethod
    def ok(cls, user_id: str) -> "AuthResult":

        return cls(status="ok", user_id=user_id)

    @classmethod
    def invalid(cls, message: str | None = None) -> "AuthResult":

        return cls(
            status="invalid_token",
            error_message=message or "Invalid token",
        )

    @classmethod
    def network_error(cls, message: str) -> "AuthResult":

        return cls(status="network_error", error_message=message)

    @classmethod
    def storage_error(cls, message: str) -> "AuthResult":

        return cls(status="storage_error", error_message=message)


class TokenManager:

    def __init__(self, http: DiscordHttpClient, session: Session) -> None:
        self._http = http
        self._session = session

    def __repr__(self) -> str:
        return f"TokenManager(session={self._session!r})"

    def validate_and_store(self, token: str) -> AuthResult:

        previous_token = self._session.token
        previous_user_id = self._session.authenticated_user_id

        try:
            self._session.token = token
        except Exception as exc:  # noqa: BLE001 - intentionally broad.
            return AuthResult.storage_error(
                f"Failed to store token in session: {type(exc).__name__}"
            )

        try:
            response = self._http.get(_VALIDATE_PATH, timeout_s=_VALIDATE_TIMEOUT_S)
        except DiscordAuthError:
            self._restore(previous_token, previous_user_id)
            return AuthResult.invalid()
        except DiscordTimeoutError:
            self._restore(previous_token, previous_user_id)
            return AuthResult.network_error(
                "Discord API request timed out"
            )
        except DiscordNetworkError:
            self._restore(previous_token, previous_user_id)
            return AuthResult.network_error(
                "Network error when calling Discord API"
            )
        except RateLimitTooLongError as exc:
            self._restore(previous_token, previous_user_id)
            return AuthResult.network_error(
                f"Discord API requested wait of {exc.retry_after_seconds:.0f}s"
            )
        except DiscordHttpError as exc:
            self._restore(previous_token, previous_user_id)
            return AuthResult.network_error(
                f"Discord API returned status {exc.status}"
            )

        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - httpx may raise various.
            self._restore(previous_token, previous_user_id)
            return AuthResult.storage_error(
                f"Failed to parse Discord API response: {type(exc).__name__}"
            )

        user_id = self._extract_user_id(payload)
        if user_id is None:
            self._restore(previous_token, previous_user_id)
            return AuthResult.storage_error(
                "Discord API did not return user ID"
            )

        try:
            self._session.authenticated_user_id = user_id
        except Exception as exc:  # noqa: BLE001 - Requirement 2.5.
            self._restore(previous_token, previous_user_id)
            return AuthResult.storage_error(
                f"Failed to store user ID: "
                f"{type(exc).__name__}"
            )

        return AuthResult.ok(user_id=user_id)


    def _restore(self, token: str | None, user_id: str | None) -> None:

        self._session.token = token
        self._session.authenticated_user_id = user_id

    @staticmethod
    def _extract_user_id(payload: object) -> str | None:

        if not isinstance(payload, dict):
            return None
        raw = payload.get("id")
        if raw is None:
            return None
        try:
            user_id = str(raw)
        except Exception:  # noqa: BLE001 - str(...) on weird objects.
            return None
        if not user_id:
            return None
        return user_id
