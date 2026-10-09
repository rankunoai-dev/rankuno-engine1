"""DELETE /jobs/{id} on the Postgres store (audit F2).

`PostgresJobStore` used to drop `password_hash`, so a job created with a
password could never be deleted: every attempt answered 403 "deletion requires
a password". These run the real route over the store's real SQL, against the
in-memory fake cursor `tests/core/test_postgres_store.py` provides.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from src.api.server import API_PREFIX, create_app
from src.core.auth import hash_password
from src.core.postgres_store import PostgresJobStore
from src.core.url_safety import UrlSafetyPolicy

from tests.api.conftest import TEST_SESSION_SECRET, auth_headers
from tests.core.test_postgres_store import _factory, _FakeDB

PUBLIC_IP = "93.184.216.34"


@pytest.fixture
def db() -> _FakeDB:
    return _FakeDB(budgets={"org-a": 5.0})


@pytest.fixture
def store(db: _FakeDB) -> PostgresJobStore:
    return PostgresJobStore(fallback_store=MagicMock(), connection_factory=_factory(db))


@pytest.fixture
def client(tmp_path, store: PostgresJobStore) -> Iterator[TestClient]:
    app = create_app(
        store=store,
        url_policy=UrlSafetyPolicy(resolver=lambda _host: [PUBLIC_IP]),
        deliverable_jobs_root=tmp_path / "deliverable_jobs",
        rulebooks_root=tmp_path / "rulebooks",
        session_secret=TEST_SESSION_SECRET,
    )
    with TestClient(app) as test_client:
        yield test_client


def _delete(client: TestClient, job_id: str, password: str) -> int:
    response = client.request(
        "DELETE",
        f"{API_PREFIX}/jobs/{job_id}",
        json={"password": password},
        headers=auth_headers("org-a", "alice"),
    )
    return response.status_code


def test_wrong_password_is_403_and_the_job_survives(
    client: TestClient, store: PostgresJobStore, db: _FakeDB
) -> None:
    job = store.create(
        "seo_crawl", {"url": "https://a.test"}, org_id="org-a", password_hash=hash_password("right")
    )
    assert _delete(client, job.id, "wrong") == 403
    assert job.id in db.jobs


def test_correct_password_deletes_the_job(
    client: TestClient, store: PostgresJobStore, db: _FakeDB
) -> None:
    job = store.create(
        "seo_crawl", {"url": "https://a.test"}, org_id="org-a", password_hash=hash_password("right")
    )
    # A fresh read, as the route does: the hash must come back from the database.
    assert store.get(job.id).password_hash is not None
    assert _delete(client, job.id, "right") == 204
    assert job.id not in db.jobs
    assert _delete(client, job.id, "right") == 404


def test_job_without_a_password_still_refuses_deletion(
    client: TestClient, store: PostgresJobStore
) -> None:
    job = store.create("seo_crawl", {"url": "https://a.test"}, org_id="org-a")
    assert _delete(client, job.id, "anything") == 403
