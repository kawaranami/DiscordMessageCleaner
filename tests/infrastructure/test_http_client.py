from __future__ import annotations

from typing import Any, Callable

import httpx
import pytest

from discord_message_purger.domain.exceptions import (
    DiscordAuthError,
    DiscordForbiddenError,
    DiscordHttpError,
    DiscordNetworkError,
    DiscordNotFoundError,
    DiscordOtherClientError,
    DiscordServerError,
    DiscordTimeoutError,
    RateLimitTooLongError,
)
from discord_message_purger.infrastructure.http_client import (
    DiscordHttpClient,
    build_route_key,
)
from discord_message_purger.infrastructure.rate_limiter import RateLimiter


class _RecordingRateLimiter:

    def __init__(self, *, retry_after: float = 0.0) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._retry_after = retry_after

    def before_request(self, route_key: str, cancel_event: Any = None) -> None:
        self.calls.append(("before_request", route_key))

    def after_response(self, route_key: str, response: Any) -> None:
        self.calls.append(("after_response", (route_key, response.status_code)))

    def handle_429(self, response: Any, ctx: Any) -> None:
        self.calls.append(("handle_429", response.status_code))


def _make_client(
    *,
    handler: Callable[[httpx.Request], httpx.Response],
    rate_limiter: Any | None = None,
    token: str | None = "test-token",
) -> tuple[DiscordHttpClient, _RecordingRateLimiter]:

    transport = httpx.MockTransport(handler)
    client = httpx.Client(
        base_url="https://discord.com/api/v10",
        transport=transport,
    )
    rl = rate_limiter if rate_limiter is not None else _RecordingRateLimiter()
    discord_client = DiscordHttpClient(
        token_provider=lambda: token,
        rate_limiter=rl,
        client=client,
    )
    return discord_client, rl


@pytest.mark.parametrize(
    "method, path, expected",
    [
        ("GET", "/users/@me", "GET /users/@me"),
        ("GET", "/users/@me/guilds", "GET /users/@me/guilds"),
        ("GET", "/guilds/123/channels", "GET /guilds/123/channels"),
        (
            "DELETE",
            "/channels/111/messages/222",
            "DELETE /channels/111/messages/{id}",
        ),
        (
            "GET",
            "/channels/111/messages",
            "GET /channels/111/messages",
        ),
        ("get", "/users/@me", "GET /users/@me"),
        (
            "GET",
            "/channels/111/messages?limit=100&before=999",
            "GET /channels/111/messages",
        ),
    ],
)
def test_build_route_key_handles_major_params(
    method: str, path: str, expected: str
) -> None:

    assert build_route_key(method, path) == expected


def test_repr_does_not_leak_token() -> None:

    client, _ = _make_client(
        handler=lambda req: httpx.Response(200, json={}),
        token="super-secret-token-value",
    )
    rendered = repr(client)
    assert "super-secret-token-value" not in rendered
    assert "token=***" in rendered


def test_authorization_header_has_no_prefix() -> None:

    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        for k, v in request.headers.items():
            seen_headers[k.lower()] = v
        return httpx.Response(200, json={"id": "u1"})

    client, _ = _make_client(handler=handler, token="raw-user-token")
    response = client.get("/users/@me", timeout_s=10.0)

    assert response.status_code == 200
    auth = seen_headers.get("authorization")
    assert auth == "raw-user-token", (
        "user-токен должен передаваться как есть, без префикса Bot/Bearer; "
        f"получено: {auth!r}"
    )


def test_no_authorization_header_when_token_provider_returns_none() -> None:

    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        for k, v in request.headers.items():
            seen_headers[k.lower()] = v
        return httpx.Response(401, json={"message": "401"})

    client, _ = _make_client(handler=handler, token=None)
    with pytest.raises(DiscordAuthError):
        client.get("/users/@me", timeout_s=10.0)

    assert "authorization" not in seen_headers


def test_token_provider_called_per_request() -> None:

    tokens: list[str] = ["token-A", "token-B"]
    seen_auth: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("Authorization", ""))
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    httpx_client = httpx.Client(
        base_url="https://discord.com/api/v10", transport=transport
    )

    state: dict[str, int] = {"i": 0}

    def provider() -> str:
        token = tokens[state["i"]]
        state["i"] += 1
        return token

    client = DiscordHttpClient(
        token_provider=provider,
        rate_limiter=_RecordingRateLimiter(),
        client=httpx_client,
    )

    client.get("/users/@me", timeout_s=10.0)
    client.get("/users/@me/guilds", timeout_s=10.0)

    assert seen_auth == ["token-A", "token-B"]


def test_calls_rate_limiter_before_and_after_request() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "X-RateLimit-Remaining": "4",
                "X-RateLimit-Reset-After": "1.0",
                "X-RateLimit-Bucket": "test",
            },
            json={"id": "u1"},
        )

    client, rl = _make_client(handler=handler)
    client.get("/users/@me", timeout_s=10.0)

    assert [name for (name, _) in rl.calls] == [
        "before_request",
        "after_response",
    ]
    assert rl.calls[0][1] == "GET /users/@me"
    assert rl.calls[1][1] == ("GET /users/@me", 200)


def test_429_invokes_handle_429_and_retries_request() -> None:

    responses: list[httpx.Response] = [
        httpx.Response(
            429,
            json={"retry_after": 0.0, "message": "rate limited"},
            headers={"Retry-After": "0"},
        ),
        httpx.Response(204, headers={}),
    ]
    sleep_calls: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    rl = RateLimiter(sleep_fn=lambda s: sleep_calls.append(s))
    transport = httpx.MockTransport(handler)
    httpx_client = httpx.Client(
        base_url="https://discord.com/api/v10", transport=transport
    )
    client = DiscordHttpClient(
        token_provider=lambda: "t",
        rate_limiter=rl,
        client=httpx_client,
    )

    response = client.delete("/channels/111/messages/222", timeout_s=10.0)
    assert response.status_code == 204
    assert responses == []


def test_429_with_excessive_retry_after_raises_rate_limit_too_long() -> None:

    sleep_calls: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"retry_after": 700.0, "message": "rate limited"},
            headers={"Retry-After": "700"},
        )

    rl = RateLimiter(sleep_fn=lambda s: sleep_calls.append(s))
    transport = httpx.MockTransport(handler)
    httpx_client = httpx.Client(
        base_url="https://discord.com/api/v10", transport=transport
    )
    client = DiscordHttpClient(
        token_provider=lambda: "t",
        rate_limiter=rl,
        client=httpx_client,
    )

    with pytest.raises(RateLimitTooLongError) as exc_info:
        client.get("/users/@me", timeout_s=10.0)

    assert exc_info.value.retry_after_seconds == 700.0
    assert sleep_calls == []


@pytest.mark.parametrize(
    "status, expected_exc",
    [
        (401, DiscordAuthError),
        (403, DiscordForbiddenError),
        (404, DiscordNotFoundError),
        (400, DiscordOtherClientError),
        (402, DiscordOtherClientError),
        (418, DiscordOtherClientError),
        (500, DiscordServerError),
        (502, DiscordServerError),
        (504, DiscordServerError),
    ],
)
def test_status_code_maps_to_typed_exception(
    status: int, expected_exc: type[DiscordHttpError]
) -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=f"error body for {status}")

    client, _ = _make_client(handler=handler)
    with pytest.raises(expected_exc) as exc_info:
        client.get("/users/@me", timeout_s=10.0)

    err = exc_info.value
    assert err.status == status
    assert f"error body for {status}" in err.body


def test_2xx_returns_response() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204, headers={})

    client, _ = _make_client(handler=handler)
    response = client.delete("/channels/1/messages/2", timeout_s=10.0)
    assert response.status_code == 204


def test_get_passes_query_params() -> None:

    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=[])

    client, _ = _make_client(handler=handler)
    client.get(
        "/channels/111/messages",
        timeout_s=30.0,
        params={"limit": 100, "before": "999"},
    )

    assert seen == {"limit": "100", "before": "999"}


def test_timeout_exception_translated_to_discord_timeout_error() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated read timeout")

    client, _ = _make_client(handler=handler)
    with pytest.raises(DiscordTimeoutError):
        client.get("/users/@me", timeout_s=10.0)


def test_connect_timeout_translated_to_discord_timeout_error() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated connect timeout")

    client, _ = _make_client(handler=handler)
    with pytest.raises(DiscordTimeoutError):
        client.get("/users/@me", timeout_s=10.0)


def test_network_error_translated_to_discord_network_error() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated network failure")

    client, _ = _make_client(handler=handler)
    with pytest.raises(DiscordNetworkError):
        client.get("/users/@me", timeout_s=10.0)


def test_close_does_not_close_externally_owned_client() -> None:

    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={}))
    httpx_client = httpx.Client(
        base_url="https://discord.com/api/v10", transport=transport
    )
    client = DiscordHttpClient(
        token_provider=lambda: "t",
        rate_limiter=_RecordingRateLimiter(),
        client=httpx_client,
    )

    client.close()
    response = httpx_client.get("/users/@me")
    assert response.status_code == 200
