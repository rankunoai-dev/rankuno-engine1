"""End-to-end tests for revoking and rotating a desktop worker's credential.

Every "is it rejected?" assertion goes through the real worker auth
dependency (`require_worker_principal` -> `verify_worker_credential`) by
calling a real daemon route, not by reading `is_active` back from the store:
the defect these routes close was a flag that existed and that nothing
acted on, so asserting the flag alone would prove nothing.
"""

from __future__ import annotations

import json
from typing import NoReturn

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from src.api.server import API_PREFIX, create_app
from src.core.state_store import DiskJobStore
from src.core.url_safety import UrlSafetyPolicy
from src.core.worker_auth import DiskWorkerStore, WorkerStoreUnavailableError
from src.core.worker_dispatch_schemas import WorkerJobStatus

from tests.api.conftest import TEST_SESSION_SECRET, auth_headers
from tests.api.test_worker_routes import (
    BUNDLE_SECRET,
    DISPATCH_SECRET,
    PUBLIC_IP,
    _FakeWorkerDispatchStore,
    _preview_and_confirm,
)


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


def _register(client: TestClient, org_id: str = "default") -> dict[str, str]:
    response = client.post(
        f"{API_PREFIX}/workers", json={"display_name": "desk"}, headers=auth_headers(org_id)
    )
    assert response.status_code == 201, response.text
    body: dict[str, str] = response.json()
    return body


def _bearer(worker_id: str, secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {worker_id}:{secret}"}


def _poll(client: TestClient, worker_id: str, secret: str) -> int:
    response = client.get(f"{API_PREFIX}/workers/dispatch/poll", headers=_bearer(worker_id, secret))
    return response.status_code


def _revoke(client: TestClient, worker_id: str, org_id: str = "default") -> Response:
    return client.post(f"{API_PREFIX}/workers/{worker_id}/revoke", headers=auth_headers(org_id))


def _rotate(client: TestClient, worker_id: str, org_id: str = "default") -> Response:
    return client.post(
        f"{API_PREFIX}/workers/{worker_id}/rotate-credential", headers=auth_headers(org_id)
    )


# --- revoke ---------------------------------------------------------------------


def test_revoked_worker_is_rejected_by_the_real_auth_dependency(client):
    worker = _register(client)
    assert _poll(client, worker["worker_id"], worker["worker_secret"]) == 200

    response = _revoke(client, worker["worker_id"])

    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False
    assert response.json()["is_online"] is False
    assert _poll(client, worker["worker_id"], worker["worker_secret"]) == 401
    heartbeat = client.post(
        f"{API_PREFIX}/workers/heartbeat",
        json={"templates": []},
        headers=_bearer(worker["worker_id"], worker["worker_secret"]),
    )
    assert heartbeat.status_code == 401


def test_revoke_is_idempotent(client):
    worker = _register(client)
    assert _revoke(client, worker["worker_id"]).status_code == 200
    again = _revoke(client, worker["worker_id"])
    assert again.status_code == 200
    assert again.json()["is_active"] is False


def test_revoked_worker_is_listed_as_inactive(client):
    worker = _register(client)
    _revoke(client, worker["worker_id"])
    listed = client.get(f"{API_PREFIX}/workers", headers=auth_headers()).json()["workers"]
    assert [(w["worker_id"], w["is_active"]) for w in listed] == [(worker["worker_id"], False)]


def test_revoke_response_never_carries_a_secret_or_hash(client, worker_store):
    worker = _register(client)
    body = _revoke(client, worker["worker_id"]).text
    assert worker["worker_secret"] not in body
    assert worker_store.get(worker["worker_id"]).secret_hash not in body
    assert "secret" not in json.loads(body)


def test_revoke_of_another_orgs_worker_is_indistinguishable_from_unknown(client):
    worker = _register(client, org_id="acme")

    cross = _revoke(client, worker["worker_id"], org_id="globex")
    unknown = _revoke(client, "wkr-does-not-exist", org_id="globex")

    assert cross.status_code == unknown.status_code == 404
    # And the victim's credential still works: nothing was changed.
    assert _poll(client, worker["worker_id"], worker["worker_secret"]) == 200


def test_revoke_requires_authentication(client):
    worker = _register(client)
    response = client.post(f"{API_PREFIX}/workers/{worker['worker_id']}/revoke")
    assert response.status_code == 401
    assert _poll(client, worker["worker_id"], worker["worker_secret"]) == 200


def test_revoked_worker_cannot_upload_or_report_an_in_flight_job(client, dispatch_store):
    worker = _register(client)
    headers = _bearer(worker["worker_id"], worker["worker_secret"])
    _poll(client, worker["worker_id"], worker["worker_secret"])  # online, so dispatch is allowed
    job_id = _preview_and_confirm(client, worker_id=worker["worker_id"])["id"]
    claimed = client.get(f"{API_PREFIX}/workers/dispatch/poll", headers=headers)
    assert claimed.json()["assignment"] is not None

    _revoke(client, worker["worker_id"])

    upload = client.post(
        f"{API_PREFIX}/workers/jobs/{job_id}/upload", content=b"zip", headers=headers
    )
    failed = client.post(
        f"{API_PREFIX}/workers/jobs/{job_id}/failed", json={"error": "x"}, headers=headers
    )
    progress = client.post(f"{API_PREFIX}/workers/jobs/{job_id}/progress", json={}, headers=headers)
    assert (upload.status_code, failed.status_code, progress.status_code) == (401, 401, 401)
    # Left for the existing stale-dispatch sweep; revoke does not touch jobs.
    assert dispatch_store.get_job(job_id).status is WorkerJobStatus.DISPATCHED


# --- rotate ---------------------------------------------------------------------


def test_rotate_rejects_the_old_secret_and_accepts_the_new_one(client):
    worker = _register(client)

    response = _rotate(client, worker["worker_id"])

    assert response.status_code == 200, response.text
    rotated = response.json()
    assert rotated["worker_id"] == worker["worker_id"]
    assert rotated["org_id"] == "default"
    assert rotated["worker_secret"] != worker["worker_secret"]
    assert _poll(client, worker["worker_id"], worker["worker_secret"]) == 401
    assert _poll(client, worker["worker_id"], rotated["worker_secret"]) == 200


def test_rotate_returns_the_secret_exactly_once_and_stores_only_a_hash(client, worker_store):
    worker = _register(client)
    response = _rotate(client, worker["worker_id"])
    secret = response.json()["worker_secret"]

    assert response.text.count(secret) == 1
    stored = worker_store.get(worker["worker_id"])
    assert stored.secret_hash.startswith("pbkdf2_")
    assert secret not in stored.secret_hash
    on_disk = (worker_store._root / "workers.json").read_text(encoding="utf-8")
    assert secret not in on_disk


def test_rotate_is_the_recovery_path_after_a_revoke(client):
    worker = _register(client)
    _revoke(client, worker["worker_id"])

    rotated = _rotate(client, worker["worker_id"]).json()

    assert _poll(client, worker["worker_id"], worker["worker_secret"]) == 401
    assert _poll(client, worker["worker_id"], rotated["worker_secret"]) == 200


def test_rotate_marks_the_worker_offline_until_the_new_secret_checks_in(client):
    worker = _register(client)
    _poll(client, worker["worker_id"], worker["worker_secret"])

    _rotate(client, worker["worker_id"])

    listed = client.get(f"{API_PREFIX}/workers", headers=auth_headers()).json()["workers"]
    assert listed[0]["is_online"] is False
    assert listed[0]["last_seen_at"] is None


def test_rotate_of_another_orgs_worker_is_404_and_changes_nothing(client):
    worker = _register(client, org_id="acme")

    response = _rotate(client, worker["worker_id"], org_id="globex")

    assert response.status_code == 404
    assert "worker_secret" not in response.text
    assert _poll(client, worker["worker_id"], worker["worker_secret"]) == 200


def test_rotate_requires_authentication(client):
    worker = _register(client)
    response = client.post(f"{API_PREFIX}/workers/{worker['worker_id']}/rotate-credential")
    assert response.status_code == 401
    assert _poll(client, worker["worker_id"], worker["worker_secret"]) == 200


# --- store outage ---------------------------------------------------------------


def _unavailable(*_args: object, **_kwargs: object) -> NoReturn:
    raise WorkerStoreUnavailableError("database down")


@pytest.mark.parametrize("action", [_revoke, _rotate])
def test_store_outage_is_503_not_404(client, worker_store, monkeypatch, action):
    worker = _register(client)
    monkeypatch.setattr(worker_store, "set_active", _unavailable)
    monkeypatch.setattr(worker_store, "replace_credential", _unavailable)
    assert action(client, worker["worker_id"]).status_code == 503
