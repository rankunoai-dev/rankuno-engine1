"""The persistent, multi-replica-safe half of ADR 0015's dual approval gate.

ADR 0015 condition 5: the preview/confirm dispatch gate and the job queue
move to a shared, persistent store before this ships with more than one
cloud replica — reusing Postgres (`src.core.postgres_config`, already
present), not inventing a third storage mechanism, and not silently falling
back to an in-process store the way `screaming_frog_control.preview_tokens`
correctly does for its single-workstation case (ADR 0004) but this cloud
surface cannot.

The failure mode this exists to prevent, named explicitly per condition 5:
two cloud API replicas, an operator confirms on replica A (which would mint
a token only that replica remembers), the worker's poll lands on replica B,
which never heard of it. **The safe failure is "approval silently fails,
nothing runs" — never "unrecognized token fails open."** Every method below
either finds a real, unexpired, unconsumed row in the shared database or
returns `None`/raises; nothing here has a local fallback path that could
paper over Postgres being unreachable by quietly approving anyway. A
`DispatchStoreUnavailableError` propagates instead, for the API layer to
turn into a `503` — a refused request is the safe failure; a silently
approved one is not.

This intentionally does *not* mirror `PostgresJobStore`'s disk-fallback
pattern. That fallback exists for job *records*, where "keep working, in
degraded form, on one machine" is an acceptable trade (ADR 0004's
single-workstation posture). It is not acceptable for an approval gate: a
degraded fallback that still approves things is exactly the
`AutoApproveProvider`-by-another-name shape CLAUDE.md §3 forbids.

The `WorkerDispatchStore` Protocol, the shared errors, and the row-mapping
helper live in `src.core.worker_dispatch_store` — split out so each file
stays under this codebase's 400-line target; both modules are one design.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

from src.core.logger import get_logger
from src.core.postgres_config import get_postgres_settings
from src.core.worker_dispatch_schemas import (
    DispatchPreviewToken,
    WorkerJob,
    WorkerJobEnvelope,
    WorkerJobKind,
    WorkerJobStatus,
)
from src.core.worker_dispatch_store import (
    DEFAULT_PREVIEW_TTL_S,
    SELECT_COLUMNS,
    DispatchStoreUnavailableError,
    WorkerJobNotFoundError,
    row_to_job,
)

if TYPE_CHECKING:
    from psycopg import Connection

__all__ = ["PostgresWorkerDispatchStore"]

_logger = get_logger("core.postgres_worker_dispatch_store")


class PostgresWorkerDispatchStore:
    """Postgres-backed implementation of `WorkerDispatchStore`.

    No circuit breaker, no fallback (see module docstring). A
    `connection_factory` is accepted so tests can inject a fake
    psycopg-shaped connection without a live database — production callers
    leave it `None` and get a fresh connection per call from
    `get_postgres_settings()`, matching `PostgresJobStore`'s own posture on
    credential rotation (re-read per connection, never cached across calls).
    """

    def __init__(self, connection_factory: Callable[[], Connection] | None = None) -> None:
        """Build the store.

        Args:
            connection_factory: Returns a new `psycopg.Connection`. Defaults
                to a real connection built from `get_postgres_settings()`.
        """
        self._connection_factory = connection_factory or self._default_connection_factory

    @staticmethod
    def _default_connection_factory() -> Connection:
        import psycopg

        settings = get_postgres_settings()
        connection_string = settings.get_connection_string()
        return psycopg.connect(connection_string)

    def _connect(self) -> Connection:
        try:
            return self._connection_factory()
        except Exception as exc:  # noqa: BLE001 - re-raised as a typed, fail-closed error
            raise DispatchStoreUnavailableError(f"cannot reach the dispatch store: {exc}") from exc

    def mint_dispatch_preview(
        self,
        *,
        org_id: str,
        worker_id: str,
        seed_url: str,
        template_name: str | None,
        correlation_id: str,
        ttl_s: float = DEFAULT_PREVIEW_TTL_S,
    ) -> DispatchPreviewToken:
        """Mint gate (a)'s preview token. Nothing is queued yet."""
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_s)
        conn = self._connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO org_configs (org_id, display_name) VALUES (%s, %s) "
                    "ON CONFLICT (org_id) DO NOTHING",
                    (org_id, f"Org {org_id}"),
                )
                cur.execute(
                    "INSERT INTO worker_dispatch_previews "
                    "(token, org_id, worker_id, seed_url, template_name, correlation_id, "
                    "expires_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (token, org_id, worker_id, seed_url, template_name, correlation_id, expires_at),
                )
        except Exception as exc:  # noqa: BLE001 - fail closed, never silently approve
            raise DispatchStoreUnavailableError(f"cannot mint dispatch preview: {exc}") from exc
        finally:
            conn.close()
        return DispatchPreviewToken(
            token=token,
            org_id=org_id,
            worker_id=worker_id,
            seed_url=seed_url,
            template_name=template_name,
            correlation_id=correlation_id,
            expires_at=expires_at,
        )

    def confirm_dispatch(
        self,
        token: str,
        *,
        org_id: str,
        worker_id: str,
        seed_url: str,
        template_name: str | None,
        correlation_id: str,
    ) -> WorkerJob | None:
        """Atomically consume the preview token and queue a job.

        One transaction: the `UPDATE ... RETURNING` on the preview row and
        the `INSERT` of the job row either both land or neither does — a
        crash between them must never leave a consumed token with no job to
        show for it.
        """
        job_id = uuid.uuid4().hex
        now = datetime.now(UTC)
        conn = self._connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE worker_dispatch_previews SET consumed_at = %s "
                    "WHERE token = %s AND org_id = %s AND worker_id = %s AND seed_url = %s "
                    "AND template_name IS NOT DISTINCT FROM %s "
                    "AND correlation_id = %s AND consumed_at IS NULL AND expires_at > %s "
                    "RETURNING token",
                    (
                        now,
                        token,
                        org_id,
                        worker_id,
                        seed_url,
                        template_name,
                        correlation_id,
                        now,
                    ),
                )
                if cur.fetchone() is None:
                    _logger.warning(
                        "worker_dispatch_confirm_rejected_bad_token",
                        extra={"org": org_id, "worker_id": worker_id},
                    )
                    return None

                cur.execute(
                    "INSERT INTO worker_jobs "
                    "(id, org_id, worker_id, kind, seed_url, template_name, correlation_id, "
                    "status, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        job_id,
                        org_id,
                        worker_id,
                        WorkerJobKind.SCREAMING_FROG_CRAWL.value,
                        seed_url,
                        template_name,
                        correlation_id,
                        WorkerJobStatus.QUEUED.value,
                        now,
                        now,
                    ),
                )
        except Exception as exc:  # noqa: BLE001 - fail closed, never silently approve
            raise DispatchStoreUnavailableError(f"cannot confirm dispatch: {exc}") from exc
        finally:
            conn.close()

        _logger.info("worker_job_queued", extra={"job_id": job_id, "worker_id": worker_id})
        return WorkerJob(
            id=job_id,
            org_id=org_id,
            worker_id=worker_id,
            kind=WorkerJobKind.SCREAMING_FROG_CRAWL,
            envelope=WorkerJobEnvelope(
                job_id=job_id,
                seed_url=seed_url,
                template_name=template_name,
                correlation_id=correlation_id,
            ),
            status=WorkerJobStatus.QUEUED,
            created_at=now,
            updated_at=now,
        )

    def claim_next_job(self, *, worker_id: str, org_id: str) -> WorkerJob | None:
        """Atomically claim the oldest queued job pinned to this worker.

        `FOR UPDATE SKIP LOCKED` inside the CTE is what makes this safe
        across cloud replicas (condition 5): two replicas racing the same
        worker's poll can each claim a *different* queued job, never the
        same one twice, with no application-level locking required.
        """
        now = datetime.now(UTC)
        # `SELECT_COLUMNS` is a fixed module constant, never caller input;
        # every value in this query is still bound via a `%s` placeholder.
        query = (
            "WITH next_job AS ("  # noqa: S608
            "  SELECT id FROM worker_jobs "
            "  WHERE worker_id = %s AND org_id = %s AND status = %s "
            "  ORDER BY created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED"
            ") "
            "UPDATE worker_jobs SET status = %s, dispatched_at = %s, updated_at = %s "
            f"WHERE id IN (SELECT id FROM next_job) RETURNING {SELECT_COLUMNS}"
        )
        conn = self._connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    query,
                    (
                        worker_id,
                        org_id,
                        WorkerJobStatus.QUEUED.value,
                        WorkerJobStatus.DISPATCHED.value,
                        now,
                        now,
                    ),
                )
                row = cur.fetchone()
        except Exception as exc:  # noqa: BLE001 - fail closed, never silently approve
            raise DispatchStoreUnavailableError(f"cannot claim next job: {exc}") from exc
        finally:
            conn.close()
        if row is None:
            return None
        job = row_to_job(row)
        _logger.info("worker_job_claimed", extra={"job_id": job.id, "worker_id": worker_id})
        return job

    def get_job(self, job_id: str) -> WorkerJob:
        """Read one job.

        Raises:
            WorkerJobNotFoundError: If no such job exists.
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                # `SELECT_COLUMNS` is a fixed module constant, never caller
                # input; `job_id` is still bound via a `%s` placeholder.
                cur.execute(
                    f"SELECT {SELECT_COLUMNS} FROM worker_jobs WHERE id = %s",  # noqa: S608
                    (job_id,),
                )
                row = cur.fetchone()
        except Exception as exc:  # noqa: BLE001
            raise DispatchStoreUnavailableError(f"cannot read job {job_id}: {exc}") from exc
        finally:
            conn.close()
        if row is None:
            msg = f"no worker job with id {job_id!r}"
            raise WorkerJobNotFoundError(msg)
        return row_to_job(row)

    def list_jobs_for_org(self, org_id: str) -> list[WorkerJob]:
        """Every job for an org, newest first."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    # `SELECT_COLUMNS` is a fixed module constant, never
                    # caller input; `org_id` is bound via a `%s` placeholder.
                    f"SELECT {SELECT_COLUMNS} FROM worker_jobs "  # noqa: S608
                    "WHERE org_id = %s ORDER BY created_at DESC",
                    (org_id,),
                )
                rows = cur.fetchall()
        except Exception as exc:  # noqa: BLE001
            raise DispatchStoreUnavailableError(f"cannot list jobs for {org_id}: {exc}") from exc
        finally:
            conn.close()
        return [row_to_job(row) for row in rows]

    def expire_stale_dispatched(self, *, org_id: str, older_than_s: float) -> int:
        """Sweep abandoned `DISPATCHED` jobs for one org to `FAILED`.

        Scoped to a single org and driven by a request rather than a
        background thread: the API process here is a web worker, and adding
        a sweeper thread to it would multiply by replica count the same way
        `CLAUDE.md` §8 already records for the rate limiter. The two callers
        — a worker's poll and the dashboard's job list — between them cover
        both the "daemon alive, one job wedged" and "daemon dead, nobody
        polling" cases.

        See `WorkerDispatchStore.expire_stale_dispatched` for why the
        terminal state is `FAILED` and not a requeue.
        """
        cutoff = datetime.now(UTC) - timedelta(seconds=older_than_s)
        now = datetime.now(UTC)
        error = (
            f"the worker stopped reporting after claiming this job; no result "
            f"arrived within {int(older_than_s)}s. Start the worker daemon and "
            f"launch the crawl again."
        )
        conn = self._connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE worker_jobs SET status = %s, error = %s, "
                    "updated_at = %s, finished_at = %s "
                    "WHERE org_id = %s AND status = %s AND dispatched_at IS NOT NULL "
                    "AND dispatched_at < %s",
                    (
                        WorkerJobStatus.FAILED.value,
                        error,
                        now,
                        now,
                        org_id,
                        WorkerJobStatus.DISPATCHED.value,
                        cutoff,
                    ),
                )
                swept = cur.rowcount
        except Exception as exc:  # noqa: BLE001
            raise DispatchStoreUnavailableError(f"cannot expire stale jobs: {exc}") from exc
        finally:
            conn.close()
        if swept:
            _logger.warning(
                "worker_jobs_expired_stale_dispatch", extra={"org": org_id, "count": swept}
            )
        return int(swept)

    _TRANSITION_FIELDS = frozenset({"bundle_size_bytes", "error"})
    """Closed set of column names `_transition` may assign, so the dynamic
    `SET` clause below is built only from names this class itself passes —
    never from anything resembling caller input."""

    def _transition(self, job_id: str, *, status: WorkerJobStatus, **fields: object) -> WorkerJob:
        if not set(fields) <= self._TRANSITION_FIELDS:
            msg = f"_transition() does not allow columns {set(fields) - self._TRANSITION_FIELDS}"
            raise ValueError(msg)
        now = datetime.now(UTC)
        extra_assignments = ", ".join(f"{name} = %s" for name in fields)
        set_clause = ", ".join(
            part
            for part in ("status = %s", "updated_at = %s", "finished_at = %s", extra_assignments)
            if part
        )
        conn = self._connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    # `set_clause`/`SELECT_COLUMNS` are built only from the
                    # fixed `_TRANSITION_FIELDS` set asserted above and a
                    # module constant — never caller input. Every value is
                    # still bound via a `%s` placeholder.
                    f"UPDATE worker_jobs SET {set_clause} WHERE id = %s "  # noqa: S608
                    f"RETURNING {SELECT_COLUMNS}",
                    (status.value, now, now, *fields.values(), job_id),
                )
                row = cur.fetchone()
        except Exception as exc:  # noqa: BLE001
            raise DispatchStoreUnavailableError(f"cannot update job {job_id}: {exc}") from exc
        finally:
            conn.close()
        if row is None:
            msg = f"no worker job with id {job_id!r}"
            raise WorkerJobNotFoundError(msg)
        return row_to_job(row)

    def mark_uploaded(
        self, job_id: str, *, bundle_size_bytes: int, partial: bool = False
    ) -> WorkerJob:
        """Move a job to `SUCCEEDED`/`PARTIAL` once its bundle is stored."""
        status = WorkerJobStatus.PARTIAL if partial else WorkerJobStatus.SUCCEEDED
        return self._transition(job_id, status=status, bundle_size_bytes=bundle_size_bytes)

    def mark_failed(self, job_id: str, error: str) -> WorkerJob:
        """Move a job to `FAILED` with a reason."""
        return self._transition(job_id, status=WorkerJobStatus.FAILED, error=error)

    def store_upload(
        self,
        job_id: str,
        *,
        org_id: str,
        worker_id: str,
        encrypted_bytes: bytes,
        retention_days: int,
    ) -> None:
        """Persist an already-validated, already-encrypted bundle blob.

        `ON CONFLICT ... DO UPDATE` rather than a bare `INSERT`: a job can
        only ever be marked uploaded once in practice (its status moves off
        `DISPATCHED`), but an idempotent upsert costs nothing and avoids a
        second, redundant existence check under a lock.
        """
        expires_at = datetime.now(UTC) + timedelta(days=retention_days)
        conn = self._connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO worker_job_uploads "
                    "(job_id, org_id, worker_id, encrypted_bytes, size_bytes, expires_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (job_id) DO UPDATE SET "
                    "encrypted_bytes = EXCLUDED.encrypted_bytes, "
                    "size_bytes = EXCLUDED.size_bytes, expires_at = EXCLUDED.expires_at",
                    (job_id, org_id, worker_id, encrypted_bytes, len(encrypted_bytes), expires_at),
                )
        except Exception as exc:  # noqa: BLE001 - fail closed, never silently approve
            raise DispatchStoreUnavailableError(f"cannot store upload for {job_id}: {exc}") from exc
        finally:
            conn.close()

    def read_upload(self, job_id: str, *, org_id: str) -> bytes | None:
        """Read one org's encrypted bundle blob, or `None` if absent/expired."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT encrypted_bytes FROM worker_job_uploads "
                    "WHERE job_id = %s AND org_id = %s AND expires_at > %s",
                    (job_id, org_id, datetime.now(UTC)),
                )
                row = cur.fetchone()
        except Exception as exc:  # noqa: BLE001
            raise DispatchStoreUnavailableError(f"cannot read upload for {job_id}: {exc}") from exc
        finally:
            conn.close()
        if row is None:
            return None
        return bytes(cast(bytes, row[0]))
