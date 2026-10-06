"""`RankunoCloudClient`: the import CLI's only network path (ADR 0034, audit condition 6)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator

import httpx
import pytest
from src.core.config import Settings
from src.core.errors import ConfigurationError, IntegrationError
from src.core.rate_limiter import RateLimiterRegistry
from src.integrations import base_client
from src.integrations.rankuno_cloud_client import CloudImportRejectedError, RankunoCloudClient

BASE = "https://cloud.example.com"
TOKEN = "session-token-VALUE"
PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def fresh_limiter_and_no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base_client, "_SHARED_LIMITERS", RateLimiterRegistry())
    # The retry policy's real backoff is seconds; the attempts are what is under test.
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda _seconds: None)


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)


def _client(
    handler: Callable[[httpx.Request], httpx.Response], settings: Settings, base: str = BASE
) -> RankunoCloudClient:
    return RankunoCloudClient(base, settings, transport=httpx.MockTransport(handler))


def _login_ok(request: httpx.Request) -> httpx.Response | None:
    if request.url.path == "/api/v1/auth/login":
        return httpx.Response(
            200,
            json={"token": TOKEN, "org_id": "org-a", "expires_at": "2026-10-08T00:00:00Z"},
        )
    return None


class TestBaseUrl:
    @pytest.mark.parametrize(
        "url", ["http://cloud.example.com", "ftp://cloud.example.com", "nonsense"]
    )
    def test_insecure_or_invalid_urls_are_refused(self, url: str, settings: Settings) -> None:
        with pytest.raises(ConfigurationError):
            RankunoCloudClient(url, settings)

    def test_plain_http_to_loopback_is_allowed(self, settings: Settings) -> None:
        assert (
            RankunoCloudClient("http://127.0.0.1:8000", settings).base_url
            == "http://127.0.0.1:8000"
        )

    def test_redirects_are_off_and_tls_is_verified(self, settings: Settings) -> None:
        client = RankunoCloudClient(BASE, settings)
        assert client._client.follow_redirects is False


class TestFlow:
    def test_login_then_import_sends_the_bearer_and_the_exact_bytes(
        self, settings: Settings
    ) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if (login := _login_ok(request)) is not None:
                return login
            return httpx.Response(
                201,
                json={
                    "id": "job-1",
                    "status": "succeeded",
                    "label": "x",
                    "pages": 3,
                    "duplicate": False,
                },
            )

        client = _client(handler, settings)
        assert client.login("alice", PASSWORD) == "org-a"
        result = client.import_bundle(b"\x1f\x8bBUNDLE")
        assert (result.job_id, result.pages, result.duplicate, result.org_id) == (
            "job-1",
            3,
            False,
            "org-a",
        )
        upload = seen[-1]
        assert upload.headers["Authorization"] == f"Bearer {TOKEN}"
        assert upload.headers["Content-Type"] == "application/gzip"
        assert upload.content == b"\x1f\x8bBUNDLE"

    def test_import_before_login_is_refused_locally(self, settings: Settings) -> None:
        client = _client(lambda _r: httpx.Response(500), settings)
        with pytest.raises(CloudImportRejectedError):
            client.import_bundle(b"x")

    def test_close_drops_the_token(self, settings: Settings) -> None:
        client = _client(lambda r: _login_ok(r) or httpx.Response(500), settings)
        client.login("alice", PASSWORD)
        client.close()
        with pytest.raises(CloudImportRejectedError):
            client.import_bundle(b"x")


class TestFailures:
    @pytest.mark.parametrize("status", [301, 302, 307, 308])
    def test_any_redirect_is_a_hard_error_and_is_not_followed(
        self, status: int, settings: Settings
    ) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(status, headers={"Location": "https://evil.example/collect"})

        client = _client(handler, settings)
        with pytest.raises(CloudImportRejectedError) as caught:
            client.login("alice", PASSWORD)
        assert "redirect" in caught.value.detail
        assert calls == [f"{BASE}/api/v1/auth/login"]

    @pytest.mark.parametrize("status", [401, 409, 413, 415, 422])
    def test_a_refusal_is_not_retried(self, status: int, settings: Settings) -> None:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if (login := _login_ok(request)) is not None:
                return login
            calls.append(1)
            return httpx.Response(status, json={"detail": "nope"})

        client = _client(handler, settings)
        client.login("alice", PASSWORD)
        with pytest.raises(CloudImportRejectedError) as caught:
            client.import_bundle(b"x")
        assert caught.value.status_code == status
        assert calls == [1]

    def test_a_sanitised_422_is_flattened_for_the_terminal(self, settings: Settings) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if (login := _login_ok(request)) is not None:
                return login
            detail = {
                "error": "the bundle failed validation",
                "error_count": 1,
                "locations": ["status"],
            }
            return httpx.Response(422, json={"detail": detail})

        client = _client(handler, settings)
        client.login("alice", PASSWORD)
        with pytest.raises(CloudImportRejectedError) as caught:
            client.import_bundle(b"x")
        assert caught.value.detail == "the bundle failed validation (1 problem(s): status)"

    def test_transient_failures_retry_with_identical_bytes(self, settings: Settings) -> None:
        bodies: list[bytes] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if (login := _login_ok(request)) is not None:
                return login
            bodies.append(request.content)
            if len(bodies) == 1:
                raise httpx.ConnectError("reset")
            if len(bodies) == 2:
                return httpx.Response(503, json={"detail": "db down"})
            return httpx.Response(
                200,
                json={
                    "id": "job-1",
                    "status": "succeeded",
                    "label": "x",
                    "pages": 1,
                    "duplicate": True,
                },
            )

        client = _client(handler, settings)
        client.login("alice", PASSWORD)
        assert client.import_bundle(b"SAME-BYTES").duplicate is True
        assert bodies == [b"SAME-BYTES"] * 3

    def test_exhausted_retries_surface_as_integration_error(self, settings: Settings) -> None:
        client = _client(lambda r: _login_ok(r) or httpx.Response(502), settings)
        client.login("alice", PASSWORD)
        with pytest.raises(IntegrationError):
            client.import_bundle(b"x")


@pytest.fixture
def captured(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    root = logging.getLogger("rankuno")
    root.addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG, logger="rankuno")
    try:
        yield caplog
    finally:
        root.removeHandler(caplog.handler)


def test_neither_the_password_nor_the_token_is_logged(
    settings: Settings, captured: pytest.LogCaptureFixture
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if (login := _login_ok(request)) is not None:
            return login
        raise httpx.ConnectError(f"failed sending {request.headers.get('Authorization')}")

    client = _client(handler, settings)
    client.login("alice", PASSWORD)
    with pytest.raises(IntegrationError) as caught:
        client.import_bundle(b"x")
    text = "\n".join(f"{r.getMessage()} {r.__dict__!r}" for r in captured.records) + str(
        caught.value
    )
    assert TOKEN not in text
    assert PASSWORD not in text
