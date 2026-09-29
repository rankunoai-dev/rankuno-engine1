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

`url_list_sha256` (ADR 0023) is the one field added since, and it is a
**digest, never bytes**. A list-mode dispatch can carry up to 10,000 URLs;
putting them here would turn a poll response into a multi-megabyte body, put
operator-supplied strings inside a signed artifact that gets logged, and
leave `extra="forbid"`'s minimality with nothing left to protect. The worker
fetches the bytes over its own authenticated, org-scoped channel and
re-computes this digest before it launches anything, so the hash travels and
the data does not.
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
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
"""Lowercase hex SHA-256, exactly as `hashlib.sha256().hexdigest()` produces
it. Pinned as a pattern rather than a bare `str` so a truncated, upper-cased
or prefixed digest is refused at the boundary instead of quietly never
matching anything downstream."""


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
    """The worker uploaded a bundle, but it cannot produce a deliverable.

    Reached today by exactly one rule: export files arrived without
    `internal_all.csv`, the spine `load_screaming_frog_bundle` requires
    non-optionally (`worker_routes.upload_bundle`, cycle 0113). The data is
    kept and downloadable; what it is not is a finished job. Also the status
    reserved for a degraded run in the licence sense (`ScreamingFrogJobOutput`
    parity), which `tool.execute()` still raises on rather than returning."""

    FAILED = "failed"
    """The worker could not complete the run. `WorkerJob.error` says why."""


class WorkerJobEnvelope(StrictModel):
    """The exact, minimal payload a worker needs to run one job.

    ADR 0015 condition 8. Deliberately carries nothing else: no crawl
    options, no path override, no raw command. The worker re-validates
    every field itself (`UrlSafetyPolicy.validate()` on `seed_url`,
    `TemplateRegistry.resolve()` on `template_name`, and a fresh SHA-256 over
    the URL-list bytes it fetched) rather than trusting the cloud's own
    admission check — across an untrusted network hop that second check is
    the load-bearing one, not defense in depth.

    Attributes:
        job_id: The job this envelope describes.
        seed_url: The crawl root. Still present and still validated in list
            mode: it names the site in every log line and approval summary,
            and its registrable domain is what the list was filtered against.
            It is simply not what `--crawl-list` is given.
        template_name: A `.seospiderconfig` the worker holds, by name.
        correlation_id: Transport metadata.
        url_list_sha256: Digest of the approved URL-list file, or `None` for
            an ordinary link-following `--crawl` run. Its presence is what
            puts the worker into list mode; the bytes are fetched separately
            (see the module docstring).
    """

    job_id: str = Field(min_length=1, max_length=64)
    seed_url: str = Field(min_length=1, max_length=2048)
    template_name: str | None = Field(default=None, min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    url_list_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)


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
        url_list_url_count: How many URLs the approved list held, or `None`
            for an ordinary `--crawl` job. Kept on the job rather than derived
            from the stored list so the finished-job truncation check costs no
            second read, and so it outlives the list blob's own retention
            expiry.
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
    url_list_url_count: int | None = Field(default=None, ge=0)


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
    url_list_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    """Bound into gate (a) alongside the triple above (ADR 0023).

    Without it an operator could be shown a preview of a three-URL list and
    confirm a hundred-thousand-URL one: the confirm request would carry a
    different digest, every field the token actually checked would still
    match, and the approval would mean nothing.
    """


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
    url_list_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    """Inside the claims, so the existing HMAC covers it with no change to the
    signing code at all (ADR 0023).

    A network attacker who swapped this digest for one naming a different
    stored list would invalidate the same signature that protects `seed_url` —
    which is exactly why condition 4 signs one object and not two.
    """
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
