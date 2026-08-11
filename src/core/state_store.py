"""Durable job records for work that outlives the request that started it.

A 20k-page crawl takes minutes. Nothing that long can run inside an HTTP
request, so the request that *starts* a crawl and the request that *reads* its
result are different requests, in different connections, possibly on different
sides of a process restart. This module is what they share.

Domain-agnostic, deliberately
-----------------------------
`core/` must not import from `modules/` (CLAUDE.md §1). So this store knows
nothing about crawls, pages or classification: a job carries an opaque
`request` mapping in and an opaque `result` mapping out, and the caller that
owns the domain types validates them at its own boundary. The alternative —
typing `JobRecord.result` as `PageClassificationOutput` — would be a
`core -> modules` import and a build failure.

That constraint is also the right design. The same store will hold PPC and
research jobs without modification.

Metadata and results are stored separately. A finished 20k-page result is
roughly 16 MB; listing jobs must not read it, or the job list becomes the most
expensive endpoint in the system.

Durability
----------
Every write goes to a temporary file and is then moved into place with
`os.replace`, which is atomic. A process killed mid-write leaves either the
previous record or the new one, never a half-written record that fails to parse
and takes the job with it.

`recover_orphans()` closes the other half of the same problem: a job that was
`RUNNING` when the process died has no one running it any more, and would
otherwise be polled forever by a UI waiting for it to finish.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import Field

from src.core.logger import get_logger
from src.core.schemas import StrictModel

__all__ = [
    "MAX_RECENT_ITEMS",
    "DiskJobStore",
    "JobNotFoundError",
    "JobRecord",
    "JobStatus",
    "JobStore",
    "JobTelemetry",
]

_logger = get_logger("core.state_store")


class JobStatus(StrEnum):
    """Lifecycle of a background job.

    Lowercase values, matching the other governance enums (CLAUDE.md §7 ruling
    3) and the `JobStatus` union the frontend already declares.
    """

    QUEUED = "queued"
    """Accepted and persisted, not yet picked up by a worker."""

    RUNNING = "running"
    """A worker is executing it now."""

    SUCCEEDED = "succeeded"
    """Finished, with a complete result."""

    PARTIAL = "partial"
    """Finished, but the result is incomplete — a crawl that hit its ceiling.

    Distinct from `SUCCEEDED` because the caller must be able to tell that what
    it is looking at is not the whole site. Presenting a truncated crawl as a
    complete one is how an audit reaches a confident wrong conclusion.
    """

    FAILED = "failed"
    """Did not produce a result. `error` says why."""


TERMINAL_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.PARTIAL, JobStatus.FAILED})
"""Statuses from which a job never moves again, so a poller can stop."""


MAX_RECENT_ITEMS = 20
"""Recent work items retained for display.

A bound, not a preference. A 20,000-page crawl returning every URL on every
status poll would push megabytes per second at a browser that only ever renders
the last handful — the poller would cost more than the crawl.
"""


class JobNotFoundError(KeyError):
    """No job exists with the given id."""


class JobTelemetry(StrictModel):
    """Live progress for a running job.

    Kept deliberately small: this rides on every status poll, and a poller runs
    for the whole life of a long job.

    Domain-agnostic like the rest of this module — "items" are whatever the job
    processes. The API layer maps crawl vocabulary onto these fields; nothing
    here imports from `modules/`.

    Attributes:
        completed: Units of work finished — for a crawl, pages fetched.
        discovered: Units known to exist. Grows during a crawl as discovery
            finds more, so it is an estimate rather than a fixed total.
        rate_per_sec: Smoothed throughput. Smoothed rather than instantaneous
            because a single slow response would otherwise swing the estimate.
        eta_seconds: Seconds remaining at the current rate, or `None` while it
            cannot be estimated honestly — before any work completes, and
            before enough time has passed for a rate to mean anything.
        recent_items: The last `MAX_RECENT_ITEMS` things processed, newest last.
        updated_at: When this snapshot was taken.
    """

    completed: int = Field(default=0, ge=0)
    discovered: int = Field(default=0, ge=0)
    rate_per_sec: float = Field(default=0.0, ge=0.0)
    eta_seconds: float | None = Field(default=None, ge=0.0)
    recent_items: tuple[str, ...] = ()
    updated_at: datetime | None = None

    @property
    def fraction(self) -> float | None:
        """Completion as 0.0–1.0, or `None` when the total is not yet known.

        Measured against `discovered`, never against a configured ceiling: a
        300-page site crawled with a 20,000-page ceiling is finished at 300, and
        dividing by the ceiling would leave the bar at 1.5% forever.
        """
        if self.discovered <= 0:
            return None
        return min(1.0, self.completed / self.discovered)


class JobRecord(StrictModel):
    """Metadata for one background job. Small enough to list cheaply.

    Attributes:
        id: Opaque identifier. Generated by the store, never by a client — a
            client-supplied id is a path-traversal parameter.
        tool_name: Which tool this job runs, e.g. `seo.page_classifier`.
        label: Human-facing description, shown in a job list.
        request: The tool's input payload, serialised. Opaque here; the API
            layer validates it back into a typed model.
        status: Current lifecycle state.
        created_at: When the job was accepted.
        updated_at: When the status last changed.
        started_at: When a worker picked it up.
        finished_at: When it reached a terminal status.
        error: Failure reason. Set only for `FAILED`.
        has_result: Whether a result blob exists to fetch.
        has_checkpoint: Whether partial work was saved before the job ended.
            Distinct from `has_result`: a checkpoint is what survived an
            interruption, not what the job set out to produce.
        telemetry: Live progress. Meaningful only while `RUNNING`; retained
            afterwards so a finished job still shows what it did.
    """

    id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    label: str = ""
    request: Mapping[str, object] = Field(default_factory=dict)
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    has_result: bool = False
    has_checkpoint: bool = False
    telemetry: JobTelemetry = JobTelemetry()

    @property
    def is_terminal(self) -> bool:
        """Whether the job has reached a state it will never leave."""
        return self.status in TERMINAL_STATUSES


class JobStore(Protocol):
    """The persistence seam.

    A Protocol so the hosted deployment (ADR 0004) can drop in a shared
    implementation — Redis, Postgres — without the API layer changing. The disk
    implementation below is correct for a single local process and explicitly
    not for several (see `DiskJobStore`).
    """

    def create(self, tool_name: str, request: Mapping[str, object], label: str = "") -> JobRecord:
        """Persist a new job in `QUEUED` and return it."""
        ...

    def get(self, job_id: str) -> JobRecord:
        """Read one job's metadata."""
        ...

    def list_jobs(self) -> list[JobRecord]:
        """Every job, newest first. Metadata only."""
        ...

    def mark_running(self, job_id: str) -> JobRecord:
        """Move a job to `RUNNING`."""
        ...

    def update_telemetry(self, job_id: str, telemetry: JobTelemetry) -> JobRecord:
        """Replace a job's progress snapshot."""
        ...

    def mark_failed(self, job_id: str, error: str) -> JobRecord:
        """Move a job to `FAILED` with a reason."""
        ...

    def finish(
        self, job_id: str, result: Mapping[str, object], *, partial: bool = False
    ) -> JobRecord:
        """Store a result and move the job to a terminal success state."""
        ...

    def read_result(self, job_id: str) -> Mapping[str, object]:
        """Read a job's result blob."""
        ...

    def write_checkpoint(self, job_id: str, payload: Mapping[str, object]) -> None:
        """Save partial work so an interruption does not lose it."""
        ...

    def read_checkpoint(self, job_id: str) -> Mapping[str, object] | None:
        """Read saved partial work, or `None` if there is none."""
        ...

    def recover_orphans(self) -> list[str]:
        """Fail every job left non-terminal by a previous process."""
        ...


def _now() -> datetime:
    return datetime.now(UTC)


def _atomic_write(path: Path, payload: str) -> None:
    """Write `payload` to `path` so that a crash cannot leave it half-written.

    The temporary file is created in the destination directory rather than the
    system temp dir: `os.replace` is only atomic within a filesystem, and on
    Windows it fails outright across volumes.
    """
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


class DiskJobStore:
    """A `JobStore` backed by one JSON file per job under a single directory.

    Single-process only. The lock is a `threading.Lock`, which serialises the
    API's event loop against its worker threads but does nothing across
    processes — two servers sharing a directory would interleave writes. That is
    the same in-process limitation the rate limiter and cost ledger carry
    (CLAUDE.md §8), and it is acceptable for the same reason: ADR 0004 targets a
    single local workstation.
    """

    def __init__(self, root: Path | str) -> None:
        """Create the store, making its directory if absent.

        Args:
            root: Directory to hold job files. Created if it does not exist.
        """
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @property
    def root(self) -> Path:
        """Directory holding the job files."""
        return self._root

    def _record_path(self, job_id: str) -> Path:
        return self._root / f"{job_id}.json"

    def _result_path(self, job_id: str) -> Path:
        return self._root / f"{job_id}.result.json"

    def _checkpoint_path(self, job_id: str) -> Path:
        return self._root / f"{job_id}.checkpoint.json"

    def _read(self, job_id: str) -> JobRecord:
        path = self._record_path(job_id)
        if not path.exists():
            msg = f"no job with id {job_id!r}"
            raise JobNotFoundError(msg)
        return JobRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def _write(self, record: JobRecord) -> None:
        _atomic_write(self._record_path(record.id), record.model_dump_json())

    def create(self, tool_name: str, request: Mapping[str, object], label: str = "") -> JobRecord:
        """Persist a new job in `QUEUED`.

        The id is generated here rather than accepted from the caller. Every id
        becomes a filename, so a caller-supplied one is a path-traversal
        parameter — `../../etc/passwd` would be a valid "job id".

        Args:
            tool_name: Which tool the job runs.
            request: The tool's serialised input payload.
            label: Human-facing description for a job list.

        Returns:
            The persisted record.
        """
        moment = _now()
        record = JobRecord(
            id=uuid.uuid4().hex,
            tool_name=tool_name,
            label=label,
            request=dict(request),
            status=JobStatus.QUEUED,
            created_at=moment,
            updated_at=moment,
        )
        with self._lock:
            self._write(record)
        _logger.info("job_created", extra={"job_id": record.id, "tool": tool_name})
        return record

    def get(self, job_id: str) -> JobRecord:
        """Read one job's metadata.

        Raises:
            JobNotFoundError: If no such job exists.
        """
        with self._lock:
            return self._read(job_id)

    def list_jobs(self) -> list[JobRecord]:
        """Every job, newest first.

        Reads metadata only, never result blobs. A record that fails to parse is
        skipped rather than raised: one corrupt file must not make the job list
        permanently unavailable.
        """
        records: list[JobRecord] = []
        with self._lock:
            for path in self._root.glob("*.json"):
                if path.name.endswith(".result.json"):
                    continue
                try:
                    records.append(JobRecord.model_validate_json(path.read_text(encoding="utf-8")))
                except (ValueError, OSError) as exc:
                    _logger.warning(
                        "job_record_unreadable", extra={"path": path.name, "error": str(exc)}
                    )
        return sorted(records, key=lambda record: record.created_at, reverse=True)

    def _transition(self, job_id: str, **changes: object) -> JobRecord:
        """Apply a status change under the lock, so no update is lost."""
        with self._lock:
            record = self._read(job_id)
            updated = record.model_copy(update={**changes, "updated_at": _now()})
            self._write(updated)
        return updated

    def mark_running(self, job_id: str) -> JobRecord:
        """Move a job to `RUNNING` and stamp its start time."""
        return self._transition(job_id, status=JobStatus.RUNNING, started_at=_now())

    def update_telemetry(self, job_id: str, telemetry: JobTelemetry) -> JobRecord:
        """Replace a job's progress snapshot.

        Callers must throttle. Every call rewrites the record through
        `os.replace` and an `fsync`; calling this per unit of work on a
        20,000-page crawl would spend more time in the filesystem than on the
        network.

        Args:
            job_id: The job.
            telemetry: The new snapshot.
        """
        return self._transition(job_id, telemetry=telemetry)

    def mark_failed(self, job_id: str, error: str) -> JobRecord:
        """Move a job to `FAILED` with a reason.

        Args:
            job_id: The job.
            error: Operator-facing reason. Must say something; a failed job with
                a blank reason is indistinguishable from a bug in the store.
        """
        return self._transition(
            job_id, status=JobStatus.FAILED, error=error or "unknown error", finished_at=_now()
        )

    def finish(
        self, job_id: str, result: Mapping[str, object], *, partial: bool = False
    ) -> JobRecord:
        """Store a result blob and move the job to a terminal success state.

        The blob is written **before** the metadata. A reader only learns a
        result exists by seeing `has_result` on the record, so writing in this
        order means a crash between the two writes leaves a job that still looks
        unfinished — recoverable — rather than one that advertises a result
        which is not there.

        Args:
            job_id: The job.
            result: The tool's serialised output.
            partial: True when the result is incomplete, e.g. a crawl that hit
                its page ceiling.

        Returns:
            The updated record.
        """
        with self._lock:
            self._read(job_id)  # Fail before writing a blob for a job that is gone.
            _atomic_write(self._result_path(job_id), json.dumps(dict(result)))

        status = JobStatus.PARTIAL if partial else JobStatus.SUCCEEDED
        record = self._transition(job_id, status=status, has_result=True, finished_at=_now())
        _logger.info("job_finished", extra={"job_id": job_id, "status": status.value})
        return record

    def read_result(self, job_id: str) -> Mapping[str, object]:
        """Read a job's result blob.

        Raises:
            JobNotFoundError: If the job or its result does not exist.
        """
        path = self._result_path(job_id)
        with self._lock:
            self._read(job_id)
            if not path.exists():
                msg = f"job {job_id!r} has no result"
                raise JobNotFoundError(msg)
            loaded: Mapping[str, object] = json.loads(path.read_text(encoding="utf-8"))
        return loaded

    def write_checkpoint(self, job_id: str, payload: Mapping[str, object]) -> None:
        """Save partial work for a job that may not finish.

        Written before the metadata flag, so a crash between the two leaves a
        record that does not advertise a checkpoint it lacks — the same ordering
        `finish` uses, and for the same reason.

        Callers must throttle: this rewrites a file through `os.replace` and an
        `fsync`, and a 20,000-URL payload is not small.
        """
        with self._lock:
            self._read(job_id)  # Fail before writing for a job that is gone.
            _atomic_write(self._checkpoint_path(job_id), json.dumps(dict(payload)))
        self._transition(job_id, has_checkpoint=True)

    def read_checkpoint(self, job_id: str) -> Mapping[str, object] | None:
        """Read a job's saved partial work.

        Returns `None` rather than raising when absent or unreadable: a corrupt
        checkpoint should cost the recovery, not the ability to see the job at
        all. A truncated write is exactly what a power failure produces.
        """
        path = self._checkpoint_path(job_id)
        with self._lock:
            if not path.exists():
                return None
            try:
                loaded: Mapping[str, object] = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError) as exc:
                _logger.warning(
                    "checkpoint_unreadable", extra={"job_id": job_id, "error": str(exc)}
                )
                return None
        return loaded

    def recover_orphans(self) -> list[str]:
        """Fail every job left non-terminal by a previous process.

        Call once at startup. A job that was `RUNNING` when the process died has
        no worker any more, and nothing will ever move it: a UI polling it would
        wait for a result that is never coming. Marking it `FAILED` is honest —
        the work really was lost, because there is no crawl checkpointing
        (CLAUDE.md §8) to resume from.

        Returns:
            The ids that were failed.
        """
        recovered: list[str] = []
        for record in self.list_jobs():
            if record.is_terminal:
                continue
            reason = "interrupted by a server restart"
            if record.has_checkpoint:
                # Cycle 0013 said the work was "genuinely lost", which was true
                # then and is not now: a checkpoint survives the process. The
                # job still failed, but what it found is recoverable.
                reason = f"{reason} — partial results were saved and can be viewed"
            self.mark_failed(record.id, reason)
            recovered.append(record.id)

        if recovered:
            _logger.warning("orphaned_jobs_recovered", extra={"count": len(recovered)})
        return recovered
