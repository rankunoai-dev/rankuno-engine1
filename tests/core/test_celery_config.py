"""Tests for Celery configuration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.core.celery_config import (
    _build_broker_url,
    _build_result_backend_url,
    get_celery_app,
)


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
        assert "redis://localhost:6379/1" == url

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
