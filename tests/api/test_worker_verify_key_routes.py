"""ADR 0028 over HTTP: the published verify key, and what a poll now mints.

`GET /workers/dispatch-verify-key` is what lets a worker installer stop asking
the operator for the shared HMAC secret. These tests prove it is behind
operator authentication, publishes exactly the key the poll route signs with,
and refuses — rather than inventing a key — on a deployment that has not
configured Ed25519 yet.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.api.server import API_PREFIX, create_app
from src.api.worker_verify_key_routes import build_dispatch_verify_key_router
from src.core.state_store import DiskJobStore
from src.core.url_safety import UrlSafetyPolicy
from src.core.worker_auth import DiskWorkerStore
from src.core.worker_dispatch_keys import DispatchSigningKey, DispatchVerifyKey
from src.core.worker_dispatch_signing import (
    DispatchAssignmentError,
    verify_dispatch_assignment,
)

from tests.api.conftest import TEST_SESSION_SECRET, auth_headers
from tests.api.test_worker_routes import (
    BUNDLE_SECRET,
    DISPATCH_SECRET,
    PUBLIC_IP,
    _FakeWorkerDispatchStore,
    _preview_and_confirm,
    _register_worker,
    _worker_headers,
)

SIGNING_KEY = DispatchSigningKey.generate()
URL = f"{API_PREFIX}/workers/dispatch-verify-key"


@pytest.fixture
def client(tmp_path) -> TestClient:
    app = create_app(
        store=DiskJobStore(tmp_path / "jobs"),
        url_policy=UrlSafetyPolicy(resolver=lambda _h: [PUBLIC_IP]),
        session_secret=TEST_SESSION_SECRET,
        worker_store=DiskWorkerStore(tmp_path / "workers"),
        worker_dispatch_store=_FakeWorkerDispatchStore(),
        dispatch_signing_secret=DISPATCH_SECRET,
        dispatch_signing_key=SIGNING_KEY,
        bundle_encryption_secret=BUNDLE_SECRET,
    )
    with TestClient(app) as test_client:
        yield test_client


def test_the_verify_key_requires_an_operator_session(client):
    assert client.get(URL).status_code == 401
    assert client.get(URL, headers={"Authorization": "Bearer forged"}).status_code == 401


def test_a_worker_credential_is_not_an_operator_session(client):
    worker = _register_worker(client)
    response = client.get(
        URL, headers=_worker_headers(worker["worker_id"], worker["worker_secret"])
    )
    assert response.status_code == 401


def test_the_verify_key_is_the_public_half_of_the_signing_key(client):
    response = client.get(URL, headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "algorithm": "Ed25519",
        "kid": SIGNING_KEY.kid,
        "public_key": SIGNING_KEY.public_key_b64,
    }
    assert SIGNING_KEY.private_key_secret().get_secret_value() not in response.text


def test_a_deployment_without_an_ed25519_key_answers_503_not_a_made_up_key():
    state = SimpleNamespace(session_secret=TEST_SESSION_SECRET, dispatch_signing_key=None)
    app = FastAPI()
    app.include_router(build_dispatch_verify_key_router(state), prefix=API_PREFIX)  # type: ignore[arg-type]
    response = TestClient(app).get(URL, headers=auth_headers())
    assert response.status_code == 503
    assert "WORKER_DISPATCH_SIGNING_PRIVATE_KEY" in response.json()["detail"]


def test_a_poll_during_the_transition_verifies_on_old_and_new_workers(client):
    """Dual-signed: the published key verifies it, and so does the legacy secret."""
    worker = _register_worker(client)
    _preview_and_confirm(client, worker_id=worker["worker_id"])
    poll = client.get(
        f"{API_PREFIX}/workers/dispatch/poll",
        headers=_worker_headers(worker["worker_id"], worker["worker_secret"]),
    )
    token = poll.json()["assignment"]["token"]
    published = DispatchVerifyKey.from_base64(
        client.get(URL, headers=auth_headers()).json()["public_key"]
    )
    identity = {"worker_id": worker["worker_id"], "org_id": "default"}

    assert verify_dispatch_assignment(token, verify_key=published, **identity).seed_url == (
        "https://e.com/"
    )
    assert verify_dispatch_assignment(token, secret=DISPATCH_SECRET, **identity).seed_url == (
        "https://e.com/"
    )
    with pytest.raises(DispatchAssignmentError):
        verify_dispatch_assignment(
            token, verify_key=DispatchSigningKey.generate().verify_key, **identity
        )


def test_the_cloud_refuses_to_start_with_no_way_to_sign(tmp_path, monkeypatch):
    """Fail closed: neither an Ed25519 key nor an emitting HMAC secret resolves."""
    from src.core.config import Settings
    from src.core.errors import ConfigurationError

    monkeypatch.setattr(Settings, "dispatch_ed25519_signing_key", property(lambda _s: None))
    monkeypatch.setattr(Settings, "dispatch_hmac_issuing_secret", property(lambda _s: None))
    with pytest.raises(ConfigurationError, match="WORKER_DISPATCH_SIGNING_PRIVATE_KEY"):
        create_app(
            store=DiskJobStore(tmp_path / "jobs"),
            url_policy=UrlSafetyPolicy(resolver=lambda _h: [PUBLIC_IP]),
            session_secret=TEST_SESSION_SECRET,
            worker_store=DiskWorkerStore(tmp_path / "workers"),
            worker_dispatch_store=_FakeWorkerDispatchStore(),
            bundle_encryption_secret=BUNDLE_SECRET,
        )
