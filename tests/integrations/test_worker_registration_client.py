"""The setup-time operator client (ADR 0030). Every call hits `httpx.MockTransport`."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from src.core.config import Settings
from src.core.errors import ConfigurationError, IntegrationError
from src.core.worker_dispatch_keys import DispatchSigningKey
from src.integrations.worker_registration_client import (
    VERIFY_KEY_PATH,
    OperatorSession,
    WorkerRegistrationClient,
    WorkerRegistrationError,
)

KEY = DispatchSigningKey.generate()
PASSWORD = "operator-pass-9f3"
SESSION = OperatorSession(token=SecretStr("session-tok"), org_id="acme")


class _Cloud:
    def __init__(self, **statuses: int) -> None:
        self.statuses = statuses
        self.requests: list[httpx.Request] = []
        self.kid = KEY.kid

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/v1/auth/login":
            status = self.statuses.get("login", 200)
            body = {"token": "session-tok", "org_id": "acme"} if status == 200 else {"x": PASSWORD}
            return httpx.Response(status, json=body)
        if path == VERIFY_KEY_PATH:
            status = self.statuses.get("verify", 200)
            body = {"kid": self.kid, "public_key": KEY.public_key_b64}
            return httpx.Response(status, json=body)
        if path == "/api/v1/workers":
            status = self.statuses.get("register", 201)
            body = {"worker_id": "wkr-1", "worker_secret": "cred-1", "org_id": "acme"}
            return httpx.Response(status, json=body)
        return httpx.Response(404)


def _client(
    tmp_path: Path, cloud: _Cloud, url: str = "https://cloud.example.com"
) -> WorkerRegistrationClient:
    settings = Settings(_env_file=None, audit_log_path=tmp_path / "a.jsonl", default_timeout_s=2.0)
    return WorkerRegistrationClient(
        url, settings=settings, transport=httpx.MockTransport(cloud.handler)
    )


def _reason(exc: IntegrationError) -> str:
    assert isinstance(exc.__cause__, WorkerRegistrationError)
    return str(exc.__cause__)


def test_the_happy_path_returns_session_key_and_registration(tmp_path: Path) -> None:
    cloud = _Cloud()
    with _client(tmp_path, cloud) as client:
        session = client.login("alice", SecretStr(PASSWORD))
        key = client.fetch_verify_key(session)
        registration = client.register_worker(session, "Alice PC")
    assert session.org_id == "acme"
    assert key.kid == KEY.kid
    assert registration.worker_id == "wkr-1"
    assert registration.credential.get_secret_value() == "cred-1"
    login_body = json.loads(cloud.requests[0].content)
    assert login_body == {"operator_id": "alice", "password": PASSWORD}
    assert cloud.requests[1].headers["Authorization"] == "Bearer session-tok"


def test_plain_http_to_a_remote_host_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="https://"):
        _client(tmp_path, _Cloud(), url="http://cloud.example.com")


def test_plain_http_to_localhost_is_allowed(tmp_path: Path) -> None:
    _client(tmp_path, _Cloud(), url="http://localhost:8000").close()


def test_a_rejected_login_is_named_by_status_never_by_body(tmp_path: Path) -> None:
    with _client(tmp_path, _Cloud(login=401)) as client, pytest.raises(IntegrationError) as caught:
        client.login("alice", SecretStr(PASSWORD))
    assert "HTTP 401" in _reason(caught.value)
    assert PASSWORD not in str(caught.value)


def test_a_login_without_a_token_is_refused(tmp_path: Path) -> None:
    cloud = _Cloud()
    cloud.handler = lambda request: httpx.Response(200, json={"org_id": "acme"})  # type: ignore[method-assign]
    with _client(tmp_path, cloud) as client, pytest.raises(IntegrationError) as caught:
        client.login("alice", SecretStr(PASSWORD))
    assert "no session" in _reason(caught.value)


def test_a_cloud_without_ed25519_is_explained(tmp_path: Path) -> None:
    with _client(tmp_path, _Cloud(verify=503)) as client, pytest.raises(IntegrationError) as caught:
        client.fetch_verify_key(SESSION)
    assert "does not sign crawl dispatches" in _reason(caught.value)


def test_other_verify_key_failures_are_named_by_status(tmp_path: Path) -> None:
    with _client(tmp_path, _Cloud(verify=403)) as client, pytest.raises(IntegrationError) as caught:
        client.fetch_verify_key(SESSION)
    assert "HTTP 403" in _reason(caught.value)


def test_a_key_that_does_not_match_its_kid_is_refused(tmp_path: Path) -> None:
    cloud = _Cloud()
    cloud.kid = "not-the-kid"
    with _client(tmp_path, cloud) as client, pytest.raises(IntegrationError) as caught:
        client.fetch_verify_key(SESSION)
    assert "does not match" in _reason(caught.value)


def test_a_malformed_key_is_refused(tmp_path: Path) -> None:
    cloud = _Cloud()
    cloud.handler = lambda request: httpx.Response(200, json={"kid": "k", "public_key": "@@"})  # type: ignore[method-assign]
    with _client(tmp_path, cloud) as client, pytest.raises(IntegrationError) as caught:
        client.fetch_verify_key(SESSION)
    assert "malformed" in _reason(caught.value)


def test_registration_is_attempted_exactly_once(tmp_path: Path) -> None:
    """A retried POST /workers could mint a worker nobody holds the credential for."""
    cloud = _Cloud(register=500)
    with _client(tmp_path, cloud) as client, pytest.raises(IntegrationError):
        client.register_worker(SESSION, "Alice PC")
    assert [r.url.path for r in cloud.requests] == ["/api/v1/workers"]


def test_an_incomplete_registration_response_is_refused(tmp_path: Path) -> None:
    cloud = _Cloud()
    cloud.handler = lambda request: httpx.Response(201, json={"worker_id": "wkr-1"})  # type: ignore[method-assign]
    with _client(tmp_path, cloud) as client, pytest.raises(IntegrationError) as caught:
        client.register_worker(SESSION, "Alice PC")
    assert "incomplete" in _reason(caught.value)


def test_the_password_never_reaches_a_log(tmp_path: Path, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    with _client(tmp_path, _Cloud(login=401)) as client, pytest.raises(IntegrationError):
        client.login("alice", SecretStr(PASSWORD))
    with _client(tmp_path, _Cloud()) as client:
        client.login("alice", SecretStr(PASSWORD))
    assert PASSWORD not in caplog.text
    client.authenticate()  # a no-op by design: nothing is held in settings
