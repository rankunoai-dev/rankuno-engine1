"""`GET /crawl-activity`: per-org counts of in-flight crawls across both engines.

What must hold: no token is a 401 (same as `/jobs`); an org only ever sees its
own numbers, from either engine; only live statuses count; the cap is the one
`try_reserve` enforces; an unconfigured dispatch store is zero, never a 500;
and the cache expires on the monotonic clock without ever crossing orgs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from src.api.server import API_PREFIX, SF_TOOL_NAME, create_app
from src.core.state_store import DiskJobStore, JobRecord, JobStatus
from src.core.url_safety import UrlSafetyPolicy
from src.core.worker_dispatch_schemas import (
    WorkerJob,
    WorkerJobEnvelope,
    WorkerJobKind,
    WorkerJobStatus,
)
from src.core.worker_dispatch_store import DispatchStoreUnavailableError

from tests.api.conftest import TEST_SESSION_SECRET, auth_headers

URL = f"{API_PREFIX}/crawl-activity"


class _FakeDispatchStore:
    """Only what the counter touches, plus a call counter to observe caching."""

    def __init__(self) -> None:
        self.jobs: list[WorkerJob] = []
        self.list_calls = 0
        self.unavailable = False

    def add(
        self,
        org_id: str,
        status: WorkerJobStatus,
        *,
        dispatched_at: datetime | None = None,
    ) -> None:
        now = datetime.now(UTC)
        job_id = f"job{len(self.jobs)}"
        self.jobs.append(
            WorkerJob(
                id=job_id,
                org_id=org_id,
                worker_id="w1",
                kind=WorkerJobKind.SCREAMING_FROG_CRAWL,
                envelope=WorkerJobEnvelope(
                    job_id=job_id, seed_url="https://example.com/", correlation_id="c"
                ),
                status=status,
                created_at=now,
                updated_at=now,
                dispatched_at=dispatched_at,
            )
        )

    def list_jobs_for_org(self, org_id: str) -> list[WorkerJob]:
        self.list_calls += 1
        if self.unavailable:
            raise DispatchStoreUnavailableError("not configured")
        return [j for j in self.jobs if j.org_id == org_id]


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def store(tmp_path) -> DiskJobStore:
    return DiskJobStore(tmp_path / "jobs")


@pytest.fixture
def dispatch() -> _FakeDispatchStore:
    return _FakeDispatchStore()


@pytest.fixture
def app_and_client(tmp_path, store, dispatch):
    app = create_app(
        store=store,
        url_policy=UrlSafetyPolicy(resolver=lambda h: ["93.184.216.34"]),
        session_secret=TEST_SESSION_SECRET,
        worker_dispatch_store=dispatch,
        max_concurrent_jobs=3,
        deliverable_jobs_root=tmp_path / "deliverables",
        rulebooks_root=tmp_path / "rulebooks",
    )
    clock = _Clock()
    app.state.api.crawl_activity.clock = clock
    with TestClient(app) as test_client:
        yield test_client, clock


@pytest.fixture
def client(app_and_client) -> TestClient:
    return app_and_client[0]


def _job(
    store: DiskJobStore, org_id: str, status: JobStatus, tool: str = "seo.page_classifier"
) -> JobRecord:
    record = store.create(tool, {}, org_id=org_id)
    if status is JobStatus.RUNNING:
        store.mark_running(record.id)
    elif status is JobStatus.SUCCEEDED:
        store.mark_running(record.id)
        store.finish(record.id, {})
    elif status is JobStatus.PARTIAL:
        store.mark_running(record.id)
        store.finish(record.id, {}, partial=True)
    elif status is JobStatus.FAILED:
        store.mark_failed(record.id, "boom")
    return record


def _get(client: TestClient, org_id: str = "org-a") -> dict[str, int]:
    response = client.get(URL, headers=auth_headers(org_id=org_id))
    assert response.status_code == 200, response.text
    body: dict[str, int] = response.json()
    return body


def test_requires_authentication(client):
    assert client.get(URL).status_code == 401


def test_a_forged_token_is_401(client):
    assert client.get(URL, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_an_empty_org_reports_zeros_and_the_cap(client):
    assert _get(client) == {"rankuno_active": 0, "rankuno_cap": 3, "sf_active": 0}


def test_cap_is_the_configured_reservation_cap(client):
    assert _get(client)["rankuno_cap"] == 3


def test_only_queued_and_running_rankuno_jobs_count(client, store):
    _job(store, "org-a", JobStatus.QUEUED)
    _job(store, "org-a", JobStatus.RUNNING)
    _job(store, "org-a", JobStatus.SUCCEEDED)
    _job(store, "org-a", JobStatus.PARTIAL)
    _job(store, "org-a", JobStatus.FAILED)
    assert _get(client)["rankuno_active"] == 2


def test_local_screaming_frog_records_are_not_rankuno_crawls(client, store):
    _job(store, "org-a", JobStatus.RUNNING, tool=SF_TOOL_NAME)
    assert _get(client)["rankuno_active"] == 0


def test_only_queued_and_dispatched_worker_jobs_count(client, dispatch):
    recent = datetime.now(UTC)
    dispatch.add("org-a", WorkerJobStatus.QUEUED)
    dispatch.add("org-a", WorkerJobStatus.DISPATCHED, dispatched_at=recent)
    for terminal in (WorkerJobStatus.SUCCEEDED, WorkerJobStatus.PARTIAL, WorkerJobStatus.FAILED):
        dispatch.add("org-a", terminal)
    assert _get(client)["sf_active"] == 2


def test_a_stale_dispatched_job_is_not_counted(client, dispatch):
    """A dead worker's job the sweep would fail must not inflate the badge."""
    long_ago = datetime.now(UTC) - timedelta(hours=4)
    dispatch.add("org-a", WorkerJobStatus.DISPATCHED, dispatched_at=long_ago)
    assert _get(client)["sf_active"] == 0
    assert dispatch.jobs[0].status is WorkerJobStatus.DISPATCHED  # read-only: no sweep


def test_org_isolation_on_both_engines(client, store, dispatch):
    _job(store, "org-a", JobStatus.RUNNING)
    _job(store, "org-a", JobStatus.QUEUED)
    dispatch.add("org-a", WorkerJobStatus.QUEUED)
    _job(store, "org-b", JobStatus.RUNNING)
    dispatch.add("org-b", WorkerJobStatus.QUEUED)
    dispatch.add("org-b", WorkerJobStatus.QUEUED)
    dispatch.add("org-b", WorkerJobStatus.QUEUED)

    assert _get(client, "org-a") == {"rankuno_active": 2, "rankuno_cap": 3, "sf_active": 1}
    assert _get(client, "org-b") == {"rankuno_active": 1, "rankuno_cap": 3, "sf_active": 3}
    assert _get(client, "org-c") == {"rankuno_active": 0, "rankuno_cap": 3, "sf_active": 0}


def test_unconfigured_worker_dispatch_is_zero_not_500(client, store, dispatch):
    dispatch.unavailable = True
    _job(store, "org-a", JobStatus.RUNNING)
    assert _get(client) == {"rankuno_active": 1, "rankuno_cap": 3, "sf_active": 0}


def test_the_response_carries_integers_only(client, store, dispatch):
    _job(store, "org-a", JobStatus.RUNNING)
    dispatch.add("org-a", WorkerJobStatus.QUEUED)
    body = _get(client)
    assert set(body) == {"rankuno_active", "rankuno_cap", "sf_active"}
    assert all(type(v) is int for v in body.values())


def test_the_cache_absorbs_polling_then_refreshes_after_the_ttl(app_and_client, store, dispatch):
    client, clock = app_and_client
    _job(store, "org-a", JobStatus.RUNNING)
    dispatch.add("org-a", WorkerJobStatus.QUEUED)
    assert _get(client) == {"rankuno_active": 1, "rankuno_cap": 3, "sf_active": 1}

    _job(store, "org-a", JobStatus.RUNNING)
    dispatch.add("org-a", WorkerJobStatus.QUEUED)
    clock.now += 4.9
    assert _get(client) == {"rankuno_active": 1, "rankuno_cap": 3, "sf_active": 1}
    assert dispatch.list_calls == 1

    clock.now += 0.2
    assert _get(client) == {"rankuno_active": 2, "rankuno_cap": 3, "sf_active": 2}
    assert dispatch.list_calls == 2


def test_a_failed_dispatch_lookup_is_cached_too(app_and_client, dispatch):
    client, clock = app_and_client
    dispatch.unavailable = True
    for _ in range(3):
        assert _get(client)["sf_active"] == 0
    assert dispatch.list_calls == 1

    dispatch.unavailable = False
    dispatch.add("org-a", WorkerJobStatus.QUEUED)
    clock.now += 6
    assert _get(client)["sf_active"] == 1


def test_the_cache_never_serves_one_orgs_number_to_another(app_and_client, store, dispatch):
    client, _clock = app_and_client
    _job(store, "org-a", JobStatus.RUNNING)
    dispatch.add("org-a", WorkerJobStatus.QUEUED)
    assert _get(client, "org-a")["rankuno_active"] == 1
    assert _get(client, "org-a")["sf_active"] == 1
    # Within the TTL, a different org must not inherit org-a's cached values.
    assert _get(client, "org-b") == {"rankuno_active": 0, "rankuno_cap": 3, "sf_active": 0}
    assert _get(client, "org-a") == {"rankuno_active": 1, "rankuno_cap": 3, "sf_active": 1}
