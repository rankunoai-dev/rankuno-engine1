"""HTTP surface for ADR 0015's cloud <-> desktop-worker dispatch.

A separate router from `server.py`, matching `deliverables_routes.py`'s and
`auth.py`'s own reasoning: that module is already well past this project's
400-line target, and a router built from `ApiState` rather than importing
`server.py` keeps the dependency one-way. The same size pressure split this
surface three ways — this module holds the routes a *daemon* calls,
`worker_dashboard_routes.py` the routes a *human* calls, and
`worker_route_helpers.py` the checks both perform first. The division is the
authentication boundary: everything here goes through
`require_worker_principal`, everything there through `require_principal`.
`build_worker_router` composes both, so `server.py` still mounts one router.

The whole surface, in the order ADR 0015's binding conditions introduce it:

* `POST /workers`, `GET /workers` — worker registration/listing (dashboard
  module). Human-authenticated; a worker's long-lived credential is shown
  exactly once, in the registration response (condition 2). The listing
  carries liveness, so a dashboard never offers "Launch" to a desktop that
  is asleep.
* `GET /workers/{worker_id}/templates` (dashboard module) — org-scoped read
  of what one worker reported it holds, for the launch form's dropdown.
* `POST /workers/{worker_id}/dispatch/preview`,
  `POST /workers/{worker_id}/dispatch` (dashboard module) — gate (a), the
  cloud-side preview/confirm exchange, additionally bound to `worker_id`
  (condition 3(a)). Nothing is queued until confirm succeeds, and confirm
  refuses an offline worker rather than queueing into a void.
* `GET /workers/jobs`, `GET /workers/jobs/{job_id}`,
  `GET /workers/jobs/{job_id}/bundle` (dashboard module) — org-scoped read
  access to the job queue and to a finished job's decrypted bundle.
* `POST /workers/heartbeat` — worker-authenticated check-in that also
  reports which `.seospiderconfig` templates that machine holds. The cloud
  host has none of its own; the worker is the only place they exist.
* `GET /workers/dispatch/poll` — worker-authenticated. Claims the oldest
  queued job pinned to *this* worker and mints gate (b)'s signed assignment
  (condition 3(b)). Never accepts a `worker_id` the request claims — the
  authenticated principal is the only source of that value (condition 2's
  IDOR rule).
* `POST /workers/jobs/{job_id}/upload`, `POST /workers/jobs/{job_id}/failed`
  — worker-authenticated job outcome reporting. The upload path size-caps
  before buffering, then validates, allow-lists, and encrypts before it ever
  reaches storage (condition 9, condition 11).
* `POST /workers/jobs/{job_id}/progress` — worker-authenticated, best-effort
  live progress reporting while a job is still running. Additive to ADR
  0015, not part of it: never changes a job's lifecycle `status`, and every
  field it persists is optional everywhere it is read.

No circuit breaker on this router's own outbound behaviour is needed — it
has none; every failure mode here is either a `DispatchStoreUnavailableError`
(mapped to `503`, never a silent approval — condition 5) or a `4xx` the
caller can act on.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Header, HTTPException, Request, status

from src.api.auth import require_worker_principal
from src.api.worker_dashboard_routes import build_worker_dashboard_router
from src.api.worker_route_helpers import (
    owned_job,
    read_capped_body,
    rebuild_zip,
    worker_store_unavailable,
)
from src.api.worker_schemas import (
    PollResponse,
    WorkerFailureReport,
    WorkerHeartbeatRequest,
    WorkerHeartbeatResponse,
    WorkerJobAccepted,
    WorkerProgressReport,
)
from src.core.config import get_settings
from src.core.logger import get_logger
from src.core.worker_auth import WorkerStoreUnavailableError
from src.core.worker_bundle_crypto import encrypt_bytes
from src.core.worker_dispatch_signing import issue_dispatch_assignment
from src.core.worker_dispatch_store import DispatchStoreUnavailableError
from src.modules.seo.screaming_frog_control.upload_manifest import (
    BundleUploadError,
    validate_and_extract_bundle,
)

if TYPE_CHECKING:
    from src.api.server import ApiState

__all__ = ["build_worker_router"]

_logger = get_logger("api.worker_routes")


def build_worker_router(state: ApiState) -> APIRouter:
    """Build every ADR 0015 worker-dispatch route over `state`.

    The human-authenticated routes are registered first, so a path that
    could match both halves resolves the same way it did when all of them
    lived in one module — splitting the file must not silently reorder the
    surface.
    """
    router = APIRouter()
    router.include_router(build_worker_dashboard_router(state))

    @router.post("/workers/heartbeat", response_model=WorkerHeartbeatResponse)
    def heartbeat(
        payload: WorkerHeartbeatRequest, authorization: str | None = Header(default=None)
    ) -> WorkerHeartbeatResponse:
        """Record that this worker is awake and what templates it holds.

        Raises:
            HTTPException: `401` unauthenticated; `503` the worker store is
                unreachable.
        """
        principal = require_worker_principal(authorization, worker_store=state.worker_store)
        try:
            worker = state.worker_store.touch(
                principal.worker_id,
                seen_at=datetime.now(UTC),
                template_names=tuple(payload.template_names),
            )
        except WorkerStoreUnavailableError as exc:
            raise worker_store_unavailable(exc) from exc
        return WorkerHeartbeatResponse(
            worker_id=worker.worker_id,
            last_seen_at=worker.last_seen_at or datetime.now(UTC),
            template_names=list(worker.template_names),
        )

    @router.get("/workers/dispatch/poll", response_model=PollResponse)
    def poll_for_job(authorization: str | None = Header(default=None)) -> PollResponse:
        """A worker daemon's poll: claim its own oldest queued job, if any.

        `worker_id`/`org_id` come only from the verified credential
        (condition 2) — nothing in this request can name a different
        worker's queue. The poll itself is the liveness signal: a daemon
        that is running polls, and one that is not, does not.

        Raises:
            HTTPException: `401` unauthenticated; `503` the dispatch store
                or the worker store is unreachable.
        """
        principal = require_worker_principal(authorization, worker_store=state.worker_store)
        settings = get_settings()
        try:
            state.worker_store.touch(principal.worker_id, seen_at=datetime.now(UTC))
        except WorkerStoreUnavailableError as exc:
            raise worker_store_unavailable(exc) from exc

        try:
            # A poll is the natural moment to notice this worker abandoned
            # something: it is here, so anything of its own still marked
            # DISPATCHED from hours ago is not coming back.
            state.worker_dispatch_store.expire_stale_dispatched(
                org_id=principal.org_id, older_than_s=settings.worker_dispatch_timeout_s
            )
            job = state.worker_dispatch_store.claim_next_job(
                worker_id=principal.worker_id, org_id=principal.org_id
            )
        except DispatchStoreUnavailableError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        if job is None:
            return PollResponse(assignment=None)

        assignment = issue_dispatch_assignment(
            job_id=job.id,
            worker_id=job.worker_id,
            org_id=job.org_id,
            kind=job.kind,
            seed_url=job.envelope.seed_url,
            template_name=job.envelope.template_name,
            correlation_id=job.envelope.correlation_id,
            secret=state.dispatch_signing_secret,
            ttl_s=settings.worker_dispatch_assignment_ttl_s,
        )
        return PollResponse(assignment=assignment)

    @router.post("/workers/jobs/{job_id}/upload", response_model=WorkerJobAccepted)
    async def upload_bundle(
        job_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> WorkerJobAccepted:
        """Accept and store a completed job's validated, encrypted bundle.

        The body is the raw zip archive — matching this codebase's existing
        "raw body, not `multipart/form-data`" convention
        (`server.reconcile_screaming_frog`'s own docstring: `python-
        multipart` is not a dependency, and adding one for this would be a
        poor trade).

        Safe to retry. Home broadband drops mid-upload; a worker that
        retries lands on `store_upload`'s `ON CONFLICT (job_id) DO UPDATE`,
        which replaces the blob wholesale rather than appending, so a second
        attempt cannot produce two bundles or a spliced one. The bytes
        stored are always a freshly rebuilt archive of a fully validated
        upload, never a partially received body — a truncated retry fails
        `validate_and_extract_bundle` and never reaches storage at all.

        Raises:
            HTTPException: `401` unauthenticated; `404` unknown job; `403`
                a job belonging to a different worker or org (condition 2's
                IDOR rule, applied to the upload path); `413` the body is
                over the size cap, refused before it is buffered; `400` the
                body is empty or fails bundle validation (condition 9);
                `503` the dispatch store is unreachable.
        """
        principal = require_worker_principal(authorization, worker_store=state.worker_store)
        job = owned_job(state, job_id, principal.worker_id, principal.org_id)

        settings = get_settings()
        max_bytes = settings.worker_upload_max_bytes
        body = await read_capped_body(request, max_bytes=max_bytes)
        if not body:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="empty upload body")

        try:
            members = validate_and_extract_bundle(body, max_total_bytes=max_bytes)
        except BundleUploadError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        rebuilt = rebuild_zip(members)
        encrypted = encrypt_bytes(rebuilt, secret=state.bundle_encryption_secret)
        try:
            state.worker_dispatch_store.store_upload(
                job.id,
                org_id=principal.org_id,
                worker_id=principal.worker_id,
                encrypted_bytes=encrypted,
                retention_days=settings.worker_bundle_retention_days,
            )
            updated = state.worker_dispatch_store.mark_uploaded(
                job.id, bundle_size_bytes=len(rebuilt)
            )
        except DispatchStoreUnavailableError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

        _logger.info(
            "worker_bundle_uploaded",
            extra={"job_id": job.id, "worker_id": principal.worker_id, "members": len(members)},
        )
        return WorkerJobAccepted(id=updated.id, status=updated.status.value)

    @router.post("/workers/jobs/{job_id}/failed", response_model=WorkerJobAccepted)
    def report_failure(
        job_id: str,
        payload: WorkerFailureReport,
        authorization: str | None = Header(default=None),
    ) -> WorkerJobAccepted:
        """Record that a claimed job could not be completed.

        Raises:
            HTTPException: `401` unauthenticated; `404` unknown job; `403`
                a job belonging to a different worker or org; `503` the
                dispatch store is unreachable.
        """
        principal = require_worker_principal(authorization, worker_store=state.worker_store)
        job = owned_job(state, job_id, principal.worker_id, principal.org_id)
        try:
            updated = state.worker_dispatch_store.mark_failed(job.id, payload.error)
        except DispatchStoreUnavailableError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        return WorkerJobAccepted(id=updated.id, status=updated.status.value)

    @router.post("/workers/jobs/{job_id}/progress", response_model=WorkerJobAccepted)
    def report_progress(
        job_id: str,
        payload: WorkerProgressReport,
        authorization: str | None = Header(default=None),
    ) -> WorkerJobAccepted:
        """Record a claimed job's latest live progress snapshot.

        Never changes a job's lifecycle `status` — it can arrive any number
        of times, in any order relative to network retries or a job's own
        terminal transition, and a late or out-of-order report after the job
        has already finished is harmless (`WorkerDispatchStore.
        update_job_progress`'s own docstring). The same per-job ownership
        check `/failed` and `/upload` already enforce applies here
        unchanged — a worker reporting progress on a job it did not claim is
        refused exactly like every other per-job route (ADR 0015 condition
        2's IDOR rule, condition 6's per-worker pinning).

        Raises:
            HTTPException: `401` unauthenticated; `404` unknown job; `403`
                a job belonging to a different worker or org; `503` the
                dispatch store is unreachable.
        """
        principal = require_worker_principal(authorization, worker_store=state.worker_store)
        job = owned_job(state, job_id, principal.worker_id, principal.org_id)
        try:
            updated = state.worker_dispatch_store.update_job_progress(
                job.id,
                pages_crawled=payload.pages_crawled,
                progress_pct=payload.progress_pct,
                phase=payload.phase,
            )
        except DispatchStoreUnavailableError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        return WorkerJobAccepted(id=updated.id, status=updated.status.value)

    return router
