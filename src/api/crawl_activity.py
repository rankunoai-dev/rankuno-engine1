"""`GET /crawl-activity`: how many crawls the caller's organization has in flight.

The header indicator this feeds must read the same on every device an org's
users are signed in on, so it cannot be browser-local state, and it cannot be
`GET /health`: that route is unauthenticated and process-global, so it would
disclose other organizations' load, and it counts neither worker-dispatched
Screaming Frog jobs nor anything per-org.

Two numbers come from two different stores, and each is cached per org for a
few seconds:

* `DiskJobStore.list_jobs()` globs and parses every record on every call. A
  header polled every ten seconds by several users must not become a
  full-directory read per request.
* `PostgresWorkerDispatchStore` opens a fresh connection per call with no pool
  (ADR 0015 condition 5). Uncached, N users polling would be N connections per
  interval, and an unreachable database would block a threadpool thread per
  request while it timed out.

The cache also holds a *failed* dispatch lookup (as zero). Retrying a dead
database on every poll is precisely the load pattern that keeps it dead.

Stale `DISPATCHED` jobs are filtered here, read-only, instead of calling
`expire_stale_dispatched`. That sweep is an `UPDATE`; running a write on a
polled GET, on a second connection, to fix a display number is the wrong trade.
`GET /workers/jobs` and the worker's poll still perform the real sweep, so the
rows converge; this route just refuses to count a job the sweep would fail.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import APIRouter, Header
from pydantic import Field

from src.api.auth import require_principal
from src.core.config import get_settings
from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.core.state_store import JobStatus
from src.core.worker_dispatch_schemas import WorkerJobStatus
from src.core.worker_dispatch_store import DispatchStoreUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.api.server import ApiState
    from src.core.state_store import JobStore
    from src.core.worker_dispatch_schemas import WorkerJob
    from src.core.worker_dispatch_store import WorkerDispatchStore

__all__ = [
    "CRAWL_ACTIVITY_TTL_S",
    "CrawlActivityCounter",
    "CrawlActivityView",
    "build_crawl_activity_router",
]

_logger = get_logger("api.crawl_activity")

CRAWL_ACTIVITY_TTL_S = 5.0
"""How long one org's count is reused. Half the UI's 10 s poll, so an indicator is
never more than one refresh behind, while N users cost one read per 5 s."""


class CrawlActivityView(StrictModel):
    """Integers only: nothing here identifies a job, a URL, or another org."""

    rankuno_active: int = Field(
        ge=0,
        description="The caller's org's Rankuno-engine jobs currently queued or running.",
    )
    rankuno_cap: int = Field(
        ge=1,
        description="Server-wide maximum concurrent Rankuno crawls (what try_reserve enforces).",
    )
    sf_active: int = Field(
        ge=0,
        description="The caller's org's Screaming Frog worker jobs currently queued or dispatched.",
    )


class _OrgTtlCache:
    """A tiny per-org value cache. Lock-protected; one compute per org per expiry."""

    def __init__(self, ttl_s: float, clock: Callable[[], float]) -> None:
        self._ttl_s = ttl_s
        self._clock = clock
        self._guard = threading.Lock()
        self._entries: dict[str, tuple[float, int]] = {}
        self._org_locks: dict[str, threading.Lock] = {}

    def get(self, org_id: str, compute: Callable[[], int]) -> int:
        """Return the org's cached value, recomputing once it has expired.

        A per-org lock serialises the recompute so a burst of pollers arriving
        at expiry produces one read, not one each. The key is the org, never a
        shared slot, so one org's number cannot be served to another.
        """
        with self._guard:
            org_lock = self._org_locks.setdefault(org_id, threading.Lock())
        with org_lock:
            now = self._clock()
            with self._guard:
                entry = self._entries.get(org_id)
            if entry is not None and now < entry[0]:
                return entry[1]
            value = compute()
            with self._guard:
                self._entries[org_id] = (self._clock() + self._ttl_s, value)
            return value


class CrawlActivityCounter:
    """Per-org, TTL-cached counts of in-flight crawls across both engines."""

    def __init__(
        self,
        store: JobStore,
        dispatch_store: WorkerDispatchStore,
        *,
        exclude_tool_name: str,
        ttl_s: float = CRAWL_ACTIVITY_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Build the counter.

        Args:
            store: The Rankuno job store.
            dispatch_store: The worker dispatch store.
            exclude_tool_name: Tool whose records are not Rankuno-engine
                crawls (local Screaming Frog), passed in because this module
                cannot import `server` without a cycle.
            ttl_s: Cache lifetime per org, per number.
            clock: Monotonic clock; injectable so tests need not sleep.
        """
        self._store = store
        self._dispatch_store = dispatch_store
        self._exclude_tool_name = exclude_tool_name
        self.clock = clock
        self._rankuno = _OrgTtlCache(ttl_s, lambda: self.clock())
        self._sf = _OrgTtlCache(ttl_s, lambda: self.clock())

    def rankuno_active(self, org_id: str) -> int:
        """This org's queued or running Rankuno jobs."""

        def compute() -> int:
            live = (JobStatus.QUEUED, JobStatus.RUNNING)
            return sum(
                1
                for job in self._store.list_jobs()
                if job.org_id == org_id
                and job.status in live
                and job.tool_name != self._exclude_tool_name
            )

        return self._rankuno.get(org_id, compute)

    def sf_active(self, org_id: str, *, stale_after_s: float) -> int:
        """This org's queued or dispatched worker jobs; `0` if the store is unreachable.

        Unreachable includes "Postgres was never configured" - both surface as
        `DispatchStoreUnavailableError`. `GET /workers/jobs` answers that with
        a 503 because its whole purpose is that data; a header badge answers
        with zero, since a broken indicator must not break the page around it.
        """

        def compute() -> int:
            cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_s)
            try:
                jobs = self._dispatch_store.list_jobs_for_org(org_id)
            except DispatchStoreUnavailableError as exc:
                _logger.warning(
                    "crawl_activity_dispatch_store_unavailable", extra={"error": str(exc)}
                )
                return 0

            def counts(job: WorkerJob) -> bool:
                if job.org_id != org_id:
                    return False
                if job.status is WorkerJobStatus.QUEUED:
                    return True
                return job.status is WorkerJobStatus.DISPATCHED and (
                    job.dispatched_at is None or job.dispatched_at >= cutoff
                )

            return sum(1 for job in jobs if counts(job))

        return self._sf.get(org_id, compute)


def build_crawl_activity_router(state: ApiState) -> APIRouter:
    """Build the router. `state` is closed over, as in the other route modules."""
    router = APIRouter()

    @router.get("/crawl-activity", response_model=CrawlActivityView)
    def crawl_activity(authorization: str | None = Header(default=None)) -> CrawlActivityView:
        """Counts of the caller's org's in-flight crawls.

        Raises:
            HTTPException: `401` if the token is missing or invalid.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        counter = state.crawl_activity
        return CrawlActivityView(
            rankuno_active=counter.rankuno_active(principal.org_id),
            rankuno_cap=state.max_concurrent_jobs,
            sf_active=counter.sf_active(
                principal.org_id, stale_after_s=get_settings().worker_dispatch_timeout_s
            ),
        )

    return router
