"""FastAPI application serving crawl jobs to the React UI.

Why jobs and not a synchronous endpoint
---------------------------------------
A 20k-page crawl takes minutes. It cannot run inside a request: the browser, and
every proxy between it and here, will time out long before it finishes. So
`POST /jobs` accepts the work, returns `202` with an id, and the client polls.

Why a worker thread and not `BackgroundTasks`
---------------------------------------------
`PageClassificationTool.execute()` is synchronous and calls `asyncio.run()`
internally. Running it in FastAPI's `BackgroundTasks` would execute it *on the
event loop*, blocking every other request for the whole crawl — including the
`GET /jobs/{id}` polls the UI needs to show progress. It is dispatched to a
worker thread with `asyncio.to_thread` instead, which is also what lets the
concurrency cap mean anything.

What this layer does not do
---------------------------
No safety control is implemented here. SSRF validation, robots compliance,
per-host throttling, guardrails and audit logging all live in the tool and its
fetcher. The one apparent exception is the URL check on `POST /jobs`, which is
not a second guard but an early one: the same `UrlSafetyPolicy` the crawl will
use anyway, run at admission so a bad URL is a `400` the operator sees
immediately rather than a job that fails a moment later.

Binding
-------
`serve()` binds `127.0.0.1` deliberately. This server has no authentication, and
it will fetch arbitrary URLs on request — on a routable interface that is an
open proxy. Local-only is the security boundary (ADR 0004).
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import Field, ValidationError

from src.core.errors import UnsafeUrlError
from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.core.state_store import (
    MAX_RECENT_ITEMS,
    DiskJobStore,
    JobNotFoundError,
    JobRecord,
    JobStatus,
    JobStore,
    JobTelemetry,
)
from src.core.url_safety import UrlSafetyPolicy
from src.modules.seo.page_classifier.discovery import DiscoveryReport, SiteGraph
from src.modules.seo.page_classifier.schemas import (
    ConsensusMethod,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)
from src.modules.seo.page_classifier.screaming_frog_merge import (
    merge_reconciled_urls,
)
from src.modules.seo.page_classifier.tool import (
    CrawlSummary,
    PageClassificationInput,
    PageClassificationOutput,
    PageClassificationTool,
    reparse_placement,
)
from src.modules.seo.page_classifier.weights import SiteProfile, WeightProfileReport

__all__ = ["ApiState", "CrawlCheckpointer", "TelemetryRecorder", "create_app", "serve"]

_logger = get_logger("api.server")

API_PREFIX = "/api/v1"

API_VERSION = "0.1.0"
"""Version of the HTTP contract, not of the engine.

Separate on purpose: the engine's classification can improve without the request
and response shapes changing, and a client pins to the shapes.
"""

DEFAULT_MAX_CONCURRENT_JOBS = 3
"""Simultaneous crawls this process will run.

Not about local CPU — the fetcher's token bucket already bounds politeness per
host. It bounds *memory*: each in-flight crawl holds its whole graph, including
page HTML, until it finishes. Three 20k-page crawls at once is already several
gigabytes.
"""

DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)
"""The Vite dev server, and nothing else.

Not `*`. A wildcard would let any page the operator happens to be visiting read
crawl results out of this server.
"""

TOOL_NAME = "seo.page_classifier"

TELEMETRY_FLUSH_SECONDS = 0.5
"""Minimum gap between telemetry writes.

Not a preference — a correctness bound. Each write rewrites the job record
through `os.replace` and an `fsync`. Flushing per page on a 20,000-page crawl
would spend more wall-clock in the filesystem than on the network, so the
telemetry would slow the thing it is measuring.
"""

TELEMETRY_WARMUP_SECONDS = 3.0
"""Elapsed time before an ETA is offered at all.

A rate computed over the first fraction of a second is noise, and an ETA derived
from it swings between seconds and hours. Showing nothing is better than showing
a number that is about to change by two orders of magnitude.
"""

RATE_SMOOTHING = 0.3
"""EMA weight for the newest rate sample, 0–1.

Lower is smoother. At 0.3 a single stalled request moves the estimate a little;
an instantaneous rate would make it jump on every retry.
"""


CHECKPOINT_INTERVAL_S = 10.0
"""Minimum gap between checkpoint writes."""

CHECKPOINT_EVERY_PAGES = 100
"""Pages between checkpoints, whichever boundary arrives first.

Two triggers because either alone fails at one end of the range. Time alone
under-saves a fast crawl — Turbo at 25 pages/sec puts 250 pages between writes.
Page count alone under-saves a slow one, where 100 pages can be several minutes
of work exposed to a power cut.
"""


class CrawlCheckpointer:
    """Saves the discovered URL set so an interruption does not lose the crawl.

    Deliberately **not** the classified output. Re-serialising every profile on
    each write means megabytes through `fsync` hundreds of times per crawl —
    measurably more expensive than the crawling. URLs are what cannot be
    recovered without going back to the network; classification is CPU-only and
    can be redone.

    Called from crawler threads, so mutations are under the lock.
    """

    def __init__(self, store: JobStore, job_id: str, base_url: str) -> None:
        """Build a checkpointer for one job."""
        self._store = store
        self._job_id = job_id
        self._base_url = base_url
        self._lock = threading.Lock()
        self._last_write = 0.0
        self._last_count = 0

    def __call__(self, graph: SiteGraph) -> None:
        """Save the graph if enough time or enough pages have passed."""
        now = time.monotonic()
        with self._lock:
            count = len(graph)
            due = (
                now - self._last_write >= CHECKPOINT_INTERVAL_S
                or count - self._last_count >= CHECKPOINT_EVERY_PAGES
            )
            if not due or count == 0:
                return
            self._last_write = now
            self._last_count = count
            # Materialised inside the throttle, never outside it: at 20,000
            # nodes building these tuples is the expensive part of a checkpoint.
            urls = graph.all_urls()
            unfetched = graph.unfetched_urls()

        try:
            self._store.write_checkpoint(
                self._job_id,
                {
                    "base_url": self._base_url,
                    "urls": list(urls),
                    # What a resumed crawl would still have to fetch. Recorded
                    # here because it cannot be recovered afterwards: the result
                    # holds a row for every *discovered* URL, fetched or not, so
                    # nothing downstream can tell the two apart.
                    "unfetched": list(unfetched),
                    "saved_at_count": count,
                },
            )
        except JobNotFoundError:
            _logger.debug("checkpoint_job_missing", extra={"job_id": self._job_id})


class TelemetryRecorder:
    """Turns raw progress callbacks into a throttled, smoothed snapshot.

    Lives in the API layer, not in the crawler: throughput smoothing and write
    throttling are presentation concerns for a polling client, and the engine
    should not know that anyone is watching.

    Called from crawler threads, so every mutation is under the lock.
    """

    def __init__(self, store: JobStore, job_id: str, ceiling: int) -> None:
        """Build a recorder for one job.

        Args:
            store: Where snapshots are persisted.
            job_id: The job being reported on.
            ceiling: `max_pages`, used only to cap the denominator — never as
                the denominator itself.
        """
        self._store = store
        self._job_id = job_id
        self._ceiling = ceiling
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._last_flush = 0.0
        self._last_completed = 0
        self._last_sample = self._started
        self._rate = 0.0

    def __call__(self, completed: int, discovered: int, recent: tuple[str, ...]) -> None:
        """Record progress. Cheap, non-blocking, and never raises."""
        now = time.monotonic()
        with self._lock:
            self._update_rate(completed, now)
            if now - self._last_flush < TELEMETRY_FLUSH_SECONDS and completed > 0:
                return
            self._last_flush = now
            snapshot = self._snapshot(completed, discovered, recent, now)

        try:
            self._store.update_telemetry(self._job_id, snapshot)
        except JobNotFoundError:
            # The job was deleted mid-crawl. Losing telemetry is not a reason to
            # interrupt work that is still producing a result.
            _logger.debug("telemetry_job_missing", extra={"job_id": self._job_id})

    def _update_rate(self, completed: int, now: float) -> None:
        elapsed = now - self._last_sample
        if elapsed < 0.05:
            return
        sample = max(0, completed - self._last_completed) / elapsed
        # Seeded rather than blended on the first sample: blending against a
        # zero start would halve the very first estimate.
        self._rate = (
            sample
            if self._rate == 0.0
            else (RATE_SMOOTHING * sample + (1 - RATE_SMOOTHING) * self._rate)
        )
        self._last_completed = completed
        self._last_sample = now

    def _snapshot(
        self, completed: int, discovered: int, recent: tuple[str, ...], now: float
    ) -> JobTelemetry:
        # Capped at the ceiling because the crawl stops there; measured against
        # what was discovered because that is the real total. Using the ceiling
        # as the denominator leaves a 300-page site reading 1.5% forever.
        total = min(discovered, self._ceiling) if discovered else 0
        remaining = max(0, total - completed)

        eta: float | None = None
        if now - self._started >= TELEMETRY_WARMUP_SECONDS and self._rate > 0 and total > 0:
            eta = remaining / self._rate

        return JobTelemetry(
            completed=completed,
            discovered=total,
            rate_per_sec=round(self._rate, 3),
            eta_seconds=None if eta is None else round(eta, 1),
            recent_items=recent[-MAX_RECENT_ITEMS:],
            updated_at=datetime.now(UTC),
        )


class HealthView(StrictModel):
    """Liveness response."""

    status: str = "ok"
    active_jobs: int = 0
    max_concurrent_jobs: int = DEFAULT_MAX_CONCURRENT_JOBS


class ReconciliationSummary(StrictModel):
    """What a Screaming Frog reconciliation found, and what it did about it.

    Returned instead of a bare `JobRecord` because the counts are the point: an
    operator uploads an export to learn the size of the gap, and half of them
    will not want the merged job at all. The new job's id is included so the UI
    can open it when they do.
    """

    job_id: str
    """The merged result, saved as a new job. Equal to `source_job_id` when
    nothing was merged — there is no new job in that case."""

    source_job_id: str
    base_url: str

    frog_rows: int = 0
    """Rows read from the export."""

    in_both: int = 0
    """URLs both crawlers found."""

    missed_pages: int = 0
    """Live, indexable, in-scope pages the engine never reached. Merged."""

    orphans: int = 0
    """Published pages no internal link reaches. Found only by the engine, and
    left where they are — their absence from the export *is* the finding."""

    merged: int = 0
    """Pages added to the tree. Zero is a normal outcome."""

    frog_reasons: Mapping[str, int] = Field(default_factory=dict)
    """Why each frog-only URL was not merged, by reason."""

    engine_reasons: Mapping[str, int] = Field(default_factory=dict)
    """Why each engine-only URL is absent from the export, by reason."""


class JobAccepted(StrictModel):
    """What `POST /jobs` returns: an id to poll, not a result."""

    id: str
    status: str
    label: str = ""


class ApiState:
    """Everything the endpoints need, built once per application.

    Held on `app.state` rather than in module globals so a test can construct an
    isolated app — its own job directory, its own resolver — without touching
    the process the next test runs in.
    """

    def __init__(
        self,
        store: JobStore,
        url_policy: UrlSafetyPolicy,
        max_concurrent_jobs: int = DEFAULT_MAX_CONCURRENT_JOBS,
    ) -> None:
        """Build the shared state.

        Args:
            store: Job persistence.
            url_policy: SSRF policy used at admission and by the crawl.
            max_concurrent_jobs: Simultaneous crawls before requests are refused.
        """
        self.store = store
        self.url_policy = url_policy
        self.max_concurrent_jobs = max_concurrent_jobs
        self._active: set[str] = set()
        self._lock = threading.Lock()
        # Strong references to in-flight tasks. `asyncio` only holds weak ones,
        # so without this the garbage collector may cancel a running crawl.
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def active_count(self) -> int:
        """Crawls running right now."""
        with self._lock:
            return len(self._active)

    def try_reserve(self, job_id: str) -> bool:
        """Claim a concurrency slot, or report that none is free.

        Checked and claimed under one lock. Testing capacity and then reserving
        in two steps would let two simultaneous requests both pass the check.
        """
        with self._lock:
            if len(self._active) >= self.max_concurrent_jobs:
                return False
            self._active.add(job_id)
            return True

    def release(self, job_id: str) -> None:
        """Give a concurrency slot back."""
        with self._lock:
            self._active.discard(job_id)

    def rekey(self, provisional: str, job_id: str) -> None:
        """Move a reservation from a provisional id onto the real one.

        Capacity has to be claimed before the store mints an id, or a refusal
        leaves a persisted job behind. This transfers the claim without ever
        dropping it, so the slot cannot be taken in between.
        """
        with self._lock:
            self._active.discard(provisional)
            self._active.add(job_id)

    def is_active(self, job_id: str) -> bool:
        """Whether this job currently holds a concurrency slot."""
        with self._lock:
            return job_id in self._active

    def track(self, task: asyncio.Task[None]) -> None:
        """Hold a strong reference to an in-flight task until it completes.

        `asyncio` keeps only weak references to tasks, so a crawl with no other
        referent can be garbage-collected mid-run — the job would simply stop,
        leaving no error and no result.
        """
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


def _run_job(state: ApiState, job_id: str, payload: PageClassificationInput) -> None:
    """Execute one crawl to completion. Runs on a worker thread.

    Never raises: this runs detached, so an exception escaping here would be
    logged by asyncio and leave the job `RUNNING` forever with nothing to move
    it. Every path ends in a terminal status.
    """
    store = state.store
    try:
        store.mark_running(job_id)
        result = PageClassificationTool(
            url_policy=state.url_policy,
            progress_sink=TelemetryRecorder(store, job_id, payload.resolved_max_pages),
            checkpoint_sink=CrawlCheckpointer(store, job_id, payload.base_url),
            # Kept so a later fix to the header-menu parser can be applied to
            # this result without re-crawling. One page; the menu is global.
            homepage_sink=lambda html: store.write_homepage(job_id, html),
        ).run(payload)

        if not result.ok or result.data is None:
            store.mark_failed(job_id, result.error or "the tool returned no data")
            return

        output = result.data
        if not isinstance(output, PageClassificationOutput):  # pragma: no cover - defensive
            store.mark_failed(job_id, f"unexpected output type {type(output).__name__}")
            return

        # `truncated` means the crawl hit its ceiling, so the graph is a subset
        # of the site. Recorded as PARTIAL so the UI can say so rather than
        # presenting an incomplete crawl as a finished one.
        store.finish(
            job_id,
            output.model_dump(mode="json"),
            partial=output.discovery.truncated,
        )
    except Exception as exc:  # noqa: BLE001 - a detached worker must not leak
        _logger.exception("job_crashed", extra={"job_id": job_id})
        store.mark_failed(job_id, f"{type(exc).__name__}: {exc}")


async def _dispatch(state: ApiState, job_id: str, payload: PageClassificationInput) -> None:
    """Run a job on a worker thread and always release its slot."""
    try:
        await asyncio.to_thread(_run_job, state, job_id, payload)
    finally:
        state.release(job_id)


def create_app(
    store: JobStore | None = None,
    url_policy: UrlSafetyPolicy | None = None,
    *,
    jobs_root: Path | str | None = None,
    max_concurrent_jobs: int = DEFAULT_MAX_CONCURRENT_JOBS,
    allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS,
) -> FastAPI:
    """Build the application.

    A factory, not a module-level singleton, so tests get an isolated instance
    and so importing this module has no side effects — a module-level app would
    create the jobs directory and run orphan recovery at import time, including
    during test collection.

    Args:
        store: Job persistence. Defaults to a `DiskJobStore` under `jobs_root`.
        url_policy: SSRF policy applied at admission and inherited by the crawl.
        jobs_root: Directory for the default store. Defaults to `.jobs/`.
        max_concurrent_jobs: Simultaneous crawls before `429`.
        allowed_origins: Exact CORS origins. Never a wildcard.

    Returns:
        The configured application.
    """
    resolved_store: JobStore = (
        store if store is not None else DiskJobStore(jobs_root or Path(".jobs"))
    )
    state = ApiState(
        store=resolved_store,
        url_policy=url_policy if url_policy is not None else UrlSafetyPolicy(),
        max_concurrent_jobs=max_concurrent_jobs,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        # A job left RUNNING by a killed process has no worker any more. Nothing
        # would ever move it, and a polling UI would wait forever.
        orphans = resolved_store.recover_orphans()
        if orphans:
            _logger.warning("recovered_orphaned_jobs", extra={"count": len(orphans)})
        yield

    app = FastAPI(
        title="Rankuno AI Engine",
        version=API_VERSION,
        summary="Local API for the Phase 1 Page Classification Engine.",
        lifespan=lifespan,
    )
    app.state.api = state

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    # The endpoints close over `state` rather than receiving it through
    # `Depends`. With `from __future__ import annotations` every annotation is a
    # string, and FastAPI resolves those against the *module* namespace — a
    # dependency alias defined inside this factory is invisible there, so the
    # parameter silently degrades into a required query parameter and every
    # request 422s. A closure has no such failure mode.

    @app.get(f"{API_PREFIX}/health", response_model=HealthView)
    def health() -> HealthView:
        """Liveness, plus how much crawl capacity is free."""
        return HealthView(
            active_jobs=state.active_count,
            max_concurrent_jobs=state.max_concurrent_jobs,
        )

    @app.post(
        f"{API_PREFIX}/jobs", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED
    )
    async def create_job(payload: PageClassificationInput) -> JobAccepted:
        """Accept a crawl and return an id to poll.

        `202`, never `200`: nothing has been crawled when this returns.

        Raises:
            HTTPException: `400` if the URL fails SSRF validation, `429` if no
                concurrency slot is free.
        """
        return _start(payload, payload.base_url)

    @app.get(f"{API_PREFIX}/jobs", response_model=list[JobRecord])
    def list_jobs() -> list[JobRecord]:
        """Every job, newest first. Metadata only — never a result blob."""
        return state.store.list_jobs()

    @app.get(f"{API_PREFIX}/jobs/{{job_id}}", response_model=JobRecord)
    def get_job(job_id: str) -> JobRecord:
        """One job's status.

        Raises:
            HTTPException: `404` if no such job exists.
        """
        try:
            return state.store.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no job {job_id}") from exc

    @app.get(f"{API_PREFIX}/jobs/{{job_id}}/result")
    def get_result(job_id: str) -> Mapping[str, object]:
        """A finished job's `PageClassificationOutput`.

        Returned as the stored mapping rather than re-validated into the model:
        it was serialised *from* that model, and re-parsing 16 MB on every fetch
        buys nothing.

        Raises:
            HTTPException: `404` if unknown, `409` if the job has not finished.
        """
        try:
            record = state.store.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no job {job_id}") from exc

        if not record.has_result:
            # 409, not 404: the job exists and may yet produce a result. A 404
            # would tell a polling client to give up.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"job {job_id} is {record.status.value} and has no result",
            )
        return state.store.read_result(job_id)

    @app.get(f"{API_PREFIX}/jobs/{{job_id}}/checkpoint")
    def get_checkpoint(job_id: str) -> Mapping[str, object]:
        """A renderable view of what a job saved before it ended.

        Shaped as a `PageClassificationOutput` so the client renders it through
        exactly the path it uses for a finished crawl — a second shape would
        mean a second set of components to keep in step.

        Every page comes back `UNKNOWN`, which is honest rather than lazy: a
        checkpoint stores URLs, not classifications. The structure is real; what
        each page *is* was never determined.

        Raises:
            HTTPException: `404` if the job or its checkpoint does not exist.
        """
        try:
            state.store.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no job {job_id}") from exc

        checkpoint = state.store.read_checkpoint(job_id)
        if checkpoint is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail=f"job {job_id} saved no partial work"
            )
        return _checkpoint_as_output(checkpoint).model_dump(mode="json")

    def _start(payload: PageClassificationInput, label: str) -> JobAccepted:
        """Admit a crawl, reserve a slot, and dispatch it.

        Shared by every endpoint that starts work so admission cannot drift
        between them. SSRF validation in particular must not become something
        one entry point does and another forgets — a retry re-runs a stored
        payload, and a stored payload is not automatically still safe: DNS moves,
        and a host that resolved publicly last week may resolve to a private
        address today.
        """
        try:
            state.url_policy.validate(payload.base_url)
        except UnsafeUrlError as exc:
            _logger.warning("job_rejected_unsafe_url", extra={"url": payload.base_url})
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        # Capacity is claimed *before* the record exists. The other order
        # persisted a job for every refusal and immediately marked it failed, so
        # a user retrying against a full server manufactured a permanent FAILED
        # row per click — 16 of 99 records on one workstation were nothing but
        # refusals, indistinguishable in the list from crawls that really ran.
        #
        # The slot is reserved against a provisional id and re-keyed once the
        # record exists, because `try_reserve` needs something to hold and the
        # id is the store's to mint.
        pending = f"pending:{uuid4().hex}"
        if not state.try_reserve(pending):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"at most {state.max_concurrent_jobs} crawls may run at once",
            )
        try:
            record = state.store.create(TOOL_NAME, payload.model_dump(mode="json"), label=label)
        except Exception:
            # The store failed, so there is no job and nothing will ever release
            # this slot. Leaking it would cost a permanent slot per failure.
            state.release(pending)
            raise
        state.rekey(pending, record.id)
        state.track(asyncio.create_task(_dispatch(state, record.id, payload)))
        return JobAccepted(id=record.id, status=record.status.value, label=record.label)

    def _stored_payload(job_id: str) -> PageClassificationInput:
        """Rebuild the input a job was started with.

        Raises:
            HTTPException: `404` if there is no such job, `409` if its stored
                request cannot be replayed.
        """
        try:
            record = state.store.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no job {job_id}") from exc

        if not record.request:
            # Jobs created before the request was stored, and any record written
            # by a different tool. Refused rather than guessed at: inventing a
            # payload would crawl with settings the operator never chose.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"job {job_id} did not record the request it ran, so it cannot be re-run",
            )
        try:
            return PageClassificationInput.model_validate(record.request)
        except ValidationError as exc:
            # A record written before a schema change. Says so plainly instead
            # of surfacing a pydantic traceback to the operator.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"job {job_id} was run with settings this build no longer accepts",
            ) from exc

    @app.post(
        f"{API_PREFIX}/jobs/{{job_id}}/retry",
        response_model=JobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def retry_job(job_id: str) -> JobAccepted:
        """Run a job's crawl again from scratch, with its original settings.

        A new job, never a mutation of the old one. The original record is the
        evidence of what happened and when; overwriting it would destroy the
        history an audit depends on, and a failed crawl is often the finding.

        Deliberately unrestricted by the original job's outcome: re-running a
        *successful* crawl to pick up site changes is as legitimate as retrying
        a failed one.

        Raises:
            HTTPException: `404` if there is no such job, `409` if its settings
                cannot be replayed, `400` if the URL no longer passes SSRF
                validation, `429` if no concurrency slot is free.
        """
        payload = _stored_payload(job_id)
        return _start(payload, f"{payload.base_url} (retry)")

    @app.post(f"{API_PREFIX}/jobs/{{job_id}}/reparse", response_model=JobRecord)
    async def reparse_job(job_id: str) -> JobRecord:
        """Re-run placement over a finished job under today's rules.

        Synchronous and offline. No worker thread, no concurrency slot, no
        network: the homepage body is read from this job's sidecar and the
        classified pages come from its stored result. A 27,562-page crawl
        reparses in well under a second.

        A **new** job, never a mutation of the old one, for the same reason
        retry is. The original is the evidence of what the site looked like when
        it was crawled; overwriting it would destroy the comparison that makes a
        reparse worth running.

        What this can and cannot pick up follows from what was stored. With a
        homepage sidecar the menu is re-parsed, so a `nav_tree_parser` fix
        applies. Without one — every crawl run before the sidecar existed — the
        stored menu stands and only the placement rules re-run. Breadcrumbs are
        never re-extracted: the page bodies are gone.

        Raises:
            HTTPException: `404` if there is no such job, `409` if it has no
                stored result to reparse.
        """
        try:
            stored = state.store.read_result(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail=f"no job {job_id} with a result"
            ) from exc

        try:
            before = PageClassificationOutput.model_validate(stored)
        except ValidationError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="this job's result predates the current output contract",
            ) from exc

        homepage = state.store.read_homepage(job_id)
        after = reparse_placement(before, homepage)

        record = state.store.create(
            TOOL_NAME,
            {"base_url": before.base_url},
            label=f"{before.base_url} (reparsed)",
        )
        state.store.finish(record.id, after.model_dump(mode="json"))
        # Carried over so the new job can itself be reparsed. Without this the
        # chain breaks after one hop, which is exactly when it matters.
        if homepage:
            state.store.write_homepage(record.id, homepage)
        _logger.info(
            "job_reparsed",
            extra={"source": job_id, "job_id": record.id, "menu_reparsed": bool(homepage)},
        )
        return state.store.get(record.id)

    @app.post(
        f"{API_PREFIX}/jobs/{{job_id}}/reconcile/screaming-frog",
        response_model=ReconciliationSummary,
    )
    async def reconcile_screaming_frog(job_id: str, request: Request) -> ReconciliationSummary:
        """Compare a Screaming Frog export against a finished job, and merge the gap.

        **Entirely optional.** Nothing else in the engine calls this, and a crawl
        that never sees an export behaves exactly as it always has. This is an
        extra pass an operator may run when they happen to have a Screaming Frog
        licence and a reason to cross-check.

        The body is the raw CSV, sent as `text/csv` — not `multipart/form-data`.
        FastAPI's file upload needs `python-multipart`, which is not a
        dependency of this project, and adding a package to accept one file when
        Starlette already hands over the request body would be a poor trade. The
        browser reads the file and POSTs its text.

        Synchronous and offline, like reparse: no worker thread, no concurrency
        slot, no network. Merging 250 pages into a 27,656-page crawl takes about
        1.2 seconds, nearly all of it re-running placement over the combined set.

        A **new** job when anything merges, never a mutation of the old one. The
        original is the evidence of what the crawl alone found, and the whole
        value of a reconciliation is the comparison. When nothing merges, no job
        is created and `job_id` echoes the source.

        Raises:
            HTTPException: `404` if there is no such job, `409` if its result
                predates the current output contract, `400` if the body is
                empty or is not a readable export.
        """
        body = await request.body()
        if not body.strip():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="empty body: POST the Screaming Frog CSV as text/csv",
            )

        try:
            stored = state.store.read_result(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail=f"no job {job_id} with a result"
            ) from exc

        try:
            before = PageClassificationOutput.model_validate(stored)
        except ValidationError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="this job's result predates the current output contract",
            ) from exc

        # `utf-8-sig`: Screaming Frog writes a byte-order mark, and without this
        # the first header keeps an invisible prefix, never matches "Address",
        # and the whole export silently reconciles to nothing.
        try:
            outcome = merge_reconciled_urls(before, body.decode("utf-8-sig", errors="replace"))
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        report = outcome.report
        target = job_id
        if outcome.merged:
            record = state.store.create(
                TOOL_NAME,
                {"base_url": before.base_url},
                label=f"{before.base_url} (+{outcome.merged} from Screaming Frog)",
            )
            state.store.finish(record.id, outcome.output.model_dump(mode="json"))
            homepage = state.store.read_homepage(job_id)
            # Carried over so the merged job can itself be reparsed later.
            if homepage:
                state.store.write_homepage(record.id, homepage)
            target = record.id

        _logger.info(
            "job_reconciled",
            extra={
                "source": job_id,
                "job_id": target,
                "merged": outcome.merged,
                "missed": len(report.missed_pages),
            },
        )
        return ReconciliationSummary(
            job_id=target,
            source_job_id=job_id,
            base_url=before.base_url,
            frog_rows=report.frog_rows,
            in_both=report.in_both,
            missed_pages=len(report.missed_pages),
            orphans=len(report.orphans),
            merged=outcome.merged,
            frog_reasons=dict(report.frog_reasons),
            engine_reasons=dict(report.engine_reasons),
        )

    @app.post(f"{API_PREFIX}/jobs/{{job_id}}/cancel", response_model=JobRecord)
    async def cancel_job(job_id: str) -> JobRecord:
        """Abandon a job and give its concurrency slot back.

        **This releases the slot; it does not stop the crawl.** The work runs on
        a worker thread via `asyncio.to_thread`, and a Python thread cannot be
        killed from outside — cancelling the awaiting task does not reach into
        it either. The thread keeps fetching until it finishes or the process
        exits, and its result is discarded when it does.

        That is a weaker guarantee than the button implies, and it is still
        worth having. The failure this exists for is a crawl wedged in network
        I/O for hours: two stripe.com jobs held two of three slots for sixteen
        hours on one workstation, so every new crawl was refused by a server
        that was, for practical purposes, doing nothing. Releasing the slot
        restores the ability to work; waiting for the thread does not.

        A real stop needs a cancellation flag the crawl checks between fetches.
        That does not exist yet — see the build log for this cycle.

        Raises:
            HTTPException: `404` if there is no such job, `409` if it has
                already reached a terminal state.
        """
        try:
            record = state.store.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no job {job_id}") from exc
        if record.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"job is {record.status.value} and has already finished",
            )

        state.release(job_id)
        updated = state.store.mark_failed(
            job_id,
            "cancelled by operator — the crawl thread may still be running until it "
            "finishes or the server restarts",
        )
        _logger.warning("job_cancelled", extra={"job_id": job_id})
        return updated

    @app.post(
        f"{API_PREFIX}/jobs/{{job_id}}/resume",
        response_model=JobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def resume_job(job_id: str) -> JobAccepted:
        """Crawl the URLs an interrupted job discovered but never fetched.

        A separate job producing a separate result — **not** a merge into the
        original. Merging is not a matter of appending pages: inbound link
        counts, orphan flags and navigation coverage are properties of the whole
        graph, and a checkpoint stores URLs only. Classifying the remainder
        against a graph missing the pages already crawled would produce wrong
        in-degrees and wrong orphan flags, and orphan detection is a headline
        finding in these reports.

        Refused unless the original crawl genuinely stopped early. A crawl that
        ran to completion still shows more URLs discovered than fetched — a
        sitemap lists pages no link reaches, and faceted filters are declined on
        purpose — so `discovered > fetched` is normal and is not unfinished
        work. `truncated` and `stopped_reason` are what distinguish the two.

        Raises:
            HTTPException: `404` if there is no such job or it saved no partial
                work, `409` if it did not stop early, is still running, or has
                nothing left to fetch, and the codes `retry` can raise.
        """
        payload = _stored_payload(job_id)
        record = state.store.get(job_id)

        if not record.is_terminal:
            # Its checkpoint is still moving, so any delta read now is stale
            # before the resumed crawl starts.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"job {job_id} is still {record.status.value}",
            )

        checkpoint = state.store.read_checkpoint(job_id)
        if checkpoint is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail=f"job {job_id} saved no partial work"
            )

        unfetched = checkpoint.get("unfetched")
        if not isinstance(unfetched, list):
            # Written before checkpoints recorded this. The discovered set alone
            # cannot tell fetched from unfetched, so resuming would re-fetch
            # everything — which is what `retry` is, said honestly.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=(
                    f"job {job_id} predates resumable checkpoints and cannot be "
                    "resumed; retry it instead"
                ),
            )

        remaining = tuple(url for url in unfetched if isinstance(url, str))
        if not remaining:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"job {job_id} fetched every URL it discovered",
            )

        resumed = payload.model_copy(update={"seed_urls": remaining})
        return _start(resumed, f"{payload.base_url} (resumed +{len(remaining):,})")

    return app


def _checkpoint_as_output(checkpoint: Mapping[str, object]) -> PageClassificationOutput:
    """Rebuild a renderable output from saved URLs.

    The classifications are placeholders, and `stopped_reason` says so in the one
    place every consumer already reads — so a recovered view cannot be mistaken
    for a completed crawl.
    """
    base_url = str(checkpoint.get("base_url") or "")
    raw = checkpoint.get("urls")
    urls = [str(item) for item in raw] if isinstance(raw, list) else []

    return PageClassificationOutput(
        base_url=base_url,
        site_profile=SiteProfile(),
        weight_profile=WeightProfileReport.for_site(SiteProfile()),
        discovery=DiscoveryReport(
            base_url=base_url,
            total_urls=len(urls),
            stopped_reason=(
                "recovered from a checkpoint — these URLs were discovered before the "
                "crawl was interrupted, and none of them were classified"
            ),
        ),
        summary=CrawlSummary(pages_classified=len(urls), unknown_pages=len(urls)),
        pages=tuple(_placeholder_profile(url) for url in urls),
    )


def _placeholder_profile(url: str) -> FullPageIntelligenceProfile:
    """An unclassified page, carrying only what a checkpoint actually knows."""
    return FullPageIntelligenceProfile(
        url=url,
        canonical_url=url,
        normalized_path=url,
        hierarchy_level=HierarchyLevel.L3_LEAF_PAGE,
        primary_page_type=PrimaryPageType.UNKNOWN,
        depth_from_l0=1,
        search_intent=SearchIntent.INFORMATIONAL,
        signals_evaluated=(
            SignalScore(
                source=SignalSource.SITEMAP_INDEX,
                suggested_level=HierarchyLevel.L3_LEAF_PAGE,
                suggested_page_type=PrimaryPageType.UNKNOWN,
                confidence=0.0,
                notes="discovered before the crawl was interrupted; never classified",
            ),
        ),
        final_confidence_score=0.0,
        consensus_method=ConsensusMethod.LAYER0_FAST_PATH,
    )


class ServerConfig(StrictModel):
    """Bind settings for `serve()`."""

    host: str = "127.0.0.1"
    port: int = Field(default=8000, gt=0, le=65535)
    jobs_root: str = ".jobs"


def serve(config: ServerConfig | None = None) -> None:  # pragma: no cover - process entry point
    """Run the server.

    Binds loopback by default and that default should not be changed casually:
    there is no authentication, and the server fetches arbitrary URLs on
    request. Exposed on a routable interface it is an open proxy.
    """
    import uvicorn

    settings = config or ServerConfig()
    uvicorn.run(
        create_app(jobs_root=settings.jobs_root),
        host=settings.host,
        port=settings.port,
        log_config=None,
    )


if __name__ == "__main__":  # pragma: no cover
    serve()
