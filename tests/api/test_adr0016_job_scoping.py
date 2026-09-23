"""ADR 0016 conditions 2 and 3: the job-family org-ownership retrofit.

Fifteen routes read, mutated, or served a job-scoped artefact by `job_id`
with **zero** org-ownership check before this ADR: the fourteen the ADR
names by direct inspection (`get_checkpoint`, `retry_job`, `reparse_job`,
`reconcile_screaming_frog`, `cancel_job`, `resume_job`, `get_reconciliation`,
`download_reconciliation`, `get_performance`, `download_opportunities`,
`download_opportunities_workbook`, `download_matched`, `download_unmatched`,
`download_reconciliation_workbook`) plus `upload_gsc`, found by the same
direct inspection this implementation cycle did and fixed alongside them
for the identical reason, even though the ADR's own route enumeration does
not name it (a correction recorded in the build log, not a silent addition).

Every test below proves the same shape: an authenticated caller from `org-b`
must get `403` (or the route's own `404`-before-ownership-check where a
prerequisite is missing) when it reaches for a job `org-a` owns — never the
data, never a silent default. `test_resume_job_...` additionally covers
condition 3: `resume_job` must attribute the resumed crawl to the original
job's org, not silently to `default`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from src.api.server import API_PREFIX, create_app
from src.core.schemas import OrgConfig
from src.core.state_store import DiskJobStore, DiskOrgConfigStore, JobStatus
from src.core.url_safety import UrlSafetyPolicy

from tests.api.conftest import TEST_SESSION_SECRET, auth_headers

PUBLIC_IP = "93.184.216.34"
SAFE_URL = "https://e.com/"


@pytest.fixture
def store(tmp_path) -> DiskJobStore:
    return DiskJobStore(tmp_path / "jobs")


@pytest.fixture
def org_store(tmp_path) -> DiskOrgConfigStore:
    store = DiskOrgConfigStore(tmp_path / "orgs")
    store.create(OrgConfig(org_id="org-a", display_name="Org A"))
    store.create(OrgConfig(org_id="org-b", display_name="Org B"))
    return store


@pytest.fixture
def client(store, org_store) -> TestClient:
    """Authenticated as `org-a`."""
    app = create_app(
        store=store,
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        org_config_store=org_store,
        session_secret=TEST_SESSION_SECRET,
    )
    with TestClient(app, headers=auth_headers(org_id="org-a")) as test_client:
        yield test_client


@pytest.fixture
def victim_job_id(store) -> str:
    """A finished job owned by `org-b` — the record `org-a` must never reach."""
    record = store.create(
        "seo.page_classifier", {"base_url": SAFE_URL}, label="victim", org_id="org-b"
    )
    store.finish(record.id, {"base_url": SAFE_URL, "pages": []})
    return record.id


class TestCrossOrgDenialOnPreviouslyUncheckedRoutes:
    """Each of these returned data (or acted) for any org before this ADR."""

    def test_get_checkpoint(self, client, store, victim_job_id):
        store.write_checkpoint(victim_job_id, {"base_url": SAFE_URL, "urls": [SAFE_URL]})
        response = client.get(f"{API_PREFIX}/jobs/{victim_job_id}/checkpoint")
        assert response.status_code == 403

    def test_retry_job(self, client, victim_job_id):
        response = client.post(f"{API_PREFIX}/jobs/{victim_job_id}/retry")
        assert response.status_code == 403

    def test_reparse_job(self, client, victim_job_id):
        response = client.post(f"{API_PREFIX}/jobs/{victim_job_id}/reparse")
        assert response.status_code == 403

    def test_reconcile_screaming_frog(self, client, victim_job_id):
        response = client.post(
            f"{API_PREFIX}/jobs/{victim_job_id}/reconcile/screaming-frog",
            content=b"Address\nhttps://e.com/\n",
            headers={"Content-Type": "text/csv"},
        )
        assert response.status_code == 403

    def test_cancel_job(self, client, store, victim_job_id):
        # Cancel only applies to a non-terminal job; use a fresh queued one.
        record = store.create("seo.page_classifier", {"base_url": SAFE_URL}, org_id="org-b")
        response = client.post(f"{API_PREFIX}/jobs/{record.id}/cancel")
        assert response.status_code == 403
        assert store.get(record.id).status is JobStatus.QUEUED

    def test_resume_job(self, client, store, victim_job_id):
        store.write_checkpoint(
            victim_job_id, {"base_url": SAFE_URL, "urls": [SAFE_URL], "unfetched": [SAFE_URL]}
        )
        response = client.post(f"{API_PREFIX}/jobs/{victim_job_id}/resume")
        assert response.status_code == 403

    def test_get_reconciliation(self, client, store, victim_job_id):
        store.write_reconciliation(victim_job_id, {"summary": {}, "created_at": "2026-01-01"})
        response = client.get(f"{API_PREFIX}/jobs/{victim_job_id}/reconciliation")
        assert response.status_code == 403

    def test_download_reconciliation(self, client, store, victim_job_id):
        store.write_reconciliation(victim_job_id, {"summary": {}, "created_at": "2026-01-01"})
        response = client.get(f"{API_PREFIX}/jobs/{victim_job_id}/reconciliation.csv")
        assert response.status_code == 403

    def test_download_reconciliation_workbook(self, client, store, victim_job_id):
        store.write_reconciliation(victim_job_id, {"summary": {}, "created_at": "2026-01-01"})
        response = client.get(f"{API_PREFIX}/jobs/{victim_job_id}/reconciliation.xlsx")
        assert response.status_code == 403

    def test_download_urls_workbook(self, client, victim_job_id):
        """Not in the ADR's fourteen.

        Added alongside `urls.xlsx` itself, so this route never had a window
        where it lacked the check.
        """
        response = client.get(f"{API_PREFIX}/jobs/{victim_job_id}/urls.xlsx")
        assert response.status_code == 403

    def test_get_performance(self, client, store, victim_job_id):
        store.write_performance(victim_job_id, {"summary": {}, "created_at": "2026-01-01"})
        response = client.get(f"{API_PREFIX}/jobs/{victim_job_id}/performance")
        assert response.status_code == 403

    def test_download_opportunities(self, client, store, victim_job_id):
        store.write_performance(victim_job_id, {"summary": {}, "created_at": "2026-01-01"})
        response = client.get(f"{API_PREFIX}/jobs/{victim_job_id}/opportunities.csv")
        assert response.status_code == 403

    def test_download_opportunities_workbook(self, client, store, victim_job_id):
        store.write_performance(victim_job_id, {"summary": {}, "created_at": "2026-01-01"})
        response = client.get(f"{API_PREFIX}/jobs/{victim_job_id}/opportunities.xlsx")
        assert response.status_code == 403

    def test_download_matched(self, client, store, victim_job_id):
        store.write_performance(victim_job_id, {"summary": {}, "created_at": "2026-01-01"})
        response = client.get(f"{API_PREFIX}/jobs/{victim_job_id}/matched.csv")
        assert response.status_code == 403

    def test_download_unmatched(self, client, store, victim_job_id):
        store.write_performance(victim_job_id, {"summary": {}, "created_at": "2026-01-01"})
        response = client.get(f"{API_PREFIX}/jobs/{victim_job_id}/unmatched.csv")
        assert response.status_code == 403

    def test_upload_gsc(self, client, victim_job_id):
        """Not in the ADR's fourteen — found and fixed alongside them (see module docstring)."""
        response = client.post(
            f"{API_PREFIX}/jobs/{victim_job_id}/performance/gsc",
            content=b"Top pages\nhttps://e.com/,1,1,1%,1.0\n",
        )
        assert response.status_code == 403


class TestOwnOrgStillWorks:
    """The retrofit must not collaterally deny a caller acting on their own job."""

    def test_get_checkpoint_on_own_job(self, client, store, org_store):
        record = store.create("seo.page_classifier", {"base_url": SAFE_URL}, org_id="org-a")
        store.write_checkpoint(record.id, {"base_url": SAFE_URL, "urls": [SAFE_URL]})
        response = client.get(f"{API_PREFIX}/jobs/{record.id}/checkpoint")
        assert response.status_code == 200

    def test_cancel_own_job(self, client, store):
        record = store.create("seo.page_classifier", {"base_url": SAFE_URL}, org_id="org-a")
        response = client.post(f"{API_PREFIX}/jobs/{record.id}/cancel")
        assert response.status_code == 200


class TestUnauthenticatedIsRejected:
    """No bearer token at all must be `401` on every retrofitted route, not a default."""

    @pytest.mark.parametrize(
        ("method", "path_suffix"),
        [
            ("get", "/checkpoint"),
            ("post", "/retry"),
            ("post", "/reparse"),
            ("post", "/cancel"),
            ("post", "/resume"),
            ("get", "/reconciliation"),
            ("get", "/reconciliation.csv"),
            ("get", "/performance"),
            ("get", "/opportunities.csv"),
            ("get", "/opportunities.xlsx"),
            ("get", "/urls.xlsx"),
            ("get", "/matched.csv"),
            ("get", "/unmatched.csv"),
            ("post", "/reconcile/screaming-frog"),
            ("post", "/performance/gsc"),
        ],
    )
    def test_route_requires_authentication(self, store, org_store, method, path_suffix):
        app = create_app(
            store=store,
            url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
            org_config_store=org_store,
            session_secret=TEST_SESSION_SECRET,
        )
        record = store.create("seo.page_classifier", {"base_url": SAFE_URL}, org_id="org-a")
        with TestClient(app) as anonymous_client:
            response = getattr(anonymous_client, method)(
                f"{API_PREFIX}/jobs/{record.id}{path_suffix}"
            )
        assert response.status_code == 401


class TestResumeJobOrgAttribution:
    """ADR 0016 condition 3: `resume_job` must not silently default to 'default'."""

    def test_resumed_job_keeps_the_original_org(self, client, store):
        """Condition 3 regression: resumed jobs used to lose their org.

        `resume_job` previously omitted `org_id`, so every resumed crawl was
        silently misattributed to 'default' regardless of who owned it — the
        same fix `retry_job` already applied correctly.
        """
        record = store.create(
            "seo.page_classifier",
            {"base_url": SAFE_URL, "max_pages": 5, "crawl_dom": False},
            org_id="org-a",
        )
        store.finish(record.id, {"base_url": SAFE_URL, "pages": []})
        store.write_checkpoint(
            record.id,
            {
                "base_url": SAFE_URL,
                "urls": [SAFE_URL, f"{SAFE_URL}a"],
                "unfetched": [f"{SAFE_URL}a"],
            },
        )

        response = client.post(f"{API_PREFIX}/jobs/{record.id}/resume")

        assert response.status_code == 202, response.text
        resumed_id = response.json()["id"]
        assert store.get(resumed_id).org_id == "org-a"


class TestPerPrincipalRateLimit:
    """ADR 0016 condition 7: a rate-limit key partitioned per principal.

    Distinct from `web.crawl` and from `ApiState._active`/`_facet_active`'s
    process-global concurrency caps, so one bad actor cannot starve every
    other org's admission capacity.
    """

    def test_create_job_is_refused_once_the_principal_bucket_is_empty(self, client):
        state = client.app.state.api
        bucket = state.principal_rate_limiter.get_or_create("principal:test-operator")
        while bucket.try_acquire():
            pass  # Drain it completely — the rate check runs before org lookup.

        response = client.post(
            f"{API_PREFIX}/jobs",
            json={"base_url": SAFE_URL, "max_pages": 5, "crawl_dom": False},
        )
        assert response.status_code == 429

    def test_a_different_principal_is_unaffected(self, client, store, org_store):
        state = client.app.state.api
        bucket = state.principal_rate_limiter.get_or_create("principal:test-operator")
        while bucket.try_acquire():
            pass

        # Same client object, but a token for a different operator entirely —
        # the exhausted bucket above must not apply to it.
        response = client.post(
            f"{API_PREFIX}/jobs",
            json={"base_url": SAFE_URL, "max_pages": 5, "crawl_dom": False},
            headers=auth_headers(org_id="org-a", operator_id="a-different-operator"),
        )
        assert response.status_code != 429

    def test_the_bucket_is_scoped_to_this_apistate_not_shared_globally(self, store, org_store):
        """A fresh `create_app()` call must not inherit a drained bucket.

        Each test app gets its own rate-limit registry.
        """
        app = create_app(
            store=store,
            url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
            org_config_store=org_store,
            session_secret=TEST_SESSION_SECRET,
        )
        assert app.state.api.principal_rate_limiter.get_or_create(
            "principal:test-operator"
        ).try_acquire()
