"""Tests for the local HTTP API.

No test here performs real network I/O. `PageClassificationTool` is replaced
wholesale where a crawl would otherwise run, so what is under test is the
*transport*: admission control, status transitions, and the shape of what a
polling client receives.

The one thing worth stating up front: the API must never present an unfinished
job as a finished one, and must never leave a job in a state nothing will move
it out of. Most of these tests are about those two properties.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from src.api import server as server_module
from src.api.server import API_PREFIX, create_app
from src.core.state_store import DiskJobStore, JobStatus
from src.core.url_safety import UrlSafetyPolicy
from src.modules.seo.page_classifier.discovery import DiscoveryReport
from src.modules.seo.page_classifier.tool import (
    CrawlSummary,
    PageClassificationOutput,
)
from src.modules.seo.page_classifier.weights import SiteProfile, WeightProfileReport

PUBLIC_IP = "93.184.216.34"
SAFE_URL = "https://e.com/"


class StubResult:
    """Stands in for `ToolResult` without importing the generic machinery."""

    def __init__(self, ok: bool = True, data: object = None, error: str | None = None) -> None:
        """Record what the stubbed tool should report."""
        self.ok = ok
        self.data = data
        self.error = error


class StubTool:
    """A `PageClassificationTool` that returns instantly instead of crawling."""

    result: StubResult = StubResult(ok=False, error="not configured")

    def __init__(self, **_kwargs: object) -> None:
        """Accept and ignore the real tool's constructor arguments."""

    def run(self, _payload: object) -> StubResult:
        return type(self).result


@pytest.fixture
def stub_tool(monkeypatch):
    """Replace the real tool for the duration of a test."""
    monkeypatch.setattr(server_module, "PageClassificationTool", StubTool)
    return StubTool


@pytest.fixture
def store(tmp_path) -> DiskJobStore:
    return DiskJobStore(tmp_path / "jobs")


@pytest.fixture
def client(store):
    """A client whose SSRF resolver is deterministic, not DNS-dependent."""
    app = create_app(
        store=store,
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
    )
    with TestClient(app) as test_client:
        yield test_client


def post_job(client, url: str = SAFE_URL, **overrides: object):
    body = {"base_url": url, "max_pages": 5, "crawl_dom": False, **overrides}
    return client.post(f"{API_PREFIX}/jobs", json=body)


def run_job(client, store, url: str = SAFE_URL, **overrides: object) -> str:
    """Submit a job and wait for the worker to finish it.

    The wait is not test scaffolding around a slow system — it is the contract.
    `POST /jobs` returns `202` the moment the work is *accepted*, so a job is
    still `queued` or `running` when the response arrives. Asserting on its
    outcome immediately would be asserting on a race.

    Returns:
        The job id.

    Raises:
        AssertionError: If the job does not finish, which means the worker was
            never dispatched or died without recording a terminal status.
    """
    response = post_job(client, url, **overrides)
    assert response.status_code == 202, response.text
    job_id: str = response.json()["id"]

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if store.get(job_id).is_terminal:
            return job_id
        time.sleep(0.01)

    pytest.fail(f"job {job_id} never reached a terminal status")


class TestHealth:
    def test_reports_ok(self, client):
        response = client.get(f"{API_PREFIX}/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_reports_spare_capacity(self, client):
        body = client.get(f"{API_PREFIX}/health").json()
        assert body["active_jobs"] == 0
        assert body["max_concurrent_jobs"] >= 1


class TestAdmissionControl:
    def test_a_safe_url_is_accepted_with_202(self, client, stub_tool):
        """202, not 200: nothing has been crawled when this returns."""
        stub_tool.result = StubResult(ok=False, error="stopped")
        response = post_job(client)
        assert response.status_code == 202
        assert response.json()["id"]

    @pytest.mark.parametrize(
        "hostile",
        [
            "http://127.0.0.1:8000/",
            "http://localhost/",
            "http://[::1]/",
            "http://169.254.169.254/latest/meta-data/",
            "file:///etc/passwd",
        ],
    )
    def test_ssrf_targets_are_rejected_at_admission(self, client, hostile):
        """The reason this check exists at the door, not only in the crawl.

        `169.254.169.254` is the cloud metadata endpoint — the single most
        valuable SSRF target there is. A rejection must be a 400 the operator
        sees, not a job that fails quietly some milliseconds later.
        """
        assert post_job(client, hostile).status_code == 400

    def test_a_rejected_url_creates_no_job(self, client, store):
        post_job(client, "http://127.0.0.1/")
        assert store.list_jobs() == []

    def test_the_rejection_says_why(self, client):
        detail = post_job(client, "http://127.0.0.1/").json()["detail"]
        assert detail, "a 400 with no reason is unactionable"

    def test_a_malformed_body_is_a_422(self, client):
        assert client.post(f"{API_PREFIX}/jobs", json={"max_pages": 5}).status_code == 422

    def test_unknown_fields_are_rejected(self, client):
        """`StrictModel` forbids extras, so a typo'd field cannot be ignored."""
        response = post_job(client, surprise=1)
        assert response.status_code == 422


class TestConcurrencyCap:
    def test_excess_jobs_are_refused_with_429(self, store):
        """Each in-flight crawl holds its whole graph in memory."""
        app = create_app(
            store=store,
            url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
            max_concurrent_jobs=1,
        )
        state = app.state.api
        assert state.try_reserve("occupier") is True

        with TestClient(app) as client:
            response = post_job(client)
        assert response.status_code == 429

    def test_a_refused_job_is_not_left_pending(self, store):
        """A 429'd job must reach a terminal state, or a poller waits forever."""
        app = create_app(
            store=store,
            url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
            max_concurrent_jobs=1,
        )
        app.state.api.try_reserve("occupier")
        with TestClient(app) as client:
            post_job(client)

        records = store.list_jobs()
        assert len(records) == 1
        assert records[0].status is JobStatus.FAILED
        assert records[0].is_terminal

    def test_reserving_is_atomic(self, store):
        """Check-then-reserve in two steps would let both callers through."""
        app = create_app(store=store, max_concurrent_jobs=2)
        state = app.state.api
        assert [state.try_reserve(f"j{index}") for index in range(3)] == [True, True, False]

    def test_releasing_frees_a_slot(self, store):
        app = create_app(store=store, max_concurrent_jobs=1)
        state = app.state.api
        state.try_reserve("a")
        assert state.try_reserve("b") is False
        state.release("a")
        assert state.try_reserve("b") is True

    def test_releasing_an_unknown_job_is_harmless(self, store):
        """`_dispatch` releases in a `finally`; a double release must not raise."""
        state = create_app(store=store).state.api
        state.release("never-reserved")
        assert state.active_count == 0


class TestJobLifecycle:
    def test_a_successful_crawl_reaches_succeeded(self, client, store, stub_tool):
        stub_tool.result = StubResult(ok=True, data=_fake_output(truncated=False))
        job_id = run_job(client, store)
        assert store.get(job_id).status is JobStatus.SUCCEEDED

    def test_a_truncated_crawl_reaches_partial(self, client, store, stub_tool):
        """The UI must be able to say the crawl is incomplete."""
        stub_tool.result = StubResult(ok=True, data=_fake_output(truncated=True))
        job_id = run_job(client, store)
        assert store.get(job_id).status is JobStatus.PARTIAL

    def test_a_tool_failure_reaches_failed_with_a_reason(self, client, store, stub_tool):
        stub_tool.result = StubResult(ok=False, error="robots.txt disallowed /")
        job_id = run_job(client, store)
        record = store.get(job_id)
        assert record.status is JobStatus.FAILED
        assert record.error == "robots.txt disallowed /"

    def test_a_crashing_tool_still_reaches_a_terminal_state(self, client, store, monkeypatch):
        """The worker runs detached. An escaping exception would strand the job.

        It would stay `RUNNING` with nothing left to move it, and a polling UI
        would wait indefinitely for a result that is never coming.
        """

        class ExplodingTool:
            def __init__(self, **_kwargs: object) -> None:
                pass

            def run(self, _payload: object) -> object:
                raise RuntimeError("transport exploded")

        monkeypatch.setattr(server_module, "PageClassificationTool", ExplodingTool)
        job_id = run_job(client, store)

        record = store.get(job_id)
        assert record.status is JobStatus.FAILED
        assert "transport exploded" in (record.error or "")

    def test_a_finished_job_frees_its_slot(self, client, store, stub_tool):
        """A slot leaked on completion would cap the server at three crawls ever."""
        stub_tool.result = StubResult(ok=True, data=_fake_output(truncated=False))
        run_job(client, store)
        assert client.get(f"{API_PREFIX}/health").json()["active_jobs"] == 0


class TestReadingJobs:
    def test_an_unknown_job_is_404(self, client):
        assert client.get(f"{API_PREFIX}/jobs/nope").status_code == 404

    def test_a_missing_result_is_409_not_404(self, client, store):
        """404 would tell a polling client to give up on a live job.

        The record is created directly rather than through `POST`, so the job
        stays `running` instead of racing a worker to a terminal status.
        """
        job_id = store.create("seo.page_classifier", {"base_url": SAFE_URL}).id
        store.mark_running(job_id)

        response = client.get(f"{API_PREFIX}/jobs/{job_id}/result")
        assert response.status_code == 409

    def test_a_result_is_returned_once_finished(self, client, store, stub_tool):
        stub_tool.result = StubResult(ok=True, data=_fake_output(truncated=False))
        job_id = run_job(client, store)

        response = client.get(f"{API_PREFIX}/jobs/{job_id}/result")
        assert response.status_code == 200
        assert response.json()["base_url"] == SAFE_URL

    def test_the_job_list_omits_result_blobs(self, client, store, stub_tool):
        """Listing must stay cheap; a 20k result is ~16 MB."""
        stub_tool.result = StubResult(ok=True, data=_fake_output(truncated=False))
        run_job(client, store)

        listing = client.get(f"{API_PREFIX}/jobs").json()
        assert len(listing) == 1
        assert "result" not in listing[0]
        assert listing[0]["has_result"] is True

    def test_the_status_payload_carries_what_a_poller_needs(self, client, store, stub_tool):
        stub_tool.result = StubResult(ok=True, data=_fake_output(truncated=False))
        job_id = run_job(client, store)

        body = client.get(f"{API_PREFIX}/jobs/{job_id}").json()
        assert body["status"] == "succeeded"
        assert body["has_result"] is True
        assert body["label"] == SAFE_URL


class TestCors:
    def test_the_vite_origin_is_allowed(self, client):
        response = client.get(f"{API_PREFIX}/health", headers={"Origin": "http://localhost:5173"})
        assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_an_arbitrary_origin_is_not_allowed(self, client):
        """A wildcard would let any page the operator visits read crawl results."""
        response = client.get(f"{API_PREFIX}/health", headers={"Origin": "https://evil.test"})
        assert response.headers.get("access-control-allow-origin") is None


class TestStartupRecovery:
    def test_orphaned_jobs_are_failed_on_startup(self, tmp_path):
        """A job left RUNNING by a killed process has no worker any more."""
        store = DiskJobStore(tmp_path / "jobs")
        job_id = store.create("seo.page_classifier", {"base_url": SAFE_URL}).id
        store.mark_running(job_id)

        with TestClient(create_app(store=store)):
            pass

        assert store.get(job_id).status is JobStatus.FAILED


def _fake_output(*, truncated: bool) -> PageClassificationOutput:
    """An empty but genuine `PageClassificationOutput`.

    A real instance rather than a stand-in, because the server type-checks what
    the tool returned before persisting it. A duck-typed object would pass the
    tests while the production path rejected the real thing.
    """
    return PageClassificationOutput(
        base_url=SAFE_URL,
        site_profile=SiteProfile(),
        weight_profile=WeightProfileReport.for_site(SiteProfile()),
        discovery=DiscoveryReport(base_url=SAFE_URL, truncated=truncated),
        summary=CrawlSummary(),
    )


class TestBlockedCrawlSurfacing:
    """A blocked crawl must reach the client as a failure, not as a result.

    The tool raises `CrawlBlockedError`, `BaseTool.run()` converts it to a
    non-success `ToolResult`, and the API must persist that as `FAILED` with the
    reason intact. If any link in that chain drops the message, the UI shows a
    green job with one confident page and no explanation.
    """

    def test_a_blocked_crawl_becomes_a_failed_job(self, client, store, stub_tool):
        stub_tool.result = StubResult(
            ok=False,
            error="Crawl failed: all 6 requests were refused by the target server.",
        )
        job_id = run_job(client, store)

        record = store.get(job_id)
        assert record.status is JobStatus.FAILED
        assert record.has_result is False, "no result blob for a crawl that produced nothing"

    def test_the_refusal_reason_reaches_the_client(self, client, store, stub_tool):
        stub_tool.result = StubResult(ok=False, error="all 6 requests were refused")
        job_id = run_job(client, store)

        body = client.get(f"{API_PREFIX}/jobs/{job_id}").json()
        assert "refused" in (body["error"] or "")

    def test_a_failed_job_offers_no_result_endpoint(self, client, store, stub_tool):
        """409, so a poller learns it has stopped rather than retrying forever."""
        stub_tool.result = StubResult(ok=False, error="all requests refused")
        job_id = run_job(client, store)

        assert client.get(f"{API_PREFIX}/jobs/{job_id}/result").status_code == 409


class TestTelemetryRecorder:
    """Progress reporting must not cost more than the work it reports on.

    Each write rewrites the job record through `os.replace` and an `fsync`, so
    an unthrottled recorder on a 20,000-page crawl would spend more wall-clock
    in the filesystem than on the network.
    """

    def test_the_first_call_flushes_immediately(self, store):
        """A crawl that shows nothing until half a second in looks stuck."""
        job_id = store.create("seo.page_classifier", {}).id
        server_module.TelemetryRecorder(store, job_id, 100)(0, 50, ())
        assert store.get(job_id).telemetry.discovered == 50

    def test_rapid_calls_are_throttled(self, store):
        job_id = store.create("seo.page_classifier", {}).id
        recorder = server_module.TelemetryRecorder(store, job_id, 100)
        recorder(0, 50, ())
        for completed in range(1, 60):
            recorder(completed, 50, ())
        # Only the initial flush should have landed inside half a second.
        assert store.get(job_id).telemetry.completed == 0

    def test_progress_is_measured_against_discovery_not_the_ceiling(self, store):
        """A 300-page site crawled with a 20,000 ceiling finishes at 300.

        Dividing by the ceiling would leave the bar at 1.5% forever.
        """
        job_id = store.create("seo.page_classifier", {}).id
        server_module.TelemetryRecorder(store, job_id, 20_000)(300, 300, ())
        telemetry = store.get(job_id).telemetry
        assert telemetry.discovered == 300
        assert telemetry.fraction == 1.0

    def test_discovery_beyond_the_ceiling_is_capped(self, store):
        """The crawl stops at the ceiling, so the denominator does too."""
        job_id = store.create("seo.page_classifier", {}).id
        server_module.TelemetryRecorder(store, job_id, 500)(0, 4_427, ())
        assert store.get(job_id).telemetry.discovered == 500

    def test_no_eta_during_warmup(self, store):
        """A rate over the first fraction of a second swings by orders of magnitude."""
        job_id = store.create("seo.page_classifier", {}).id
        server_module.TelemetryRecorder(store, job_id, 100)(5, 100, ())
        assert store.get(job_id).telemetry.eta_seconds is None

    def test_recent_items_are_capped(self, store):
        """20,000 URLs on every poll would cost more than the crawl."""
        job_id = store.create("seo.page_classifier", {}).id
        urls = tuple(f"https://e.com/{n}/" for n in range(200))
        server_module.TelemetryRecorder(store, job_id, 1_000)(0, 200, urls)

        recent = store.get(job_id).telemetry.recent_items
        assert len(recent) == 20
        assert recent[-1] == "https://e.com/199/", "newest last"

    def test_a_deleted_job_does_not_break_the_crawl(self, store):
        """Losing telemetry must not interrupt work still producing a result."""
        recorder = server_module.TelemetryRecorder(store, "gone", 100)
        recorder(1, 10, ())  # must not raise

    def test_telemetry_survives_into_the_status_payload(self, client, store, stub_tool):
        stub_tool.result = StubResult(ok=True, data=_fake_output(truncated=False))
        job_id = run_job(client, store)
        assert "telemetry" in client.get(f"{API_PREFIX}/jobs/{job_id}").json()


class TestTelemetryContract:
    def test_fraction_is_none_before_anything_is_discovered(self):
        """`None`, not zero: an unknown total is not a total of zero."""
        from src.core.state_store import JobTelemetry

        assert JobTelemetry().fraction is None

    def test_fraction_cannot_exceed_one(self):
        """Discovery shrinks when duplicates merge; the bar must not overrun."""
        from src.core.state_store import JobTelemetry

        assert JobTelemetry(completed=120, discovered=100).fraction == 1.0
