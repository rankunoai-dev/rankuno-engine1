"""Tests for Idempotency-Key header handling in create_job endpoint.

These tests verify that duplicate requests with the same Idempotency-Key
return the existing job instead of creating a new one.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from src.api.server import create_app
from src.core.schemas import OrgConfig
from src.core.state_store import DiskJobStore

from tests.api.conftest import TEST_SESSION_SECRET, auth_headers


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the API."""
    app = create_app(DiskJobStore(".jobs"), session_secret=TEST_SESSION_SECRET)
    return TestClient(app, headers=auth_headers())


class TestIdempotencyKeyDeduplication:
    """Tests for idempotency key deduplication."""

    def test_first_request_creates_job(self, client: TestClient) -> None:
        """First request with Idempotency-Key should create a job."""
        payload = {
            "base_url": "https://example.com",
            "max_depth": 2,
            "crawl_dom": True,
            "respect_robots": True,
            "llm_spend_cap_usd": 0.0,
        }

        response = client.post(
            "/api/v1/jobs",
            json=payload,
            headers={"Idempotency-Key": "test-key-001"},
        )

        assert response.status_code == 202
        data = response.json()
        assert "id" in data
        assert "status" in data

    def test_duplicate_request_returns_existing_job(self, client: TestClient) -> None:
        """Duplicate request with same Idempotency-Key should return existing job."""
        payload = {
            "base_url": "https://example.com",
            "max_depth": 2,
            "crawl_dom": True,
            "respect_robots": True,
            "llm_spend_cap_usd": 0.0,
        }

        # First request
        response1 = client.post(
            "/api/v1/jobs",
            json=payload,
            headers={"Idempotency-Key": "test-key-002"},
        )
        assert response1.status_code == 202
        job1 = response1.json()
        job1_id = job1["id"]

        # Duplicate request
        response2 = client.post(
            "/api/v1/jobs",
            json=payload,
            headers={"Idempotency-Key": "test-key-002"},
        )
        assert response2.status_code == 202
        job2 = response2.json()
        job2_id = job2["id"]

        # Should return the same job
        assert job1_id == job2_id

    def test_different_idempotency_keys_create_different_jobs(self, client: TestClient) -> None:
        """Different Idempotency-Key values should create different jobs."""
        payload = {
            "base_url": "https://example.com",
            "max_depth": 2,
            "crawl_dom": True,
            "respect_robots": True,
            "llm_spend_cap_usd": 0.0,
        }

        response1 = client.post(
            "/api/v1/jobs",
            json=payload,
            headers={"Idempotency-Key": "test-key-003"},
        )
        job1_id = response1.json()["id"]

        response2 = client.post(
            "/api/v1/jobs",
            json=payload,
            headers={"Idempotency-Key": "test-key-004"},
        )
        job2_id = response2.json()["id"]

        # Should create different jobs
        assert job1_id != job2_id

    def test_request_without_idempotency_key_always_creates_new_job(
        self, client: TestClient
    ) -> None:
        """Requests without Idempotency-Key should always create new jobs."""
        payload = {
            "base_url": "https://example.com",
            "max_depth": 2,
            "crawl_dom": True,
            "respect_robots": True,
            "llm_spend_cap_usd": 0.0,
        }

        response1 = client.post("/api/v1/jobs", json=payload)
        job1_id = response1.json()["id"]

        response2 = client.post("/api/v1/jobs", json=payload)
        job2_id = response2.json()["id"]

        # Should create different jobs even without idempotency key
        assert job1_id != job2_id

    def test_idempotency_key_per_org(self, client: TestClient) -> None:
        """Same Idempotency-Key for different orgs should create different jobs.

        Org comes from the verified session token now (ADR 0016 condition 4),
        never from a header — `create_job` no longer reads `X-Org-Id` at all,
        so this authenticates as two different orgs via two different tokens
        instead. Both orgs must exist in this fixture's (real, unmocked)
        org config store before a job can be admitted, so this seeds them
        directly rather than relying on `default` being auto-created.
        """
        payload = {
            "base_url": "https://example.com",
            "max_depth": 2,
            "crawl_dom": True,
            "respect_robots": True,
            "llm_spend_cap_usd": 0.0,
        }
        org_store = client.app.state.api.org_config_store
        for org_id in ("org1", "org2"):
            try:
                org_store.get(org_id)
            except KeyError:
                org_store.create(OrgConfig(org_id=org_id, display_name=org_id))

        response1 = client.post(
            "/api/v1/jobs",
            json=payload,
            headers={"Idempotency-Key": "test-key-005", **auth_headers(org_id="org1")},
        )
        assert response1.status_code == 202, response1.text
        job1_id = response1.json()["id"]

        response2 = client.post(
            "/api/v1/jobs",
            json=payload,
            headers={"Idempotency-Key": "test-key-005", **auth_headers(org_id="org2")},
        )
        assert response2.status_code == 202, response2.text
        job2_id = response2.json()["id"]

        # Should create different jobs for different orgs
        assert job1_id != job2_id
