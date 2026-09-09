"""Tests for PostgreSQL configuration loading and caching."""

from __future__ import annotations

import pytest
from src.core.postgres_config import (
    PostgresSettings,
    get_postgres_settings,
    reset_postgres_settings_cache,
)


class TestPostgresSettings:
    """Tests for PostgresSettings configuration model."""

    def test_defaults(self) -> None:
        """Settings should use sensible defaults."""
        settings = PostgresSettings()
        assert settings.postgres_host == "localhost"
        assert settings.postgres_port == 5432
        assert settings.postgres_database == "rankuno"
        assert settings.postgres_user == "rankuno"
        assert settings.postgres_password is None

    def test_from_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Settings should load from environment variables."""
        monkeypatch.setenv("POSTGRES_HOST", "db.example.com")
        monkeypatch.setenv("POSTGRES_PORT", "5433")
        monkeypatch.setenv("POSTGRES_DATABASE", "production")
        monkeypatch.setenv("POSTGRES_USER", "prod_user")
        monkeypatch.setenv("POSTGRES_PASSWORD", "secret_password")

        settings = PostgresSettings()
        assert settings.postgres_host == "db.example.com"
        assert settings.postgres_port == 5433
        assert settings.postgres_database == "production"
        assert settings.postgres_user == "prod_user"
        assert settings.postgres_password.get_secret_value() == "secret_password"

    def test_password_is_secret_str(self) -> None:
        """Password should be held as SecretStr and never printed."""
        settings = PostgresSettings(postgres_password="my_password")  # noqa: S106
        # SecretStr.__str__() returns '***' to avoid accidental logging
        assert str(settings.postgres_password) == "**********"
        # Only get_secret_value() exposes the actual value
        assert settings.postgres_password.get_secret_value() == "my_password"

    def test_port_validation_minimum(self) -> None:
        """Port must be >= 1."""
        with pytest.raises(ValueError):
            PostgresSettings(postgres_port=0)

    def test_port_validation_maximum(self) -> None:
        """Port must be <= 65535."""
        with pytest.raises(ValueError):
            PostgresSettings(postgres_port=65536)

    def test_port_valid_range(self) -> None:
        """Port can be any value in valid range."""
        settings = PostgresSettings(postgres_port=1)
        assert settings.postgres_port == 1

        settings = PostgresSettings(postgres_port=65535)
        assert settings.postgres_port == 65535


class TestPostgresSettingsCaching:
    """Tests for caching behavior of get_postgres_settings()."""

    def test_caching_returns_same_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Successive calls to get_postgres_settings() return the same instance."""
        reset_postgres_settings_cache()
        monkeypatch.setenv("POSTGRES_HOST", "host1")

        settings1 = get_postgres_settings()
        settings2 = get_postgres_settings()
        assert settings1 is settings2

    def test_cache_clear_forces_reload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """After cache_clear(), environment changes are reflected."""
        reset_postgres_settings_cache()
        monkeypatch.setenv("POSTGRES_HOST", "host1")

        settings1 = get_postgres_settings()
        assert settings1.postgres_host == "host1"

        # Change environment and clear cache
        monkeypatch.setenv("POSTGRES_HOST", "host2")
        reset_postgres_settings_cache()

        settings2 = get_postgres_settings()
        assert settings2.postgres_host == "host2"
        assert settings1 is not settings2

    def test_secret_rotation_drill(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cache clear allows testing secret rotation without restart.

        This simulates the workflow:
        1. Rotate database password in secrets manager
        2. Update environment variable
        3. Call reset_postgres_settings_cache()
        4. New connections use new credential
        """
        reset_postgres_settings_cache()
        monkeypatch.setenv("POSTGRES_PASSWORD", "old_password")

        old_settings = get_postgres_settings()
        assert old_settings.postgres_password.get_secret_value() == "old_password"

        # Simulate password rotation
        monkeypatch.setenv("POSTGRES_PASSWORD", "new_password")
        reset_postgres_settings_cache()

        new_settings = get_postgres_settings()
        assert new_settings.postgres_password.get_secret_value() == "new_password"

    def test_cache_maxsize_one(self) -> None:
        """Cache size is 1, so only the most recent instance is cached."""
        # This is implicitly tested by the fact that lru_cache(maxsize=1)
        # is used in the implementation. We just verify the behavior.
        reset_postgres_settings_cache()

        settings1 = get_postgres_settings()
        settings2 = get_postgres_settings()
        # Both should be the same instance
        assert settings1 is settings2

        info = get_postgres_settings.cache_info()
        assert info.maxsize == 1
