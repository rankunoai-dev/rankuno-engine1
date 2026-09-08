"""Named Search Console profiles at the API boundary.

Two properties, and every test here is about one of them:

* The account list publishes **names only**. A profile is a refresh token with
  a label, and the label is all a browser is ever shown.
* An unknown name is refused at admission, on every path that starts a crawl.
  Never defaulted: a crawl that silently reads a different client's Search
  Console is worse than one that does not start.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from src.api import server as server_module
from src.api.server import API_PREFIX, create_app
from src.core.config import Settings
from src.core.state_store import DiskJobStore
from src.core.url_safety import UrlSafetyPolicy

PUBLIC_IP = "93.184.216.34"
SAFE_URL = "https://e.com/"
REFRESH_TOKEN = "rt-acme-1//0gSecretValueThatMustNeverLeave"  # noqa: S105 - fake, for leak checks


class StubResult:
    """Stands in for `ToolResult` without importing the generic machinery."""

    ok = True
    data: dict[str, object] = {"base_url": SAFE_URL}
    error: str | None = None


class StubTool:
    """A `PageClassificationTool` that returns instantly instead of crawling."""

    def __init__(self, **_kwargs: object) -> None:
        """Accept and ignore the real tool's constructor arguments."""

    def run(self, _payload: object) -> StubResult:
        return StubResult()


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "google_oauth_client_id": "shared-id",
        "google_oauth_client_secret": SecretStr("shared-secret"),
        "google_oauth_refresh_token": SecretStr("default-rt"),
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def store(tmp_path) -> DiskJobStore:
    return DiskJobStore(tmp_path / "jobs")


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setattr(server_module, "PageClassificationTool", StubTool)
    app = create_app(
        store=store,
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def configured(monkeypatch):
    """Two named profiles plus the flat default. The secrets are what leak checks hunt."""
    settings = _settings(
        gsc_accounts={
            "acme": {"refresh_token": REFRESH_TOKEN},
            "globex": {"refresh_token": "rt-globex", "client_id": "globex-id"},
        }
    )
    monkeypatch.setattr(server_module, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def unconfigured(monkeypatch):
    settings = _settings()
    monkeypatch.setattr(server_module, "get_settings", lambda: settings)
    return settings


def post_job(client, **overrides: object):
    body = {"base_url": SAFE_URL, "max_pages": 5, "crawl_dom": False, **overrides}
    return client.post(f"{API_PREFIX}/jobs", json=body)


class TestListAccounts:
    def test_lists_names_only(self, client, configured):
        response = client.get(f"{API_PREFIX}/gsc/accounts")
        assert response.status_code == 200
        assert response.json() == {"accounts": ["acme", "globex"]}

    def test_body_carries_no_credential(self, client, configured):
        """The whole point of a names-only view. Checked against the raw text."""
        text = client.get(f"{API_PREFIX}/gsc/accounts").text
        for secret in (REFRESH_TOKEN, "rt-globex", "globex-id", "shared-secret", "default-rt"):
            assert secret not in text

    def test_empty_when_unconfigured(self, client, unconfigured):
        assert client.get(f"{API_PREFIX}/gsc/accounts").json() == {"accounts": []}


class TestCreateJobWithAccount:
    def test_unknown_account_is_400_and_creates_no_job(self, client, store, configured):
        response = post_job(client, gsc_account="initech")
        assert response.status_code == 400
        assert response.json()["detail"] == "unknown GSC account 'initech'"
        assert store.list_jobs() == []

    def test_known_account_is_accepted(self, client, store, configured):
        response = post_job(client, gsc_account="acme")
        assert response.status_code == 202, response.text
        assert store.get(response.json()["id"]).request["gsc_account"] == "acme"

    def test_no_account_is_unchanged(self, client, unconfigured):
        """The single-account path predates profiles and must keep working."""
        assert post_job(client).status_code == 202
        assert post_job(client, gsc_account=None).status_code == 202

    def test_unknown_account_is_400_even_with_none_configured(self, client, store, unconfigured):
        """No profiles at all is not a reason to fall back to the default."""
        assert post_job(client, gsc_account="acme").status_code == 400
        assert store.list_jobs() == []

    def test_malformed_name_is_422(self, client, configured):
        """Shape is the schema's job; existence is admission's. Different codes."""
        assert post_job(client, gsc_account="Acme Corp").status_code == 422


class TestReplayWithAccount:
    def test_retry_with_a_now_unknown_account_is_400(self, client, store, configured):
        """A profile deleted from `.env.local` between runs must not be replayed."""
        record = store.create(
            server_module.TOOL_NAME,
            {"base_url": SAFE_URL, "max_pages": 5, "crawl_dom": False, "gsc_account": "initech"},
        )
        response = client.post(f"{API_PREFIX}/jobs/{record.id}/retry")
        assert response.status_code == 400
        assert "initech" in response.json()["detail"]
        assert len(store.list_jobs()) == 1

    def test_retry_with_a_known_account_is_accepted(self, client, store, configured):
        record = store.create(
            server_module.TOOL_NAME,
            {"base_url": SAFE_URL, "max_pages": 5, "crawl_dom": False, "gsc_account": "globex"},
        )
        assert client.post(f"{API_PREFIX}/jobs/{record.id}/retry").status_code == 202
