from __future__ import annotations

import httpx
import pytest

from discord_message_purger.application.session import Session
from discord_message_purger.application.token_manager import (
    AuthResult,
    TokenManager,
)
from discord_message_purger.infrastructure.http_client import DiscordHttpClient
from discord_message_purger.infrastructure.rate_limiter import RateLimiter


def _make_manager(
    handler,
    *,
    session: Session | None = None,
    rate_limiter: RateLimiter | None = None,
) -> tuple[TokenManager, Session, list[httpx.Request]]:

    captured: list[httpx.Request] = []

    def _wrapped(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return handler(request)

    transport = httpx.MockTransport(_wrapped)
    httpx_client = httpx.Client(
        base_url="https://discord.com/api/v10", transport=transport
    )
    sess = session if session is not None else Session()
    rl = rate_limiter if rate_limiter is not None else RateLimiter(
        sleep_fn=lambda _s: None
    )
    discord_client = DiscordHttpClient(
        token_provider=lambda: sess.token,
        rate_limiter=rl,
        client=httpx_client,
    )
    manager = TokenManager(http=discord_client, session=sess)
    return manager, sess, captured


def test_validate_and_store_success_writes_token_and_user_id() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "user-42", "username": "x"})

    manager, sess, _ = _make_manager(handler)
    result = manager.validate_and_store("real-token")

    assert result == AuthResult.ok(user_id="user-42")
    assert sess.token == "real-token"
    assert sess.authenticated_user_id == "user-42"


def test_validate_and_store_sends_authorization_header_without_prefix() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "u1"})

    manager, _, captured = _make_manager(handler)
    manager.validate_and_store("plain-token")

    assert len(captured) == 1
    request = captured[0]
    assert request.method == "GET"
    assert request.url.path == "/api/v10/users/@me"
    assert request.headers.get("Authorization") == "plain-token"


def test_http_401_returns_invalid_token_and_rolls_back_session() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "401: Unauthorized"})

    manager, sess, _ = _make_manager(handler)
    result = manager.validate_and_store("bad-token")

    assert result.status == "invalid_token"
    assert result.user_id is None
    assert sess.token is None
    assert sess.authenticated_user_id is None


@pytest.mark.parametrize("status", [400, 403, 404, 418, 500, 502, 503])
def test_other_http_codes_return_network_error(status: int) -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="boom")

    manager, sess, _ = _make_manager(handler)
    result = manager.validate_and_store("token")

    assert result.status == "network_error"
    assert "token" not in (result.error_message or "")
    assert sess.token is None
    assert sess.authenticated_user_id is None


def test_timeout_returns_network_error() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout")

    manager, sess, _ = _make_manager(handler)
    result = manager.validate_and_store("t")

    assert result.status == "network_error"
    assert sess.token is None
    assert sess.authenticated_user_id is None


def test_network_error_returns_network_error() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated connect error")

    manager, sess, _ = _make_manager(handler)
    result = manager.validate_and_store("t")

    assert result.status == "network_error"
    assert sess.token is None
    assert sess.authenticated_user_id is None


def test_http_200_with_invalid_json_returns_storage_error() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"not a json at all",
            headers={"content-type": "text/plain"},
        )

    manager, sess, _ = _make_manager(handler)
    result = manager.validate_and_store("token")

    assert result.status == "storage_error"
    assert sess.token is None
    assert sess.authenticated_user_id is None


def test_http_200_without_id_returns_storage_error() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"username": "x"})

    manager, sess, _ = _make_manager(handler)
    result = manager.validate_and_store("token")

    assert result.status == "storage_error"
    assert sess.token is None
    assert sess.authenticated_user_id is None


def test_http_200_with_user_id_write_failure_returns_storage_error() -> None:

    class _FlakySession:
        def __init__(self) -> None:
            self.consent_granted = False
            self._token: str | None = None
            self._user_id: str | None = None
            self._reject_user_id_writes = False

        @property
        def token(self) -> str | None:
            return self._token

        @token.setter
        def token(self, value: str | None) -> None:
            self._token = value

        @property
        def authenticated_user_id(self) -> str | None:
            return self._user_id

        @authenticated_user_id.setter
        def authenticated_user_id(self, value: str | None) -> None:
            if self._reject_user_id_writes and value is not None:
                raise RuntimeError("simulated storage failure")
            self._user_id = value

        def __repr__(self) -> str:
            return "_FlakySession(token=***)"

    sess = _FlakySession()
    sess._reject_user_id_writes = True

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "u1"})

    captured: list[httpx.Request] = []

    def _wrapped(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return handler(request)

    transport = httpx.MockTransport(_wrapped)
    httpx_client = httpx.Client(
        base_url="https://discord.com/api/v10", transport=transport
    )
    rl = RateLimiter(sleep_fn=lambda _s: None)
    discord_client = DiscordHttpClient(
        token_provider=lambda: sess.token,
        rate_limiter=rl,
        client=httpx_client,
    )
    manager = TokenManager(http=discord_client, session=sess)  # type: ignore[arg-type]

    result = manager.validate_and_store("good-token")

    assert result.status == "storage_error"
    assert sess.token is None
    assert sess.authenticated_user_id is None


def test_repr_does_not_leak_token() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "u1"})

    manager, sess, _ = _make_manager(handler)
    secret = "super-secret-discord-token"
    manager.validate_and_store(secret)

    rendered_manager = repr(manager)
    rendered_session = repr(sess)
    assert secret not in rendered_manager
    assert secret not in rendered_session
    assert "***" in rendered_session


def test_error_messages_do_not_leak_token() -> None:

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            text="Internal error: Authorization=super-secret-discord-token",
        )

    manager, _, _ = _make_manager(handler)
    secret = "super-secret-discord-token"
    result = manager.validate_and_store(secret)

    assert result.status == "network_error"
    assert secret not in (result.error_message or "")
