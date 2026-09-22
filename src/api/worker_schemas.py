"""HTTP request/response `StrictModel`s for ADR 0015's worker-dispatch routes.

Split out of `worker_routes.py` to keep that module under this codebase's
400-line target — the same reasoning `deliverables_routes.py` and
`server.py` already state for their own size. These are wire shapes only;
the domain records they map to or from (`Worker`, `WorkerJob`, ...) live in
`src.core.worker_auth`/`src.core.worker_dispatch_schemas`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field

from src.core.schemas import StrictModel
from src.core.worker_auth import MAX_REPORTED_TEMPLATES, TEMPLATE_NAME_PATTERN
from src.core.worker_dispatch_schemas import (
    SignedDispatchAssignment,
    WorkerJobEnvelope,
    WorkerJobKind,
    WorkerJobPhase,
)

__all__ = [
    "DispatchConfirmRequest",
    "DispatchPreviewRequest",
    "DispatchPreviewResponse",
    "PollResponse",
    "WorkerFailureReport",
    "WorkerHeartbeatRequest",
    "WorkerHeartbeatResponse",
    "WorkerJobAccepted",
    "WorkerJobListView",
    "WorkerJobView",
    "WorkerListView",
    "WorkerProgressReport",
    "WorkerRegisterRequest",
    "WorkerRegisterResponse",
    "WorkerSummary",
    "WorkerTemplatesView",
]

TemplateName = Annotated[str, Field(pattern=TEMPLATE_NAME_PATTERN)]
"""A worker-reported template name, constrained at the HTTP boundary.

The first of two independent checks. A worker daemon is a machine on
someone's desk, not part of the trust boundary, so what it says about itself
is untrusted input: the name is validated here before it is stored and
validated again by `Worker.template_names` before it is persisted. Either
alone would be enough today; together they mean a future caller that builds
a `Worker` without going through this request model still cannot store a
name that could become a path component."""


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
    """One registered worker, without its secret hash.

    Attributes:
        last_seen_at: The raw fact — when this worker last polled or sent a
            heartbeat. `None` means never.
        is_online: The server's verdict on that fact, using
            `Settings.worker_offline_after_s`. Served rather than left to
            the browser so there is exactly one staleness rule in the
            system; a dashboard that invented its own would be the copy
            nothing tests.
        template_names: What this worker reported it holds locally. Empty
            until its daemon sends a heartbeat — the API host has no
            `.seospiderconfig` files of its own and never did.
    """

    worker_id: str
    org_id: str
    display_name: str
    is_active: bool
    created_at: datetime
    last_seen_at: datetime | None = None
    is_online: bool = False
    template_names: list[str] = Field(default_factory=list)


class WorkerListView(StrictModel):
    """Every worker registered for the caller's org.

    Attributes:
        offline_after_s: The threshold behind `WorkerSummary.is_online`,
            published so a dashboard can explain the verdict ("last seen
            4 minutes ago, offline after 60s") instead of re-deriving it.
    """

    workers: list[WorkerSummary]
    offline_after_s: float


class WorkerHeartbeatRequest(StrictModel):
    """What `POST /workers/heartbeat` accepts.

    Carries no `worker_id`: the authenticated credential is the only source
    of that value (ADR 0015 condition 2's IDOR rule). A worker can only ever
    describe itself.
    """

    template_names: list[TemplateName] = Field(
        default_factory=list, max_length=MAX_REPORTED_TEMPLATES
    )


class WorkerHeartbeatResponse(StrictModel):
    """Confirmation of a check-in, and what the cloud now believes."""

    worker_id: str
    last_seen_at: datetime
    template_names: list[str]


class WorkerTemplatesView(StrictModel):
    """One worker's locally available Screaming Frog templates.

    Attributes:
        reported_at: When the worker last told the cloud anything at all.
            `None` means it never has, which is why `templates` may be empty
            for a machine that in fact holds several — absence of a report
            is not a report of absence, and a dropdown should say so.
    """

    worker_id: str
    templates: list[str]
    reported_at: datetime | None = None


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
    worker_online: bool = False
    worker_last_seen_at: datetime | None = None
    """Carried on the preview, not just the confirm, so the confirmation
    modal can warn *before* the operator commits rather than after: confirm
    refuses an offline worker outright, and a 409 at that point is a worse
    way to learn the PC is asleep than a line in the dialog."""


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
    """One dispatch job's cloud-tracked state.

    Attributes:
        pages_crawled: The worker's most recently reported live page count.
            `None` until a progress report has arrived — which may be never,
            for a job whose worker predates this feature, or one still
            waiting on its first `SCREAMING_FROG_PROGRESS_POLL_INTERVAL_S`
            tick. A dashboard must render this field's absence as "no data
            yet", not as zero pages.
        progress_pct: The worker's most recently reported completion
            estimate, taken verbatim from Screaming Frog's own number. Can
            decrease between two reports (`WorkerJob.progress_pct`'s own
            docstring) — not a bug to guard against client-side.
        current_phase: The worker's most recently reported coarse phase.
    """

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
    pages_crawled: int | None = None
    progress_pct: float | None = None
    current_phase: WorkerJobPhase | None = None


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


class WorkerProgressReport(StrictModel):
    """What `POST /workers/jobs/{job_id}/progress` accepts.

    Every field optional and independently meaningful: a worker may report
    partial knowledge (e.g. a phase transition alone, before the crawl's
    first `SpiderProgress` line) and `extra="forbid"` still guards against a
    stray or renamed field silently going nowhere (CLAUDE.md §1.2). This
    endpoint never changes a job's lifecycle `status` — see
    `WorkerDispatchStore.update_job_progress`'s own docstring.
    """

    pages_crawled: int | None = Field(default=None, ge=0)
    progress_pct: float | None = Field(default=None, ge=0.0)
    phase: WorkerJobPhase | None = None
