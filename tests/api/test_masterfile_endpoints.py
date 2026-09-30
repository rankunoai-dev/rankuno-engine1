"""Tests for `POST /jobs/{id}/masterfile/{slug}` (cycle 0107).

This route shipped with no test coverage at all and could not succeed for any
input: it resolved its CSVs from `state.store.root / job_id / "sf_export"` - a
subdirectory of a flat file store, written by nothing in this repository - and
then read the *deliverable* store's result under a *crawl* job id, which
raises `JobNotFoundError`. Every request was a `409`, and would have been a
`500` had the first check ever passed.

So the load-bearing test here is `test_a_screaming_frog_job_builds_a_masterfile`:
one id in, one deliverable id out, a real workbook downloadable at the end.
The rest pin the failure modes apart, because "no bundle yet", "bundle
expired" and "no such job" are three different things an operator has to be
able to act on differently.
"""

from __future__ import annotations

import io
import time
import uuid
import zipfile
from datetime import UTC, datetime

import openpyxl
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from src.api.server import API_PREFIX, create_app
from src.core.state_store import DiskJobStore
from src.core.url_safety import UrlSafetyPolicy
from src.core.worker_bundle_crypto import encrypt_bytes
from src.core.worker_dispatch_schemas import (
    WorkerJob,
    WorkerJobEnvelope,
    WorkerJobKind,
    WorkerJobStatus,
)
from src.core.worker_dispatch_store import DispatchStoreUnavailableError, WorkerJobNotFoundError
from src.modules.seo.screaming_frog_control.upload_manifest import ALLOWED_BUNDLE_FILENAMES

from tests.api.conftest import TEST_SESSION_SECRET, auth_headers

PUBLIC_IP = "93.184.216.34"
SEED_URL = "https://example.com/"
CRAWLED_URL = "https://example.com/pricing"
BUNDLE_SECRET = SecretStr("test-only-bundle-encryption-secret")
OTHER_BUNDLE_SECRET = SecretStr("a-different-test-only-bundle-secret")

EXPORT: dict[str, str] = {
    "internal_all.csv": (
        "Address,Content Type,Status Code,Indexability,Inlinks\n"
        f"{CRAWLED_URL},text/html,200,Indexable,7\n"
    ),
    "h1_missing.csv": f"Address,Occurrences\n{CRAWLED_URL},0\n",
}


def bundle_bytes() -> bytes:
    """A zip shaped like a real worker upload - allow-listed names, BOM CSVs."""
    assert set(EXPORT) <= ALLOWED_BUNDLE_FILENAMES
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in EXPORT.items():
            archive.writestr(name, body.encode("utf-8-sig"))
    return buffer.getvalue()


class _FakeDispatchStore:
    """The two `WorkerDispatchStore` methods this route calls, and no more.

    Deliberately not the larger fake in `test_worker_routes.py`: that one
    exists to drive the dispatch lifecycle, and importing it here would tie
    this module's fixtures to another file's queue semantics. `read_upload`
    filters on `org_id` and on expiry the same way the Postgres
    implementation does in SQL, so a cross-org or expiry test cannot pass on
    the route's own check alone.
    """

    def __init__(self) -> None:
        self.jobs: dict[str, WorkerJob] = {}
        self.uploads: dict[str, bytes] = {}
        self.expired: set[str] = set()
        self.unavailable = False

    def add_job(
        self,
        *,
        org_id: str = "org-a",
        status: WorkerJobStatus = WorkerJobStatus.SUCCEEDED,
        bundle: bytes | None = None,
        secret: SecretStr = BUNDLE_SECRET,
        expired: bool = False,
    ) -> str:
        job_id = uuid.uuid4().hex
        now = datetime.now(UTC)
        self.jobs[job_id] = WorkerJob(
            id=job_id,
            org_id=org_id,
            worker_id="wkr-desktop-1",
            kind=WorkerJobKind.SCREAMING_FROG_CRAWL,
            envelope=WorkerJobEnvelope(
                job_id=job_id,
                seed_url=SEED_URL,
                template_name="default",
                correlation_id="ui-abc-123",
            ),
            status=status,
            created_at=now,
            updated_at=now,
            bundle_size_bytes=None if bundle is None else len(bundle),
        )
        if bundle is not None:
            self.uploads[job_id] = encrypt_bytes(bundle, secret=secret)
        if expired:
            self.expired.add(job_id)
        return job_id

    def get_job(self, job_id: str) -> WorkerJob:
        if self.unavailable:
            raise DispatchStoreUnavailableError("dispatch store is unreachable")
        try:
            return self.jobs[job_id]
        except KeyError:
            raise WorkerJobNotFoundError(job_id) from None

    def read_upload(self, job_id: str, *, org_id: str) -> bytes | None:
        job = self.jobs.get(job_id)
        if job is None or job.org_id != org_id or job_id in self.expired:
            return None
        return self.uploads.get(job_id)


@pytest.fixture
def crawl_store(tmp_path) -> DiskJobStore:
    return DiskJobStore(tmp_path / "jobs")


@pytest.fixture
def dispatch_store() -> _FakeDispatchStore:
    return _FakeDispatchStore()


@pytest.fixture
def client(tmp_path, crawl_store, dispatch_store) -> TestClient:
    app = create_app(
        store=crawl_store,
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        deliverable_jobs_root=tmp_path / "deliverable_jobs",
        rulebooks_root=tmp_path / "rulebooks",
        session_secret=TEST_SESSION_SECRET,
        worker_dispatch_store=dispatch_store,
        bundle_encryption_secret=BUNDLE_SECRET,
    )
    with TestClient(app) as test_client:
        yield test_client


def poll_deliverable(client: TestClient, deliverable_id: str, org_id: str = "org-a") -> dict:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        body = client.get(
            f"{API_PREFIX}/deliverables/{deliverable_id}", headers=auth_headers(org_id)
        ).json()
        if body["status"] in ("succeeded", "partial", "failed"):
            return body
        time.sleep(0.02)
    pytest.fail(f"deliverable {deliverable_id} never reached a terminal status")


def build(client: TestClient, job_id: str, slug: str = "h1", org_id: str = "org-a"):
    return client.post(
        f"{API_PREFIX}/jobs/{job_id}/masterfile/{slug}", headers=auth_headers(org_id)
    )


class TestScreamingFrogMasterfile:
    def test_a_screaming_frog_job_builds_a_masterfile(self, client, dispatch_store) -> None:
        """The whole point: one id sent, one id polled, a real workbook out."""
        job_id = dispatch_store.add_job(bundle=bundle_bytes())

        accepted = build(client, job_id)
        assert accepted.status_code == 202, accepted.text
        body = accepted.json()
        assert body["label"] == f"{SEED_URL} — h1"

        finished = poll_deliverable(client, body["id"])
        assert finished["status"] == "succeeded", finished.get("error")

        download = client.get(
            f"{API_PREFIX}/deliverables/{body['id']}/download", headers=auth_headers("org-a")
        )
        assert download.status_code == 200, download.text
        sheet = openpyxl.load_workbook(io.BytesIO(download.content)).active
        assert sheet is not None
        rows = [tuple(row) for row in sheet.iter_rows(values_only=True)]
        assert any(row[0] == CRAWLED_URL for row in rows), rows

    def test_the_deliverable_records_its_source_job(self, client, dispatch_store) -> None:
        job_id = dispatch_store.add_job(bundle=bundle_bytes())
        body = build(client, job_id).json()
        poll_deliverable(client, body["id"])

        record = client.get(
            f"{API_PREFIX}/deliverables/{body['id']}", headers=auth_headers("org-a")
        ).json()
        assert record["request"]["source_job_id"] == job_id
        assert record["request"]["service_slug"] == "h1"

    def test_a_partial_crawl_bundle_still_builds(self, client, dispatch_store) -> None:
        """`PARTIAL` means the run degraded, not that the export is unusable."""
        job_id = dispatch_store.add_job(bundle=bundle_bytes(), status=WorkerJobStatus.PARTIAL)
        assert build(client, job_id).status_code == 202


class TestFailureModesAreDistinguishable:
    def test_a_job_with_no_uploaded_bundle_is_409(self, client, dispatch_store) -> None:
        job_id = dispatch_store.add_job(status=WorkerJobStatus.DISPATCHED, bundle=None)
        response = build(client, job_id)
        assert response.status_code == 409
        assert "uploaded no export bundle" in response.json()["detail"]

    def test_a_bundle_past_its_retention_window_is_410(self, client, dispatch_store) -> None:
        """Gone, not missing: the job is right there, its bundle is not."""
        job_id = dispatch_store.add_job(bundle=bundle_bytes(), expired=True)
        response = build(client, job_id)
        assert response.status_code == 410
        assert "retention window" in response.json()["detail"]

    def test_an_unknown_id_is_404(self, client) -> None:
        response = build(client, "0" * 32)
        assert response.status_code == 404
        assert "no job" in response.json()["detail"]

    def test_another_orgs_job_is_403(self, client, dispatch_store) -> None:
        job_id = dispatch_store.add_job(org_id="org-b", bundle=bundle_bytes())
        assert build(client, job_id, org_id="org-a").status_code == 403

    def test_an_unknown_service_is_404_before_any_lookup(self, client, dispatch_store) -> None:
        job_id = dispatch_store.add_job(bundle=bundle_bytes())
        response = build(client, job_id, slug="not_a_service")
        assert response.status_code == 404
        assert "unknown masterfile service" in response.json()["detail"]

    def test_an_undecryptable_bundle_is_500_naming_the_setting(
        self, client, dispatch_store
    ) -> None:
        job_id = dispatch_store.add_job(bundle=bundle_bytes(), secret=OTHER_BUNDLE_SECRET)
        response = build(client, job_id)
        assert response.status_code == 500
        assert "WORKER_BUNDLE_ENCRYPTION_SECRET" in response.json()["detail"]

    def test_an_unreachable_dispatch_store_is_503(self, client, dispatch_store) -> None:
        dispatch_store.unavailable = True
        assert build(client, "0" * 32).status_code == 503

    def test_authentication_is_required(self, client, dispatch_store) -> None:
        job_id = dispatch_store.add_job(bundle=bundle_bytes())
        assert client.post(f"{API_PREFIX}/jobs/{job_id}/masterfile/h1").status_code == 401


class TestNativeCrawlJobs:
    def test_a_native_crawl_job_is_refused_with_a_reason(self, client, crawl_store) -> None:
        """It has no Screaming Frog CSVs and never will - say that, not 500."""
        record = crawl_store.create("seo.page_classifier", {"base_url": SEED_URL}, org_id="org-a")
        crawl_store.finish(record.id, {"base_url": SEED_URL})

        response = build(client, record.id)
        assert response.status_code == 409
        assert "native engine crawl" in response.json()["detail"]

    def test_another_orgs_crawl_job_is_403_not_a_reason(self, client, crawl_store) -> None:
        """The refusal must not confirm that another org's id exists."""
        record = crawl_store.create("seo.page_classifier", {"base_url": SEED_URL}, org_id="org-b")
        assert build(client, record.id, org_id="org-a").status_code == 403


class TestBatchDownload:
    """Build every measurable masterfile and ZIP them into one download."""

    def test_batch_builds_a_zip_with_all_measurable_services(self, client, dispatch_store) -> None:
        job_id = dispatch_store.add_job(bundle=bundle_bytes())

        accepted = client.post(
            f"{API_PREFIX}/jobs/{job_id}/masterfiles/all", headers=auth_headers("org-a")
        )
        assert accepted.status_code == 202, accepted.text
        body = accepted.json()
        assert "all masterfiles" in body["label"]

        finished = poll_deliverable(client, body["id"])
        assert finished["status"] == "succeeded", finished.get("error")

        download = client.get(
            f"{API_PREFIX}/deliverables/{body['id']}/download", headers=auth_headers("org-a")
        )
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/zip"

        with zipfile.ZipFile(io.BytesIO(download.content)) as zf:
            names = set(zf.namelist())
            assert "h1.xlsx" in names
            assert len(names) >= 10

    def test_batch_records_source_and_service_list(self, client, dispatch_store) -> None:
        job_id = dispatch_store.add_job(bundle=bundle_bytes())
        body = client.post(
            f"{API_PREFIX}/jobs/{job_id}/masterfiles/all", headers=auth_headers("org-a")
        ).json()

        finished = poll_deliverable(client, body["id"])
        assert finished["status"] == "succeeded"
        assert finished["has_result"] is True

        record = client.get(
            f"{API_PREFIX}/deliverables/{body['id']}", headers=auth_headers("org-a")
        ).json()
        assert record["request"]["source"] == "masterfile_batch"
        assert len(record["request"]["services"]) > 0

    def test_batch_rejects_native_crawl_job(self, client, crawl_store) -> None:
        record = crawl_store.create("seo.page_classifier", {"base_url": SEED_URL}, org_id="org-a")
        crawl_store.finish(record.id, {"base_url": SEED_URL})

        response = client.post(
            f"{API_PREFIX}/jobs/{record.id}/masterfiles/all", headers=auth_headers("org-a")
        )
        assert response.status_code == 409
        assert "native engine crawl" in response.json()["detail"]

    def test_batch_requires_authentication(self, client, dispatch_store) -> None:
        job_id = dispatch_store.add_job(bundle=bundle_bytes())
        assert client.post(f"{API_PREFIX}/jobs/{job_id}/masterfiles/all").status_code == 401


class TestAvailableServices:
    """What the masterfile menu is allowed to claim.

    It used to advertise twenty-one identical buttons, four of which
    could not put a row in a workbook: their source file is not in
    `ALLOWED_BUNDLE_FILENAMES`, so no bundle this engine produces can carry
    it. The endpoint now says which, and says why.
    """

    def available(self, client) -> list[dict[str, object]]:
        response = client.get(f"{API_PREFIX}/masterfiles/available")
        assert response.status_code == 200
        return response.json()["services"]

    def test_every_advertised_slug_is_listed(self, client) -> None:
        listed = self.available(client)
        assert len(listed) == 21
        assert {entry["slug"] for entry in listed} >= {"h1", "custom_extraction"}

    def test_a_service_with_no_reachable_export_is_flagged_with_a_reason(self, client) -> None:
        """Flagged and kept, never dropped from the list.

        An operator looking for Custom Extraction has to
        find it and read why it is unavailable; hidden would teach them the
        feature does not exist.
        """
        by_slug = {entry["slug"]: entry for entry in self.available(client)}

        unmeasurable = {slug for slug, entry in by_slug.items() if not entry["measurable"]}
        assert unmeasurable == {
            "custom_extraction",
            "custom_search_ga4_gtm",
            "custom_search_og_twitter",
            "functional_internal_links",
        }
        for slug in unmeasurable:
            assert by_slug[slug]["reason"]

    def test_a_working_service_carries_the_flag_and_no_reason(self, client) -> None:
        by_slug = {entry["slug"]: entry for entry in self.available(client)}

        assert by_slug["h1"] == {"slug": "h1", "measurable": True, "reason": None}
        assert len([e for e in by_slug.values() if e["measurable"]]) == 17

    def test_the_flag_is_not_an_enforcement_point(self, client, dispatch_store) -> None:
        """A flagged service is still buildable.

        A loose export directory can
        hold files an uploaded bundle may not, and refusing here would break
        that path to fix a display problem.
        """
        job_id = dispatch_store.add_job(bundle=bundle_bytes())

        assert build(client, job_id, slug="custom_extraction").status_code == 202
