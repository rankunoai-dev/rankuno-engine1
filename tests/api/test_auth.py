"""Tests for the ADR 0016 HTTP-layer glue.

`require_principal`, `org_scoped_or_404`, and the `POST /auth/login` route.
Token/password mechanics themselves are `tests/core/test_auth.py`'s job;
this file is about the HTTP translation — which status code, which header,
which detail message — and about the login route's own admission logic
(wrong password, unknown operator, inactive operator, rate limiting).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from src.api.auth import LoginRequest, org_scoped_or_404, require_principal
from src.api.server import API_PREFIX, _seed_bootstrap_operator, create_app
from src.core.auth import DiskOperatorStore, Operator, hash_password, verify_password
from src.core.config import Settings
from src.core.state_store import DiskJobStore
from src.core.url_safety import UrlSafetyPolicy

from tests.api.conftest import TEST_SESSION_SECRET, mint_token

PUBLIC_IP = "93.184.216.34"


class _Record:
    """A minimal stand-in for `JobRecord`/`RulebookRecord` — only `org_id` matters."""

    def __init__(self, org_id: str) -> None:
        self.org_id = org_id


# --- require_principal --------------------------------------------------------


def test_require_principal_accepts_a_valid_token():
    token = mint_token(org_id="acme")
    principal = require_principal(f"Bearer {token}", session_secret=TEST_SESSION_SECRET)
    assert principal.org_id == "acme"


def test_require_principal_rejects_a_missing_header():
    with pytest.raises(HTTPException) as exc_info:
        require_principal(None, session_secret=TEST_SESSION_SECRET)
    assert exc_info.value.status_code == 401


def test_require_principal_rejects_an_empty_header():
    with pytest.raises(HTTPException) as exc_info:
        require_principal("", session_secret=TEST_SESSION_SECRET)
    assert exc_info.value.status_code == 401


@pytest.mark.parametrize(
    "malformed",
    [
        "not-a-bearer-token",
        "Basic dXNlcjpwYXNz",
        "bearer",
        "Bearer",
        "Bearer ",
    ],
)
def test_require_principal_rejects_a_non_bearer_scheme(malformed: str):
    with pytest.raises(HTTPException) as exc_info:
        require_principal(malformed, session_secret=TEST_SESSION_SECRET)
    assert exc_info.value.status_code == 401


def test_require_principal_rejects_a_token_signed_with_a_different_secret():
    token = mint_token(org_id="acme")
    with pytest.raises(HTTPException) as exc_info:
        require_principal(f"Bearer {token}", session_secret=SecretStr("a-different-key"))
    assert exc_info.value.status_code == 401


# --- org_scoped_or_404 ---------------------------------------------------------


def test_org_scoped_or_404_allows_the_owning_org():
    record = _Record(org_id="acme")
    org_scoped_or_404(record=record, record_id="job-1", org_id="acme", kind="job")  # no raise


def test_org_scoped_or_404_denies_a_different_org():
    record = _Record(org_id="acme")
    with pytest.raises(HTTPException) as exc_info:
        org_scoped_or_404(record=record, record_id="job-1", org_id="someone-else", kind="job")
    assert exc_info.value.status_code == 403


# --- POST /auth/login -----------------------------------------------------------


@pytest.fixture
def operator_store(tmp_path) -> DiskOperatorStore:
    store = DiskOperatorStore(tmp_path / "operators")
    store.create(
        Operator(
            operator_id="alice",
            org_id="acme",
            display_name="Alice",
            password_hash=hash_password("correct horse battery staple"),
        )
    )
    store.create(
        Operator(
            operator_id="disabled-bob",
            org_id="acme",
            display_name="Bob",
            password_hash=hash_password("whatever"),
            is_active=False,
        )
    )
    return store


@pytest.fixture
def login_client(tmp_path, operator_store) -> TestClient:
    app = create_app(
        store=DiskJobStore(tmp_path / "jobs"),
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        operator_store=operator_store,
        session_secret=TEST_SESSION_SECRET,
    )
    with TestClient(app) as client:
        yield client


def test_login_with_correct_credentials_issues_a_token(login_client):
    response = login_client.post(
        f"{API_PREFIX}/auth/login",
        json={"operator_id": "alice", "password": "correct horse battery staple"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["org_id"] == "acme"
    assert body["token_type"] == "bearer"  # noqa: S105 - an auth scheme name, not a credential
    assert body["token"]

    # The issued token must actually authenticate against this same app.
    protected = login_client.get(
        f"{API_PREFIX}/jobs", headers={"Authorization": f"Bearer {body['token']}"}
    )
    assert protected.status_code == 200


def test_login_with_wrong_password_is_401(login_client):
    response = login_client.post(
        f"{API_PREFIX}/auth/login",
        json={"operator_id": "alice", "password": "wrong password entirely"},
    )
    assert response.status_code == 401


def test_login_with_unknown_operator_is_401(login_client):
    response = login_client.post(
        f"{API_PREFIX}/auth/login",
        json={"operator_id": "nobody-registered", "password": "anything"},
    )
    assert response.status_code == 401


def test_login_response_is_identically_shaped_for_unknown_vs_wrong_password(login_client):
    """A response that let a caller tell the two apart is a username-enumeration oracle."""
    unknown = login_client.post(
        f"{API_PREFIX}/auth/login",
        json={"operator_id": "nobody-registered", "password": "anything"},
    )
    wrong_password = login_client.post(
        f"{API_PREFIX}/auth/login",
        json={"operator_id": "alice", "password": "wrong password entirely"},
    )
    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.json() == wrong_password.json()


def test_login_with_inactive_operator_is_401(login_client):
    response = login_client.post(
        f"{API_PREFIX}/auth/login",
        json={"operator_id": "disabled-bob", "password": "whatever"},
    )
    assert response.status_code == 401


def test_login_is_rate_limited_per_operator(login_client):
    """A brute-force loop against one operator id must eventually be refused."""
    statuses = [
        login_client.post(
            f"{API_PREFIX}/auth/login",
            json={"operator_id": "alice", "password": "wrong"},
        ).status_code
        for _ in range(15)
    ]
    assert 429 in statuses


def test_login_rejects_extra_fields():
    """`LoginRequest` is a `StrictModel`: an unexpected field is a validation error."""
    with pytest.raises(ValidationError, match="extra"):
        LoginRequest.model_validate({"operator_id": "alice", "password": "x", "is_admin": True})


def test_build_auth_router_is_mounted_under_the_api_prefix(tmp_path, operator_store):
    """A smoke test that the factory wiring in `create_app` is actually in effect.

    Posting a malformed body proves the route itself exists and is reachable
    (a `422` from FastAPI's own validation) rather than inspecting FastAPI's
    internal router structure, which differs across versions.
    """
    app = create_app(
        store=DiskJobStore(tmp_path / "jobs"),
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        operator_store=operator_store,
        session_secret=TEST_SESSION_SECRET,
    )
    with TestClient(app) as client:
        response = client.post(f"{API_PREFIX}/auth/login", json={})
    assert response.status_code == 422


# --- _seed_bootstrap_operator ---------------------------------------------------


def _bootstrap_settings(tmp_path, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "audit_log_path": tmp_path / "audit.jsonl",
    }
    base.update(overrides)
    return Settings(**base)


def test_seed_bootstrap_operator_creates_one_when_configured(tmp_path):
    """The only way to log in before any operator exists (see the function's own docstring)."""
    store = DiskOperatorStore(tmp_path / "operators")
    settings = _bootstrap_settings(
        tmp_path,
        auth_bootstrap_operator_id="alice",
        auth_bootstrap_operator_password=SecretStr("correct horse battery staple"),
        auth_bootstrap_operator_org_id="acme",
    )

    _seed_bootstrap_operator(store, settings)

    operator = store.get("alice")
    assert operator.org_id == "acme"
    assert verify_password("correct horse battery staple", operator.password_hash)


def test_seed_bootstrap_operator_is_a_noop_without_bootstrap_settings(tmp_path):
    store = DiskOperatorStore(tmp_path / "operators")
    settings = _bootstrap_settings(tmp_path)

    _seed_bootstrap_operator(store, settings)

    assert store.list_operators() == []


def test_seed_bootstrap_operator_never_overwrites_an_existing_operator(tmp_path):
    """Runs on every `create_app()` call; must act at most once per store."""
    store = DiskOperatorStore(tmp_path / "operators")
    store.create(
        Operator(
            operator_id="alice",
            org_id="acme",
            display_name="Alice",
            password_hash=hash_password("the-real-password"),
        )
    )
    settings = _bootstrap_settings(
        tmp_path,
        auth_bootstrap_operator_id="alice",
        auth_bootstrap_operator_password=SecretStr("attacker-supplied-password"),
    )

    _seed_bootstrap_operator(store, settings)

    assert verify_password("the-real-password", store.get("alice").password_hash)
