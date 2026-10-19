"""`Settings.ga4_access_store`: Postgres-only, cached, and never the env token (ADR 0038)."""

from __future__ import annotations

import base64

import pytest
from pydantic import SecretStr
from src.core.config import Settings
from src.core.errors import ConfigurationError
from src.core.postgres_ga4_access_store import PostgresGa4AccessStore

_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
_ENV_TOKEN = "1//0gENV-GOOGLE-OAUTH-REFRESH-TOKEN"  # noqa: S105 - fake canary


class _Postgres:
    def __init__(self, configured: bool) -> None:
        self._configured = configured

    def is_configured(self) -> bool:
        return self._configured

    def get_connection_string(self) -> str:
        return "postgresql://unused"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"_env_file": None}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def postgres(monkeypatch: pytest.MonkeyPatch):
    state = {"configured": False}

    def fake() -> _Postgres:
        return _Postgres(bool(state["configured"]))

    monkeypatch.setattr("src.core.postgres_config.get_postgres_settings", fake)
    return state


def test_no_postgres_means_no_ga4_store(postgres: dict[str, object]) -> None:
    assert _settings().ga4_access_store is None


def test_postgres_without_a_key_refuses_to_build(postgres: dict[str, object]) -> None:
    postgres["configured"] = True
    with pytest.raises(ConfigurationError, match="GSC_CREDENTIAL_ENCRYPTION_KEY"):
        _ = _settings().ga4_access_store


def test_postgres_with_a_key_builds_one_cached_store(postgres: dict[str, object]) -> None:
    postgres["configured"] = True
    settings = _settings(gsc_credential_encryption_key=SecretStr(_KEY))
    first = settings.ga4_access_store
    assert isinstance(first, PostgresGa4AccessStore)
    assert settings.ga4_access_store is first  # one breaker, shared by API and crawl


def test_the_environment_refresh_token_is_never_a_ga4_credential(
    postgres: dict[str, object],
) -> None:
    """`GOOGLE_OAUTH_REFRESH_TOKEN` is the GSC default. GA4 must not read it."""
    settings = _settings(google_oauth_refresh_token=SecretStr(_ENV_TOKEN))
    assert settings.ga4_access_store is None


def test_ga4_caps_default_to_unverified_operator_settings() -> None:
    settings = _settings()
    assert settings.ga4_max_pages_per_crawl == 50_000
    assert settings.ga4_max_rows_per_request == 10_000
    assert settings.ga4_daily_calls_per_org == 200
    assert settings.ga4_requests_per_minute == 60
    assert settings.ga4_max_list_pages == 10
    assert settings.ga4_breaker_failure_threshold == 5
    assert settings.ga4_breaker_recovery_s == 60.0
