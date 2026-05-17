from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

from discord_message_purger.domain.exceptions import RateLimitTooLongError


_SLEEP_CHUNK_SECONDS: float = 0.1

_RETRY_AFTER_CLAMP_MAX_SECONDS: float = 60.0

_RETRY_AFTER_HARD_LIMIT_SECONDS: float = 600.0

_MIN_DELETE_INTERVAL_SECONDS: float = 0.25


@runtime_checkable
class _CancellableContext(Protocol):

    cancel_event: threading.Event


@dataclass
class ResetWindow:

    remaining: int = -1
    reset_at: float | None = None
    bucket: str | None = None


def _safe_float(value: Any) -> float | None:

    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _safe_int(value: Any) -> int | None:

    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class RateLimiter:

    def __init__(
        self,
        on_wait_started: Callable[[float, str], None] | None = None,
        on_wait_ended: Callable[[], None] | None = None,
        time_source: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._on_wait_started = on_wait_started
        self._on_wait_ended = on_wait_ended
        self._time_source = time_source
        self._sleep_fn = sleep_fn

        self._routes: dict[str, ResetWindow] = {}
        self._global_window: ResetWindow | None = None

        self._last_delete_completed_at: float | None = None


    def before_request(
        self,
        route_key: str,
        cancel_event: threading.Event | None = None,
    ) -> None:

        route_window = self._routes.get(route_key)
        if route_window is not None:
            wait_seconds = self._seconds_until_reset(route_window)
            if wait_seconds > 0.0:
                self._wait(wait_seconds, "reset", cancel_event)
                self._routes.pop(route_key, None)

        if self._global_window is not None:
            wait_seconds = self._seconds_until_reset(self._global_window)
            if wait_seconds > 0.0:
                self._wait(wait_seconds, "global reset", cancel_event)
                self._global_window = None

    def enforce_min_delete_interval(
        self,
        cancel_event: threading.Event | None = None,
    ) -> None:

        now = self._time_source()
        last = self._last_delete_completed_at
        if last is not None:
            elapsed = now - last
            wait_seconds = _MIN_DELETE_INTERVAL_SECONDS - elapsed
            if wait_seconds > 0.0:
                self.interruptible_sleep(wait_seconds, cancel_event)

        self._last_delete_completed_at = self._time_source()

    def after_response(self, route_key: str, response: Any) -> None:

        headers = self._extract_headers(response)
        if not headers:
            return

        remaining = _safe_int(headers.get("X-RateLimit-Remaining"))
        reset_after = _safe_float(headers.get("X-RateLimit-Reset-After"))
        bucket = headers.get("X-RateLimit-Bucket")
        is_global = self._header_truthy(headers.get("X-RateLimit-Global"))

        if remaining is None and reset_after is None and bucket is None:
            return

        now = self._time_source()
        reset_at: float | None = None
        if reset_after is not None and reset_after >= 0.0:
            reset_at = now + reset_after

        window = ResetWindow(
            remaining=remaining if remaining is not None else -1,
            reset_at=reset_at,
            bucket=bucket if isinstance(bucket, str) else None,
        )

        self._routes[route_key] = window

        if is_global:
            self._global_window = ResetWindow(
                remaining=window.remaining,
                reset_at=window.reset_at,
                bucket=window.bucket,
            )

    def handle_429(self, response: Any, ctx: _CancellableContext | None) -> None:

        retry_after = self._extract_retry_after(response)

        if retry_after > _RETRY_AFTER_HARD_LIMIT_SECONDS:
            raise RateLimitTooLongError(retry_after_seconds=retry_after)

        clamped = max(0.0, min(retry_after, _RETRY_AFTER_CLAMP_MAX_SECONDS))

        cancel_event = ctx.cancel_event if ctx is not None else None
        self._wait(clamped, "rate limit", cancel_event)


    def interruptible_sleep(
        self,
        seconds: float,
        cancel_event: threading.Event | None,
    ) -> None:

        if seconds is None or math.isnan(seconds) or seconds <= 0.0:
            return

        if cancel_event is not None and cancel_event.is_set():
            return

        deadline = self._time_source() + seconds
        while True:
            now = self._time_source()
            remaining = deadline - now
            if remaining <= 0.0:
                return
            if cancel_event is not None and cancel_event.is_set():
                return

            chunk = remaining if remaining < _SLEEP_CHUNK_SECONDS else _SLEEP_CHUNK_SECONDS
            self._sleep_fn(chunk)


    def _wait(
        self,
        seconds: float,
        reason: str,
        cancel_event: threading.Event | None,
    ) -> None:

        if seconds <= 0.0:
            return

        if self._on_wait_started is not None:
            self._on_wait_started(seconds, reason)
        try:
            self.interruptible_sleep(seconds, cancel_event)
        finally:
            if self._on_wait_ended is not None:
                self._on_wait_ended()

    def _seconds_until_reset(self, window: ResetWindow) -> float:

        if window.reset_at is None:
            return 0.0
        if window.remaining != 0:
            return 0.0
        delta = window.reset_at - self._time_source()
        return delta if delta > 0.0 else 0.0

    def _extract_headers(self, response: Any) -> dict[str, Any]:

        if response is None:
            return {}
        headers = getattr(response, "headers", None)
        if headers is None and isinstance(response, dict):
            headers = response.get("headers")
        if headers is None:
            return {}

        try:
            items = list(headers.items())
        except AttributeError:
            return {}
        return {str(k): v for k, v in items} | {
            str(k).lower(): v for k, v in items
        }

    @staticmethod
    def _header_truthy(value: Any) -> bool:

        if value is None:
            return False
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        return text not in {"", "false", "0"}

    def _extract_retry_after(self, response: Any) -> float:

        retry_after = self._retry_after_from_body(response)
        if retry_after is None:
            headers = self._extract_headers(response)
            retry_after = _safe_float(headers.get("Retry-After"))

        if retry_after is None or retry_after < 0.0:
            return 0.0
        return retry_after

    @staticmethod
    def _retry_after_from_body(response: Any) -> float | None:

        if response is None:
            return None

        body: Any = None

        json_attr = getattr(response, "json", None)
        if callable(json_attr):
            try:
                body = json_attr()
            except Exception:
                body = None
        elif json_attr is not None:
            body = json_attr

        if body is None and isinstance(response, dict):
            raw = response.get("json")
            if callable(raw):
                try:
                    body = raw()
                except Exception:
                    body = None
            else:
                body = raw

        if not isinstance(body, dict):
            return None

        return _safe_float(body.get("retry_after"))


__all__ = ["RateLimiter", "ResetWindow"]
