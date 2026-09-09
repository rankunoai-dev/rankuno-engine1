"""Redis connection configuration and client factory.

Provides typed, validated configuration for Redis connections used by
the rate limiter and task queue (Celery). Supports password authentication
and connection pooling.
"""

from __future__ import annotations

from functools import lru_cache

import redis
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = [
    "RedisSettings",
    "get_redis_client",
    "reset_redis_settings_cache",
]


class RedisSettings(BaseSettings):
    """Redis connection configuration loaded from environment.

    Attributes:
        redis_host: Redis server hostname or IP address.
        redis_port: Redis server port (default 6379).
        redis_db: Redis database number (default 0).
        redis_password: Redis password (optional, held as SecretStr).
    """

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    redis_host: str = Field(
        default="localhost",
        description="Redis server hostname or IP address.",
    )
    redis_port: int = Field(
        default=6379,
        ge=1,
        le=65535,
        description="Redis server port.",
    )
    redis_db: int = Field(
        default=0,
        ge=0,
        le=15,
        description="Redis database number.",
    )
    redis_password: SecretStr | None = Field(
        default=None,
        description="Redis password (optional).",
    )


@lru_cache(maxsize=1)
def get_redis_client() -> redis.Redis:  # type: ignore
    """Return a cached Redis client connection.

    The client is cached so that connection parameters are read exactly once
    and every module observes an identical Redis connection. Use
    reset_redis_settings_cache() to invalidate this cache for testing.

    Returns:
        A redis.Redis client instance.

    Raises:
        redis.ConnectionError: If connection fails.
    """
    settings = RedisSettings()
    password = settings.redis_password.get_secret_value() if settings.redis_password else None

    return redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=password,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_keepalive=True,
        health_check_interval=30,
    )


def reset_redis_settings_cache() -> None:
    """Clear the Redis client cache.

    Intended for tests only. After calling this, the next call to
    get_redis_client() will create a new connection with fresh settings.
    """
    get_redis_client.cache_clear()
