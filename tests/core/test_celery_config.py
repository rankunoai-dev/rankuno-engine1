"""Tests for Celery configuration."""

from __future__ import annotations

import ssl
from pathlib import Path
from unittest.mock import MagicMock, patch

from pydantic import SecretStr
from src.core.celery_config import (
    _build_broker_url,
    _build_result_backend_url,
    get_celery_app,
)
from src.core.config import Environment, Settings


class TestCeleryConfiguration:
    """Tests for Celery app configuration."""

    @patch("src.core.celery_config.get_redis_client")
    def test_celery_app_creation(self, mock_get_redis: MagicMock) -> None:
        """get_celery_app should return a Celery app."""
        mock_redis = MagicMock()
        mock_redis.connection_pool.connection_kwargs = {
            "host": "localhost",
            "port": 6379,
            "db": 0,
        }
        mock_get_redis.return_value = mock_redis

        app = get_celery_app()

        assert app is not None
        assert hasattr(app, "send_task")
        assert hasattr(app, "conf")

    @patch("src.core.celery_config.get_redis_client")
    def test_celery_app_configuration(self, mock_get_redis: MagicMock) -> None:
        """Celery app should have correct configuration."""
        mock_redis = MagicMock()
        mock_redis.connection_pool.connection_kwargs = {
            "host": "localhost",
            "port": 6379,
            "db": 0,
        }
        mock_get_redis.return_value = mock_redis

        app = get_celery_app()

        # Check serialization
        assert app.conf.task_serializer == "json"
        assert app.conf.result_serializer == "json"
        assert "json" in app.conf.accept_content

        # Check timing
        assert app.conf.task_time_limit > 0
        assert app.conf.task_soft_time_limit > 0

    @patch("src.core.celery_config.get_redis_client")
    def test_celery_app_has_queues(self, mock_get_redis: MagicMock) -> None:
        """Celery app should define task queues."""
        mock_redis = MagicMock()
        mock_redis.connection_pool.connection_kwargs = {
            "host": "localhost",
            "port": 6379,
            "db": 0,
        }
        mock_get_redis.return_value = mock_redis

        app = get_celery_app()

        assert "crawl" in app.conf.task_queues
        assert "recovery" in app.conf.task_queues

    @patch("src.core.celery_config.get_redis_client")
    def test_celery_app_has_task_routes(self, mock_get_redis: MagicMock) -> None:
        """Celery app should route tasks to correct queues."""
        mock_redis = MagicMock()
        mock_redis.connection_pool.connection_kwargs = {
            "host": "localhost",
            "port": 6379,
            "db": 0,
        }
        mock_get_redis.return_value = mock_redis

        app = get_celery_app()

        assert "src.workers.job_executor.execute_crawl" in app.conf.task_routes
        assert "src.workers.job_executor.recover_job" in app.conf.task_routes


class TestBrokerUrlBuilding:
    """Tests for broker URL construction."""

    def test_build_broker_url_without_password(self) -> None:
        """Should build correct URL without password."""
        settings = {"host": "localhost", "port": 6379, "db": 0}
        url = _build_broker_url(settings)
        assert url == "redis://localhost:6379/0"

    def test_build_broker_url_with_password(self) -> None:
        """Should build correct URL with password."""
        settings = {
            "host": "redis.example.com",
            "port": 6380,
            "db": 1,
            "password": "secret",
        }
        url = _build_broker_url(settings)
        assert url == "redis://:secret@redis.example.com:6380/1"

    def test_build_result_backend_url(self) -> None:
        """Should use different DB for result backend."""
        settings = {"host": "localhost", "port": 6379, "db": 0}
        url = _build_result_backend_url(settings)
        # Should use DB 1 for results
        assert url == "redis://localhost:6379/1"

    def test_build_result_backend_with_password(self) -> None:
        """Should pass password to result backend."""
        settings = {
            "host": "redis.example.com",
            "port": 6380,
            "password": "secret",
        }
        url = _build_result_backend_url(settings)
        assert "secret@" in url
        assert "redis.example.com:6380/1" in url


class TestProductionTlsConfiguration:
    """Regression tests for the rediss:// ssl_cert_reqs defect.

    In production, celery_config switches both the broker and result
    backend to rediss:// (TLS). Celery's Redis backend rejects a rediss://
    URL that has no ssl_cert_reqs, and kombu's Redis transport silently
    ignores a non-dict `broker_use_ssl` (leaving the broker connection
    un-encrypted despite the rediss:// URL). Both require dict-based SSL
    options, not a bare `True`.
    """

    def _production_settings(self, tmp_path: Path) -> Settings:
        return Settings(
            _env_file=None,
            audit_log_path=tmp_path / "a.jsonl",
            environment=Environment.PRODUCTION,
            auth_session_secret=SecretStr("a" * 32),
            worker_dispatch_signing_secret=SecretStr("b" * 32),
            worker_bundle_encryption_secret=SecretStr("c" * 32),
        )

    @patch("src.core.celery_config.get_redis_client")
    @patch("src.core.celery_config.get_settings")
    def test_production_backend_construction_does_not_raise(
        self, mock_get_settings: MagicMock, mock_get_redis: MagicMock, tmp_path: Path
    ) -> None:
        """Accessing app.backend in production must not raise ValueError.

        Regression test: with the old code (`broker_use_ssl = True` and no
        ssl_cert_reqs supplied anywhere), celery.backends.redis.RedisBackend
        raises `ValueError: A rediss:// URL must have parameter
        ssl_cert_reqs ...` the moment `app.backend` is first accessed.
        """
        mock_get_settings.return_value = self._production_settings(tmp_path)
        mock_redis = MagicMock()
        mock_redis.connection_pool.connection_kwargs = {
            "host": "dummyhost",
            "port": 6379,
            "db": 0,
            "password": "dummypass",
        }
        mock_get_redis.return_value = mock_redis

        app = get_celery_app()

        # Accessing .backend triggers lazy construction, which is where the
        # old code raised ValueError.
        assert app.backend is not None

    @patch("src.core.celery_config.get_redis_client")
    @patch("src.core.celery_config.get_settings")
    def test_production_uses_dict_based_ssl_options(
        self, mock_get_settings: MagicMock, mock_get_redis: MagicMock, tmp_path: Path
    ) -> None:
        """broker_use_ssl and redis_backend_use_ssl must be dicts, not bool.

        Celery/kombu require dict-shaped SSL options for both the broker
        and the result backend; a bare `True` is either rejected (backend)
        or silently ignored (broker, degrading to plaintext despite
        rediss://).
        """
        mock_get_settings.return_value = self._production_settings(tmp_path)
        mock_redis = MagicMock()
        mock_redis.connection_pool.connection_kwargs = {
            "host": "dummyhost",
            "port": 6379,
            "db": 0,
        }
        mock_get_redis.return_value = mock_redis

        app = get_celery_app()

        assert isinstance(app.conf.broker_use_ssl, dict)
        assert app.conf.broker_use_ssl["ssl_cert_reqs"] == ssl.CERT_NONE
        assert isinstance(app.conf.redis_backend_use_ssl, dict)
        assert app.conf.redis_backend_use_ssl["ssl_cert_reqs"] == ssl.CERT_NONE
        assert app.conf.broker_url.startswith("rediss://")
        assert app.conf.result_backend.startswith("rediss://")
