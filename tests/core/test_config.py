"""Tests for typed configuration loading."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError
from src.core.config import Environment, Settings, get_settings, reset_settings_cache
from src.core.errors import ConfigurationError


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


# -- Named GSC account profiles ------------------------------------------------


def _oauth(**overrides: object) -> Settings:
    base = {
        "_env_file": None,
        "google_oauth_client_id": "shared-id",
        "google_oauth_client_secret": SecretStr("shared-secret"),
        "google_oauth_refresh_token": SecretStr("default-rt"),
    }
    base.update(overrides)
    return Settings(**base)


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
