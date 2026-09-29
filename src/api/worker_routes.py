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

from fastapi import APIRouter, Header, HTTPException, Request, Response, status

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
from src.core.worker_templates import WorkerTemplateReport
from src.modules.seo.screaming_frog_control.upload_manifest import (
    SPINE_FILENAME,
    BundleUploadError,
    validate_and_extract_bundle,
)

if TYPE_CHECKING:
    from src.api.server import ApiState

__all__ = ["build_worker_router"]

_logger = get_logger("api.worker_routes")

_EMPTY_BUNDLE_ERROR = (
    "The crawl produced no export files. Screaming Frog writes its exports only "
    "when a crawl finishes, so a run that was stopped, killed, or crashed before "
    "the end leaves an empty output folder. Nothing was recovered from this run — "
    "start the crawl again."
)
"""Written to `WorkerJob.error`, so it is read by an operator on a dashboard,
not by an engineer in a stack trace. It names the mechanism and the next
action, because "0 files" on its own is indistinguishable from "the site has
no pages"."""

_MISSING_SPINE_REASON = (
    f"The crawl uploaded its export files but not {SPINE_FILENAME}, the page list "
    "every report is built from. The files are kept and can be downloaded, but no "
    "report can be produced from them — run the crawl again."
)
"""Carried on the `PARTIAL` transition for the same reason: the dashboard
shows `WorkerJob.error` beside a partial row, and a partial row with nothing
there renders as a bare "No reason was recorded." — a worse answer than the
wrong status it replaced."""


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
                templates=WorkerTemplateReport(
                    templates=tuple(payload.templates),
                    unrecognised_count=payload.unrecognised_count,
                ),
            )
        except WorkerStoreUnavailableError as exc:
            raise worker_store_unavailable(exc) from exc
        return WorkerHeartbeatResponse(
            worker_id=worker.worker_id,
            last_seen_at=worker.last_seen_at or datetime.now(UTC),
            templates=list(worker.templates),
            unrecognised_count=worker.unrecognised_template_count,
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
            url_list_sha256=job.envelope.url_list_sha256,
            secret=state.dispatch_signing_secret,
            ttl_s=settings.worker_dispatch_assignment_ttl_s,
        )
        return PollResponse(assignment=assignment)

    @router.get("/workers/jobs/{job_id}/url-list")
    def download_url_list(
        job_id: str, authorization: str | None = Header(default=None)
    ) -> Response:
        """Hand a claimed job its approved `--crawl-list` file (ADR 0023).

        The only channel by which bytes travel cloud -> worker. Everything
        else in ADR 0015 goes the other way, so this route is a genuine change
        in posture and is scoped accordingly: `owned_job` requires the caller
        to be *the* worker this job was pinned to, not merely a worker in the
        right org (condition 2's IDOR rule, condition 6's pinning), and
        `read_url_list` then filters on `org_id` in SQL a second time — the
        same belt-and-braces `download_bundle` already applies to the reverse
        direction.

        The digest is deliberately **not** sent in a header. The worker
        already holds it inside its own signed assignment claims, which is the
        only copy it may trust; a second copy travelling beside the bytes
        would be a copy an attacker who could alter the bytes could also
        alter.

        Raises:
            HTTPException: `401` unauthenticated; `404` unknown job, a job
                with no URL list, or a list that has expired; `403` a job
                belonging to a different worker or org; `503` the dispatch
                store is unreachable.
        """
        principal = require_worker_principal(authorization, worker_store=state.worker_store)
        job = owned_job(state, job_id, principal.worker_id, principal.org_id)
        digest = job.envelope.url_list_sha256
        if digest is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail=f"job {job_id} is not a list crawl and has no URL list",
            )
        try:
            stored = state.worker_dispatch_store.read_url_list(digest, org_id=principal.org_id)
        except DispatchStoreUnavailableError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        if stored is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail=(
                    f"the URL list for job {job_id} is no longer stored; it passed its "
                    f"retention window. Preview and dispatch the crawl again."
                ),
            )
        _logger.info(
            "worker_url_list_downloaded",
            extra={
                "job_id": job.id,
                "worker_id": principal.worker_id,
                "urls": stored.url_count,
                "bytes": len(stored.body),
            },
        )
        return Response(content=stored.body, media_type="text/plain; charset=utf-8")

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

        What the bundle contains decides the job's terminal status, because
        nothing else in this system can tell a finished crawl from a killed
        one (cycle 0113): no export files at all is `FAILED`, export files
        without `internal_all.csv` is `PARTIAL` — real data, but no
        deliverable can be built from it — and only a bundle carrying the
        spine is `SUCCEEDED`. All three are `200`: the report itself was
        accepted and the job is terminal, so a worker must not retry.

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

        if not members:
            # A valid archive with nothing in it is not a finished crawl. The
            # bytes are not stored: a 22-byte empty zip offered as a download
            # is the exact failure this branch exists to stop.
            try:
                updated = state.worker_dispatch_store.mark_failed(job.id, _EMPTY_BUNDLE_ERROR)
            except DispatchStoreUnavailableError as exc:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
            _logger.warning(
                "worker_bundle_empty",
                extra={
                    "job_id": job.id,
                    "worker_id": principal.worker_id,
                    "members": 0,
                    # Kept alongside `members` so this stays distinguishable
                    # from "files arrived but the allow-list dropped them":
                    # that case cannot reach here (an unlisted member is a
                    # 400), so an empty archive with a near-empty body is
                    # specifically "killed before export".
                    "bundle_bytes": len(body),
                },
            )
            return WorkerJobAccepted(id=updated.id, status=updated.status.value)

        rebuilt = rebuild_zip(members)
        encrypted = encrypt_bytes(rebuilt, secret=state.bundle_encryption_secret)
        # `load_screaming_frog_bundle` requires the spine non-optionally, so a
        # bundle without it can never become a deliverable however many other
        # files it carries. Stored anyway — partial data is worth keeping —
        # but never presented as a clean finish.
        spine_present = SPINE_FILENAME in members
        try:
            state.worker_dispatch_store.store_upload(
                job.id,
                org_id=principal.org_id,
                worker_id=principal.worker_id,
                encrypted_bytes=encrypted,
                retention_days=settings.worker_bundle_retention_days,
            )
            updated = state.worker_dispatch_store.mark_uploaded(
                job.id,
                bundle_size_bytes=len(rebuilt),
                partial=not spine_present,
                reason=None if spine_present else _MISSING_SPINE_REASON,
            )
        except DispatchStoreUnavailableError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

        _logger.info(
            "worker_bundle_uploaded",
            extra={
                "job_id": job.id,
                "worker_id": principal.worker_id,
                "members": len(members),
                "spine_present": spine_present,
                "status": updated.status.value,
            },
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
