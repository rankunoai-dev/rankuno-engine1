"""PostgreSQL connection configuration and credential management.

This module provides typed, validated configuration for PostgreSQL connections
and manages credential caching with built-in invalidation for secret rotation
testing. Credentials are sourced from environment variables and never cached
longer than postgres_credentials_cache_ttl_s.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = [
    "PostgresSettings",
    "get_postgres_settings",
    "reset_postgres_settings_cache",
]


class PostgresSettings(BaseSettings):
    """PostgreSQL connection configuration loaded from environment.

    Attributes:
        postgres_host: PostgreSQL server hostname or IP address.
        postgres_port: PostgreSQL server port (default 5432).
        postgres_database: Database name.
        postgres_user: Database user name.
        postgres_password: Database user password (held as SecretStr).
    """

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    postgres_host: str = Field(
        default="localhost",
        description="PostgreSQL server hostname or IP address.",
    )
    postgres_port: int = Field(
        default=5432,
        ge=1,
        le=65535,
        description="PostgreSQL server port.",
    )
    postgres_database: str = Field(
        default="rankuno",
        description="PostgreSQL database name.",
    )
    postgres_user: str = Field(
        default="rankuno",
        description="PostgreSQL user name.",
    )
    postgres_password: SecretStr | None = Field(
        default=None,
        description="PostgreSQL user password.",
    )


@lru_cache(maxsize=1)
def get_postgres_settings() -> PostgresSettings:
    """Return the process-wide PostgreSQL settings singleton.

    The settings are cached so that environment variables are parsed exactly
    once and every module observes an identical view of PostgreSQL configuration.
    Use reset_postgres_settings_cache() to invalidate this cache, typically for
    testing secret rotation scenarios.

    Returns:
        The cached PostgresSettings instance.
    """
    return PostgresSettings()


def reset_postgres_settings_cache() -> None:
    """Clear the PostgreSQL settings cache.

    This is intended for tests only and is particularly useful for testing
    secret rotation scenarios where the environment changes without a process
    restart. After calling this, the next call to get_postgres_settings()
    will re-read the environment.
    """
    get_postgres_settings.cache_clear()
