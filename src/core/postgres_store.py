"""PostgreSQL job store implementation with atomic cost tracking.

This module implements the JobStore protocol using PostgreSQL as the backend,
providing atomic job creation + cost charging in a single transaction. Uses a
circuit breaker to gracefully fall back to disk storage during outages.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.core.circuit_breaker import CircuitBreaker
from src.core.logger import get_logger
from src.core.postgres_config import get_postgres_settings
from src.core.state_store import JobRecord, JobStatus, JobStore, JobTelemetry

if TYPE_CHECKING:
    from psycopg import Connection

_logger = get_logger(__name__)


class PostgresJobStore(JobStore):
    """PostgreSQL-backed job store with atomic cost ledger integration.

    Provides atomic job creation + cost charging in a single transaction using
    SELECT FOR UPDATE to lock the organization's budget row. Falls back to
    disk storage when PostgreSQL is unavailable via circuit breaker.

    Attributes:
        circuit_breaker: CircuitBreaker instance tracking PostgreSQL health.
        fallback_store: DiskJobStore used when circuit is open.
    """

    def __init__(
        self,
        circuit_breaker: CircuitBreaker | None = None,
        fallback_store: JobStore | None = None,
    ) -> None:
        """Initialize PostgreSQL job store with optional circuit breaker.

        Args:
            circuit_breaker: Circuit breaker for database resilience.
                If None, creates a default instance.
            fallback_store: Fallback store for when PostgreSQL is unavailable.
                If None, creates a DiskJobStore.
        """
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        if fallback_store is None:
            from pathlib import Path

            from src.core.state_store import DiskJobStore

            repo_root = Path(__file__).resolve().parents[2]
            jobs_dir = repo_root / ".jobs"
            fallback_store = DiskJobStore(jobs_dir)
        self.fallback_store = fallback_store

    def _get_connection(self) -> Connection:
        """Get a new PostgreSQL connection with fresh credentials.

        Re-reads credentials from environment on each connection to support
        secret rotation without restarting.

        Returns:
            A psycopg sync connection.

        Raises:
            psycopg.OperationalError: If connection fails.
        """
        import psycopg

        settings = get_postgres_settings()
        password = (
            settings.postgres_password.get_secret_value() if settings.postgres_password else ""
        )
        connection_string = (
            f"postgresql://{settings.postgres_user}:{password}@"
            f"{settings.postgres_host}:{settings.postgres_port}/"
            f"{settings.postgres_database}"
        )
        return psycopg.connect(connection_string)

    def create(
        self,
        tool_name: str,
        request: Mapping[str, object],
        label: str = "",
        facet_id: str = "seo.page_classifier",
        org_id: str | None = None,
    ) -> JobRecord:
        """Create a new job with atomic cost charging.

        In a single transaction:
        1. Lock organization's budget row with SELECT FOR UPDATE
        2. Verify budget available
        3. Create job record
        4. Charge estimated cost ($0.50)

        Falls back to disk store if circuit is open.

        Args:
            tool_name: Tool name (e.g., 'seo.page_classifier').
            request: Tool input payload.
            label: Human-facing description.
            facet_id: Facet identifier.
            org_id: Organization ID. Defaults to 'default'.

        Returns:
            The created JobRecord.

        Raises:
            ValueError: If organization has no budget or does not exist.
            psycopg.OperationalError: If database connection fails (triggers fallback).
        """
        org_id = org_id or "default"
        job_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC)

        # Check circuit breaker first
        if self.circuit_breaker.is_open():
            _logger.warning(
                "postgres_circuit_open",
                extra={
                    "job_id": job_id,
                    "org_id": org_id,
                    "fallback": "disk",
                },
            )
            return self.fallback_store.create(
                tool_name=tool_name,
                request=request,
                label=label,
                facet_id=facet_id,
                org_id=org_id,
            )

        # Attempt atomic transaction
        try:
            import psycopg

            conn = self._get_connection()
            try:
                with conn, conn.cursor() as cur:
                    # Lock org budget row (SELECT FOR UPDATE)
                    cur.execute(
                        "SELECT llm_credit_limit_usd FROM org_configs WHERE org_id = %s FOR UPDATE",
                        (org_id,),
                    )
                    budget_row = cur.fetchone()

                    if not budget_row or budget_row[0] <= 0:
                        raise ValueError(f"Organization {org_id} has no budget or does not exist")

                    # Create job
                    cur.execute(
                        "INSERT INTO jobs "
                        "(id, org_id, tool_name, facet_id, request, status, "
                        "created_at, updated_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            job_id,
                            org_id,
                            tool_name,
                            facet_id,
                            json.dumps(request),
                            "queued",
                            now,
                            now,
                        ),
                    )

                    # Charge cost (estimated $0.50)
                    cur.execute(
                        "INSERT INTO cost_ledger "
                        "(org_id, job_id, amount_usd, status) "
                        "VALUES (%s, %s, %s, %s)",
                        (org_id, job_id, 0.50, "charged"),
                    )

                self.circuit_breaker.record_success()
                return JobRecord(
                    id=job_id,
                    tool_name=tool_name,
                    label=label,
                    org_id=org_id,
                    facet_id=facet_id,
                    request=dict(request),
                    status=JobStatus.QUEUED,
                    created_at=now,
                    updated_at=now,
                )

            finally:
                conn.close()

        except (psycopg.OperationalError, psycopg.DatabaseError) as err:
            self.circuit_breaker.record_failure(err)
            if self.circuit_breaker.is_open():
                _logger.warning(
                    "postgres_circuit_open_fallback",
                    extra={
                        "job_id": job_id,
                        "org_id": org_id,
                        "error": str(err),
                    },
                )
                return self.fallback_store.create(
                    tool_name=tool_name,
                    request=request,
                    label=label,
                    facet_id=facet_id,
                    org_id=org_id,
                )
            raise

    def get(self, job_id: str) -> JobRecord:
        """Retrieve a job by ID.

        Falls back to disk store if PostgreSQL is unavailable.

        Args:
            job_id: Job identifier.

        Returns:
            The JobRecord.

        Raises:
            KeyError: If job not found.
        """
        if self.circuit_breaker.is_open():
            return self.fallback_store.get(job_id)

        try:
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, org_id, tool_name, facet_id, request, status, "
                        "created_at, updated_at, started_at, finished_at, error, "
                        "has_result, telemetry "
                        "FROM jobs WHERE id = %s",
                        (job_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise KeyError(f"Job {job_id} not found")

                    self.circuit_breaker.record_success()
                    return JobRecord(
                        id=row[0],
                        org_id=row[1],
                        tool_name=row[2],
                        facet_id=row[3],
                        request=row[4],
                        status=JobStatus(row[5]),
                        created_at=row[6],
                        updated_at=row[7],
                        started_at=row[8],
                        finished_at=row[9],
                        error=row[10],
                        has_result=row[11],
                        telemetry=JobTelemetry(**row[12]) if row[12] else JobTelemetry(),
                    )
            finally:
                conn.close()

        except Exception as err:
            self.circuit_breaker.record_failure(err)
            if self.circuit_breaker.is_open():
                return self.fallback_store.get(job_id)
            raise

    def list_jobs(self) -> list[JobRecord]:
        """List all jobs, newest first.

        Falls back to disk store if PostgreSQL is unavailable.

        Returns:
            List of JobRecords ordered by created_at DESC.
        """
        if self.circuit_breaker.is_open():
            return self.fallback_store.list_jobs()

        try:
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, org_id, tool_name, facet_id, request, status, "
                        "created_at, updated_at, started_at, finished_at, error, "
                        "has_result, telemetry "
                        "FROM jobs ORDER BY created_at DESC"
                    )
                    rows = cur.fetchall()
                    self.circuit_breaker.record_success()

                    jobs = []
                    for row in rows:
                        jobs.append(
                            JobRecord(
                                id=row[0],
                                org_id=row[1],
                                tool_name=row[2],
                                facet_id=row[3],
                                request=row[4],
                                status=JobStatus(row[5]),
                                created_at=row[6],
                                updated_at=row[7],
                                started_at=row[8],
                                finished_at=row[9],
                                error=row[10],
                                has_result=row[11],
                                telemetry=JobTelemetry(**row[12]) if row[12] else JobTelemetry(),
                            )
                        )
                    return jobs
            finally:
                conn.close()

        except Exception as err:
            self.circuit_breaker.record_failure(err)
            if self.circuit_breaker.is_open():
                return self.fallback_store.list_jobs()
            raise

    def mark_running(self, job_id: str) -> JobRecord:
        """Mark a job as RUNNING. Falls back to disk store if needed."""
        if self.circuit_breaker.is_open():
            return self.fallback_store.mark_running(job_id)
        return self.fallback_store.mark_running(job_id)

    def update_telemetry(self, job_id: str, telemetry: JobTelemetry) -> JobRecord:
        """Update job telemetry. Falls back to disk store if needed."""
        if self.circuit_breaker.is_open():
            return self.fallback_store.update_telemetry(job_id, telemetry)
        return self.fallback_store.update_telemetry(job_id, telemetry)

    def mark_failed(self, job_id: str, error: str) -> JobRecord:
        """Mark job as FAILED with error. Falls back to disk store if needed."""
        if self.circuit_breaker.is_open():
            return self.fallback_store.mark_failed(job_id, error)
        return self.fallback_store.mark_failed(job_id, error)

    def finish(
        self, job_id: str, result: Mapping[str, object], *, partial: bool = False
    ) -> JobRecord:
        """Finish job with result. Falls back to disk store if needed."""
        if self.circuit_breaker.is_open():
            return self.fallback_store.finish(job_id, result, partial=partial)
        return self.fallback_store.finish(job_id, result, partial=partial)

    def read_result(self, job_id: str) -> Mapping[str, object]:
        """Read job result. Falls back to disk store if needed."""
        if self.circuit_breaker.is_open():
            return self.fallback_store.read_result(job_id)
        return self.fallback_store.read_result(job_id)

    def write_checkpoint(self, job_id: str, payload: Mapping[str, object]) -> None:
        """Write checkpoint. Falls back to disk store if needed."""
        if self.circuit_breaker.is_open():
            self.fallback_store.write_checkpoint(job_id, payload)
            return
        self.fallback_store.write_checkpoint(job_id, payload)

    def read_checkpoint(self, job_id: str) -> Mapping[str, object] | None:
        """Read checkpoint. Falls back to disk store if needed."""
        if self.circuit_breaker.is_open():
            return self.fallback_store.read_checkpoint(job_id)
        return self.fallback_store.read_checkpoint(job_id)

    def write_homepage(self, job_id: str, html: str) -> None:
        """Write homepage. Falls back to disk store if needed."""
        if self.circuit_breaker.is_open():
            self.fallback_store.write_homepage(job_id, html)
            return
        self.fallback_store.write_homepage(job_id, html)

    def read_homepage(self, job_id: str) -> str | None:
        """Read homepage. Falls back to disk store if needed."""
        if self.circuit_breaker.is_open():
            return self.fallback_store.read_homepage(job_id)
        return self.fallback_store.read_homepage(job_id)
