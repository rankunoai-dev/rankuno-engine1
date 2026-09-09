"""Tests for PostgreSQL job store implementation.

These tests verify that PostgresJobStore properly delegates to the fallback
DiskJobStore and handles circuit breaker state transitions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from src.core.circuit_breaker import CircuitBreaker
from src.core.postgres_store import PostgresJobStore
from src.core.state_store import JobRecord, JobStatus


class TestPostgresJobStoreInitialization:
    """Tests for PostgresJobStore initialization."""

    def test_initialization_with_defaults(self) -> None:
        """PostgresJobStore should initialize with default circuit breaker and fallback."""
        store = PostgresJobStore()
        assert store.circuit_breaker is not None
        assert store.fallback_store is not None

    def test_initialization_with_custom_circuit_breaker(self) -> None:
        """PostgresJobStore should accept a custom circuit breaker."""
        breaker = CircuitBreaker()
        store = PostgresJobStore(circuit_breaker=breaker)
        assert store.circuit_breaker is breaker

    def test_initialization_with_custom_fallback(self) -> None:
        """PostgresJobStore should accept a custom fallback store."""
        fallback = MagicMock()
        store = PostgresJobStore(fallback_store=fallback)
        assert store.fallback_store is fallback


class TestPostgresJobStoreCircuitBreakerFallback:
    """Tests for circuit breaker fallback behavior."""

    def test_create_uses_fallback_when_circuit_open(self) -> None:
        """create() should use fallback store when circuit is open."""
        fallback = MagicMock()
        fallback.create.return_value = JobRecord(
            id="test-job",
            tool_name="test",
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
        )

        breaker = CircuitBreaker(failure_threshold=1)
        store = PostgresJobStore(circuit_breaker=breaker, fallback_store=fallback)

        # Trigger circuit open
        breaker.record_failure(RuntimeError("test"))
        assert breaker.is_open()

        # Create should use fallback
        result = store.create(
            tool_name="test_tool",
            request={"key": "value"},
        )

        fallback.create.assert_called_once()
        assert result.id == "test-job"

    def test_get_uses_fallback_when_circuit_open(self) -> None:
        """get() should use fallback store when circuit is open."""
        fallback = MagicMock()
        fallback.get.return_value = JobRecord(
            id="test-job",
            tool_name="test",
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
        )

        breaker = CircuitBreaker(failure_threshold=1)
        store = PostgresJobStore(circuit_breaker=breaker, fallback_store=fallback)

        # Trigger circuit open
        breaker.record_failure(RuntimeError("test"))

        result = store.get("test-job")
        fallback.get.assert_called_once_with("test-job")
        assert result.id == "test-job"

    def test_list_jobs_uses_fallback_when_circuit_open(self) -> None:
        """list_jobs() should use fallback store when circuit is open."""
        fallback = MagicMock()
        fallback.list_jobs.return_value = []

        breaker = CircuitBreaker(failure_threshold=1)
        store = PostgresJobStore(circuit_breaker=breaker, fallback_store=fallback)

        # Trigger circuit open
        breaker.record_failure(RuntimeError("test"))

        result = store.list_jobs()
        fallback.list_jobs.assert_called_once()
        assert result == []


class TestPostgresJobStoreMethodDelegation:
    """Tests for fallback delegation of all store methods."""

    def test_mark_running_delegates_to_fallback(self) -> None:
        """mark_running() should delegate to fallback."""
        fallback = MagicMock()
        store = PostgresJobStore(fallback_store=fallback)
        store.mark_running("job-id")
        fallback.mark_running.assert_called_once_with("job-id")

    def test_update_telemetry_delegates_to_fallback(self) -> None:
        """update_telemetry() should delegate to fallback."""
        from src.core.state_store import JobTelemetry

        fallback = MagicMock()
        store = PostgresJobStore(fallback_store=fallback)
        telemetry = JobTelemetry()
        store.update_telemetry("job-id", telemetry)
        fallback.update_telemetry.assert_called_once_with("job-id", telemetry)

    def test_mark_failed_delegates_to_fallback(self) -> None:
        """mark_failed() should delegate to fallback."""
        fallback = MagicMock()
        store = PostgresJobStore(fallback_store=fallback)
        store.mark_failed("job-id", "error message")
        fallback.mark_failed.assert_called_once_with("job-id", "error message")

    def test_finish_delegates_to_fallback(self) -> None:
        """finish() should delegate to fallback."""
        fallback = MagicMock()
        store = PostgresJobStore(fallback_store=fallback)
        result = {"key": "value"}
        store.finish("job-id", result)
        fallback.finish.assert_called_once_with("job-id", result, partial=False)

    def test_read_result_delegates_to_fallback(self) -> None:
        """read_result() should delegate to fallback."""
        fallback = MagicMock()
        fallback.read_result.return_value = {"key": "value"}
        store = PostgresJobStore(fallback_store=fallback)
        result = store.read_result("job-id")
        fallback.read_result.assert_called_once_with("job-id")
        assert result == {"key": "value"}

    def test_write_checkpoint_delegates_to_fallback(self) -> None:
        """write_checkpoint() should delegate to fallback."""
        fallback = MagicMock()
        store = PostgresJobStore(fallback_store=fallback)
        payload = {"key": "value"}
        store.write_checkpoint("job-id", payload)
        fallback.write_checkpoint.assert_called_once_with("job-id", payload)

    def test_read_checkpoint_delegates_to_fallback(self) -> None:
        """read_checkpoint() should delegate to fallback."""
        fallback = MagicMock()
        fallback.read_checkpoint.return_value = {"key": "value"}
        store = PostgresJobStore(fallback_store=fallback)
        result = store.read_checkpoint("job-id")
        fallback.read_checkpoint.assert_called_once_with("job-id")
        assert result == {"key": "value"}

    def test_write_homepage_delegates_to_fallback(self) -> None:
        """write_homepage() should delegate to fallback."""
        fallback = MagicMock()
        store = PostgresJobStore(fallback_store=fallback)
        store.write_homepage("job-id", "<html>test</html>")
        fallback.write_homepage.assert_called_once_with("job-id", "<html>test</html>")

    def test_read_homepage_delegates_to_fallback(self) -> None:
        """read_homepage() should delegate to fallback."""
        fallback = MagicMock()
        fallback.read_homepage.return_value = "<html>test</html>"
        store = PostgresJobStore(fallback_store=fallback)
        result = store.read_homepage("job-id")
        fallback.read_homepage.assert_called_once_with("job-id")
        assert result == "<html>test</html>"
