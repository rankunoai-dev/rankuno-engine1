"""End-to-end tests for ADR 0015's cloud-side worker-dispatch HTTP surface.

The security-critical properties this file exists to prove, matching the
ADR's own binding conditions:

* Worker registration and every worker-facing dispatch route require a
  verified credential — never a bare header (condition 1/2).
* A worker attempting to claim, upload to, or report failure against
  another worker's job is provably rejected, even inside the same org
  (condition 2's IDOR rule, condition 6's per-worker pinning).
* The dual approval gate works end to end: gate (a)'s preview/confirm
  exchange controls whether a job is ever queued; gate (b)'s signed
  assignment is independently verifiable and fails closed when the
  verifying identity does not match (condition 3).
* `WorkerJobEnvelope`/request models reject unexpected fields via
  `StrictModel`'s `extra="forbid"` (condition 8).

`PostgresWorkerDispatchStore`'s own SQL and atomicity are covered by
`tests/core/test_postgres_worker_dispatch_store.py`; this file uses a
simple in-memory fake implementing the same `WorkerDispatchStore` Protocol,
so what is under test here is the HTTP/auth/ownership layer, not the SQL.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from typing import NoReturn

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from src.api.server import API_PREFIX, create_app
from src.core.state_store import DiskJobStore
from src.core.url_safety import UrlSafetyPolicy
from src.core.worker_auth import (
    MAX_REPORTED_TEMPLATES,
    DiskWorkerStore,
    WorkerStoreUnavailableError,
)
from src.core.worker_dispatch_schemas import (
    DispatchPreviewToken,
    WorkerJob,
    WorkerJobEnvelope,
    WorkerJobKind,
    WorkerJobStatus,
)
from src.core.worker_dispatch_signing import verify_dispatch_assignment
from src.core.worker_dispatch_store import (
    DEFAULT_PREVIEW_TTL_S,
    DispatchStoreUnavailableError,
)

from tests.api.conftest import TEST_SESSION_SECRET, auth_headers

PUBLIC_IP = "93.184.216.34"
DISPATCH_SECRET = SecretStr("test-only-dispatch-signing-secret")
BUNDLE_SECRET = SecretStr("test-only-bundle-encryption-secret")


class _FakeWorkerDispatchStore:
    """A pure-Python `WorkerDispatchStore` — HTTP-layer tests only."""

    def __init__(self) -> None:
        self._previews: dict[str, DispatchPreviewToken] = {}
        self._consumed_previews: set[str] = set()
        self._jobs: dict[str, WorkerJob] = {}
        self._uploads: dict[str, bytes] = {}
        self._expired_uploads: set[str] = set()

    def mint_dispatch_preview(
        self,
        *,
        org_id,
        worker_id,
        seed_url,
        template_name,
        correlation_id,
        ttl_s=DEFAULT_PREVIEW_TTL_S,
    ) -> DispatchPreviewToken:
        token = DispatchPreviewToken(
            token=uuid.uuid4().hex,
            org_id=org_id,
            worker_id=worker_id,
            seed_url=seed_url,
            template_name=template_name,
            correlation_id=correlation_id,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_s),
        )
        self._previews[token.token] = token
        return token

    def confirm_dispatch(
        self, token, *, org_id, worker_id, seed_url, template_name, correlation_id
    ) -> WorkerJob | None:
        record = self._previews.get(token)
        if (
            record is None
            or token in self._consumed_previews
            or record.org_id != org_id
            or record.worker_id != worker_id
            or record.seed_url != seed_url
            or record.template_name != template_name
            or record.correlation_id != correlation_id
            or record.expires_at < datetime.now(UTC)
        ):
            return None
        self._consumed_previews.add(token)
        job_id = uuid.uuid4().hex
        now = datetime.now(UTC)
        job = WorkerJob(
            id=job_id,
            org_id=org_id,
            worker_id=worker_id,
            kind=WorkerJobKind.SCREAMING_FROG_CRAWL,
            envelope=WorkerJobEnvelope(
                job_id=job_id,
                seed_url=seed_url,
                template_name=template_name,
                correlation_id=correlation_id,
            ),
            status=WorkerJobStatus.QUEUED,
            created_at=now,
            updated_at=now,
        )
        self._jobs[job_id] = job
        return job

    def claim_next_job(self, *, worker_id, org_id) -> WorkerJob | None:
        candidates = sorted(
            (
                j
                for j in self._jobs.values()
                if j.worker_id == worker_id
                and j.org_id == org_id
                and j.status is WorkerJobStatus.QUEUED
            ),
            key=lambda j: j.created_at,
        )
        if not candidates:
            return None
        job = candidates[0].model_copy(
            update={"status": WorkerJobStatus.DISPATCHED, "dispatched_at": datetime.now(UTC)}
        )
        self._jobs[job.id] = job
        return job

    def get_job(self, job_id) -> WorkerJob:
        from src.core.worker_dispatch_store import WorkerJobNotFoundError

        try:
            return self._jobs[job_id]
        except KeyError:
            raise WorkerJobNotFoundError(job_id) from None

    def list_jobs_for_org(self, org_id) -> list[WorkerJob]:
        return sorted(
            (j for j in self._jobs.values() if j.org_id == org_id),
            key=lambda j: j.created_at,
            reverse=True,
        )

    def mark_uploaded(self, job_id, *, bundle_size_bytes, partial=False) -> WorkerJob:
        status = WorkerJobStatus.PARTIAL if partial else WorkerJobStatus.SUCCEEDED
        job = self._jobs[job_id].model_copy(
            update={
                "status": status,
                "bundle_size_bytes": bundle_size_bytes,
                "finished_at": datetime.now(UTC),
            }
        )
        self._jobs[job_id] = job
        return job

    def mark_failed(self, job_id, error) -> WorkerJob:
        job = self._jobs[job_id].model_copy(
            update={
                "status": WorkerJobStatus.FAILED,
                "error": error,
                "finished_at": datetime.now(UTC),
            }
        )
        self._jobs[job_id] = job
        return job

    def store_upload(self, job_id, *, org_id, worker_id, encrypted_bytes, retention_days) -> None:
        self._uploads[job_id] = encrypted_bytes

    def read_upload(self, job_id, *, org_id) -> bytes | None:
        job = self._jobs.get(job_id)
        if job is None or job.org_id != org_id or job_id in self._expired_uploads:
            # The Postgres implementation filters on org_id and expires_at in
            # SQL. The fake must too, or the cross-org and expiry tests would
            # be passing on the route's check alone and would not notice the
            # store's own filter being dropped.
            return None
        return self._uploads.get(job_id)

    def expire_stale_dispatched(self, *, org_id, older_than_s) -> int:
        cutoff = datetime.now(UTC) - timedelta(seconds=older_than_s)
        swept = 0
        for job_id, job in list(self._jobs.items()):
            if (
                job.org_id != org_id
                or job.status is not WorkerJobStatus.DISPATCHED
                or job.dispatched_at is None
                or job.dispatched_at >= cutoff
            ):
                continue
            self._jobs[job_id] = job.model_copy(
                update={
                    "status": WorkerJobStatus.FAILED,
                    "error": "the worker stopped reporting after claiming this job",
                    "finished_at": datetime.now(UTC),
                }
            )
            swept += 1
        return swept


@pytest.fixture
def dispatch_store() -> _FakeWorkerDispatchStore:
    return _FakeWorkerDispatchStore()


@pytest.fixture
def worker_store(tmp_path) -> DiskWorkerStore:
    return DiskWorkerStore(tmp_path / "workers")


@pytest.fixture
def client(tmp_path, dispatch_store, worker_store) -> TestClient:
    app = create_app(
        store=DiskJobStore(tmp_path / "jobs"),
        url_policy=UrlSafetyPolicy(resolver=lambda h: [PUBLIC_IP]),
        session_secret=TEST_SESSION_SECRET,
        worker_store=worker_store,
        worker_dispatch_store=dispatch_store,
        dispatch_signing_secret=DISPATCH_SECRET,
        bundle_encryption_secret=BUNDLE_SECRET,
    )
    with TestClient(app) as test_client:
        yield test_client


def _register_worker(
    client: TestClient, *, org_id: str = "default", name: str = "desktop-1", online: bool = True
) -> dict[str, str]:
    """Register a worker and, by default, make it look like its daemon is up.

    `online=True` issues one real poll, which is exactly what marks a worker
    live: dispatch confirm now refuses an offline worker (409), so a test
    fixture that registered a worker and never started its daemon would be
    modelling a sleeping PC, not a working one. `online=False` is the
    deliberate opposite, for the tests that assert the refusal.
    """
    response = client.post(
        f"{API_PREFIX}/workers",
        json={"display_name": name},
        headers=auth_headers(org_id=org_id),
    )
    assert response.status_code == 201, response.text
    body: dict[str, str] = response.json()
    if online:
        poll = client.get(
            f"{API_PREFIX}/workers/dispatch/poll",
            headers=_worker_headers(body["worker_id"], body["worker_secret"]),
        )
        assert poll.status_code == 200, poll.text
    return body


def _worker_headers(worker_id: str, secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {worker_id}:{secret}"}


# --- Worker registration (condition 1/2) ----------------------------------------


def test_register_worker_requires_authentication(client):
    response = client.post(f"{API_PREFIX}/workers", json={"display_name": "desktop-1"})
    assert response.status_code == 401


def test_register_worker_issues_a_secret_shown_exactly_once(client, worker_store):
    body = _register_worker(client)
    assert body["worker_secret"]
    assert body["org_id"] == "default"

    stored = worker_store.get(body["worker_id"])
    assert stored.secret_hash != body["worker_secret"]
    assert "pbkdf2_" in stored.secret_hash


def test_list_workers_requires_authentication(client):
    response = client.get(f"{API_PREFIX}/workers")
    assert response.status_code == 401


def test_list_workers_is_org_scoped(client):
    _register_worker(client, org_id="acme", name="acme-desktop")
    _register_worker(client, org_id="globex", name="globex-desktop")

    acme_view = client.get(f"{API_PREFIX}/workers", headers=auth_headers(org_id="acme"))
    assert acme_view.status_code == 200
    names = [w["display_name"] for w in acme_view.json()["workers"]]
    assert names == ["acme-desktop"]


def test_poll_rejects_a_missing_credential(client):
    response = client.get(f"{API_PREFIX}/workers/dispatch/poll")
    assert response.status_code == 401


def test_poll_rejects_an_unregistered_worker(client):
    response = client.get(
        f"{API_PREFIX}/workers/dispatch/poll", headers=_worker_headers("wkr-ghost", "anything")
    )
    assert response.status_code == 401


def test_poll_rejects_the_wrong_secret(client):
    body = _register_worker(client)
    response = client.get(
        f"{API_PREFIX}/workers/dispatch/poll",
        headers=_worker_headers(body["worker_id"], "totally-wrong-secret"),
    )
    assert response.status_code == 401


# --- Dispatch preview/confirm: gate (a) ------------------------------------------


def _preview_and_confirm(
    client: TestClient, *, worker_id: str, org_id: str = "default", seed_url: str = "https://e.com/"
) -> dict:
    preview = client.post(
        f"{API_PREFIX}/workers/{worker_id}/dispatch/preview",
        json={"seed_url": seed_url, "correlation_id": "corr-1"},
        headers=auth_headers(org_id=org_id),
    )
    assert preview.status_code == 200, preview.text
    confirm = client.post(
        f"{API_PREFIX}/workers/{worker_id}/dispatch",
        json={"token": preview.json()["token"], "seed_url": seed_url, "correlation_id": "corr-1"},
        headers=auth_headers(org_id=org_id),
    )
    assert confirm.status_code == 202, confirm.text
    return confirm.json()


def test_preview_requires_authentication(client):
    worker = _register_worker(client)
    response = client.post(
        f"{API_PREFIX}/workers/{worker['worker_id']}/dispatch/preview",
        json={"seed_url": "https://e.com/", "correlation_id": "c1"},
    )
    assert response.status_code == 401


def test_preview_rejects_a_worker_owned_by_another_org(client):
    worker = _register_worker(client, org_id="acme")
    response = client.post(
        f"{API_PREFIX}/workers/{worker['worker_id']}/dispatch/preview",
        json={"seed_url": "https://e.com/", "correlation_id": "c1"},
        headers=auth_headers(org_id="globex"),
    )
    assert response.status_code == 403


def test_confirm_without_a_prior_preview_is_rejected(client):
    worker = _register_worker(client)
    response = client.post(
        f"{API_PREFIX}/workers/{worker['worker_id']}/dispatch",
        json={"token": "never-minted", "seed_url": "https://e.com/", "correlation_id": "c1"},
        headers=auth_headers(),
    )
    assert response.status_code == 403


def test_confirm_token_is_single_use(client):
    worker = _register_worker(client)
    preview = client.post(
        f"{API_PREFIX}/workers/{worker['worker_id']}/dispatch/preview",
        json={"seed_url": "https://e.com/", "correlation_id": "c1"},
        headers=auth_headers(),
    ).json()

    first = client.post(
        f"{API_PREFIX}/workers/{worker['worker_id']}/dispatch",
        json={"token": preview["token"], "seed_url": "https://e.com/", "correlation_id": "c1"},
        headers=auth_headers(),
    )
    second = client.post(
        f"{API_PREFIX}/workers/{worker['worker_id']}/dispatch",
        json={"token": preview["token"], "seed_url": "https://e.com/", "correlation_id": "c1"},
        headers=auth_headers(),
    )
    assert first.status_code == 202
    assert second.status_code == 403


def test_preview_rejects_an_unsafe_seed_url(client):
    worker = _register_worker(client)
    response = client.post(
        f"{API_PREFIX}/workers/{worker['worker_id']}/dispatch/preview",
        json={"seed_url": "http://169.254.169.254/", "correlation_id": "c1"},
        headers=auth_headers(),
    )
    assert response.status_code == 400


def test_dispatch_confirm_request_rejects_extra_fields():
    """ADR 0015 condition 8: no `extra_args`/`raw_command` ever."""
    from src.api.worker_schemas import DispatchConfirmRequest

    with pytest.raises(ValidationError, match="extra"):
        DispatchConfirmRequest.model_validate(
            {
                "token": "x",
                "seed_url": "https://e.com/",
                "correlation_id": "c1",
                "extra_args": "--danger",
            }
        )


def test_worker_job_envelope_rejects_extra_fields():
    """The envelope itself, independent of the HTTP request models."""
    with pytest.raises(ValidationError, match="extra"):
        WorkerJobEnvelope.model_validate(
            {
                "job_id": "job-1",
                "seed_url": "https://e.com/",
                "template_name": None,
                "correlation_id": "c1",
                "raw_command": "rm -rf /",
            }
        )


# --- Poll + claim: never another worker's job (condition 2/6) ------------------


def test_a_worker_never_receives_another_workers_queued_job(client):
    worker_a = _register_worker(client, name="worker-a")
    worker_b = _register_worker(client, name="worker-b")
    _preview_and_confirm(client, worker_id=worker_a["worker_id"])

    poll_b = client.get(
        f"{API_PREFIX}/workers/dispatch/poll",
        headers=_worker_headers(worker_b["worker_id"], worker_b["worker_secret"]),
    )
    assert poll_b.status_code == 200
    assert poll_b.json()["assignment"] is None


def test_the_owning_worker_receives_the_job_via_poll(client):
    worker = _register_worker(client)
    _preview_and_confirm(client, worker_id=worker["worker_id"])

    response = client.get(
        f"{API_PREFIX}/workers/dispatch/poll",
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )
    assert response.status_code == 200
    assert response.json()["assignment"] is not None


# --- The dual gate end-to-end (condition 3) --------------------------------------


def test_dual_gate_end_to_end_worker_verifies_a_genuine_assignment(client):
    """Gate (a) queues the job; gate (b)'s artifact verifies for the real worker."""
    worker = _register_worker(client)
    _preview_and_confirm(client, worker_id=worker["worker_id"])

    poll = client.get(
        f"{API_PREFIX}/workers/dispatch/poll",
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )
    token = poll.json()["assignment"]["token"]

    claims = verify_dispatch_assignment(
        token, secret=DISPATCH_SECRET, worker_id=worker["worker_id"], org_id="default"
    )
    assert claims.seed_url == "https://e.com/"


def test_dual_gate_end_to_end_cloud_approved_but_worker_side_check_fails(client):
    """The scenario the task calls out explicitly.

    Gate (a) genuinely approved this job for `worker_a` (a real preview/
    confirm exchange happened, and the cloud legitimately dispatched it via
    poll). But `worker_b` — even holding a *valid* credential for a *real*
    worker in the *same* org — must have gate (b) refuse the artifact,
    because it is bound to a different `worker_id`. This is exactly what
    stops a worker daemon from ever trusting an unconditional boolean.
    """
    worker_a = _register_worker(client, name="worker-a")
    worker_b = _register_worker(client, name="worker-b")
    _preview_and_confirm(client, worker_id=worker_a["worker_id"])

    poll = client.get(
        f"{API_PREFIX}/workers/dispatch/poll",
        headers=_worker_headers(worker_a["worker_id"], worker_a["worker_secret"]),
    )
    token = poll.json()["assignment"]["token"]

    # worker_b independently verifying the artifact meant for worker_a must refuse.
    from src.core.worker_dispatch_signing import DispatchAssignmentError

    with pytest.raises(DispatchAssignmentError):
        verify_dispatch_assignment(
            token, secret=DISPATCH_SECRET, worker_id=worker_b["worker_id"], org_id="default"
        )


def test_dual_gate_worker_side_check_fails_on_wrong_signing_secret(client):
    """Same scenario, different cause: a misconfigured worker's own secret."""
    worker = _register_worker(client)
    _preview_and_confirm(client, worker_id=worker["worker_id"])
    poll = client.get(
        f"{API_PREFIX}/workers/dispatch/poll",
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )
    token = poll.json()["assignment"]["token"]

    from src.core.worker_dispatch_signing import DispatchAssignmentError

    with pytest.raises(DispatchAssignmentError):
        verify_dispatch_assignment(
            token,
            secret=SecretStr("not-the-real-signing-secret"),
            worker_id=worker["worker_id"],
            org_id="default",
        )


# --- Upload / failure reporting: per-job worker pinning (condition 2/6) --------


def test_upload_rejects_a_worker_claiming_another_workers_job(client):
    worker_a = _register_worker(client, name="worker-a")
    worker_b = _register_worker(client, name="worker-b")
    job = _preview_and_confirm(client, worker_id=worker_a["worker_id"])
    client.get(
        f"{API_PREFIX}/workers/dispatch/poll",
        headers=_worker_headers(worker_a["worker_id"], worker_a["worker_secret"]),
    )

    response = client.post(
        f"{API_PREFIX}/workers/jobs/{job['id']}/upload",
        content=b"PK\x03\x04not-a-real-zip",
        headers=_worker_headers(worker_b["worker_id"], worker_b["worker_secret"]),
    )
    assert response.status_code == 403


def test_report_failure_rejects_a_worker_claiming_another_workers_job(client):
    worker_a = _register_worker(client, name="worker-a")
    worker_b = _register_worker(client, name="worker-b")
    job = _preview_and_confirm(client, worker_id=worker_a["worker_id"])

    response = client.post(
        f"{API_PREFIX}/workers/jobs/{job['id']}/failed",
        json={"error": "pretending to be worker A"},
        headers=_worker_headers(worker_b["worker_id"], worker_b["worker_secret"]),
    )
    assert response.status_code == 403


def test_upload_by_the_owning_worker_succeeds(client, dispatch_store):
    """The real happy path: a valid bundle is validated, encrypted, and stored."""
    worker = _register_worker(client)
    job = _preview_and_confirm(client, worker_id=worker["worker_id"])
    client.get(
        f"{API_PREFIX}/workers/dispatch/poll",
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        archive.writestr("internal_all.csv", "Address\nhttps://e.com/\n")

    response = client.post(
        f"{API_PREFIX}/workers/jobs/{job['id']}/upload",
        content=buffer.getvalue(),
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "succeeded"
    assert dispatch_store._uploads[job["id"]]  # an encrypted blob was actually stored


def test_upload_of_an_unknown_job_is_rejected(client):
    worker = _register_worker(client)
    response = client.post(
        f"{API_PREFIX}/workers/jobs/no-such-job/upload",
        content=b"PK\x03\x04...",
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )
    assert response.status_code == 404


def test_preview_rejects_an_unknown_worker(client):
    response = client.post(
        f"{API_PREFIX}/workers/wkr-does-not-exist/dispatch/preview",
        json={"seed_url": "https://e.com/", "correlation_id": "c1"},
        headers=auth_headers(),
    )
    assert response.status_code == 404


def test_upload_requires_worker_authentication(client):
    worker = _register_worker(client)
    job = _preview_and_confirm(client, worker_id=worker["worker_id"])
    response = client.post(
        f"{API_PREFIX}/workers/jobs/{job['id']}/upload", content=b"PK\x03\x04..."
    )
    assert response.status_code == 401


def test_upload_of_an_unknown_bundle_is_rejected(client):
    worker = _register_worker(client)
    job = _preview_and_confirm(client, worker_id=worker["worker_id"])
    response = client.post(
        f"{API_PREFIX}/workers/jobs/{job['id']}/upload",
        content=b"this is not a zip at all",
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )
    assert response.status_code == 400


def test_upload_rejects_an_empty_body(client):
    worker = _register_worker(client)
    job = _preview_and_confirm(client, worker_id=worker["worker_id"])
    response = client.post(
        f"{API_PREFIX}/workers/jobs/{job['id']}/upload",
        content=b"",
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )
    assert response.status_code == 400


def test_report_failure_requires_worker_authentication(client):
    worker = _register_worker(client)
    job = _preview_and_confirm(client, worker_id=worker["worker_id"])
    response = client.post(f"{API_PREFIX}/workers/jobs/{job['id']}/failed", json={"error": "x"})
    assert response.status_code == 401


def test_report_failure_by_the_owning_worker_succeeds(client, dispatch_store):
    worker = _register_worker(client)
    job = _preview_and_confirm(client, worker_id=worker["worker_id"])
    response = client.post(
        f"{API_PREFIX}/workers/jobs/{job['id']}/failed",
        json={"error": "screaming frog crashed"},
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "failed"


# --- Job listing: org-scoped read (no UI, still an API) -------------------------


def test_get_worker_job_is_org_scoped(client):
    worker = _register_worker(client, org_id="acme")
    job = _preview_and_confirm(client, worker_id=worker["worker_id"], org_id="acme")

    same_org = client.get(
        f"{API_PREFIX}/workers/jobs/{job['id']}", headers=auth_headers(org_id="acme")
    )
    other_org = client.get(
        f"{API_PREFIX}/workers/jobs/{job['id']}", headers=auth_headers(org_id="globex")
    )
    assert same_org.status_code == 200
    assert other_org.status_code == 403


def test_get_worker_job_unknown_job_is_404(client):
    response = client.get(f"{API_PREFIX}/workers/jobs/no-such-job", headers=auth_headers())
    assert response.status_code == 404


def test_list_worker_jobs_returns_the_orgs_jobs(client):
    worker = _register_worker(client)
    job = _preview_and_confirm(client, worker_id=worker["worker_id"])

    response = client.get(f"{API_PREFIX}/workers/jobs", headers=auth_headers())
    assert response.status_code == 200
    ids = [j["id"] for j in response.json()["jobs"]]
    assert ids == [job["id"]]


def test_list_worker_jobs_requires_authentication(client):
    response = client.get(f"{API_PREFIX}/workers/jobs")
    assert response.status_code == 401


# --- Liveness: the dashboard must not offer Launch to a sleeping PC -------------


def test_a_registered_worker_that_never_polled_is_offline(client):
    """Registered is not running. The distinction is the whole point."""
    worker = _register_worker(client, online=False)

    view = client.get(f"{API_PREFIX}/workers", headers=auth_headers()).json()
    summary = next(w for w in view["workers"] if w["worker_id"] == worker["worker_id"])
    assert summary["last_seen_at"] is None
    assert summary["is_online"] is False
    assert view["offline_after_s"] > 0


def test_polling_marks_a_worker_online(client):
    worker = _register_worker(client, online=False)
    client.get(
        f"{API_PREFIX}/workers/dispatch/poll",
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )

    view = client.get(f"{API_PREFIX}/workers", headers=auth_headers()).json()
    summary = next(w for w in view["workers"] if w["worker_id"] == worker["worker_id"])
    assert summary["last_seen_at"] is not None
    assert summary["is_online"] is True


def test_a_worker_that_polled_long_ago_is_offline(client, worker_store):
    worker = _register_worker(client)
    worker_store.touch(worker["worker_id"], seen_at=datetime.now(UTC) - timedelta(days=1))

    view = client.get(f"{API_PREFIX}/workers", headers=auth_headers()).json()
    summary = next(w for w in view["workers"] if w["worker_id"] == worker["worker_id"])
    assert summary["is_online"] is False


def test_confirm_refuses_an_offline_worker_rather_than_queueing_into_a_void(client, worker_store):
    worker = _register_worker(client)
    preview = client.post(
        f"{API_PREFIX}/workers/{worker['worker_id']}/dispatch/preview",
        json={"seed_url": "https://e.com/", "correlation_id": "c1"},
        headers=auth_headers(),
    )
    assert preview.status_code == 200
    assert preview.json()["worker_online"] is True

    # The PC goes to sleep between the preview and the confirm.
    worker_store.touch(worker["worker_id"], seen_at=datetime.now(UTC) - timedelta(days=1))
    confirm = client.post(
        f"{API_PREFIX}/workers/{worker['worker_id']}/dispatch",
        json={
            "token": preview.json()["token"],
            "seed_url": "https://e.com/",
            "correlation_id": "c1",
        },
        headers=auth_headers(),
    )
    assert confirm.status_code == 409
    assert "offline" in confirm.json()["detail"]


def test_preview_reports_liveness_so_the_modal_can_warn_first(client):
    worker = _register_worker(client, online=False)
    preview = client.post(
        f"{API_PREFIX}/workers/{worker['worker_id']}/dispatch/preview",
        json={"seed_url": "https://e.com/", "correlation_id": "c1"},
        headers=auth_headers(),
    )
    assert preview.status_code == 200
    assert preview.json()["worker_online"] is False
    assert preview.json()["worker_last_seen_at"] is None


# --- Heartbeat and per-worker templates ----------------------------------------


def test_heartbeat_requires_worker_authentication(client):
    response = client.post(f"{API_PREFIX}/workers/heartbeat", json={"template_names": []})
    assert response.status_code == 401


def test_heartbeat_records_templates_and_liveness(client):
    worker = _register_worker(client, online=False)
    response = client.post(
        f"{API_PREFIX}/workers/heartbeat",
        json={"template_names": ["default-crawl", "js_rendering"]},
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["template_names"] == ["default-crawl", "js_rendering"]

    templates = client.get(
        f"{API_PREFIX}/workers/{worker['worker_id']}/templates", headers=auth_headers()
    )
    assert templates.status_code == 200
    assert templates.json()["templates"] == ["default-crawl", "js_rendering"]
    assert templates.json()["reported_at"] is not None


def test_heartbeat_rejects_a_template_name_that_could_become_a_path(client):
    """A worker is untrusted input. Server-side validation, not politeness."""
    worker = _register_worker(client)
    response = client.post(
        f"{API_PREFIX}/workers/heartbeat",
        json={"template_names": ["../../etc/passwd"]},
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )
    assert response.status_code == 422


def test_heartbeat_rejects_more_templates_than_the_cap(client):
    worker = _register_worker(client)
    response = client.post(
        f"{API_PREFIX}/workers/heartbeat",
        json={"template_names": [f"t{i}" for i in range(MAX_REPORTED_TEMPLATES + 1)]},
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )
    assert response.status_code == 422


def test_polling_does_not_wipe_previously_reported_templates(client):
    worker = _register_worker(client, online=False)
    client.post(
        f"{API_PREFIX}/workers/heartbeat",
        json={"template_names": ["default-crawl"]},
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )
    client.get(
        f"{API_PREFIX}/workers/dispatch/poll",
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )
    templates = client.get(
        f"{API_PREFIX}/workers/{worker['worker_id']}/templates", headers=auth_headers()
    )
    assert templates.json()["templates"] == ["default-crawl"]


def test_worker_templates_are_org_scoped(client):
    worker = _register_worker(client, org_id="acme")
    response = client.get(
        f"{API_PREFIX}/workers/{worker['worker_id']}/templates",
        headers=auth_headers(org_id="globex"),
    )
    assert response.status_code == 403


def test_worker_templates_requires_authentication(client):
    worker = _register_worker(client)
    response = client.get(f"{API_PREFIX}/workers/{worker['worker_id']}/templates")
    assert response.status_code == 401


# --- Bundle download: the reason any of this exists ------------------------------


def _bundle_bytes(row: str = "https://e.com/") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        archive.writestr("internal_all.csv", f"Address\n{row}\n")
    return buffer.getvalue()


def _finished_job(client: TestClient, *, org_id: str = "default") -> tuple[dict, dict]:
    """Register a worker and run one job all the way to an uploaded bundle."""
    worker = _register_worker(client, org_id=org_id)
    job = _preview_and_confirm(client, worker_id=worker["worker_id"], org_id=org_id)
    client.get(
        f"{API_PREFIX}/workers/dispatch/poll",
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )
    upload = client.post(
        f"{API_PREFIX}/workers/jobs/{job['id']}/upload",
        content=_bundle_bytes(),
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )
    assert upload.status_code == 200, upload.text
    return worker, job


def test_bundle_download_returns_the_decrypted_zip(client):
    _, job = _finished_job(client)
    response = client.get(f"{API_PREFIX}/workers/jobs/{job['id']}/bundle", headers=auth_headers())
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert job["id"] in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ["internal_all.csv"]
        assert b"https://e.com/" in archive.read("internal_all.csv")


def test_bundle_download_never_crosses_an_org_boundary(client):
    """An IDOR here leaks a customer's crawl of their own site."""
    _, job = _finished_job(client, org_id="acme")

    mine = client.get(
        f"{API_PREFIX}/workers/jobs/{job['id']}/bundle", headers=auth_headers(org_id="acme")
    )
    theirs = client.get(
        f"{API_PREFIX}/workers/jobs/{job['id']}/bundle", headers=auth_headers(org_id="globex")
    )
    assert mine.status_code == 200
    assert theirs.status_code == 403
    assert b"https://e.com/" not in theirs.content


def test_bundle_download_requires_authentication(client):
    _, job = _finished_job(client)
    response = client.get(f"{API_PREFIX}/workers/jobs/{job['id']}/bundle")
    assert response.status_code == 401


def test_bundle_download_of_a_job_with_no_upload_is_404(client):
    worker = _register_worker(client)
    job = _preview_and_confirm(client, worker_id=worker["worker_id"])
    response = client.get(f"{API_PREFIX}/workers/jobs/{job['id']}/bundle", headers=auth_headers())
    assert response.status_code == 404


def test_bundle_download_respects_the_retention_expiry(client, dispatch_store):
    _, job = _finished_job(client)
    dispatch_store._expired_uploads.add(job["id"])
    response = client.get(f"{API_PREFIX}/workers/jobs/{job['id']}/bundle", headers=auth_headers())
    assert response.status_code == 404
    assert "expired" in response.json()["detail"]


def test_bundle_download_fails_closed_when_the_blob_cannot_be_decrypted(client, dispatch_store):
    """A rotated or missing key must never yield a partial or ciphertext body."""
    _, job = _finished_job(client)
    dispatch_store._uploads[job["id"]] = b"\x00" * 128  # right shape, wrong key

    response = client.get(f"{API_PREFIX}/workers/jobs/{job['id']}/bundle", headers=auth_headers())
    assert response.status_code == 500
    assert "WORKER_BUNDLE_ENCRYPTION_SECRET" in response.json()["detail"]


def test_bundle_download_of_an_unknown_job_is_404(client):
    response = client.get(f"{API_PREFIX}/workers/jobs/nope/bundle", headers=auth_headers())
    assert response.status_code == 404


# --- The 100 MB cap, enforced before the body is buffered ------------------------


def test_upload_refuses_an_oversized_content_length_before_reading_the_body(client):
    """The declared length is refused outright - no 100 MB is ever received."""
    worker = _register_worker(client)
    job = _preview_and_confirm(client, worker_id=worker["worker_id"])
    response = client.post(
        f"{API_PREFIX}/workers/jobs/{job['id']}/upload",
        content=b"x",
        headers={
            **_worker_headers(worker["worker_id"], worker["worker_secret"]),
            "Content-Length": str(200 * 1024 * 1024),
        },
    )
    assert response.status_code == 413
    assert "MB limit" in response.json()["detail"]


def test_default_upload_cap_is_100_mb():
    from src.core.config import Settings

    assert Settings(_env_file=None).worker_upload_max_bytes == 100 * 1024 * 1024


# --- Stuck DISPATCHED jobs get a bounded way out ---------------------------------


def test_a_job_abandoned_after_being_claimed_is_swept_to_failed(client, dispatch_store):
    worker = _register_worker(client)
    job = _preview_and_confirm(client, worker_id=worker["worker_id"])
    client.get(
        f"{API_PREFIX}/workers/dispatch/poll",
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )
    # The daemon dies here, long ago.
    claimed = dispatch_store._jobs[job["id"]]
    dispatch_store._jobs[job["id"]] = claimed.model_copy(
        update={"dispatched_at": datetime.now(UTC) - timedelta(days=2)}
    )

    listed = client.get(f"{API_PREFIX}/workers/jobs", headers=auth_headers()).json()
    assert listed["jobs"][0]["status"] == "failed"
    assert "stopped reporting" in listed["jobs"][0]["error"]


def test_a_freshly_claimed_job_is_not_swept(client):
    worker = _register_worker(client)
    _preview_and_confirm(client, worker_id=worker["worker_id"])
    client.get(
        f"{API_PREFIX}/workers/dispatch/poll",
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )

    listed = client.get(f"{API_PREFIX}/workers/jobs", headers=auth_headers()).json()
    assert listed["jobs"][0]["status"] == "dispatched"


# --- Two daemons, one worker id; a double-clicked confirm ------------------------


def test_two_daemons_sharing_one_worker_id_never_claim_the_same_job(client):
    """Nothing stops an operator copying .env.local onto a second PC.

    The queue must still hand one job to exactly one claimer. Both polls use
    the same credential, so authentication cannot distinguish them - only the
    atomic QUEUED -> DISPATCHED transition can.
    """
    worker = _register_worker(client)
    _preview_and_confirm(client, worker_id=worker["worker_id"])
    headers = _worker_headers(worker["worker_id"], worker["worker_secret"])

    first = client.get(f"{API_PREFIX}/workers/dispatch/poll", headers=headers).json()
    second = client.get(f"{API_PREFIX}/workers/dispatch/poll", headers=headers).json()
    assert first["assignment"] is not None
    assert second["assignment"] is None


def test_a_double_clicked_confirm_queues_exactly_one_job(client):
    """The dispatch token is single-use; the second click must not queue a twin."""
    worker = _register_worker(client)
    preview = client.post(
        f"{API_PREFIX}/workers/{worker['worker_id']}/dispatch/preview",
        json={"seed_url": "https://e.com/", "correlation_id": "c1"},
        headers=auth_headers(),
    ).json()
    body = {"token": preview["token"], "seed_url": "https://e.com/", "correlation_id": "c1"}
    first = client.post(
        f"{API_PREFIX}/workers/{worker['worker_id']}/dispatch", json=body, headers=auth_headers()
    )
    second = client.post(
        f"{API_PREFIX}/workers/{worker['worker_id']}/dispatch", json=body, headers=auth_headers()
    )
    assert first.status_code == 202
    assert second.status_code == 403

    listed = client.get(f"{API_PREFIX}/workers/jobs", headers=auth_headers()).json()
    assert len(listed["jobs"]) == 1


def test_an_upload_retried_after_a_network_drop_leaves_one_bundle(client, dispatch_store):
    """Home broadband is flaky. A retry must replace, never duplicate."""
    worker, job = _finished_job(client)
    retry = client.post(
        f"{API_PREFIX}/workers/jobs/{job['id']}/upload",
        content=_bundle_bytes(),
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )
    assert retry.status_code == 200
    assert len(dispatch_store._uploads) == 1

    download = client.get(f"{API_PREFIX}/workers/jobs/{job['id']}/bundle", headers=auth_headers())
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert archive.namelist() == ["internal_all.csv"]


# --- Store outages fail closed, and never look like a revoked credential -------


class _BrokenWorkerStore:
    """Every `WorkerStore` method raises, as an unreachable Postgres would."""

    def _boom(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise WorkerStoreUnavailableError("cannot reach the worker store: down")

    create = get = list_workers = touch = _boom


@pytest.fixture
def broken_worker_client(tmp_path, dispatch_store) -> TestClient:
    app = create_app(
        store=DiskJobStore(tmp_path / "jobs"),
        url_policy=UrlSafetyPolicy(resolver=lambda h: [PUBLIC_IP]),
        session_secret=TEST_SESSION_SECRET,
        worker_store=_BrokenWorkerStore(),
        worker_dispatch_store=dispatch_store,
        dispatch_signing_secret=DISPATCH_SECRET,
        bundle_encryption_secret=BUNDLE_SECRET,
    )
    with TestClient(app) as test_client:
        yield test_client


def test_registering_a_worker_when_the_store_is_down_is_503(broken_worker_client):
    response = broken_worker_client.post(
        f"{API_PREFIX}/workers", json={"display_name": "d"}, headers=auth_headers()
    )
    assert response.status_code == 503


def test_listing_workers_when_the_store_is_down_is_503(broken_worker_client):
    response = broken_worker_client.get(f"{API_PREFIX}/workers", headers=auth_headers())
    assert response.status_code == 503


def test_a_worker_facing_route_answers_503_not_401_when_the_store_is_down(broken_worker_client):
    """A 401 would tell every healthy daemon its credential had been revoked."""
    for path in ("/workers/dispatch/poll",):
        response = broken_worker_client.get(
            f"{API_PREFIX}{path}", headers=_worker_headers("wkr-alice", "secret")
        )
        assert response.status_code == 503, path

    heartbeat = broken_worker_client.post(
        f"{API_PREFIX}/workers/heartbeat",
        json={"template_names": []},
        headers=_worker_headers("wkr-alice", "secret"),
    )
    assert heartbeat.status_code == 503


def test_reading_worker_templates_when_the_store_is_down_is_503(broken_worker_client):
    response = broken_worker_client.get(
        f"{API_PREFIX}/workers/wkr-alice/templates", headers=auth_headers()
    )
    assert response.status_code == 503


class _BrokenDispatchStore(_FakeWorkerDispatchStore):
    """Reads succeed; everything that touches the queue fails closed."""

    def expire_stale_dispatched(self, *, org_id, older_than_s) -> int:
        raise DispatchStoreUnavailableError("postgres is down")

    def read_upload(self, job_id, *, org_id) -> bytes | None:
        raise DispatchStoreUnavailableError("postgres is down")


@pytest.fixture
def broken_dispatch_client(tmp_path, worker_store) -> TestClient:
    app = create_app(
        store=DiskJobStore(tmp_path / "jobs"),
        url_policy=UrlSafetyPolicy(resolver=lambda h: [PUBLIC_IP]),
        session_secret=TEST_SESSION_SECRET,
        worker_store=worker_store,
        worker_dispatch_store=_BrokenDispatchStore(),
        dispatch_signing_secret=DISPATCH_SECRET,
        bundle_encryption_secret=BUNDLE_SECRET,
    )
    with TestClient(app) as test_client:
        yield test_client


def test_listing_jobs_when_the_dispatch_store_is_down_is_503(broken_dispatch_client):
    response = broken_dispatch_client.get(f"{API_PREFIX}/workers/jobs", headers=auth_headers())
    assert response.status_code == 503


def test_polling_when_the_dispatch_store_is_down_is_503(broken_dispatch_client):
    worker = broken_dispatch_client.post(
        f"{API_PREFIX}/workers", json={"display_name": "d"}, headers=auth_headers()
    ).json()
    response = broken_dispatch_client.get(
        f"{API_PREFIX}/workers/dispatch/poll",
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )
    assert response.status_code == 503
