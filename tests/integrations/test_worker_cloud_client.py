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
from src.core.errors import (
    ConfigurationError,
    IntegrationError,
    WorkerCredentialRejectedError,
)
from src.core.worker_dispatch_schemas import SignedDispatchAssignment, WorkerJobKind, WorkerJobPhase
from src.core.worker_dispatch_signing import issue_dispatch_assignment
from src.core.worker_templates import WorkerTemplate, WorkerTemplateReport
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


@pytest.mark.parametrize(
    "url",
    [
        "http://cloud.example.com",
        "http://127.0.0.1.evil.example",
        "ftp://cloud.example.com",
        "cloud.example.com",
        "http://[::1",
    ],
)
def test_a_non_https_base_url_is_refused_at_construction(tmp_path, url):
    """The worker credential and every assignment must never cross the network in clear.

    Fails on the pre-ADR-0028 client, which accepted any base URL.
    """
    settings = _settings(tmp_path, worker_cloud_api_base_url=url)
    with pytest.raises(ConfigurationError, match="WORKER_CLOUD_API_BASE_URL"):
        WorkerCloudClient(settings, transport=route_map({}))


@pytest.mark.parametrize(
    "url",
    [
        "https://cloud.example.com",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://[::1]:8000",
    ],
)
def test_https_and_loopback_http_base_urls_are_accepted(tmp_path, url):
    settings = _settings(tmp_path, worker_cloud_api_base_url=url)
    WorkerCloudClient(settings, transport=route_map({})).close()


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


def test_report_progress_posts_the_snapshot_fields_as_json(tmp_path):
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"id": "job-1", "status": "dispatched"})

    settings = _settings(tmp_path)
    client = WorkerCloudClient(settings, transport=httpx.MockTransport(handler))
    client.report_progress(
        "job-1", pages_crawled=3718, progress_pct=40.43, phase=WorkerJobPhase.CRAWLING
    )

    request = captured["request"]
    assert request.url.path == "/api/v1/workers/jobs/job-1/progress"
    assert json.loads(request.content) == {
        "pages_crawled": 3718,
        "progress_pct": 40.43,
        "phase": "crawling",
    }


def test_report_progress_sends_null_for_every_absent_field(tmp_path):
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"id": "job-1", "status": "dispatched"})

    settings = _settings(tmp_path)
    client = WorkerCloudClient(settings, transport=httpx.MockTransport(handler))
    client.report_progress("job-1", pages_crawled=None, progress_pct=None, phase=None)

    assert json.loads(captured["request"].content) == {
        "pages_crawled": None,
        "progress_pct": None,
        "phase": None,
    }


def test_report_progress_raises_integration_error_on_a_server_failure(tmp_path):
    settings = _settings(tmp_path)
    client = WorkerCloudClient(
        settings, transport=httpx.MockTransport(lambda _r: httpx.Response(503, text="down"))
    )
    with pytest.raises(IntegrationError):
        client.report_progress("job-1", pages_crawled=1, progress_pct=1.0, phase=None)


def test_close_is_idempotent(tmp_path):
    settings = _settings(tmp_path)
    client = WorkerCloudClient(settings, transport=route_map({}))
    client.close()
    client.close()


def test_context_manager_closes_on_exit(tmp_path):
    settings = _settings(tmp_path)
    with WorkerCloudClient(settings, transport=route_map({})) as client:
        assert isinstance(client, WorkerCloudClient)


# --- Heartbeat: templates live on this machine, not on the cloud host ----------


def test_heartbeat_posts_the_local_templates_with_their_descriptions(tmp_path):
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json={
                "worker_id": "wkr-alice-desktop",
                "last_seen_at": "2026-09-21T00:00:00Z",
                "templates": [{"name": "default-crawl", "description": ""}],
                "unrecognised_count": 0,
            },
        )

    client = WorkerCloudClient(_settings(tmp_path), transport=httpx.MockTransport(handler))
    client.heartbeat(
        WorkerTemplateReport(
            templates=(WorkerTemplate(name="default-crawl", description="Everything, once."),),
            unrecognised_count=2,
        )
    )

    request = captured["request"]
    assert request.url.path == "/api/v1/workers/heartbeat"
    assert json.loads(request.content) == {
        "templates": [{"name": "default-crawl", "description": "Everything, once."}],
        "unrecognised_count": 2,
    }
    assert request.headers["Authorization"] == "Bearer wkr-alice-desktop:worker-secret-value"


# --- A refused credential is not a transient failure ----------------------------


@pytest.mark.parametrize("code", [401, 403])
def test_a_refused_credential_is_raised_as_its_own_error_and_never_retried(tmp_path, code):
    """`IntegrationError` is in TRANSIENT_ERRORS; a 401 retried is a hot loop."""
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(code, text="nope")

    client = WorkerCloudClient(_settings(tmp_path), transport=httpx.MockTransport(handler))
    with pytest.raises(WorkerCredentialRejectedError):
        client.poll()
    assert len(attempts) == 1


def test_a_refused_credential_names_the_settings_to_check(tmp_path):
    client = WorkerCloudClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(lambda _r: httpx.Response(401, text="nope")),
    )
    with pytest.raises(WorkerCredentialRejectedError, match="WORKER_CREDENTIAL"):
        client.poll()


def test_a_refused_credential_never_echoes_the_secret(tmp_path):
    client = WorkerCloudClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(lambda _r: httpx.Response(401, text="nope")),
    )
    try:
        client.poll()
    except WorkerCredentialRejectedError as exc:
        assert "worker-secret-value" not in str(exc)


def test_a_server_side_outage_stays_an_integration_error(tmp_path):
    """503 means the cloud's own store is down, not that this worker is wrong.

    The distinction is what the daemon's loop acts on: an `IntegrationError`
    enters condition 10's bounded backoff and the daemon stays up, where a
    `WorkerCredentialRejectedError` ends it. The retry itself happens one
    layer up, in the poll loop — `BaseAPIClient.call()` does not retry an
    `httpx.HTTPStatusError`, which is pre-existing behaviour, not something
    this change alters.
    """
    client = WorkerCloudClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(lambda _r: httpx.Response(503, text="store unavailable")),
    )
    with pytest.raises(IntegrationError) as caught:
        client.poll()
    assert not isinstance(caught.value, WorkerCredentialRejectedError)


def test_upload_and_report_failure_also_stop_on_a_refused_credential(tmp_path):
    client = WorkerCloudClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(lambda _r: httpx.Response(401, text="nope")),
    )
    with pytest.raises(WorkerCredentialRejectedError):
        client.upload_bundle("job-1", b"PK\x03\x04")
    with pytest.raises(WorkerCredentialRejectedError):
        client.report_failure("job-1", "whatever")
    with pytest.raises(WorkerCredentialRejectedError):
        client.heartbeat(WorkerTemplateReport())


# --- fetch_url_list: the one inbound-bytes call (ADR 0023) ---------------------

_LIST_PATH = "/api/v1/workers/jobs/job-1/url-list"
_LIST_BODY = b"https://example.com/a\r\nhttps://example.com/b\r\n"


def test_fetch_url_list_returns_the_body_verbatim(tmp_path):
    """Byte-exact, because the caller hashes exactly what comes back."""
    settings = _settings(tmp_path)
    client = WorkerCloudClient(
        settings,
        transport=route_map({_LIST_PATH: httpx.Response(200, content=_LIST_BODY)}),
    )
    assert client.fetch_url_list("job-1") == _LIST_BODY


def test_fetch_url_list_does_not_re_encode_or_strip_a_bom(tmp_path):
    """A client that normalised the bytes would break the digest it is checked by."""
    body = b"\xef\xbb\xbfhttps://example.com/a\r\n"
    settings = _settings(tmp_path)
    client = WorkerCloudClient(
        settings, transport=route_map({_LIST_PATH: httpx.Response(200, content=body)})
    )
    assert client.fetch_url_list("job-1") == body


def test_fetch_url_list_sends_the_worker_bearer(tmp_path):
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        return httpx.Response(200, content=_LIST_BODY)

    client = WorkerCloudClient(_settings(tmp_path), transport=httpx.MockTransport(handler))
    client.fetch_url_list("job-1")
    assert seen == ["Bearer wkr-alice-desktop:worker-secret-value"]


@pytest.mark.parametrize("status", [401, 403])
def test_fetch_url_list_raises_credential_rejected_on_401_and_403(tmp_path, status):
    client = WorkerCloudClient(
        _settings(tmp_path),
        transport=route_map({_LIST_PATH: httpx.Response(status, text="nope")}),
    )
    with pytest.raises(WorkerCredentialRejectedError):
        client.fetch_url_list("job-1")


def test_fetch_url_list_raises_integration_error_on_a_missing_list(tmp_path):
    """A 404 must surface, not be mistaken for an empty list."""
    client = WorkerCloudClient(
        _settings(tmp_path),
        transport=route_map({_LIST_PATH: httpx.Response(404, text="no list")}),
    )
    with pytest.raises(IntegrationError):
        client.fetch_url_list("job-1")
