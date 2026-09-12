"""Tests for typed configuration loading."""

from __future__ import annotations

from typing import cast

import pytest
from pydantic import SecretStr, ValidationError
from src.core.config import (
    DEFAULT_ORG_ID,
    Environment,
    Settings,
    get_settings,
    reset_settings_cache,
)
from src.core.errors import ConfigurationError
from src.core.schemas import GscAccountCredential, OrgConfig
from src.core.state_store import OrgConfigStore


def test_defaults_are_safe(tmp_path):
    settings = Settings(_env_file=None, audit_log_path=tmp_path / "a.jsonl")
    assert settings.environment is Environment.DEVELOPMENT
    assert settings.guardrails_enabled is True
    assert settings.require_approval_for_writes is True
    assert settings.require_approval_for_spend is True


def test_log_level_is_normalised(tmp_path):
    settings = Settings(_env_file=None, audit_log_path=tmp_path / "a.jsonl", log_level="debug")
    assert settings.log_level == "DEBUG"


def test_invalid_log_level_rejected(tmp_path):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, audit_log_path=tmp_path / "a.jsonl", log_level="chatty")


def test_production_refuses_disabled_guardrails(tmp_path):
    """The one configuration we never want to discover in an incident review."""
    with pytest.raises(ConfigurationError):
        Settings(
            _env_file=None,
            audit_log_path=tmp_path / "a.jsonl",
            environment=Environment.PRODUCTION,
            guardrails_enabled=False,
        )


def test_require_returns_secret_value(tmp_path):
    settings = Settings(
        _env_file=None,
        audit_log_path=tmp_path / "a.jsonl",
        serp_api_key=SecretStr("abc123"),
    )
    assert settings.require("serp_api_key") == "abc123"


def test_require_raises_actionable_error_when_unset(tmp_path):
    settings = Settings(_env_file=None, audit_log_path=tmp_path / "a.jsonl")
    with pytest.raises(ConfigurationError, match="SERP_API_KEY"):
        settings.require("serp_api_key")


def test_require_rejects_unknown_field(tmp_path):
    settings = Settings(_env_file=None, audit_log_path=tmp_path / "a.jsonl")
    with pytest.raises(ConfigurationError):
        settings.require("not_a_real_setting")


def test_secrets_are_not_exposed_by_repr(tmp_path):
    settings = Settings(
        _env_file=None,
        audit_log_path=tmp_path / "a.jsonl",
        gemini_api_key=SecretStr("super-secret"),
    )
    assert "super-secret" not in repr(settings)


def test_get_settings_is_cached():
    reset_settings_cache()
    assert get_settings() is get_settings()


# -- Crawl concurrency cap ------------------------------------------------------


def test_max_concurrent_crawls_defaults_to_five(tmp_path):
    settings = Settings(_env_file=None, audit_log_path=tmp_path / "a.jsonl")
    assert settings.max_concurrent_crawls == 5


def test_max_concurrent_crawls_reads_environment(monkeypatch, tmp_path):
    """Railway sets the cap through the environment, so the env name is the contract."""
    monkeypatch.setenv("MAX_CONCURRENT_CRAWLS", "2")
    settings = Settings(_env_file=None, audit_log_path=tmp_path / "a.jsonl")
    assert settings.max_concurrent_crawls == 2


@pytest.mark.parametrize("value", [0, 11])
def test_max_concurrent_crawls_out_of_range_rejected(value, tmp_path):
    """Zero would refuse every crawl; above ten is more RAM than any target host has."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, audit_log_path=tmp_path / "a.jsonl", max_concurrent_crawls=value)


# -- Named GSC account profiles ------------------------------------------------


class _OrgStore:
    """The `get()` half of `OrgConfigStore`, which is all resolution reads.

    Injected everywhere a test resolves an account so that no unit test reads
    the developer's real `.orgs/org_configs.json` — accounts an operator added
    on this workstation would otherwise become part of the fixture, and the
    suite would pass or fail according to whose machine it ran on.
    """

    def __init__(self, accounts: dict[str, GscAccountCredential] | None = None) -> None:
        self._accounts = accounts or {}

    def get(self, org_id: str) -> OrgConfig:
        if org_id != DEFAULT_ORG_ID:
            raise KeyError(org_id)
        return OrgConfig(
            org_id=DEFAULT_ORG_ID,
            display_name="Default Organization",
            gsc_accounts=dict(self._accounts),
        )


def _oauth(**overrides: object) -> Settings:
    base = {
        "_env_file": None,
        "google_oauth_client_id": "shared-id",
        "google_oauth_client_secret": SecretStr("shared-secret"),
        "google_oauth_refresh_token": SecretStr("default-rt"),
    }
    base.update(overrides)
    settings = Settings(**base)
    settings._org_config_store = cast(OrgConfigStore, _OrgStore())  # noqa: SLF001 - see _OrgStore
    return settings


def test_gsc_accounts_default_empty(tmp_path):
    settings = Settings(_env_file=None, audit_log_path=tmp_path / "a.jsonl")
    assert settings.gsc_accounts == {}
    assert settings.gsc_account_names() == ()


def test_gsc_accounts_parse_nested_env(monkeypatch):
    monkeypatch.setenv("GSC_ACCOUNTS__Acme__REFRESH_TOKEN", "rt-acme")
    monkeypatch.setenv("GSC_ACCOUNTS__GLOBEX__REFRESH_TOKEN", "rt-globex")
    monkeypatch.setenv("GSC_ACCOUNTS__GLOBEX__CLIENT_ID", "globex-id")
    settings = Settings(_env_file=None)
    # Names are lowercased on load, so the request schema and the env agree.
    assert settings.gsc_account_names() == ("acme", "globex")
    assert settings.gsc_accounts["globex"].client_id == "globex-id"
    assert "rt-acme" not in repr(settings)
    assert "rt-globex" not in repr(settings)


def test_gsc_accounts_do_not_split_token_values(monkeypatch):
    # Refresh tokens contain `__`; the delimiter must only apply to keys.
    monkeypatch.setenv("GOOGLE_OAUTH_REFRESH_TOKEN", "1//abc__def__ghi")
    settings = Settings(_env_file=None)
    assert settings.google_oauth_refresh_token.get_secret_value() == "1//abc__def__ghi"


def test_resolve_gsc_account_none_uses_legacy_triple():
    creds = _oauth().resolve_gsc_account(None)
    assert creds.account is None
    assert creds.client_id == "shared-id"
    assert creds.client_secret.get_secret_value() == "shared-secret"
    assert creds.refresh_token.get_secret_value() == "default-rt"


def test_resolve_gsc_account_none_requires_legacy_triple():
    settings = Settings(_env_file=None, google_oauth_client_id="shared-id")
    with pytest.raises(ConfigurationError, match="credentials not configured"):
        settings.resolve_gsc_account(None)


def test_resolve_gsc_account_inherits_shared_client():
    settings = _oauth(gsc_accounts={"acme": {"refresh_token": "rt-acme"}})
    creds = settings.resolve_gsc_account("acme")
    assert creds.account == "acme"
    assert creds.client_id == "shared-id"
    assert creds.client_secret.get_secret_value() == "shared-secret"
    assert creds.refresh_token.get_secret_value() == "rt-acme"


def test_resolve_gsc_account_override_wins():
    settings = _oauth(
        gsc_accounts={
            "globex": {
                "refresh_token": "rt-globex",
                "client_id": "globex-id",
                "client_secret": "globex-secret",
            }
        }
    )
    creds = settings.resolve_gsc_account("GLOBEX")
    assert creds.account == "globex"
    assert creds.client_id == "globex-id"
    assert creds.client_secret.get_secret_value() == "globex-secret"


def test_resolve_gsc_account_unknown_raises_without_fallback():
    settings = _oauth(gsc_accounts={"acme": {"refresh_token": "rt-acme"}})
    with pytest.raises(ConfigurationError, match="Unknown GSC account 'nobody'.*acme"):
        settings.resolve_gsc_account("nobody")


def test_resolve_gsc_account_missing_shared_client_raises():
    settings = Settings(_env_file=None, gsc_accounts={"acme": {"refresh_token": "rt-acme"}})
    with pytest.raises(ConfigurationError, match="GSC_ACCOUNTS__ACME__CLIENT_ID"):
        settings.resolve_gsc_account("acme")


@pytest.mark.parametrize("name", ["Has Space", "Upper", "bad/char", "x" * 65])
def test_gsc_account_name_validator_rejects_bad_names(name):
    with pytest.raises(ValidationError, match="is invalid"):
        Settings(_env_file=None, gsc_accounts={name: {"refresh_token": "rt"}})


def test_gsc_account_profile_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, gsc_accounts={"acme": {"refresh_token": "rt", "token": "x"}})


# --- Org-stored accounts (cycle 0094) --------------------------------------
#
# An account an operator adds in the UI is stored against their organization,
# not in `.env.local`. Resolution has to see both sources or the UI is a form
# that writes to nowhere a crawl can read.


def _org_store(**accounts: str) -> OrgConfigStore:
    """An org store holding one refresh token per named account."""
    stored = {
        name: GscAccountCredential(refresh_token=SecretStr(token))
        for name, token in accounts.items()
    }
    return cast(OrgConfigStore, _OrgStore(stored))


def test_resolve_gsc_account_finds_an_org_stored_account():
    """The defect: an account added in the UI could not be resolved at all."""
    settings = _oauth()
    creds = settings.resolve_gsc_account("initech", org_store=_org_store(initech="rt-initech-org"))
    assert creds.account == "initech"
    assert creds.refresh_token.get_secret_value() == "rt-initech-org"
    # Inherits the shared OAuth client, exactly as an `.env.local` profile does.
    assert creds.client_id == "shared-id"
    assert creds.client_secret.get_secret_value() == "shared-secret"


def test_resolve_gsc_account_still_finds_an_env_only_account():
    """Backwards compatibility: `.env.local` profiles predate the org store."""
    settings = _oauth(gsc_accounts={"acme": {"refresh_token": "rt-acme"}})
    creds = settings.resolve_gsc_account("acme", org_store=_org_store(initech="rt-initech-org"))
    assert creds.refresh_token.get_secret_value() == "rt-acme"


def test_resolve_gsc_account_prefers_the_org_store_on_a_shared_name():
    """Re-entering an account in the UI means the credential just typed."""
    settings = _oauth(gsc_accounts={"acme": {"refresh_token": "rt-acme-env"}})
    creds = settings.resolve_gsc_account("acme", org_store=_org_store(acme="rt-acme-org"))
    assert creds.refresh_token.get_secret_value() == "rt-acme-org"


def test_resolve_gsc_account_org_credential_may_override_the_client():
    store = cast(
        OrgConfigStore,
        _OrgStore(
            {
                "initech": GscAccountCredential(
                    refresh_token=SecretStr("rt-initech"),
                    client_id="initech-id",
                    client_secret=SecretStr("initech-secret"),
                )
            }
        ),
    )
    creds = _oauth().resolve_gsc_account("initech", org_store=store)
    assert creds.client_id == "initech-id"
    assert creds.client_secret.get_secret_value() == "initech-secret"


def test_resolve_gsc_account_org_account_without_a_client_is_refused():
    """No shared client and no override is a misconfiguration, not a default."""
    settings = Settings(_env_file=None)
    with pytest.raises(ConfigurationError, match="has no OAuth client"):
        settings.resolve_gsc_account("initech", org_store=_org_store(initech="rt-initech"))


def test_resolve_gsc_account_unknown_in_both_sources_still_raises():
    settings = _oauth(gsc_accounts={"acme": {"refresh_token": "rt-acme"}})
    with pytest.raises(ConfigurationError, match="Unknown GSC account 'nobody'.*acme.*initech"):
        settings.resolve_gsc_account("nobody", org_store=_org_store(initech="rt-initech"))


def test_resolve_gsc_account_other_org_accounts_are_not_visible():
    """Tenancy: one org's stored account must not resolve for another's crawl."""
    settings = _oauth()
    with pytest.raises(ConfigurationError, match="Unknown GSC account 'initech'"):
        settings.resolve_gsc_account(
            "initech", org_id="team-a", org_store=_org_store(initech="rt-initech")
        )


def test_resolve_gsc_account_none_ignores_the_org_store():
    """The flat triple is an environment fact with no org dimension."""
    creds = _oauth().resolve_gsc_account(None, org_store=_org_store(initech="rt-initech"))
    assert creds.account is None
    assert creds.refresh_token.get_secret_value() == "default-rt"


def test_names_for_org_is_the_union_of_both_sources():
    settings = _oauth(gsc_accounts={"acme": {"refresh_token": "rt-acme"}})
    names = settings.gsc_account_names_for_org(org_store=_org_store(initech="rt", acme="rt"))
    assert names == ("acme", "initech")
    # The Settings-only view is unchanged: it answers a different question.
    assert settings.gsc_account_names() == ("acme",)


def test_names_for_org_survives_an_unreadable_store():
    """A missing org store means "no org accounts", never an exception."""

    class _Broken:
        def get(self, org_id: str) -> OrgConfig:
            raise OSError("disk gone")

    settings = _oauth(gsc_accounts={"acme": {"refresh_token": "rt-acme"}})
    broken = cast(OrgConfigStore, _Broken())
    assert settings.gsc_account_names_for_org(org_store=broken) == ("acme",)


def test_default_org_id_matches_the_stores_auto_created_org():
    """If these ever disagree, UI-added accounts resolve against an empty org."""
    assert DEFAULT_ORG_ID == "default"
