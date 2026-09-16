"""Tests for the worker daemon's outbound cloud API client (ADR 0015).

Every test runs against `httpx.MockTransport`, matching
`tests/integrations/test_http_fetcher.py`'s own convention: no socket is
ever opened.
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr
from src.core.config import Environment, Settings
from src.core.errors import ConfigurationError, IntegrationError
from src.core.worker_dispatch_schemas import SignedDispatchAssignment, WorkerJobKind
from src.core.worker_dispatch_signing import issue_dispatch_assignment
from src.integrations.worker_cloud_client import WorkerCloudClient

SECRET = SecretStr("unit-test-dispatch-signing-key")


def _settings(tmp_path, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "environment": Environment.DEVELOPMENT,
        "audit_log_path": tmp_path / "audit.jsonl",
        "worker_cloud_api_base_url": "https://cloud.example.com",
        "worker_id": "wkr-alice-desktop",
        "worker_credential": SecretStr("worker-secret-value"),
        "default_timeout_s": 2.0,
    }
    base.update(overrides)
    return Settings(**base)


def route_map(paths: dict[str, httpx.Response]) -> httpx.MockTransport:
    """A transport answering by exact path, 404 for anything unmapped."""

    def handler(request: httpx.Request) -> httpx.Response:
        return paths.get(request.url.path, httpx.Response(404, text="not found"))

    return httpx.MockTransport(handler)


def test_missing_base_url_raises_configuration_error(tmp_path):
    settings = _settings(tmp_path, worker_cloud_api_base_url=None)
    with pytest.raises(ConfigurationError):
        WorkerCloudClient(settings)


def test_authenticate_builds_worker_id_colon_secret_bearer(tmp_path):
    settings = _settings(tmp_path)
    client = WorkerCloudClient(settings, transport=route_map({}))
    client.authenticate()
    assert client._bearer == "wkr-alice-desktop:worker-secret-value"


def test_poll_sends_the_bearer_header_and_parses_no_assignment(tmp_path):
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"assignment": None})

    settings = _settings(tmp_path)
    client = WorkerCloudClient(settings, transport=httpx.MockTransport(handler))
    result = client.poll()

    assert result is None
    assert (
        captured["request"].headers["authorization"]
        == "Bearer wkr-alice-desktop:worker-secret-value"
    )
    assert captured["request"].url.path == "/api/v1/workers/dispatch/poll"


def test_poll_parses_a_returned_assignment(tmp_path):
    signed = issue_dispatch_assignment(
        job_id="job-1",
        worker_id="wkr-alice-desktop",
        org_id="acme",
        kind=WorkerJobKind.SCREAMING_FROG_CRAWL,
        seed_url="https://example.com/",
        template_name=None,
        correlation_id="corr-1",
        secret=SECRET,
        ttl_s=300.0,
    )
    body = {"assignment": json.loads(signed.model_dump_json())}

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    settings = _settings(tmp_path)
    client = WorkerCloudClient(settings, transport=httpx.MockTransport(handler))
    result = client.poll()

    assert isinstance(result, SignedDispatchAssignment)
    assert result.token == signed.token


def test_poll_raises_integration_error_on_a_server_failure(tmp_path):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    settings = _settings(tmp_path)
    client = WorkerCloudClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(IntegrationError):
        client.poll()


def test_upload_bundle_posts_the_raw_bytes_with_zip_content_type(tmp_path):
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"id": "job-1", "status": "succeeded"})

    settings = _settings(tmp_path)
    client = WorkerCloudClient(settings, transport=httpx.MockTransport(handler))
    client.upload_bundle("job-1", b"PK\x03\x04fakezipbytes")

    request = captured["request"]
    assert request.url.path == "/api/v1/workers/jobs/job-1/upload"
    assert request.headers["content-type"] == "application/zip"
    assert request.content == b"PK\x03\x04fakezipbytes"
    assert request.headers["authorization"] == "Bearer wkr-alice-desktop:worker-secret-value"


def test_report_failure_posts_the_error_as_json(tmp_path):
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"id": "job-1", "status": "failed"})

    settings = _settings(tmp_path)
    client = WorkerCloudClient(settings, transport=httpx.MockTransport(handler))
    client.report_failure("job-1", "screaming frog crashed")

    request = captured["request"]
    assert request.url.path == "/api/v1/workers/jobs/job-1/failed"
    assert json.loads(request.content) == {"error": "screaming frog crashed"}


def test_close_is_idempotent(tmp_path):
    settings = _settings(tmp_path)
    client = WorkerCloudClient(settings, transport=route_map({}))
    client.close()
    client.close()


def test_context_manager_closes_on_exit(tmp_path):
    settings = _settings(tmp_path)
    with WorkerCloudClient(settings, transport=route_map({})) as client:
        assert isinstance(client, WorkerCloudClient)
