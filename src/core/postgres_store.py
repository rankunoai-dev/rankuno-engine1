"""PostgreSQL job store: crawl jobs and their payloads survive a redeploy.

`DiskJobStore` writes under `.jobs/` on the container's own disk, which
Railway wipes on every redeploy (`railway.toml`). This store makes `jobs`
(migration 0001) and its `job_payloads` companion (migration 0006) the
durable record instead — same database the org budget and cost ledger
already live in, no new infrastructure
(`docs/adr/0022-postgres-backed-job-store.md`).

Every method follows the same shape: check the circuit breaker, attempt
Postgres, and on `psycopg.OperationalError`/`DatabaseError` record a failure
and fall back to disk once the breaker opens (`CircuitBreaker`). A fresh
`psycopg` connection is opened per call rather than pooled, matching
`PostgresWorkerDispatchStore`'s own posture: credentials are re-read from
`get_postgres_settings()` on every connection, so a rotated secret takes
effect without a restart.

`write_reconciliation`/`read_reconciliation`/`write_performance`/
`read_performance` are the one exception: they always delegate straight to
`fallback_store`, unconditionally. Neither payload is in this cycle's scope
(the ADR), and — because `JobStore` is a `Protocol`, not an ABC — leaving
them unoverridden here would silently no-op every call once this store
becomes the default, rather than raising or falling back. That would be a
regression from today's behaviour, where nothing calls this class at all.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import psycopg

from src.core.circuit_breaker import CircuitBreaker
from src.core.logger import get_logger
from src.core.postgres_config import get_postgres_settings
from src.core.state_store import (
    MAX_HOMEPAGE_BYTES,
    JobNotFoundError,
    JobRecord,
    JobStatus,
    JobStore,
    JobTelemetry,
)

if TYPE_CHECKING:
    from psycopg import Connection, Cursor

_logger = get_logger(__name__)

_JOB_COLUMNS = (
    "id, org_id, tool_name, label, facet_id, request, status, created_at, updated_at, "
    "started_at, finished_at, error, has_result, has_checkpoint, telemetry"
)
"""Column list every `jobs` read/RETURNING clause uses, in the order
`_row_to_job_record` expects. A fixed module constant, never built from
caller input."""


def _row_to_job_record(row: tuple[object, ...]) -> JobRecord:
    """Map one `_JOB_COLUMNS`-shaped database row onto a `JobRecord`."""
    (
        job_id,
        org_id,
        tool_name,
        label,
        facet_id,
        request,
        status,
        created_at,
        updated_at,
        started_at,
        finished_at,
        error,
        has_result,
        has_checkpoint,
        telemetry,
    ) = row
    return JobRecord(
        id=str(job_id),
        org_id=str(org_id),
        tool_name=str(tool_name),
        label="" if label is None else str(label),
        facet_id=str(facet_id),
        request=cast(Mapping[str, object], request),
        status=JobStatus(str(status)),
        created_at=cast(datetime, created_at),
        updated_at=cast(datetime, updated_at),
        started_at=None if started_at is None else cast(datetime, started_at),
        finished_at=None if finished_at is None else cast(datetime, finished_at),
        error=None if error is None else str(error),
        has_result=bool(has_result),
        has_checkpoint=bool(has_checkpoint),
        telemetry=JobTelemetry.model_validate(telemetry) if telemetry else JobTelemetry(),
    )


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
        connection_factory: Callable[[], Connection] | None = None,
    ) -> None:
        """Initialize PostgreSQL job store with optional circuit breaker.

        Args:
            circuit_breaker: Circuit breaker for database resilience.
                If None, creates a default instance.
            fallback_store: Fallback store for when PostgreSQL is unavailable.
                If None, creates a DiskJobStore.
            connection_factory: Returns a new `psycopg`-shaped connection.
                Defaults to a real connection built from
                `get_postgres_settings()`. Injectable so a test can supply a
                fake connection/cursor pair without a live database — see
                `PostgresWorkerDispatchStore`, which established this pattern
                for the same reason.
        """
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        if fallback_store is None:
            from pathlib import Path

            from src.core.state_store import DiskJobStore

            repo_root = Path(__file__).resolve().parents[2]
            jobs_dir = repo_root / ".jobs"
            fallback_store = DiskJobStore(jobs_dir)
        self.fallback_store = fallback_store
        self._connection_factory = connection_factory or self._default_connection_factory

    @staticmethod
    def _default_connection_factory() -> Connection:
        """Build a real `psycopg` connection, re-reading credentials each time.

        A fresh connection per call (never pooled), so a rotated secret takes
        effect without a restart — `get_postgres_settings()` re-reads its
        environment on every call too.
        """
        settings = get_postgres_settings()
        connection_string = settings.get_connection_string()
        return psycopg.connect(connection_string)

    def _get_connection(self) -> Connection:
        """Get a new PostgreSQL connection via this store's connection factory.

        Returns:
            A psycopg sync connection.

        Raises:
            psycopg.OperationalError: If connection fails.
        """
        return self._connection_factory()

    @contextmanager
    def _cursor(self) -> Generator[Cursor[Any]]:
        """One connection, one transaction, always closed.

        `with conn:` commits on a clean exit and rolls back on an exception —
        so a `JobNotFoundError` raised mid-block (see `finish`/
        `write_checkpoint`) leaves no partial write, the same guarantee
        `DiskJobStore`'s write-ordering exists to approximate without a real
        transaction.
        """
        conn = self._get_connection()
        try:
            with conn, conn.cursor() as cur:
                yield cur
        finally:
            conn.close()

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
                        "(id, org_id, tool_name, label, facet_id, request, status, "
                        "created_at, updated_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            job_id,
                            org_id,
                            tool_name,
                            label,
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
            JobNotFoundError: If job not found.
        """
        if self.circuit_breaker.is_open():
            return self.fallback_store.get(job_id)

        try:
            with self._cursor() as cur:
                # `_JOB_COLUMNS` is a fixed module constant, never caller
                # input; `job_id` is still bound via a `%s` placeholder.
                cur.execute(f"SELECT {_JOB_COLUMNS} FROM jobs WHERE id = %s", (job_id,))  # noqa: S608
                row = cur.fetchone()
        except (psycopg.OperationalError, psycopg.DatabaseError) as err:
            self.circuit_breaker.record_failure(err)
            if self.circuit_breaker.is_open():
                return self.fallback_store.get(job_id)
            raise

        self.circuit_breaker.record_success()
        if row is None:
            raise JobNotFoundError(f"no job with id {job_id!r}")
        return _row_to_job_record(row)

    def list_jobs(self) -> list[JobRecord]:
        """List all jobs, newest first.

        Falls back to disk store if PostgreSQL is unavailable.

        Returns:
            List of JobRecords ordered by created_at DESC.
        """
        if self.circuit_breaker.is_open():
            return self.fallback_store.list_jobs()

        try:
            with self._cursor() as cur:
                # `_JOB_COLUMNS` is a fixed module constant, never caller input.
                cur.execute(f"SELECT {_JOB_COLUMNS} FROM jobs ORDER BY created_at DESC")  # noqa: S608
                rows = cur.fetchall()
        except (psycopg.OperationalError, psycopg.DatabaseError) as err:
            self.circuit_breaker.record_failure(err)
            if self.circuit_breaker.is_open():
                return self.fallback_store.list_jobs()
            raise

        self.circuit_breaker.record_success()
        return [_row_to_job_record(row) for row in rows]

    def _transition(self, job_id: str, set_sql: str, params: tuple[object, ...]) -> JobRecord:
        """Run one `UPDATE jobs SET <set_sql> ... RETURNING` and map the row back.

        `set_sql` is always a fixed literal passed by a method in this class,
        never caller input; every value is still bound via `%s`.
        """
        now = datetime.now(tz=UTC)
        with self._cursor() as cur:
            cur.execute(
                f"UPDATE jobs SET {set_sql}, updated_at = %s "  # noqa: S608
                f"WHERE id = %s RETURNING {_JOB_COLUMNS}",
                (*params, now, job_id),
            )
            row = cur.fetchone()
        if row is None:
            raise JobNotFoundError(f"no job with id {job_id!r}")
        return _row_to_job_record(row)

    def mark_running(self, job_id: str) -> JobRecord:
        """Mark a job as RUNNING. Falls back to disk store once the circuit opens."""
        if self.circuit_breaker.is_open():
            return self.fallback_store.mark_running(job_id)
        try:
            record = self._transition(
                job_id, "status = %s, started_at = %s", (JobStatus.RUNNING.value, datetime.now(UTC))
            )
        except (psycopg.OperationalError, psycopg.DatabaseError) as err:
            self.circuit_breaker.record_failure(err)
            if self.circuit_breaker.is_open():
                return self.fallback_store.mark_running(job_id)
            raise
        self.circuit_breaker.record_success()
        return record

    def update_telemetry(self, job_id: str, telemetry: JobTelemetry) -> JobRecord:
        """Replace a job's progress snapshot. Falls back to disk store once the circuit opens."""
        if self.circuit_breaker.is_open():
            return self.fallback_store.update_telemetry(job_id, telemetry)
        try:
            record = self._transition(
                job_id, "telemetry = %s", (json.dumps(telemetry.model_dump(mode="json")),)
            )
        except (psycopg.OperationalError, psycopg.DatabaseError) as err:
            self.circuit_breaker.record_failure(err)
            if self.circuit_breaker.is_open():
                return self.fallback_store.update_telemetry(job_id, telemetry)
            raise
        self.circuit_breaker.record_success()
        return record

    def mark_failed(self, job_id: str, error: str) -> JobRecord:
        """Mark job as FAILED with error. Falls back to disk store once the circuit opens."""
        if self.circuit_breaker.is_open():
            return self.fallback_store.mark_failed(job_id, error)
        try:
            record = self._transition(
                job_id,
                "status = %s, error = %s, finished_at = %s",
                (JobStatus.FAILED.value, error or "unknown error", datetime.now(UTC)),
            )
        except (psycopg.OperationalError, psycopg.DatabaseError) as err:
            self.circuit_breaker.record_failure(err)
            if self.circuit_breaker.is_open():
                return self.fallback_store.mark_failed(job_id, error)
            raise
        self.circuit_breaker.record_success()
        return record

    def finish(
        self,
        job_id: str,
        result: Mapping[str, object],
        *,
        partial: bool = False,
        error: str | None = None,
    ) -> JobRecord:
        """Store a result and move the job to a terminal status, in one transaction.

        Unlike `DiskJobStore` — which writes the result blob before the
        metadata flag because two separate files cannot be updated
        atomically — this is a single Postgres transaction: the
        `job_payloads` upsert and the `jobs` update either both land or
        neither does, so there is no ordering to get right.

        Falls back to disk store once the circuit opens.
        """
        if self.circuit_breaker.is_open():
            return self.fallback_store.finish(job_id, result, partial=partial, error=error)

        now = datetime.now(tz=UTC)
        status = JobStatus.PARTIAL if partial else JobStatus.SUCCEEDED
        try:
            with self._cursor() as cur:
                cur.execute("SELECT 1 FROM jobs WHERE id = %s FOR UPDATE", (job_id,))
                if cur.fetchone() is None:
                    raise JobNotFoundError(f"no job with id {job_id!r}")
                cur.execute(
                    "INSERT INTO job_payloads (job_id, result, updated_at) VALUES (%s, %s, %s) "
                    "ON CONFLICT (job_id) DO UPDATE SET "
                    "result = EXCLUDED.result, updated_at = EXCLUDED.updated_at",
                    (job_id, json.dumps(dict(result)), now),
                )
                cur.execute(
                    f"UPDATE jobs SET status = %s, has_result = true, finished_at = %s, "  # noqa: S608
                    f"updated_at = %s, error = %s WHERE id = %s RETURNING {_JOB_COLUMNS}",
                    (status.value, now, now, error, job_id),
                )
                row = cur.fetchone()
        except JobNotFoundError:
            raise
        except (psycopg.OperationalError, psycopg.DatabaseError) as err:
            self.circuit_breaker.record_failure(err)
            if self.circuit_breaker.is_open():
                return self.fallback_store.finish(job_id, result, partial=partial, error=error)
            raise

        self.circuit_breaker.record_success()
        if row is None:  # pragma: no cover - defensive: the FOR UPDATE above already confirmed it
            raise JobNotFoundError(f"no job with id {job_id!r}")
        _logger.info("job_finished", extra={"job_id": job_id, "status": status.value})
        return _row_to_job_record(row)

    def read_result(self, job_id: str) -> Mapping[str, object]:
        """Read a job's result blob. Falls back to disk store once the circuit opens.

        Raises:
            JobNotFoundError: If the job or its result does not exist.
        """
        if self.circuit_breaker.is_open():
            return self.fallback_store.read_result(job_id)

        try:
            with self._cursor() as cur:
                cur.execute(
                    "SELECT j.id, p.result FROM jobs j "
                    "LEFT JOIN job_payloads p ON p.job_id = j.id WHERE j.id = %s",
                    (job_id,),
                )
                row = cur.fetchone()
        except (psycopg.OperationalError, psycopg.DatabaseError) as err:
            self.circuit_breaker.record_failure(err)
            if self.circuit_breaker.is_open():
                return self.fallback_store.read_result(job_id)
            raise

        self.circuit_breaker.record_success()
        if row is None:
            raise JobNotFoundError(f"no job with id {job_id!r}")
        if row[1] is None:
            raise JobNotFoundError(f"job {job_id!r} has no result")
        return cast(Mapping[str, object], row[1])

    def write_checkpoint(self, job_id: str, payload: Mapping[str, object]) -> None:
        """Save partial work. Falls back to disk store once the circuit opens.

        Raises:
            JobNotFoundError: If the job does not exist.
        """
        if self.circuit_breaker.is_open():
            self.fallback_store.write_checkpoint(job_id, payload)
            return

        now = datetime.now(tz=UTC)
        try:
            with self._cursor() as cur:
                cur.execute("SELECT 1 FROM jobs WHERE id = %s", (job_id,))
                if cur.fetchone() is None:
                    raise JobNotFoundError(f"no job with id {job_id!r}")
                cur.execute(
                    "INSERT INTO job_payloads (job_id, checkpoint, updated_at) "
                    "VALUES (%s, %s, %s) ON CONFLICT (job_id) DO UPDATE SET "
                    "checkpoint = EXCLUDED.checkpoint, updated_at = EXCLUDED.updated_at",
                    (job_id, json.dumps(dict(payload)), now),
                )
                cur.execute(
                    "UPDATE jobs SET has_checkpoint = true, updated_at = %s WHERE id = %s",
                    (now, job_id),
                )
        except JobNotFoundError:
            raise
        except (psycopg.OperationalError, psycopg.DatabaseError) as err:
            self.circuit_breaker.record_failure(err)
            if self.circuit_breaker.is_open():
                self.fallback_store.write_checkpoint(job_id, payload)
                return
            raise
        else:
            self.circuit_breaker.record_success()

    def read_checkpoint(self, job_id: str) -> Mapping[str, object] | None:
        """Read saved partial work, or `None`. Never raises — matches `DiskJobStore`.

        Falls back to disk store once the circuit opens.
        """
        if self.circuit_breaker.is_open():
            return self.fallback_store.read_checkpoint(job_id)

        try:
            with self._cursor() as cur:
                cur.execute("SELECT checkpoint FROM job_payloads WHERE job_id = %s", (job_id,))
                row = cur.fetchone()
        except (psycopg.OperationalError, psycopg.DatabaseError) as err:
            self.circuit_breaker.record_failure(err)
            if self.circuit_breaker.is_open():
                return self.fallback_store.read_checkpoint(job_id)
            _logger.warning("checkpoint_unreadable", extra={"job_id": job_id, "error": str(err)})
            return None

        self.circuit_breaker.record_success()
        if row is None or row[0] is None:
            return None
        return cast(Mapping[str, object], row[0])

    def write_homepage(self, job_id: str, html: str) -> None:
        """Save the homepage body. Never raises — matches `DiskJobStore`.

        Falls back to disk store once the circuit opens.
        """
        if len(html.encode("utf-8", "ignore")) > MAX_HOMEPAGE_BYTES:
            _logger.info("homepage_too_large", extra={"job_id": job_id})
            return
        if self.circuit_breaker.is_open():
            self.fallback_store.write_homepage(job_id, html)
            return

        now = datetime.now(tz=UTC)
        try:
            with self._cursor() as cur:
                cur.execute("SELECT 1 FROM jobs WHERE id = %s", (job_id,))
                if cur.fetchone() is None:
                    raise JobNotFoundError(f"no job with id {job_id!r}")
                cur.execute(
                    "INSERT INTO job_payloads (job_id, homepage_html, updated_at) "
                    "VALUES (%s, %s, %s) ON CONFLICT (job_id) DO UPDATE SET "
                    "homepage_html = EXCLUDED.homepage_html, updated_at = EXCLUDED.updated_at",
                    (job_id, html, now),
                )
        except JobNotFoundError as exc:
            _logger.warning("homepage_write_failed", extra={"job_id": job_id, "error": str(exc)})
            return
        except (psycopg.OperationalError, psycopg.DatabaseError) as err:
            self.circuit_breaker.record_failure(err)
            if self.circuit_breaker.is_open():
                self.fallback_store.write_homepage(job_id, html)
                return
            _logger.warning("homepage_write_failed", extra={"job_id": job_id, "error": str(err)})
            return
        else:
            self.circuit_breaker.record_success()

    def read_homepage(self, job_id: str) -> str | None:
        """Read the saved homepage body, or `None`. Never raises — matches `DiskJobStore`.

        Falls back to disk store once the circuit opens.
        """
        if self.circuit_breaker.is_open():
            return self.fallback_store.read_homepage(job_id)

        try:
            with self._cursor() as cur:
                cur.execute("SELECT homepage_html FROM job_payloads WHERE job_id = %s", (job_id,))
                row = cur.fetchone()
        except (psycopg.OperationalError, psycopg.DatabaseError) as err:
            self.circuit_breaker.record_failure(err)
            if self.circuit_breaker.is_open():
                return self.fallback_store.read_homepage(job_id)
            _logger.warning("homepage_read_failed", extra={"job_id": job_id, "error": str(err)})
            return None

        self.circuit_breaker.record_success()
        if row is None or row[0] is None:
            return None
        return cast(str, row[0])

    def write_reconciliation(self, job_id: str, payload: Mapping[str, object]) -> None:
        """Delegate to disk. Reconciliation reports are out of this cycle's Postgres scope."""
        self.fallback_store.write_reconciliation(job_id, payload)

    def read_reconciliation(self, job_id: str) -> Mapping[str, object] | None:
        """Delegate to disk. Reconciliation reports are out of this cycle's Postgres scope."""
        return self.fallback_store.read_reconciliation(job_id)

    def write_performance(self, job_id: str, payload: Mapping[str, object]) -> None:
        """Delegate to disk. Performance reports are out of this cycle's Postgres scope."""
        self.fallback_store.write_performance(job_id, payload)

    def read_performance(self, job_id: str) -> Mapping[str, object] | None:
        """Delegate to disk. Performance reports are out of this cycle's Postgres scope."""
        return self.fallback_store.read_performance(job_id)

    def recover_orphans(self) -> list[str]:
        """Fail every job left non-terminal by a previous process.

        Recovers whichever store is currently active — Postgres jobs when the
        circuit is closed, disk jobs when it is open — the same split
        `create()` already makes. A job created while the circuit was open and
        left running when the process died is recovered on the next disk-side
        `recover_orphans()` call, not this one; see the ADR for why that residual
        gap is accepted rather than solved by a dual-store scan.

        Falls back to disk store once the circuit opens.
        """
        if self.circuit_breaker.is_open():
            return self.fallback_store.recover_orphans()

        now = datetime.now(tz=UTC)
        base_reason = "interrupted by a server restart"
        checkpoint_reason = f"{base_reason} — partial results were saved and can be viewed"
        try:
            with self._cursor() as cur:
                cur.execute(
                    "UPDATE jobs SET status = %s, "
                    "error = CASE WHEN has_checkpoint THEN %s ELSE %s END, "
                    "finished_at = %s, updated_at = %s "
                    "WHERE status IN (%s, %s) RETURNING id",
                    (
                        JobStatus.FAILED.value,
                        checkpoint_reason,
                        base_reason,
                        now,
                        now,
                        JobStatus.QUEUED.value,
                        JobStatus.RUNNING.value,
                    ),
                )
                rows = cur.fetchall()
        except (psycopg.OperationalError, psycopg.DatabaseError) as err:
            self.circuit_breaker.record_failure(err)
            if self.circuit_breaker.is_open():
                return self.fallback_store.recover_orphans()
            raise

        self.circuit_breaker.record_success()
        recovered = [str(row[0]) for row in rows]
        if recovered:
            _logger.warning("orphaned_jobs_recovered", extra={"count": len(recovered)})
        return recovered
