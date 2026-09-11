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


class TestOrgLevelGscAccounts:
    """Tests for organization-level GSC account management."""

    @pytest.fixture
    def org_config_store(self, tmp_path):
        """Create an organization config store for testing."""
        from src.core.state_store import DiskOrgConfigStore
        from src.core.schemas import OrgConfig

        store = DiskOrgConfigStore(tmp_path / "orgs")
        # Create a default test organization
        org = OrgConfig(
            org_id="test-org",
            display_name="Test Organization",
        )
        store.create(org)
        return store

    @pytest.fixture
    def org_client(self, store, org_config_store, monkeypatch):
        """Create a test client with organization config store."""
        monkeypatch.setattr(server_module, "PageClassificationTool", StubTool)
        app = server_module.create_app(
            store=store,
            url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
            org_config_store=org_config_store,
        )
        with TestClient(app) as test_client:
            yield test_client

    def test_list_org_gsc_accounts_empty(self, org_client):
        """List GSC accounts for an org with no accounts."""
        response = org_client.get(f"{API_PREFIX}/orgs/test-org/gsc-accounts")
        assert response.status_code == 200
        assert response.json() == {"accounts": []}

    def test_list_org_gsc_accounts_nonexistent_org(self, org_client):
        """Listing accounts for a nonexistent org returns 404."""
        response = org_client.get(f"{API_PREFIX}/orgs/nonexistent/gsc-accounts")
        assert response.status_code == 404

    def test_create_org_gsc_account(self, org_client):
        """Create a new GSC account for an organization."""
        body = {
            "account_name": "acme",
            "refresh_token": "rt-acme-token",
            "client_id": "client-id-acme",
        }
        response = org_client.post(
            f"{API_PREFIX}/orgs/test-org/gsc-accounts",
            json=body,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["account_name"] == "acme"
        assert data["client_id"] == "client-id-acme"
        assert data["has_secret_override"] is False

    def test_create_org_gsc_account_with_secret_override(self, org_client):
        """Create an account with a custom client secret."""
        body = {
            "account_name": "globex",
            "refresh_token": "rt-globex",
            "client_id": "globex-id",
            "client_secret": "globex-secret",
        }
        response = org_client.post(
            f"{API_PREFIX}/orgs/test-org/gsc-accounts",
            json=body,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["has_secret_override"] is True

    def test_create_org_gsc_account_invalid_name(self, org_client):
        """Account name must match ^[a-z0-9_-]{1,64}$."""
        # Invalid: uppercase
        response = org_client.post(
            f"{API_PREFIX}/orgs/test-org/gsc-accounts",
            json={
                "account_name": "Acme",
                "refresh_token": "rt-token",
            },
        )
        assert response.status_code == 400
        assert "Account name must match" in response.json()["detail"]

    def test_create_org_gsc_account_invalid_name_too_long(self, org_client):
        """Account name must not exceed 64 characters."""
        response = org_client.post(
            f"{API_PREFIX}/orgs/test-org/gsc-accounts",
            json={
                "account_name": "a" * 65,
                "refresh_token": "rt-token",
            },
        )
        assert response.status_code == 400

    def test_create_org_gsc_account_for_nonexistent_org(self, org_client):
        """Creating an account for a nonexistent org returns 404."""
        response = org_client.post(
            f"{API_PREFIX}/orgs/nonexistent/gsc-accounts",
            json={
                "account_name": "acme",
                "refresh_token": "rt-token",
            },
        )
        assert response.status_code == 404

    def test_list_org_gsc_accounts_after_create(self, org_client):
        """List accounts returns the created account."""
        # Create two accounts
        for name in ["acme", "globex"]:
            org_client.post(
                f"{API_PREFIX}/orgs/test-org/gsc-accounts",
                json={
                    "account_name": name,
                    "refresh_token": f"rt-{name}",
                },
            )

        # List them
        response = org_client.get(f"{API_PREFIX}/orgs/test-org/gsc-accounts")
        assert response.status_code == 200
        data = response.json()
        assert len(data["accounts"]) == 2
        names = [acc["account_name"] for acc in data["accounts"]]
        assert names == ["acme", "globex"]  # Should be sorted

    def test_delete_org_gsc_account(self, org_client):
        """Delete a GSC account from an organization."""
        # Create an account
        org_client.post(
            f"{API_PREFIX}/orgs/test-org/gsc-accounts",
            json={
                "account_name": "temp-account",
                "refresh_token": "rt-temp",
            },
        )

        # Delete it
        response = org_client.delete(f"{API_PREFIX}/orgs/test-org/gsc-accounts/temp-account")
        assert response.status_code == 204

        # Verify it's gone
        response = org_client.get(f"{API_PREFIX}/orgs/test-org/gsc-accounts")
        accounts = response.json()["accounts"]
        assert len(accounts) == 0

    def test_delete_org_gsc_account_nonexistent_account(self, org_client):
        """Deleting a nonexistent account returns 404."""
        response = org_client.delete(f"{API_PREFIX}/orgs/test-org/gsc-accounts/nonexistent")
        assert response.status_code == 404

    def test_delete_org_gsc_account_nonexistent_org(self, org_client):
        """Deleting from a nonexistent org returns 404."""
        response = org_client.delete(f"{API_PREFIX}/orgs/nonexistent/gsc-accounts/acme")
        assert response.status_code == 404

    def test_credential_secret_not_exposed_in_list(self, org_client):
        """List response must never expose refresh tokens or secrets."""
        org_client.post(
            f"{API_PREFIX}/orgs/test-org/gsc-accounts",
            json={
                "account_name": "secret-account",
                "refresh_token": "rt-super-secret-token",
                "client_secret": "secret-value-12345",
            },
        )

        response = org_client.get(f"{API_PREFIX}/orgs/test-org/gsc-accounts")
        text = response.text
        assert "rt-super-secret-token" not in text
        assert "secret-value-12345" not in text
