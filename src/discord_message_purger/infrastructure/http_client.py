from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Iterable, Mapping

import httpx

from discord_message_purger.application.operation_context import OperationContext
from discord_message_purger.domain.exceptions import (
    DiscordAuthError,
    DiscordForbiddenError,
    DiscordHttpError,
    DiscordNetworkError,
    DiscordNotFoundError,
    DiscordOtherClientError,
    DiscordRateLimitError,
    DiscordServerError,
    DiscordTimeoutError,
)
from discord_message_purger.infrastructure.rate_limiter import RateLimiter


__all__ = ["DiscordHttpClient", "build_route_key"]


_logger = logging.getLogger(__name__)


_DEFAULT_BASE_URL: str = "https://discord.com/api/v10"

_DEFAULT_USER_AGENT: str = "DiscordMessagePurger (desktop, 0.1.0)"

_MAJOR_SEGMENTS: frozenset[str] = frozenset({"channels", "guilds", "webhooks"})


def build_route_key(method: str, path: str) -> str:

    if "?" in path:
        path = path.split("?", 1)[0]

    parts: list[str] = []
    keep_next = False
    for segment in path.lstrip("/").split("/"):
        if not segment:
            continue
        if keep_next:
            parts.append(segment)
            keep_next = False
        elif segment in _MAJOR_SEGMENTS:
            parts.append(segment)
            keep_next = True
        elif segment.isdigit():
            parts.append("{id}")
        else:
            parts.append(segment)
    return f"{method.upper()} /" + "/".join(parts)


class DiscordHttpClient:

    def __init__(
        self,
        token_provider: Callable[[], str | None],
        rate_limiter: RateLimiter,
        ctx_provider: Callable[[], OperationContext | None] | None = None,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        user_agent: str = _DEFAULT_USER_AGENT,
        client: httpx.Client | None = None,
    ) -> None:
        self._token_provider = token_provider
        self._rate_limiter = rate_limiter
        self._ctx_provider = ctx_provider
        self._base_url = base_url
        self._user_agent = user_agent
        self._client = (
            client if client is not None else httpx.Client(base_url=base_url)
        )
        self._owns_client: bool = client is None


    def __repr__(self) -> str:
        return (
            f"DiscordHttpClient(base_url={self._base_url!r}, "
            f"user_agent={self._user_agent!r}, token=***)"
        )

    def close(self) -> None:

        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "DiscordHttpClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


    def get(
        self,
        path: str,
        *,
        timeout_s: float,
        params: Mapping[str, Any] | None = None,
        max_consecutive_429: int | None = None,
    ) -> httpx.Response:

        return self._request(
            "GET",
            path,
            timeout_s=timeout_s,
            params=params,
            max_consecutive_429=max_consecutive_429,
        )

    def delete(
        self,
        path: str,
        *,
        timeout_s: float,
        max_consecutive_429: int | None = None,
    ) -> httpx.Response:

        return self._request(
            "DELETE",
            path,
            timeout_s=timeout_s,
            max_consecutive_429=max_consecutive_429,
        )


    def _build_headers(self) -> dict[str, str]:

        headers: dict[str, str] = {
            "User-Agent": self._user_agent,
            "Accept": "application/json",
        }
        token = self._token_provider()
        if token:
            headers["Authorization"] = token
        return headers

    def _current_ctx(self) -> OperationContext | None:

        if self._ctx_provider is None:
            return None
        return self._ctx_provider()

    @staticmethod
    def _cancel_event_of(ctx: OperationContext | None) -> threading.Event | None:

        if ctx is None:
            return None
        return getattr(ctx, "cancel_event", None)

    def _request(
        self,
        method: str,
        path: str,
        *,
        timeout_s: float,
        params: Mapping[str, Any] | None = None,
        max_consecutive_429: int | None = None,
    ) -> httpx.Response:

        route_key = build_route_key(method, path)
        _logger.debug("HTTP %s %s (route=%s)", method, path, route_key)
        timeout = httpx.Timeout(timeout_s)

        consecutive_429 = 0

        while True:
            ctx = self._current_ctx()
            cancel_event = self._cancel_event_of(ctx)

            self._rate_limiter.before_request(route_key, cancel_event)

            headers = self._build_headers()

            try:
                response = self._client.request(
                    method=method,
                    url=path,
                    params=dict(params) if params is not None else None,
                    headers=headers,
                    timeout=timeout,
                )
            except httpx.TimeoutException as exc:
                raise DiscordTimeoutError(
                    f"Истёк таймаут {timeout_s:g} с при запросе {method} {path}"
                ) from exc
            except httpx.NetworkError as exc:
                raise DiscordNetworkError(
                    f"Сбой сети при запросе {method} {path}: {exc!r}"
                ) from exc

            self._rate_limiter.after_response(route_key, response)

            status = response.status_code

            if status == 429:
                if (
                    max_consecutive_429 is not None
                    and consecutive_429 >= max_consecutive_429
                ):
                    body_text = self._safe_text(response)
                    retry_after = self._rate_limiter._extract_retry_after(  # noqa: SLF001
                        response
                    )
                    raise DiscordRateLimitError(
                        retry_after_seconds=retry_after,
                        body=body_text,
                    )
                self._rate_limiter.handle_429(response, ctx)
                consecutive_429 += 1
                continue

            if 200 <= status < 300:
                _logger.debug("HTTP %s %s -> %d", method, path, status)
                return response

            body_text = self._safe_text(response)
            self._raise_for_status(status, body_text)

    @staticmethod
    def _raise_for_status(status: int, body: str) -> None:

        if status == 401:
            raise DiscordAuthError(body=body)
        if status == 403:
            raise DiscordForbiddenError(body=body)
        if status == 404:
            raise DiscordNotFoundError(body=body)
        if 500 <= status < 600:
            raise DiscordServerError(status=status, body=body)
        if 400 <= status < 500:
            raise DiscordOtherClientError(status=status, body=body)
        raise DiscordHttpError(
            status=status,
            body=body,
            message=f"Неожиданный HTTP-статус {status}",
        )

    @staticmethod
    def _safe_text(response: httpx.Response) -> str:

        try:
            return response.text
        except Exception:  # noqa: BLE001 — намеренно глушим всё.
            return ""
