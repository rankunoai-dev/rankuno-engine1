"""Contracts for cloud -> desktop-worker job dispatch (ADR 0015).

Every value crossing the cloud <-> worker boundary is one of these
`StrictModel`s (CLAUDE.md §1.2) — never a loose dict, and never anything
carrying more than the ADR's own condition 8 lets it carry.

`WorkerJobKind` is a closed `StrEnum`, matching `FieldMappingStatus` and
`CircuitBreakerState`'s own convention (ADR 0015 condition 7): the worker
daemon's dispatch loop matches on this with a literal `match`/`if`, never a
string-keyed dict of callables, `eval`, or `pickle`. One member today.

`WorkerJobEnvelope` is deliberately minimal (ADR 0015 condition 8):
`{job_id, seed_url, template_name, correlation_id}`, matching
`ScreamingFrogJobInput`'s shape exactly plus the transport metadata a
network hop needs. No `extra_args`, `raw_command`, or path-override field —
`StrictModel`'s `extra="forbid"` enforces that mechanically, not just by
convention.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from src.core.schemas import StrictModel

__all__ = [
    "DispatchAssignmentClaims",
    "DispatchPreviewToken",
    "SignedDispatchAssignment",
    "WorkerJob",
    "WorkerJobEnvelope",
    "WorkerJobKind",
    "WorkerJobPhase",
    "WorkerJobStatus",
]

_IDENTIFIER_PATTERN = r"^[a-z0-9_-]{1,64}$"


class WorkerJobKind(StrEnum):
    """The closed set of job kinds a worker daemon knows how to run.

    ADR 0015 condition 7: one member today. Adding a second kind is a
    schema change reviewed like any other — never a string a caller can
    invent to reach code this daemon does not intend to expose.
    """

    SCREAMING_FROG_CRAWL = "screaming_frog_crawl"


class WorkerJobPhase(StrEnum):
    """Coarse, closed vocabulary for where a running job currently is.

    Populated only by a job whose `kind` supports live progress reporting —
    today that is `screaming_frog_control.progress_parser`, which detects
    these same two states from Screaming Frog's own trace.txt (a
    `SpiderProgress` line means `CRAWLING`; the `Completed the spider of...`
    line means the CLI has moved on to writing its CSV export, `EXPORTING`).

    Defined once, here in `core`, and imported directly by
    `screaming_frog_control` rather than duplicated as a second, module-
    local enum with the same two members: `modules -> core` is the allowed
    direction (CLAUDE.md §1.1), so there is nothing to round-trip through a
    string at a module boundary — the module's own progress snapshot model
    (`ScreamingFrogProgressSnapshot.phase`) carries this exact type.
    """

    CRAWLING = "crawling"
    """The spider is actively fetching pages; `pages_crawled`/`progress_pct`
    are Screaming Frog's own live estimate for the still-open crawl."""

    EXPORTING = "exporting"
    """The spider has finished discovering pages and is now writing the CSV
    bundle this job will upload — `pages_crawled`/`progress_pct` stop
    advancing once this phase is reported."""


class WorkerJobStatus(StrEnum):
    """Lifecycle of one cloud-tracked worker dispatch job.

    Lowercase, matching the other governance/domain enums this codebase
    already ships lowercase (`JobStatus`, `RiskClass` — CLAUDE.md §7 ruling
    3): this is a governance-adjacent status, not a Phase 1 taxonomy enum.
    """

    QUEUED = "queued"
    """Approved (ADR 0015 condition 3(a)) and persisted; not yet claimed."""

    DISPATCHED = "dispatched"
    """A specific worker claimed it via poll and is running it."""

    SUCCEEDED = "succeeded"
    """The worker uploaded a bundle and reported a clean finish."""

    PARTIAL = "partial"
    """The worker uploaded a bundle, but the run degraded (e.g. a licence
    read reporting free-tier capping) — present for parity with
    `ScreamingFrogJobOutput`'s own licence-degrade handling, though today's
    tool.execute() raises rather than returning a degraded output, so this
    status is reachable only if a future worker behaviour changes that."""

    FAILED = "failed"
    """The worker could not complete the run. `WorkerJob.error` says why."""


class WorkerJobEnvelope(StrictModel):
    """The exact, minimal payload a worker needs to run one job.

    ADR 0015 condition 8. Deliberately carries nothing else: no crawl
    options, no path override, no raw command. The worker re-validates
    every field itself (`UrlSafetyPolicy.validate()` on `seed_url`,
    `TemplateRegistry.resolve()` on `template_name`) rather than trusting
    the cloud's own admission check — across an untrusted network hop that
    second check is the load-bearing one, not defense in depth.
    """

    job_id: str = Field(min_length=1, max_length=64)
    seed_url: str = Field(min_length=1, max_length=2048)
    template_name: str | None = Field(default=None, min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)


class WorkerJob(StrictModel):
    """One cloud-tracked dispatch job, pinned to the worker that must run it.

    Attributes:
        id: Same value as `envelope.job_id`. Also the idempotency key (ADR
            0015 Step 5 answer 4): a job can only ever be claimed once, by
            the atomic `QUEUED -> DISPATCHED` transition
            `PostgresWorkerDispatchStore.claim_next_job` performs.
        org_id: Owning organization. Every dispatch route filters by this
            from the authenticated principal, never a caller-supplied value.
        worker_id: The one worker this job may ever be claimed by (ADR 0015
            condition 6) — dispatch to any other worker is a routing bug,
            not a load-balancing choice, so this field is required, not a
            preference.
        kind: Closed-enum discriminator (condition 7).
        envelope: The minimal payload (condition 8).
        status: Current lifecycle state.
        error: Why the job did not finish cleanly. `None` unless `FAILED`.
        bundle_size_bytes: Size of the uploaded, validated bundle, once one
            exists. `None` until `SUCCEEDED`/`PARTIAL`.
        pages_crawled: The worker's most recently reported page count for
            this run. `None` until the first progress report arrives, or
            forever for a job whose worker never wired progress reporting
            (an older worker build, or a job `kind` that has none) — every
            reader of this field must treat absence as "no data yet", not
            as zero.
        progress_pct: The worker's most recently reported completion
            percentage, taken verbatim from Screaming Frog's own estimate.
            Not guaranteed monotonically increasing: Screaming Frog recomputes
            it against a denominator that grows as the crawl discovers new
            URLs, so a real run can report a lower percentage than its own
            previous report. A UI must not treat a drop as an error.
        current_phase: The worker's most recently reported coarse phase.
            `None` until the first report arrives.
    """

    id: str = Field(min_length=1, max_length=64)
    org_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    worker_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    kind: WorkerJobKind
    envelope: WorkerJobEnvelope
    status: WorkerJobStatus = WorkerJobStatus.QUEUED
    created_at: datetime
    updated_at: datetime
    dispatched_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    bundle_size_bytes: int | None = Field(default=None, ge=0)
    pages_crawled: int | None = Field(default=None, ge=0)
    progress_pct: float | None = Field(default=None, ge=0.0)
    current_phase: WorkerJobPhase | None = None


class DispatchPreviewToken(StrictModel):
    """A minted, not-yet-consumed cloud-side dispatch preview token.

    ADR 0015 condition 3(a): structurally identical to
    `screaming_frog_control.preview_tokens.PreviewToken`, additionally bound
    to `worker_id` — gate (a) governs whether a job is ever queued at all,
    for a specific worker, before a `WorkerJob` row exists. Persisted in
    Postgres (ADR 0015 condition 5), never in-process, so a confirm landing
    on a different cloud replica than the preview it answers still sees it.
    """

    token: str
    org_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    worker_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    seed_url: str = Field(min_length=1, max_length=2048)
    template_name: str | None = Field(default=None, min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    expires_at: datetime


class DispatchAssignmentClaims(StrictModel):
    """What a `SignedDispatchAssignment` token's signature actually covers.

    ADR 0015 condition 4: signing a job envelope AND an approval artifact in
    one signed object means a tampered field of *either* invalidates the
    same HMAC check — there is no separate "envelope signature" a network
    attacker could leave alone while forging only the approval half.

    `jti` is this claim set's own single-use identifier (the "j" is
    borrowed from JWT convention, not a job id — `job_id` already names
    that). The worker's own idempotency ledger keys on `job_id`, which is
    sufficient for single-use in this design (see
    `worker_dispatch_signing` module docstring for why `jti` itself does
    not need separate server-side tracking).
    """

    job_id: str = Field(min_length=1, max_length=64)
    worker_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    org_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    kind: WorkerJobKind
    seed_url: str = Field(min_length=1, max_length=2048)
    template_name: str | None = Field(default=None, min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    jti: str = Field(min_length=1)
    issued_at: datetime
    expires_at: datetime


class SignedDispatchAssignment(StrictModel):
    """The wire form of one claim set: a token and its expiry.

    Mirrors `src.core.auth.SessionToken`'s shape for the same reason: a
    poll response hands this back verbatim, and the worker verifies it
    completely locally (ADR 0015 condition 3(b)) — never a bare boolean.
    """

    token: str
    expires_at: datetime
