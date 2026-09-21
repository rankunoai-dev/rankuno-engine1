"""The `WorkerDispatchStore` persistence seam (ADR 0015 condition 5).

Split out of `postgres_worker_dispatch_store` to keep each file under this
codebase's 400-line target: this module holds the Protocol, the shared
errors, and the row-mapping helper; that module holds the one Postgres
implementation. Both are part of the same design and are meant to be read
together — see `postgres_worker_dispatch_store`'s module docstring for the
"never fail open" reasoning this Protocol's contract encodes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, cast

from src.core.errors import RankunoError
from src.core.worker_dispatch_schemas import (
    DispatchPreviewToken,
    WorkerJob,
    WorkerJobEnvelope,
    WorkerJobKind,
    WorkerJobStatus,
)

__all__ = [
    "DEFAULT_PREVIEW_TTL_S",
    "DispatchStoreUnavailableError",
    "WorkerDispatchStore",
    "WorkerJobNotFoundError",
]

DEFAULT_PREVIEW_TTL_S = 120.0
"""Matches `preview_tokens.DEFAULT_TOKEN_TTL_S`: long enough for an operator
to read a confirmation modal, short enough that a leaked token is narrow."""

SELECT_COLUMNS = (
    "id, org_id, worker_id, kind, seed_url, template_name, correlation_id, "
    "status, created_at, updated_at, dispatched_at, finished_at, error, bundle_size_bytes"
)
"""Column list every `worker_jobs` read uses, in the order `row_to_job` expects."""


class DispatchStoreUnavailableError(RankunoError):
    """Postgres could not be reached. Callers must fail closed, never approve."""


class WorkerJobNotFoundError(KeyError):
    """No such worker job exists."""


class WorkerDispatchStore(Protocol):
    """The persistence seam for ADR 0015's dispatch gate and job queue.

    A Protocol, matching `JobStore`/`OperatorStore`, so a future
    implementation can replace `PostgresWorkerDispatchStore` without the API
    layer changing — condition 5 names Postgres as this cycle's choice, not
    necessarily forever.
    """

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
        ...

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

        Returns `None` — never raises — for any mismatch, expiry, or
        already-consumed token: the safe failure this module exists for.
        """
        ...

    def claim_next_job(self, *, worker_id: str, org_id: str) -> WorkerJob | None:
        """Atomically claim the oldest queued job pinned to this worker."""
        ...

    def get_job(self, job_id: str) -> WorkerJob:
        """Read one job.

        Raises:
            WorkerJobNotFoundError: If no such job exists.
        """
        ...

    def list_jobs_for_org(self, org_id: str) -> list[WorkerJob]:
        """Every job for an org, newest first."""
        ...

    def expire_stale_dispatched(self, *, org_id: str, older_than_s: float) -> int:
        """Move long-abandoned `DISPATCHED` jobs to `FAILED`. Returns the count.

        The bounded way out of the stuck-job trap: a daemon that dies after
        claiming a job leaves it `DISPATCHED` forever, and the worker's own
        single-use `ConsumedJobLedger` means the *same* job id can never run
        again even if the daemon comes back.

        Terminal `FAILED`, deliberately, rather than a requeue. Requeuing
        would hand the same `job_id` back to a worker whose ledger has
        already consumed it — it would be claimed and immediately skipped,
        a loop that looks like progress and is not. It would also re-run a
        crawl on an approval artifact the operator granted for an attempt
        that already happened; a fresh run is a fresh preview/confirm, which
        is the same rule ADR 0015 condition 3(a) applies to every other
        dispatch.
        """
        ...

    def mark_uploaded(
        self, job_id: str, *, bundle_size_bytes: int, partial: bool = False
    ) -> WorkerJob:
        """Move a job to `SUCCEEDED`/`PARTIAL` once its bundle is stored."""
        ...

    def mark_failed(self, job_id: str, error: str) -> WorkerJob:
        """Move a job to `FAILED` with a reason."""
        ...

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

        Access-scoped by `org_id`/`worker_id` at insert time, matching how
        job records are already scoped (ADR 0015 condition 11). Encryption
        happens before this call — this method knows nothing about keys.
        """
        ...

    def read_upload(self, job_id: str, *, org_id: str) -> bytes | None:
        """Read one org's encrypted bundle blob, or `None` if absent/expired.

        `org_id` is required and checked, not merely accepted, so a caller
        cannot read another organization's bundle by guessing a `job_id`.
        """
        ...


def _optional_datetime(value: object) -> datetime | None:
    return None if value is None else cast(datetime, value)


def row_to_job(row: tuple[object, ...]) -> WorkerJob:
    """Map one `SELECT_COLUMNS`-shaped database row onto a `WorkerJob`."""
    (
        job_id,
        org_id,
        worker_id,
        kind,
        seed_url,
        template_name,
        correlation_id,
        status,
        created_at,
        updated_at,
        dispatched_at,
        finished_at,
        error,
        bundle_size_bytes,
    ) = row
    return WorkerJob(
        id=str(job_id),
        org_id=str(org_id),
        worker_id=str(worker_id),
        kind=WorkerJobKind(str(kind)),
        envelope=WorkerJobEnvelope(
            job_id=str(job_id),
            seed_url=str(seed_url),
            template_name=None if template_name is None else str(template_name),
            correlation_id=str(correlation_id),
        ),
        status=WorkerJobStatus(str(status)),
        created_at=cast(datetime, created_at),
        updated_at=cast(datetime, updated_at),
        dispatched_at=_optional_datetime(dispatched_at),
        finished_at=_optional_datetime(finished_at),
        error=None if error is None else str(error),
        bundle_size_bytes=None if bundle_size_bytes is None else int(cast(int, bundle_size_bytes)),
    )
