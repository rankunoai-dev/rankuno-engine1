"""The human-authenticated half of ADR 0015's worker-dispatch surface.

Split from `worker_routes.py`, which now holds only the routes a *daemon*
calls. The division is the authentication boundary, not an arbitrary line
count: everything here goes through `require_principal` and is scoped to the
caller's org, and everything there goes through `require_worker_principal`
and is scoped to one machine's credential. Two files that each answer one
question — "is this operator allowed to see this?" versus "is this the
worker this job was pinned to?" — are easier to audit than one file that
interleaves both, and each stays inside this codebase's 400-line target.

`build_worker_dashboard_router` is included by `build_worker_router`, so
`server.py` still mounts exactly one router and route ordering between the
two halves stays deterministic.

The route worth the most scrutiny here is `GET /workers/jobs/{id}/bundle`:
it is the first path by which crawled page content leaves the platform, and
an IDOR on it would hand one customer another customer's crawl.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import StreamingResponse

from src.api.auth import org_scoped_or_404, require_principal
from src.api.worker_route_helpers import owned_worker, validate_seed_url, worker_store_unavailable
from src.api.worker_schemas import (
    DispatchConfirmRequest,
    DispatchPreviewRequest,
    DispatchPreviewResponse,
    WorkerJobAccepted,
    WorkerJobListView,
    WorkerJobView,
    WorkerListView,
    WorkerRegisterRequest,
    WorkerRegisterResponse,
    WorkerSummary,
    WorkerTemplatesView,
)
from src.core.auth import hash_password
from src.core.config import get_settings
from src.core.logger import get_logger
from src.core.worker_auth import (
    Worker,
    WorkerStoreUnavailableError,
    mint_worker_secret,
    worker_is_online,
)
from src.core.worker_bundle_crypto import BundleDecryptionError, decrypt_bytes
from src.core.worker_dispatch_schemas import WorkerJob
from src.core.worker_dispatch_store import DispatchStoreUnavailableError, WorkerJobNotFoundError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from src.api.server import ApiState

__all__ = ["build_worker_dashboard_router"]

_logger = get_logger("api.worker_dashboard_routes")

_BUNDLE_CHUNK_BYTES = 64 * 1024
"""Response chunk size for a bundle download. See `_stream_bundle` for why
the plaintext is nonetheless materialised before the first chunk is sent."""


def _to_view(job: WorkerJob) -> WorkerJobView:
    """Map a persisted `WorkerJob` onto its HTTP view."""
    return WorkerJobView.model_validate(job, from_attributes=True)


def _summarise(worker: Worker, *, offline_after_s: float) -> WorkerSummary:
    """Map a `Worker` onto its HTTP view, adding the server's liveness verdict."""
    return WorkerSummary(
        worker_id=worker.worker_id,
        org_id=worker.org_id,
        display_name=worker.display_name,
        is_active=worker.is_active,
        created_at=worker.created_at,
        last_seen_at=worker.last_seen_at,
        is_online=worker_is_online(worker, offline_after_s=offline_after_s),
        template_names=list(worker.template_names),
    )


def _stream_bundle(payload: bytes) -> Iterator[bytes]:
    """Yield an already-decrypted bundle in chunks.

    The plaintext is whole before the first chunk leaves, and that is
    deliberate, not an oversight. `worker_bundle_crypto` is encrypt-then-MAC
    over the entire blob: there is no authenticated prefix, so emitting
    bytes before the tag has been checked would be streaming unverified
    plaintext to a browser — exactly the "never a partial or plaintext body"
    rule this route is meant to hold. Chunking the *response* still keeps
    the socket from being handed one enormous buffer, and bounds the extra
    copy to 64 KB at a time.
    """
    for start in range(0, len(payload), _BUNDLE_CHUNK_BYTES):
        yield payload[start : start + _BUNDLE_CHUNK_BYTES]


def build_worker_dashboard_router(state: ApiState) -> APIRouter:  # noqa: C901 - route count
    """Build every human-authenticated worker-dispatch route over `state`."""
    router = APIRouter()

    @router.post(
        "/workers", response_model=WorkerRegisterResponse, status_code=status.HTTP_201_CREATED
    )
    def register_worker(
        payload: WorkerRegisterRequest, authorization: str | None = Header(default=None)
    ) -> WorkerRegisterResponse:
        """Register a new desktop worker for the caller's own org.

        Raises:
            HTTPException: `401` if the session token is missing/invalid;
                `503` if the worker store is unreachable.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        secret = mint_worker_secret()
        worker = Worker(
            worker_id=_new_worker_id(),
            org_id=principal.org_id,
            secret_hash=hash_password(secret),
            display_name=payload.display_name,
        )
        try:
            state.worker_store.create(worker)
        except WorkerStoreUnavailableError as exc:
            raise worker_store_unavailable(exc) from exc
        return WorkerRegisterResponse(
            worker_id=worker.worker_id, worker_secret=secret, org_id=worker.org_id
        )

    @router.get("/workers", response_model=WorkerListView)
    def list_workers(authorization: str | None = Header(default=None)) -> WorkerListView:
        """Every worker registered for the caller's org, with liveness."""
        principal = require_principal(authorization, session_secret=state.session_secret)
        offline_after_s = get_settings().worker_offline_after_s
        try:
            workers = state.worker_store.list_workers(principal.org_id)
        except WorkerStoreUnavailableError as exc:
            raise worker_store_unavailable(exc) from exc
        return WorkerListView(
            workers=[_summarise(w, offline_after_s=offline_after_s) for w in workers],
            offline_after_s=offline_after_s,
        )

    @router.get("/workers/{worker_id}/templates", response_model=WorkerTemplatesView)
    def list_worker_templates(
        worker_id: str, authorization: str | None = Header(default=None)
    ) -> WorkerTemplatesView:
        """What one worker reported it holds locally.

        Distinct from `GET /screaming-frog/templates`, which lists the API
        host's own directory and remains correct for the local single-machine
        deployment. On a cloud host that directory does not exist and is the
        wrong machine besides.

        Raises:
            HTTPException: `401` unauthenticated; `404` unknown worker;
                `403` another org's worker.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        worker = owned_worker(state, worker_id, principal.org_id)
        return WorkerTemplatesView(
            worker_id=worker.worker_id,
            templates=list(worker.template_names),
            reported_at=worker.last_seen_at,
        )

    @router.post("/workers/{worker_id}/dispatch/preview", response_model=DispatchPreviewResponse)
    def preview_dispatch(
        worker_id: str,
        payload: DispatchPreviewRequest,
        authorization: str | None = Header(default=None),
    ) -> DispatchPreviewResponse:
        """Validate a seed URL and mint gate (a)'s confirm token.

        Raises:
            HTTPException: `401` unauthenticated; `404` unknown worker;
                `403` a worker owned by another org; `400` an unsafe URL.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        worker = owned_worker(state, worker_id, principal.org_id)
        safe_url = validate_seed_url(state, payload.seed_url)
        settings = get_settings()

        token = state.worker_dispatch_store.mint_dispatch_preview(
            org_id=principal.org_id,
            worker_id=worker.worker_id,
            seed_url=safe_url,
            template_name=payload.template_name,
            correlation_id=payload.correlation_id,
            ttl_s=settings.worker_dispatch_preview_ttl_s,
        )
        return DispatchPreviewResponse(
            token=token.token,
            expires_at=token.expires_at,
            worker_id=worker.worker_id,
            seed_url=safe_url,
            template_name=payload.template_name,
            correlation_id=payload.correlation_id,
            worker_online=worker_is_online(worker, offline_after_s=settings.worker_offline_after_s),
            worker_last_seen_at=worker.last_seen_at,
        )

    @router.post(
        "/workers/{worker_id}/dispatch",
        response_model=WorkerJobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def confirm_dispatch(
        worker_id: str,
        payload: DispatchConfirmRequest,
        authorization: str | None = Header(default=None),
    ) -> WorkerJobAccepted:
        """Queue a job, given a token minted by `.../dispatch/preview`.

        Raises:
            HTTPException: `401` unauthenticated; `404` unknown worker;
                `403` a worker owned by another org, or the token is
                invalid/expired/already used; `409` the target worker is
                offline; `400` an unsafe URL; `503` the dispatch store is
                unreachable (fail closed — condition 5's "approval silently
                fails, nothing runs").
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        worker = owned_worker(state, worker_id, principal.org_id)
        settings = get_settings()
        if not worker_is_online(worker, offline_after_s=settings.worker_offline_after_s):
            # Refused, not queued. A job accepted for a sleeping PC sits in
            # the queue looking like progress and produces nothing; the
            # operator finds out minutes later, from an absence.
            _logger.warning(
                "worker_dispatch_refused_offline",
                extra={"worker_id": worker.worker_id, "last_seen_at": str(worker.last_seen_at)},
            )
            last_seen = (
                "it has never checked in"
                if worker.last_seen_at is None
                else f"last seen {worker.last_seen_at.isoformat()}"
            )
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=(
                    f"worker {worker.worker_id} is offline ({last_seen}); start the "
                    f"Rankuno worker daemon on that machine and try again"
                ),
            )
        safe_url = validate_seed_url(state, payload.seed_url)

        try:
            job = state.worker_dispatch_store.confirm_dispatch(
                payload.token,
                org_id=principal.org_id,
                worker_id=worker.worker_id,
                seed_url=safe_url,
                template_name=payload.template_name,
                correlation_id=payload.correlation_id,
            )
        except DispatchStoreUnavailableError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        if job is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="dispatch preview token is invalid, expired, or already used",
            )
        return WorkerJobAccepted(id=job.id, status=job.status.value)

    @router.get("/workers/jobs", response_model=WorkerJobListView)
    def list_worker_jobs(authorization: str | None = Header(default=None)) -> WorkerJobListView:
        """Every dispatch job for the caller's org.

        Sweeps abandoned `DISPATCHED` jobs first. This is the call that
        matters for the dead-daemon case: if nothing is polling, the poll
        route's own sweep never runs, and without this the dashboard would
        show a job as "running" indefinitely.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        try:
            state.worker_dispatch_store.expire_stale_dispatched(
                org_id=principal.org_id, older_than_s=get_settings().worker_dispatch_timeout_s
            )
            jobs = state.worker_dispatch_store.list_jobs_for_org(principal.org_id)
        except DispatchStoreUnavailableError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        return WorkerJobListView(jobs=[_to_view(job) for job in jobs])

    @router.get("/workers/jobs/{job_id}", response_model=WorkerJobView)
    def get_worker_job(
        job_id: str, authorization: str | None = Header(default=None)
    ) -> WorkerJobView:
        """Read one dispatch job's cloud-tracked state.

        Raises:
            HTTPException: `401` unauthenticated; `404` unknown job; `403`
                another org's job.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        return _to_view(human_owned_job(state, job_id, principal.org_id))

    @router.get("/workers/jobs/{job_id}/bundle")
    def download_bundle(
        job_id: str, authorization: str | None = Header(default=None)
    ) -> StreamingResponse:
        """Download one finished job's crawl bundle as a zip.

        Org-scoped by the same `org_scoped_or_404` helper every other job
        route uses, and then scoped *again* inside the store: `read_upload`
        takes `org_id` and filters on it in SQL, so even a bug in the check
        above cannot hand org A the blob belonging to org B. This is the
        first route by which crawl content leaves the platform, and an IDOR
        here leaks a customer's crawl of their own site.

        Fails closed on decryption. A missing or rotated
        `WORKER_BUNDLE_ENCRYPTION_SECRET` produces a `500` naming the
        setting, never a partial body and never the ciphertext.

        Raises:
            HTTPException: `401` unauthenticated; `404` unknown job, or no
                bundle (never uploaded, or past its retention `expires_at`
                — an expired bundle is not readable); `403` another org's
                job; `500` the stored bundle could not be decrypted; `503`
                the dispatch store is unreachable.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        job = human_owned_job(state, job_id, principal.org_id)
        try:
            blob = state.worker_dispatch_store.read_upload(job.id, org_id=principal.org_id)
        except DispatchStoreUnavailableError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        if blob is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail=f"no bundle for job {job_id}: it was never uploaded, or it has expired",
            )

        try:
            payload = decrypt_bytes(blob, secret=state.bundle_encryption_secret)
        except BundleDecryptionError as exc:
            _logger.error(  # noqa: TRY400 - the traceback adds nothing; the cause is configuration
                "worker_bundle_decrypt_failed", extra={"job_id": job_id, "error": str(exc)}
            )
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "the stored bundle could not be decrypted; "
                    "WORKER_BUNDLE_ENCRYPTION_SECRET is missing or differs from the "
                    "value in force when this bundle was uploaded"
                ),
            ) from exc

        _logger.info(
            "worker_bundle_downloaded",
            extra={"job_id": job_id, "org": principal.org_id, "bytes": len(payload)},
        )
        return StreamingResponse(
            _stream_bundle(payload),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{job_id}-bundle.zip"',
                "Content-Length": str(len(payload)),
            },
        )

    return router


def human_owned_job(state: ApiState, job_id: str, org_id: str) -> WorkerJob:
    """Read a job for a human caller, org-scoped. No worker pinning.

    Distinct from `worker_route_helpers.owned_job`, which additionally
    requires the caller to be the one worker the job is pinned to — correct
    for a daemon reporting an outcome, wrong for an operator reading their
    own org's queue.

    Raises:
        HTTPException: `404` unknown job; `403` another org's job; `503` the
            dispatch store is unreachable.
    """
    try:
        job = state.worker_dispatch_store.get_job(job_id)
    except WorkerJobNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no job {job_id}") from exc
    except DispatchStoreUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    org_scoped_or_404(record=job, record_id=job_id, org_id=org_id, kind="worker_job")
    return job


def _new_worker_id() -> str:
    """A short, URL-safe, `_IDENTIFIER_PATTERN`-shaped worker id."""
    return f"wkr-{uuid.uuid4().hex[:20]}"
