"""Named Search Console profiles at the API boundary.

Two properties, and every test here is about one of them:

* The account list publishes **names only**. A profile is a refresh token with
  a label, and the label is all a browser is ever shown.
* An unknown name is refused at admission, on every path that starts a crawl.
  Never defaulted: a crawl that silently reads a different client's Search
  Console is worse than one that does not start.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from src.api import server as server_module
from src.api.server import API_PREFIX, create_app
from src.core.config import Settings
from src.core.schemas import GscAccountCredential, OrgConfig
from src.core.state_store import DiskJobStore, DiskOrgConfigStore
from src.core.url_safety import UrlSafetyPolicy

from tests.api.conftest import TEST_SESSION_SECRET, auth_headers

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
def org_store(tmp_path) -> DiskOrgConfigStore:
    """An isolated org store holding only the auto-created default org.

    Passed explicitly so no test here reads the workstation's real
    `.orgs/org_configs.json` — accounts an operator added on this machine would
    otherwise show up in the account list these tests assert on.
    """
    return DiskOrgConfigStore(tmp_path / "orgs")


@pytest.fixture
def client(store, org_store, monkeypatch):
    monkeypatch.setattr(server_module, "PageClassificationTool", StubTool)
    app = create_app(
        store=store,
        url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
        org_config_store=org_store,
        session_secret=TEST_SESSION_SECRET,
    )
    with TestClient(app, headers=auth_headers()) as test_client:
        yield test_client


def add_org_account(org_store, name: str, *, org_id: str = "default") -> None:
    """Store a GSC account against an org, as the UI tab's POST does."""
    org = org_store.get(org_id)
    org.gsc_accounts[name] = GscAccountCredential(refresh_token=SecretStr(f"rt-{name}-org"))
    org_store.update(org)


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
        from src.core.schemas import OrgConfig
        from src.core.state_store import DiskOrgConfigStore

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
        """Create a test client authenticated as `test-org` (ADR 0016).

        These routes now derive `org_id` from the verified principal, not
        the URL — so the client has to actually be `test-org` for the
        `.../orgs/test-org/...` calls throughout this class to succeed at
        all, the same way a real caller would need to be.
        """
        monkeypatch.setattr(server_module, "PageClassificationTool", StubTool)
        app = server_module.create_app(
            store=store,
            url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
            org_config_store=org_config_store,
            session_secret=TEST_SESSION_SECRET,
        )
        with TestClient(app, headers=auth_headers(org_id="test-org")) as test_client:
            yield test_client

    def test_list_org_gsc_accounts_empty(self, org_client):
        """List GSC accounts for an org with no accounts."""
        response = org_client.get(f"{API_PREFIX}/orgs/test-org/gsc-accounts")
        assert response.status_code == 200
        assert response.json() == {"accounts": []}

    def test_list_org_gsc_accounts_nonexistent_org(self, org_client):
        """A path `org_id` other than the caller's own is 403, existing or not.

        ADR 0016 condition 1 (the CRITICAL finding this ADR closes): the
        path segment is never ground truth, so a mismatch is refused before
        an existence check ever runs — a caller unaffiliated with `nonexistent`
        must not be able to distinguish "wrong org" from "no such org" either.
        """
        response = org_client.get(f"{API_PREFIX}/orgs/nonexistent/gsc-accounts")
        assert response.status_code == 403

    def test_list_own_org_gsc_accounts_when_org_config_missing_is_404(
        self, store, org_config_store, monkeypatch
    ):
        """The caller's *own* org can still 404 if its config was deleted.

        Distinct from the mismatch case above: here `org_id` in the path
        equals the verified principal's own org, so the mismatch check
        passes and the underlying `org_config_store.get()` lookup is what
        produces the `404`.
        """
        monkeypatch.setattr(server_module, "PageClassificationTool", StubTool)
        app = server_module.create_app(
            store=store,
            url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
            org_config_store=org_config_store,
            session_secret=TEST_SESSION_SECRET,
        )
        with TestClient(app, headers=auth_headers(org_id="ghost-org")) as ghost_client:
            response = ghost_client.get(f"{API_PREFIX}/orgs/ghost-org/gsc-accounts")
        assert response.status_code == 404

    def test_create_own_org_gsc_account_when_org_config_missing_is_404(
        self, store, org_config_store, monkeypatch
    ):
        """Same as the list case, for create: own org, but no stored config."""
        monkeypatch.setattr(server_module, "PageClassificationTool", StubTool)
        app = server_module.create_app(
            store=store,
            url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
            org_config_store=org_config_store,
            session_secret=TEST_SESSION_SECRET,
        )
        with TestClient(app, headers=auth_headers(org_id="ghost-org")) as ghost_client:
            response = ghost_client.post(
                f"{API_PREFIX}/orgs/ghost-org/gsc-accounts",
                json={"account_name": "acme", "refresh_token": "rt-token"},
            )
        assert response.status_code == 404

    def test_delete_own_org_gsc_account_when_org_config_missing_is_404(
        self, store, org_config_store, monkeypatch
    ):
        """Same as the list case, for delete: own org, but no stored config."""
        monkeypatch.setattr(server_module, "PageClassificationTool", StubTool)
        app = server_module.create_app(
            store=store,
            url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
            org_config_store=org_config_store,
            session_secret=TEST_SESSION_SECRET,
        )
        with TestClient(app, headers=auth_headers(org_id="ghost-org")) as ghost_client:
            response = ghost_client.delete(f"{API_PREFIX}/orgs/ghost-org/gsc-accounts/acme")
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
        """A path `org_id` other than the caller's own is 403 (ADR 0016 condition 1).

        The CRITICAL finding this ADR closes: this route previously wrote a
        third party's Google OAuth refresh token for any `org_id` the URL
        named. It must now refuse before ever touching the store.
        """
        response = org_client.post(
            f"{API_PREFIX}/orgs/nonexistent/gsc-accounts",
            json={
                "account_name": "acme",
                "refresh_token": "rt-token",
            },
        )
        assert response.status_code == 403

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
        """A path `org_id` other than the caller's own is 403 (ADR 0016 condition 1).

        The CRITICAL finding this ADR closes: this route previously deleted
        any org's stored GSC credential for any `org_id` the URL named. It
        must now refuse before ever touching the store.
        """
        response = org_client.delete(f"{API_PREFIX}/orgs/nonexistent/gsc-accounts/acme")
        assert response.status_code == 403

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


class TestOrgGscAccountCrossOrgAccessDenied:
    """ADR 0016 condition 1 — the CRITICAL finding.

    Before this ADR, these three routes accepted `org_id` as a raw path
    parameter with zero verification: full read/write access to any
    organization's Google OAuth `refresh_token` for anyone who could guess
    an `org_id` string. Every test here uses a *real* victim org (not a
    nonexistent one, which the tests above already cover) so the fix is
    proven against the actual exploit, not just a 404 lookup miss.
    """

    @pytest.fixture
    def two_orgs(self, tmp_path) -> DiskOrgConfigStore:
        store = DiskOrgConfigStore(tmp_path / "orgs")
        store.create(OrgConfig(org_id="org-a", display_name="Org A"))
        store.create(OrgConfig(org_id="org-b", display_name="Org B"))
        return store

    @pytest.fixture
    def two_org_client(self, tmp_path, two_orgs, monkeypatch) -> TestClient:
        """Authenticated as `org-a`. `org-b` is a real, separate victim org."""
        monkeypatch.setattr(server_module, "PageClassificationTool", StubTool)
        app = server_module.create_app(
            store=DiskJobStore(tmp_path / "jobs"),
            url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
            org_config_store=two_orgs,
            session_secret=TEST_SESSION_SECRET,
        )
        with TestClient(app, headers=auth_headers(org_id="org-a")) as client:
            yield client

    def test_cannot_list_another_real_orgs_gsc_accounts(self, two_org_client, two_orgs):
        add_org_account(two_orgs, "victim-account", org_id="org-b")
        response = two_org_client.get(f"{API_PREFIX}/orgs/org-b/gsc-accounts")
        assert response.status_code == 403
        assert "victim-account" not in response.text

    def test_cannot_create_a_gsc_account_for_another_real_org(self, two_org_client, two_orgs):
        response = two_org_client.post(
            f"{API_PREFIX}/orgs/org-b/gsc-accounts",
            json={"account_name": "planted", "refresh_token": "rt-attacker-planted"},
        )
        assert response.status_code == 403
        # Nothing was written to the victim org.
        assert "planted" not in two_orgs.get("org-b").gsc_accounts

    def test_cannot_delete_another_real_orgs_gsc_account(self, two_org_client, two_orgs):
        add_org_account(two_orgs, "victim-account", org_id="org-b")
        response = two_org_client.delete(f"{API_PREFIX}/orgs/org-b/gsc-accounts/victim-account")
        assert response.status_code == 403
        # The victim's account survives the attempt.
        assert "victim-account" in two_orgs.get("org-b").gsc_accounts

    def test_own_org_still_works_unaffected(self, two_org_client, two_orgs):
        """The fix must not collaterally break a caller acting on their own org."""
        response = two_org_client.post(
            f"{API_PREFIX}/orgs/org-a/gsc-accounts",
            json={"account_name": "own-account", "refresh_token": "rt-own"},
        )
        assert response.status_code == 201
        assert "own-account" in two_orgs.get("org-a").gsc_accounts

    def test_unauthenticated_request_is_401_not_400_or_404(self, two_org_client):
        """No bearer token at all must be `401`, before any org check runs."""
        response = two_org_client.get(
            f"{API_PREFIX}/orgs/org-a/gsc-accounts", headers={"Authorization": ""}
        )
        assert response.status_code == 401


class TestOrgAccountsAreSelectable:
    """An account added in the UI must be choosable for a crawl.

    The defect: the tab wrote to the org store and the picker read `.env.local`,
    so an operator could add an account and then never use it. Both endpoints
    answered truthfully about different sets, which is why nothing looked broken.
    """

    def test_the_picker_list_includes_org_stored_accounts(self, client, org_store, configured):
        add_org_account(org_store, "initech")
        response = client.get(f"{API_PREFIX}/gsc/accounts")
        assert response.status_code == 200
        assert response.json() == {"accounts": ["acme", "globex", "initech"]}

    def test_the_picker_list_is_still_names_only(self, client, org_store, configured):
        """An org credential must not reach the browser any more than an env one."""
        add_org_account(org_store, "initech")
        assert "rt-initech-org" not in client.get(f"{API_PREFIX}/gsc/accounts").text

    def test_the_picker_list_works_with_no_env_profiles(self, client, org_store, unconfigured):
        """The org store alone is a complete answer."""
        add_org_account(org_store, "initech")
        assert client.get(f"{API_PREFIX}/gsc/accounts").json() == {"accounts": ["initech"]}

    def test_an_unknown_org_is_not_an_error_for_the_list(self, client, configured):
        """An org with no stored accounts degrades to the env profiles, never a 500.

        The org still has to be a real, authenticated principal's own org
        (ADR 0016 condition 4) — a stale `X-Org-Id` header naming a
        different org, previously enough to steer this response, is now
        inert; only the verified token's claim matters.
        """
        response = client.get(f"{API_PREFIX}/gsc/accounts", headers=auth_headers(org_id="nobody"))
        assert response.status_code == 200
        assert response.json() == {"accounts": ["acme", "globex"]}

    def test_a_stale_org_header_no_longer_has_any_effect(self, client, configured):
        """`X-Org-Id` is dead weight now — only the verified token's org counts.

        The default `client` fixture authenticates as `default`, which has
        no org-stored accounts here; setting `X-Org-Id` to a different,
        even nonexistent, org must not change the response at all.
        """
        response = client.get(f"{API_PREFIX}/gsc/accounts", headers={"X-Org-Id": "someone-else"})
        assert response.status_code == 200
        assert response.json() == {"accounts": ["acme", "globex"]}

    def test_another_orgs_accounts_are_not_listed(self, client, org_store, configured):
        team_a = OrgConfig(org_id="team-a", display_name="Team A")
        org_store.create(team_a)
        add_org_account(org_store, "initech", org_id="team-a")
        assert client.get(f"{API_PREFIX}/gsc/accounts").json() == {"accounts": ["acme", "globex"]}

    def test_an_org_stored_account_is_accepted_at_admission(
        self, client, store, org_store, configured
    ):
        """Previously 400: admission checked `.env.local` and nothing else."""
        add_org_account(org_store, "initech")
        response = post_job(client, gsc_account="initech")
        assert response.status_code == 202, response.text
        assert store.get(response.json()["id"]).request["gsc_account"] == "initech"

    def test_an_account_in_neither_source_is_still_refused(self, client, store, org_store):
        add_org_account(org_store, "initech")
        assert post_job(client, gsc_account="nobody").status_code == 400
        assert store.list_jobs() == []


class TestTheCrawlIsToldItsOrg:
    """The crawl resolves the credential, so it needs to know whose it may read.

    Admission accepting an org-stored name is only half a fix: the tool runs on a
    worker thread with nothing but its payload, and the payload deliberately does
    not carry the org — a request that could name its own tenant could name
    someone else's refresh token.
    """

    def test_the_tool_is_built_with_the_jobs_org(self, store, org_store, monkeypatch):
        captured: dict[str, object] = {}

        class Capturing(StubTool):
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

        monkeypatch.setattr(server_module, "PageClassificationTool", Capturing)
        org_store.create(OrgConfig(org_id="team-a", display_name="Team A"))

        app = create_app(
            store=store,
            url_policy=UrlSafetyPolicy(resolver=lambda host: [PUBLIC_IP]),
            org_config_store=org_store,
            session_secret=TEST_SESSION_SECRET,
        )
        with TestClient(app, headers=auth_headers()) as client:
            response = client.post(
                f"{API_PREFIX}/jobs",
                json={"base_url": SAFE_URL, "max_pages": 5, "crawl_dom": False},
                headers=auth_headers(org_id="team-a"),
            )
            assert response.status_code == 202, response.text
            job_id = response.json()["id"]
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and not store.get(job_id).is_terminal:
                time.sleep(0.01)

        assert captured["org_id"] == "team-a"
        assert store.get(job_id).request.get("org_id") is None
