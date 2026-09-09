"""Tests for Redis configuration and client factory."""

from __future__ import annotations

import pytest
from src.core.redis_config import (
    RedisSettings,
    get_redis_client,
    reset_redis_settings_cache,
)


class TestRedisSettings:
    """Tests for RedisSettings configuration model."""

    def test_defaults(self) -> None:
        """Settings should use sensible defaults."""
        settings = RedisSettings()
        assert settings.redis_host == "localhost"
        assert settings.redis_port == 6379
        assert settings.redis_db == 0
        assert settings.redis_password is None

    def test_from_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Settings should load from environment variables."""
        monkeypatch.setenv("REDIS_HOST", "redis.example.com")
        monkeypatch.setenv("REDIS_PORT", "6380")
        monkeypatch.setenv("REDIS_DB", "1")
        monkeypatch.setenv("REDIS_PASSWORD", "secret")

        settings = RedisSettings()
        assert settings.redis_host == "redis.example.com"
        assert settings.redis_port == 6380
        assert settings.redis_db == 1
        assert settings.redis_password.get_secret_value() == "secret"

    def test_port_validation(self) -> None:
        """Port must be in valid range."""
        with pytest.raises(ValueError):
            RedisSettings(redis_port=0)
        with pytest.raises(ValueError):
            RedisSettings(redis_port=65536)

    def test_db_validation(self) -> None:
        """Database number must be 0-15."""
        with pytest.raises(ValueError):
            RedisSettings(redis_db=-1)
        with pytest.raises(ValueError):
            RedisSettings(redis_db=16)

    def test_password_is_secret_str(self) -> None:
        """Password should be held as SecretStr."""
        settings = RedisSettings(redis_password="my_password")
        assert str(settings.redis_password) == "**********"
        assert settings.redis_password.get_secret_value() == "my_password"


class TestRedisClientFactory:
    """Tests for get_redis_client() factory."""

    def test_caching_returns_same_instance(self) -> None:
        """Successive calls should return same client instance."""
        reset_redis_settings_cache()
        client1 = get_redis_client()
        client2 = get_redis_client()
        assert client1 is client2

    def test_cache_clear_forces_reconnect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """After cache_clear(), new connection is created."""
        reset_redis_settings_cache()
        monkeypatch.setenv("REDIS_HOST", "host1")

        client1 = get_redis_client()
        assert client1.connection_pool.connection_kwargs["host"] == "host1"

        monkeypatch.setenv("REDIS_HOST", "host2")
        reset_redis_settings_cache()

        client2 = get_redis_client()
        assert client2.connection_pool.connection_kwargs["host"] == "host2"
        assert client1 is not client2

    def test_client_configuration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Client should be configured with correct parameters."""
        reset_redis_settings_cache()
        monkeypatch.setenv("REDIS_HOST", "myhost")
        monkeypatch.setenv("REDIS_PORT", "6380")
        monkeypatch.setenv("REDIS_DB", "2")

        client = get_redis_client()
        pool = client.connection_pool

        assert pool.connection_kwargs["host"] == "myhost"
        assert pool.connection_kwargs["port"] == 6380
        assert pool.connection_kwargs["db"] == 2
        assert pool.connection_kwargs["socket_keepalive"] is True
        assert pool.connection_kwargs["decode_responses"] is True

    def test_client_with_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Client should pass password to connection pool."""
        reset_redis_settings_cache()
        monkeypatch.setenv("REDIS_PASSWORD", "secret123")

        client = get_redis_client()
        pool = client.connection_pool

        assert pool.connection_kwargs["password"] == "secret123"

    def test_client_without_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Client should work without password when not configured."""
        reset_redis_settings_cache()
        # Ensure no password is set
        monkeypatch.delenv("REDIS_PASSWORD", raising=False)

        client = get_redis_client()
        pool = client.connection_pool

        assert pool.connection_kwargs["password"] is None
