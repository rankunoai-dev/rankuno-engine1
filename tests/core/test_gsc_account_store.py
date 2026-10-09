"""The GSC account store seam: disk behaviour, selection, and fail-closed resolution.

ADR 0036. Locally nothing changes, so the disk store is pinned to exactly what
the API did before. In the cloud, the store is Postgres and every failure is
an error, never "no such account", because "no such account" falls through to
`.env.local`.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from pydantic import SecretStr
from src.core.config import Settings
from src.core.errors import (
    ConfigurationError,
    GscAccountStoreUnavailableError,
    GscCredentialDecryptionError,
)
from src.core.gsc_account_store import DiskGscAccountStore, GscAccountSummary, UpsertOutcome
from src.core.postgres_config import reset_postgres_settings_cache
from src.core.postgres_gsc_account_store import PostgresGscAccountStore
from src.core.schemas import GscAccountCredential, OrgConfig
from src.core.state_store import DiskOrgConfigStore

TEST_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode()
_PG_ENV = ("DATABASE_URL", "POSTGRES_URL", "DATABASE_PRIVATE_URL", "POSTGRES_PASSWORD")


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "google_oauth_client_id": "shared-id",
        "google_oauth_client_secret": SecretStr("shared-secret"),
        "google_oauth_refresh_token": SecretStr("default-rt"),
        "gsc_accounts": {"acme": {"refresh_token": "rt-env-acme"}},
    }
    base.update(overrides)
    return Settings(**base)


class _Store:
    """A programmable `GscAccountStore` for resolution tests."""

    def __init__(
        self,
        accounts: dict[str, GscAccountCredential] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.accounts = accounts or {}
        self.error = error

    def _check(self) -> None:
        if self.error is not None:
            raise self.error

    def list_accounts(self, org_id: str) -> list[GscAccountSummary]:
        self._check()
        return [GscAccountSummary(account_name=n) for n in sorted(self.accounts)]

    def account_names(self, org_id: str) -> frozenset[str]:
        self._check()
        return frozenset(self.accounts)

    def get_credential(self, org_id: str, account_name: str) -> GscAccountCredential | None:
        self._check()
        return self.accounts.get(account_name)

    def upsert(
        self, org_id: str, account_name: str, credential: GscAccountCredential, *, operator_id: str
    ) -> UpsertOutcome:
        raise NotImplementedError

    def delete(self, org_id: str, account_name: str) -> bool:
        raise NotImplementedError


@pytest.fixture
def no_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _PG_ENV:
        monkeypatch.delenv(name, raising=False)
    reset_postgres_settings_cache()


@pytest.fixture
def with_postgres(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.invalid/db")
    reset_postgres_settings_cache()
    yield
    reset_postgres_settings_cache()


class TestDiskStoreKeepsLocalBehaviour:
    @pytest.fixture
    def org_store(self, tmp_path: Path) -> DiskOrgConfigStore:
        store = DiskOrgConfigStore(tmp_path / "orgs")
        store.create(OrgConfig(org_id="org-a", display_name="A"))
        return store

    def test_upsert_list_get_delete(self, org_store: DiskOrgConfigStore) -> None:
        store = DiskGscAccountStore(org_store)
        cred = GscAccountCredential(refresh_token=SecretStr("rt"), client_secret=SecretStr("s"))
        assert store.upsert("org-a", "acme", cred, operator_id="op") == "created"
        assert store.upsert("org-a", "acme", cred, operator_id="op") == "replaced"
        assert store.list_accounts("org-a") == [
            GscAccountSummary(account_name="acme", has_secret_override=True)
        ]
        assert store.account_names("org-a") == frozenset({"acme"})
        got = store.get_credential("org-a", "acme")
        assert got is not None and got.refresh_token.get_secret_value() == "rt"
        assert store.delete("org-a", "acme") is True
        assert store.delete("org-a", "acme") is False

    def test_unknown_org_reads_are_fail_soft(self, org_store: DiskOrgConfigStore) -> None:
        store = DiskGscAccountStore(org_store)
        assert store.account_names("nope") == frozenset()
        assert store.get_credential("nope", "acme") is None

    def test_unknown_org_list_and_writes_raise_key_error(
        self, org_store: DiskOrgConfigStore
    ) -> None:
        store = DiskGscAccountStore(org_store)
        cred = GscAccountCredential(refresh_token=SecretStr("rt"))
        with pytest.raises(KeyError):
            store.list_accounts("nope")
        with pytest.raises(KeyError):
            store.upsert("nope", "acme", cred, operator_id="op")
        with pytest.raises(KeyError):
            store.delete("nope", "acme")


class TestSelection:
    def test_no_postgres_selects_disk(self, tmp_path: Path, no_postgres: None) -> None:
        settings = _settings(org_config_path=tmp_path / "orgs")
        store = settings.gsc_account_store
        assert isinstance(store, DiskGscAccountStore)
        assert store.org_store is settings.org_config_store
        assert settings.gsc_account_store is store

    def test_postgres_with_key_selects_postgres(self, with_postgres: None) -> None:
        settings = _settings(gsc_credential_encryption_key=SecretStr(TEST_KEY))
        store = settings.gsc_account_store
        assert isinstance(store, PostgresGscAccountStore)
        assert settings.gsc_account_store is store

    def test_postgres_without_key_refuses(self, with_postgres: None) -> None:
        settings = _settings()
        with pytest.raises(ConfigurationError, match="GSC_CREDENTIAL_ENCRYPTION_KEY"):
            _ = settings.gsc_account_store

    def test_create_app_refuses_to_boot_without_the_key(
        self, tmp_path: Path, with_postgres: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.api import server as server_module

        settings = _settings()
        monkeypatch.setattr(server_module, "get_settings", lambda: settings)
        with pytest.raises(ConfigurationError, match="GSC_CREDENTIAL_ENCRYPTION_KEY"):
            server_module.create_app(jobs_root=tmp_path / "jobs")

    @pytest.mark.parametrize(
        "value",
        [
            base64.urlsafe_b64encode(bytes(16)).decode(),
            "definitely-not-a-key-value",
        ],
    )
    def test_malformed_key_refused_in_every_environment(
        self, value: str, no_postgres: None
    ) -> None:
        with pytest.raises(ConfigurationError) as info:
            _settings(gsc_credential_encryption_key=SecretStr(value))
        assert value not in str(info.value)

    def test_previous_without_current_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="PREVIOUS"):
            _settings(gsc_credential_encryption_key_previous=SecretStr(TEST_KEY))


class TestResolutionFailsClosed:
    """C4: only a genuine not-found falls through to `.env.local`."""

    def test_unavailable_store_propagates_and_env_profile_is_not_used(self) -> None:
        settings = _settings()
        store = _Store(error=GscAccountStoreUnavailableError())
        with pytest.raises(GscAccountStoreUnavailableError):
            settings.resolve_gsc_account("acme", org_id="org-a", account_store=store)
        with pytest.raises(GscAccountStoreUnavailableError):
            settings.gsc_account_names_for_org("org-a", account_store=store)

    def test_decryption_error_propagates_and_env_profile_is_not_used(self) -> None:
        settings = _settings()
        store = _Store(error=GscCredentialDecryptionError("acme"))
        with pytest.raises(GscCredentialDecryptionError):
            settings.resolve_gsc_account("acme", org_id="org-a", account_store=store)

    def test_genuine_not_found_falls_through_to_env(self) -> None:
        creds = _settings().resolve_gsc_account("acme", org_id="org-a", account_store=_Store())
        assert creds.refresh_token.get_secret_value() == "rt-env-acme"

    def test_org_account_wins_over_env(self) -> None:
        store = _Store({"acme": GscAccountCredential(refresh_token=SecretStr("rt-org"))})
        creds = _settings().resolve_gsc_account("acme", org_id="org-a", account_store=store)
        assert creds.refresh_token.get_secret_value() == "rt-org"

    def test_unknown_everywhere_is_configuration_error_never_default(self) -> None:
        with pytest.raises(ConfigurationError, match="Unknown GSC account"):
            _settings().resolve_gsc_account("nobody", org_id="org-a", account_store=_Store())

    def test_default_store_is_used_when_none_passed(
        self, tmp_path: Path, no_postgres: None
    ) -> None:
        settings = _settings(org_config_path=tmp_path / "orgs")
        org = settings.org_config_store.get("default")
        org.gsc_accounts["beta"] = GscAccountCredential(refresh_token=SecretStr("rt-beta"))
        settings.org_config_store.update(org)
        assert "beta" in settings.gsc_account_names_for_org()
        creds = settings.resolve_gsc_account("beta")
        assert creds.refresh_token.get_secret_value() == "rt-beta"
