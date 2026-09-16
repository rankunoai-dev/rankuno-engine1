"""HTTP request/response `StrictModel`s for ADR 0015's worker-dispatch routes.

Split out of `worker_routes.py` to keep that module under this codebase's
400-line target — the same reasoning `deliverables_routes.py` and
`server.py` already state for their own size. These are wire shapes only;
the domain records they map to or from (`Worker`, `WorkerJob`, ...) live in
`src.core.worker_auth`/`src.core.worker_dispatch_schemas`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from src.core.schemas import StrictModel
from src.core.worker_dispatch_schemas import (
    SignedDispatchAssignment,
    WorkerJobEnvelope,
    WorkerJobKind,
)

__all__ = [
    "DispatchConfirmRequest",
    "DispatchPreviewRequest",
    "DispatchPreviewResponse",
    "PollResponse",
    "WorkerFailureReport",
    "WorkerJobAccepted",
    "WorkerJobListView",
    "WorkerJobView",
    "WorkerListView",
    "WorkerRegisterRequest",
    "WorkerRegisterResponse",
    "WorkerSummary",
]


class WorkerRegisterRequest(StrictModel):
    """What `POST /workers` accepts."""

    display_name: str = Field(min_length=1, max_length=200)


class WorkerRegisterResponse(StrictModel):
    """A newly registered worker's identity and its one-time credential.

    `worker_secret` is never retrievable again after this response (ADR
    0015 condition 2) — the server stores only its PBKDF2 hash.
    """

    worker_id: str
    worker_secret: str
    org_id: str


class WorkerSummary(StrictModel):
    """One registered worker, without its secret hash."""

    worker_id: str
    org_id: str
    display_name: str
    is_active: bool
    created_at: datetime


class WorkerListView(StrictModel):
    """Every worker registered for the caller's org."""

    workers: list[WorkerSummary]


class DispatchPreviewRequest(StrictModel):
    """What `POST /workers/{worker_id}/dispatch/preview` accepts."""

    seed_url: str = Field(min_length=1, max_length=2048)
    template_name: str | None = Field(default=None, min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)


class DispatchPreviewResponse(StrictModel):
    """A confirmation-ready preview, and the token that stands for it.

    Nothing has been queued yet — mirrors
    `server.ScreamingFrogJobPreviewResponse` exactly, extended with
    `worker_id` (condition 3(a)'s worker-binding).
    """

    token: str
    expires_at: datetime
    worker_id: str
    seed_url: str
    template_name: str | None = None
    correlation_id: str


class DispatchConfirmRequest(StrictModel):
    """What `POST /workers/{worker_id}/dispatch` accepts.

    Carries no `confirmed: true` field, mirroring
    `server.ScreamingFrogJobConfirmRequest`: `token` is the only evidence
    of approval this endpoint accepts.
    """

    token: str = Field(min_length=1)
    seed_url: str = Field(min_length=1, max_length=2048)
    template_name: str | None = Field(default=None, min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)


class WorkerJobAccepted(StrictModel):
    """What a job-queuing endpoint returns: an id to poll, not a result."""

    id: str
    status: str


class WorkerJobView(StrictModel):
    """One dispatch job's cloud-tracked state."""

    id: str
    org_id: str
    worker_id: str
    kind: WorkerJobKind
    envelope: WorkerJobEnvelope
    status: str
    created_at: datetime
    updated_at: datetime
    dispatched_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    bundle_size_bytes: int | None = None


class WorkerJobListView(StrictModel):
    """Every dispatch job for the caller's org."""

    jobs: list[WorkerJobView]


class PollResponse(StrictModel):
    """What `GET /workers/dispatch/poll` returns.

    `assignment` is `None` on every poll that finds no queued work — the
    normal, majority-of-the-time answer, not an error.
    """

    assignment: SignedDispatchAssignment | None = None


class WorkerFailureReport(StrictModel):
    """What `POST /workers/jobs/{job_id}/failed` accepts."""

    error: str = Field(min_length=1, max_length=2000)
