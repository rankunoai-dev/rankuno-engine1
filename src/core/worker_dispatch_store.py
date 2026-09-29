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

from pydantic import Field

from src.core.errors import RankunoError
from src.core.schemas import StrictModel
from src.core.worker_dispatch_schemas import (
    DispatchPreviewToken,
    WorkerJob,
    WorkerJobEnvelope,
    WorkerJobKind,
    WorkerJobPhase,
    WorkerJobStatus,
)

__all__ = [
    "DEFAULT_PREVIEW_TTL_S",
    "DispatchStoreUnavailableError",
    "StoredUrlList",
    "WorkerDispatchStore",
    "WorkerJobNotFoundError",
]

DEFAULT_PREVIEW_TTL_S = 120.0
"""Matches `preview_tokens.DEFAULT_TOKEN_TTL_S`: long enough for an operator
to read a confirmation modal, short enough that a leaked token is narrow."""

SELECT_COLUMNS = (
    "id, org_id, worker_id, kind, seed_url, template_name, correlation_id, "
    "status, created_at, updated_at, dispatched_at, finished_at, error, bundle_size_bytes, "
    "pages_crawled, progress_pct, current_phase, url_list_sha256, url_list_url_count"
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
        url_list_sha256: str | None = None,
    ) -> DispatchPreviewToken:
        """Mint gate (a)'s preview token. Nothing is queued yet.

        `url_list_sha256` binds an already-generated, already-stored URL
        list into the token (ADR 0023). It defaults to `None` so every
        existing caller keeps its exact behaviour for an ordinary `--crawl`
        dispatch.
        """
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
        url_list_sha256: str | None = None,
        url_list_url_count: int | None = None,
    ) -> WorkerJob | None:
        """Atomically consume the preview token and queue a job.

        Returns `None` — never raises — for any mismatch, expiry, or
        already-consumed token: the safe failure this module exists for. A
        `url_list_sha256` that does not match the one the preview was
        minted with is exactly such a mismatch, and it is the check that
        stops an operator being shown one list and confirming another
        (ADR 0023).
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
        self,
        job_id: str,
        *,
        bundle_size_bytes: int,
        partial: bool = False,
        reason: str | None = None,
    ) -> WorkerJob:
        """Move a job to `SUCCEEDED`/`PARTIAL` once its bundle is stored.

        Args:
            job_id: The job to transition.
            bundle_size_bytes: Size of the stored, rebuilt archive.
            partial: Whether the bundle is incomplete. `PARTIAL` rather than
                `SUCCEEDED`.
            reason: Why it is partial, in an operator's words. Written to the
                same `error` column `mark_failed` uses, because that is the
                one the dashboard already reads and shows — a `PARTIAL` row
                with nothing there renders as "No reason was recorded."
        """
        ...

    def mark_failed(self, job_id: str, error: str) -> WorkerJob:
        """Move a job to `FAILED` with a reason."""
        ...

    def update_job_progress(
        self,
        job_id: str,
        *,
        pages_crawled: int | None,
        progress_pct: float | None,
        phase: WorkerJobPhase | None,
    ) -> WorkerJob:
        """Persist a worker's latest progress snapshot for a claimed job.

        Never changes `status`: a job's lifecycle transition is owned by
        `mark_uploaded`/`mark_failed`/`claim_next_job` alone, so a progress
        report racing a terminal transition can only ever overwrite these
        three columns, never resurrect or short-circuit the job itself. A
        report that arrives after the job has already finished is therefore
        harmless — it updates fields no caller should read as authoritative
        over `status` in the first place.

        Raises:
            WorkerJobNotFoundError: If no such job exists.
        """
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

    def store_url_list(
        self,
        *,
        org_id: str,
        sha256: str,
        body: bytes,
        url_count: int,
        source_job_id: str,
        retention_days: int,
    ) -> None:
        """Persist a generated `--crawl-list` file, addressed by its digest.

        Called at **preview** time, before any human has approved anything,
        so that the bytes an operator is shown a fingerprint of are the
        bytes that exist from then on. Generating at download time instead
        would let the source crawl be deleted, re-run or extended between
        approval and fetch, and the worker would crawl something nobody
        approved.

        Keyed by `(sha256, org_id)`: the digest is already the identity
        every gate compares, so a second preview producing an identical
        list reuses the row instead of writing a duplicate, and one org can
        never address another org's blob even holding the right digest.
        """
        ...

    def read_url_list(self, sha256: str, *, org_id: str) -> StoredUrlList | None:
        """Read one org's stored list, or `None` if absent or past retention."""
        ...

    def find_active_job(self, *, worker_id: str, org_id: str) -> WorkerJob | None:
        """The one `QUEUED`/`DISPATCHED` job blocking this worker, if any.

        The `seo.screaming_frog` facet is capped at `max_concurrent = 1`
        (`src.core.facet_router`), and that cap is load-bearing rather than
        conservative: Screaming Frog's `trace.txt` is shared across every
        invocation on a workstation, and the offset-scoped licence read only
        stays correct while exactly one supervised process is appending to
        it (`license_check`'s own module docstring). This is how the cloud
        dispatch path enforces the cap the local path already gets from
        `ApiState.try_reserve` — by refusing a second dispatch and naming
        the first, rather than queueing work that would corrupt that read.
        """
        ...


class StoredUrlList(StrictModel):
    """One persisted `--crawl-list` file, and the facts a caller checks.

    A `StrictModel` rather than bare `bytes` because two of these fields
    are compared, not merely displayed: `sha256` is recomputed by the
    worker after download and refused on mismatch, and `url_count` is the
    denominator of the finished job's truncation check.

    Attributes:
        sha256: Digest of `body`, as stored.
        body: The exact rendered file — CRLF-separated UTF-8 with no BOM
            (`screaming_frog_control.url_list.LIST_ENCODING`).
        url_count: How many URLs `body` holds.
        source_job_id: The Rankuno crawl the URLs came from. Audit only:
            that crawl may have been deleted since, and deliberately does
            not invalidate a list already approved against it.
    """

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    body: bytes
    url_count: int = Field(ge=0)
    source_job_id: str = Field(default="", max_length=64)


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
        pages_crawled,
        progress_pct,
        current_phase,
        url_list_sha256,
        url_list_url_count,
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
            url_list_sha256=None if url_list_sha256 is None else str(url_list_sha256),
        ),
        status=WorkerJobStatus(str(status)),
        created_at=cast(datetime, created_at),
        updated_at=cast(datetime, updated_at),
        dispatched_at=_optional_datetime(dispatched_at),
        finished_at=_optional_datetime(finished_at),
        error=None if error is None else str(error),
        bundle_size_bytes=None if bundle_size_bytes is None else int(cast(int, bundle_size_bytes)),
        pages_crawled=None if pages_crawled is None else int(cast(int, pages_crawled)),
        progress_pct=None if progress_pct is None else float(cast(float, progress_pct)),
        current_phase=None if current_phase is None else WorkerJobPhase(str(current_phase)),
        url_list_url_count=(
            None if url_list_url_count is None else int(cast(int, url_list_url_count))
        ),
    )
