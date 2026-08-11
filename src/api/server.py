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

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import Field

from src.core.errors import UnsafeUrlError
from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.core.state_store import (
    MAX_RECENT_ITEMS,
    DiskJobStore,
    JobNotFoundError,
    JobRecord,
    JobStore,
    JobTelemetry,
)
from src.core.url_safety import UrlSafetyPolicy
from src.modules.seo.page_classifier.tool import (
    PageClassificationInput,
    PageClassificationOutput,
    PageClassificationTool,
)

__all__ = ["ApiState", "TelemetryRecorder", "create_app", "serve"]

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
            progress_sink=TelemetryRecorder(store, job_id, payload.max_pages),
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
    resolved_store = store if store is not None else DiskJobStore(jobs_root or Path(".jobs"))
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
        try:
            state.url_policy.validate(payload.base_url)
        except UnsafeUrlError as exc:
            # Rejected at admission rather than letting the crawl fail later, so
            # the operator sees the reason instead of a job that dies quietly.
            _logger.warning("job_rejected_unsafe_url", extra={"url": payload.base_url})
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        record = state.store.create(
            TOOL_NAME,
            payload.model_dump(mode="json"),
            label=payload.base_url,
        )

        if not state.try_reserve(record.id):
            state.store.mark_failed(record.id, "server is at its concurrent crawl limit")
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"at most {state.max_concurrent_jobs} crawls may run at once",
            )

        state.track(asyncio.create_task(_dispatch(state, record.id, payload)))
        return JobAccepted(id=record.id, status=record.status.value, label=record.label)

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

    return app


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
