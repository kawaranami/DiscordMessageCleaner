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
            error_message=message or "Токен недействителен",
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
        except Exception as exc:  # noqa: BLE001 — намеренно широкий перехват.
            return AuthResult.storage_error(
                f"Не удалось сохранить токен в сессии: {type(exc).__name__}"
            )

        try:
            response = self._http.get(_VALIDATE_PATH, timeout_s=_VALIDATE_TIMEOUT_S)
        except DiscordAuthError:
            self._restore(previous_token, previous_user_id)
            return AuthResult.invalid()
        except DiscordTimeoutError:
            self._restore(previous_token, previous_user_id)
            return AuthResult.network_error(
                "Истёк таймаут ожидания ответа Discord_API"
            )
        except DiscordNetworkError:
            self._restore(previous_token, previous_user_id)
            return AuthResult.network_error(
                "Сбой сети при обращении к Discord_API"
            )
        except RateLimitTooLongError as exc:
            self._restore(previous_token, previous_user_id)
            return AuthResult.network_error(
                f"Discord_API запросил ожидание {exc.retry_after_seconds:.0f} с"
            )
        except DiscordHttpError as exc:
            self._restore(previous_token, previous_user_id)
            return AuthResult.network_error(
                f"Discord_API ответил кодом {exc.status}"
            )

        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 — httpx может бросить разное.
            self._restore(previous_token, previous_user_id)
            return AuthResult.storage_error(
                f"Не удалось разобрать ответ Discord_API: {type(exc).__name__}"
            )

        user_id = self._extract_user_id(payload)
        if user_id is None:
            self._restore(previous_token, previous_user_id)
            return AuthResult.storage_error(
                "Discord_API не вернул идентификатор пользователя"
            )

        try:
            self._session.authenticated_user_id = user_id
        except Exception as exc:  # noqa: BLE001 — Требование 2.5.
            self._restore(previous_token, previous_user_id)
            return AuthResult.storage_error(
                f"Не удалось сохранить идентификатор пользователя: "
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
        except Exception:  # noqa: BLE001 — str(...) на странных объектах.
            return None
        if not user_id:
            return None
        return user_id
