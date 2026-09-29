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
from src.core.worker_auth import MAX_REPORTED_TEMPLATES, WorkerTemplate
from src.core.worker_dispatch_schemas import (
    SignedDispatchAssignment,
    WorkerJobEnvelope,
    WorkerJobKind,
    WorkerJobPhase,
)
from src.modules.seo.screaming_frog_control.url_list import UrlListCounts, UrlListSource

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
    "UrlListRequest",
    "UrlListSourceOption",
    "UrlListSourcesView",
    "UrlListView",
]

# `WorkerTemplate` is the wire shape for a worker-reported template as well
# as the stored one. A worker daemon is a machine on someone's desk, not
# part of the trust boundary, so what it says about itself is untrusted
# input: reusing the model means the name pattern and the description rules
# (capped length, no control, zero-width or bidi-override characters) are
# applied at the HTTP boundary *and* again by `Worker` on the way to the
# store, from one definition that cannot drift between the two.


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
        templates: What this worker reported it holds locally, each with
            the note a human wrote beside it. Empty until its daemon sends a
            heartbeat — the API host has no `.seospiderconfig` files of its
            own and never did.
        unrecognised_template_count: How many files in that directory the
            worker had to skip because their names are not slugs. Rendered
            so an operator can tell "this machine holds nothing" from "this
            machine holds files I refused to name".
    """

    worker_id: str
    org_id: str
    display_name: str
    is_active: bool
    created_at: datetime
    last_seen_at: datetime | None = None
    is_online: bool = False
    templates: list[WorkerTemplate] = Field(default_factory=list)
    unrecognised_template_count: int = 0


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

    templates: list[WorkerTemplate] = Field(default_factory=list, max_length=MAX_REPORTED_TEMPLATES)
    unrecognised_count: int = Field(default=0, ge=0, le=MAX_REPORTED_TEMPLATES)


class WorkerHeartbeatResponse(StrictModel):
    """Confirmation of a check-in, and what the cloud now believes."""

    worker_id: str
    last_seen_at: datetime
    templates: list[WorkerTemplate]
    unrecognised_count: int = 0


class WorkerTemplatesView(StrictModel):
    """One worker's locally available Screaming Frog templates.

    Attributes:
        templates: Each template the worker reported, with the description
            a human wrote beside the config. The description is the only
            account of what a `.seospiderconfig` does that can exist: the
            file itself is an opaque Java-serialised blob.
        unrecognised_count: How many `.seospiderconfig` files the worker
            skipped because their names are not slugs. Non-zero is the
            answer to "why is this dropdown empty when the folder is full".
        reported_at: When the worker last told the cloud anything at all.
            `None` means it never has, which is why `templates` may be empty
            for a machine that in fact holds several — absence of a report
            is not a report of absence, and a dropdown should say so.
    """

    worker_id: str
    templates: list[WorkerTemplate]
    unrecognised_count: int = 0
    reported_at: datetime | None = None


class UrlListRequest(StrictModel):
    """Which crawl's URLs, and which subset of them, to run in list mode.

    Optional on a dispatch preview: omitting it is an ordinary `--crawl`
    run, which is what every caller predating ADR 0022 sends.

    Attributes:
        source_job_id: The finished Rankuno crawl to take URLs from. The
            caller's org must own it; ownership is re-checked server-side
            against the authenticated principal, never inferred from this
            id.
        source: Which subset. No default — "which URLs" is the decision
            being approved, and a default would make the large one
            reachable without a choice.
    """

    source_job_id: str = Field(min_length=1, max_length=64)
    source: UrlListSource


class UrlListView(StrictModel):
    """A generated, stored list as a confirmation modal should render it.

    Everything here except `sha256` exists so a human can tell *which*
    list this is. `sha256` is the only field any gate compares, and it is
    the field a caller must echo back on confirm.

    Attributes:
        source: Which subset was generated.
        source_job_id: The crawl it came from.
        source_label: That crawl's human-facing name.
        registrable_domain: The domain every kept URL sits inside — the
            rule that produced `counts.off_domain_dropped`.
        url_count: How many URLs the list holds.
        sha256: The fingerprint to echo back on confirm.
        sample: The first few URLs, verbatim.
        counts: The full per-stage filtering account, so a modal can say
            "Excluded 18 external URLs" and have it be true.
    """

    source: UrlListSource
    source_job_id: str
    source_label: str = ""
    registrable_domain: str = ""
    url_count: int = Field(ge=1)
    sha256: str
    sample: list[str] = Field(default_factory=list)
    counts: UrlListCounts


class UrlListSourceOption(StrictModel):
    """One offered (or refused) list source, with the reason either way.

    Attributes:
        source: The enum value to send back on preview.
        label: Exactly what the operator should see, including the
            "(Recommended)" marker — served rather than hard-coded in a UI
            so the recommendation has one owner.
        description: What this source is, in one sentence.
        available: Whether a preview using it would succeed.
        unavailable_reason: Why not, when `available` is false. Empty
            otherwise. Never empty when unavailable: "the option is greyed
            out and nobody knows why" is the failure this field exists to
            prevent.
        candidate_url_count: URLs available *before* filtering, or `None`
            when nothing could be counted. Not the number that will be
            dispatched — the preview reports that, after deduping and the
            off-domain filter have run.
        exceeds_ceiling: Whether counting stopped because the source is
            over `max_urls`, in which case `candidate_url_count` is a
            lower bound rather than a total.
    """

    source: UrlListSource
    label: str
    description: str = ""
    available: bool = False
    unavailable_reason: str = ""
    candidate_url_count: int | None = Field(default=None, ge=0)
    exceeds_ceiling: bool = False


class UrlListSourcesView(StrictModel):
    """Which list sources one finished crawl can offer, and the ceiling."""

    job_id: str
    label: str = ""
    base_url: str = ""
    max_urls: int = Field(ge=1)
    sources: list[UrlListSourceOption] = Field(default_factory=list)


class DispatchPreviewRequest(StrictModel):
    """What `POST /workers/{worker_id}/dispatch/preview` accepts."""

    seed_url: str = Field(min_length=1, max_length=2048)
    template_name: str | None = Field(default=None, min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    url_list: UrlListRequest | None = None
    """Present for a `--crawl-list` dispatch. The list is generated and
    stored by this preview call, before anyone has approved anything, so
    that the bytes the returned fingerprint names already exist."""


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
    url_list: UrlListView | None = None
    """The generated list, when one was asked for. `None` for an ordinary
    `--crawl` preview."""


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
    url_list_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    """The fingerprint from the preview response, echoed back verbatim.

    Checked inside the same atomic statement that consumes the token, not
    afterwards in Python: a confirm naming a different list must fail
    without burning the approval (ADR 0022). Echoing it rather than having
    the server look it up from the token is deliberate — it is what makes
    the mismatch detectable at all."""


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
        url_list_url_count: How many URLs a list-mode job was given, or
            `None` for an ordinary `--crawl` job.
        url_list_shortfall: URLs supplied but never crawled, once both
            numbers are known. `None` means "cannot say" — either this was
            not a list job, or no page count has arrived — and must not be
            rendered as zero. A positive value is the first truncation
            signal this system has ever been able to produce (ADR 0022):
            before a known list length, "the crawl stopped early" and "the
            site is that size" were indistinguishable.
        url_list_shortfall_note: The operator-facing explanation of a
            non-zero shortfall, naming the free-tier cap when the numbers
            fit it. Empty when there is no shortfall to explain.
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
    url_list_url_count: int | None = None
    url_list_shortfall: int | None = None
    url_list_shortfall_note: str = ""


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
