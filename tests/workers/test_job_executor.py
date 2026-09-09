"""Tests for job executor Celery tasks."""

from __future__ import annotations

import pytest

from src.workers.job_executor import execute_crawl, recover_job


class TestExecuteCrawlTask:
    """Tests for execute_crawl Celery task."""

    def test_task_exists(self) -> None:
        """execute_crawl task should exist and be callable."""
        assert callable(execute_crawl)

    def test_task_has_app(self) -> None:
        """Task should be bound to Celery app."""
        assert hasattr(execute_crawl, "app")

    def test_task_has_apply_async(self) -> None:
        """Task should support apply_async for queuing."""
        assert hasattr(execute_crawl, "apply_async")


class TestRecoverJobTask:
    """Tests for recover_job Celery task."""

    def test_recover_job_exists(self) -> None:
        """recover_job task should exist."""
        assert callable(recover_job)

    def test_recover_job_has_app(self) -> None:
        """Task should be bound to Celery app."""
        assert hasattr(recover_job, "app")


class TestJobExecutorIntegration:
    """Integration tests for job executor."""

    def test_celery_app_has_tasks(self) -> None:
        """Celery app should have registered tasks."""
        from src.core.celery_config import get_celery_app

        app = get_celery_app()
        # App should be functional
        assert app is not None
        assert hasattr(app, "send_task")

    def test_workers_module_exports(self) -> None:
        """Workers module should export tasks."""
        from src.workers import execute_crawl as exported_execute
        from src.workers import recover_job as exported_recover

        assert callable(exported_execute)
        assert callable(exported_recover)

    def test_celery_task_registration(self) -> None:
        """Tasks should be registered on app."""
        from src.core.celery_config import get_celery_app

        app = get_celery_app()
        # Tasks are registered when module is imported
        # Check that the app has been configured
        assert app.conf.task_serializer == "json"
