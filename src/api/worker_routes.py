"""HTTP surface for ADR 0015's cloud <-> desktop-worker dispatch.

A separate router from `server.py`, matching `deliverables_routes.py`'s and
`auth.py`'s own reasoning: that module is already well past this project's
400-line target, and a router built from `ApiState` rather than importing
`server.py` keeps the dependency one-way.

Every route here does exactly one of the things ADR 0015's binding
conditions require, and no more:

* `POST /workers`, `GET /workers` — worker registration/listing. Human-
  authenticated (`require_principal`); a worker's long-lived credential is
  shown exactly once, in the registration response (condition 2).
* `POST /workers/{worker_id}/dispatch/preview`,
  `POST /workers/{worker_id}/dispatch` — gate (a), the cloud-side
  preview/confirm exchange, additionally bound to `worker_id` (condition
  3(a)). Human-authenticated; nothing is queued until confirm succeeds.
* `GET /workers/dispatch/poll` — worker-authenticated
  (`require_worker_principal`). Claims the oldest queued job pinned to
  *this* worker and mints gate (b)'s signed assignment (condition 3(b)).
  Never accepts a `worker_id` the request claims — the authenticated
  principal is the only source of that value (condition 2's IDOR rule).
* `POST /workers/jobs/{job_id}/upload`, `POST /workers/jobs/{job_id}/failed`
  — worker-authenticated job outcome reporting. The upload path validates,
  allow-lists, size-caps, and encrypts before it ever reaches storage
  (condition 9, condition 11).
* `GET /workers/jobs`, `GET /workers/jobs/{job_id}` — human-authenticated,
  org-scoped read access to the job queue, for operability without a
  dashboard (explicitly out of scope this cycle).

No circuit breaker on this router's own outbound behaviour is needed — it
has none; every failure mode here is either a `DispatchStoreUnavailableError`
(mapped to `503`, never a silent approval — condition 5) or a `4xx` the
caller can act on.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from typing import TYPE_CHECKING

from fastapi import APIRouter, Header, HTTPException, Request, status

from src.api.auth import org_scoped_or_404, require_principal, require_worker_principal
from src.api.worker_schemas import (
    DispatchConfirmRequest,
    DispatchPreviewRequest,
    DispatchPreviewResponse,
    PollResponse,
    WorkerFailureReport,
    WorkerJobAccepted,
    WorkerJobListView,
    WorkerJobView,
    WorkerListView,
    WorkerRegisterRequest,
    WorkerRegisterResponse,
    WorkerSummary,
)
from src.core.auth import hash_password
from src.core.config import get_settings
from src.core.errors import UnsafeUrlError
from src.core.logger import get_logger
from src.core.worker_auth import Worker, WorkerNotFoundError, mint_worker_secret
from src.core.worker_bundle_crypto import encrypt_bytes
from src.core.worker_dispatch_schemas import WorkerJob
from src.core.worker_dispatch_signing import issue_dispatch_assignment
from src.core.worker_dispatch_store import DispatchStoreUnavailableError, WorkerJobNotFoundError
from src.modules.seo.screaming_frog_control.upload_manifest import (
    BundleUploadError,
    validate_and_extract_bundle,
)

if TYPE_CHECKING:
    from src.api.server import ApiState

__all__ = ["build_worker_router"]

_logger = get_logger("api.worker_routes")


def _to_view(job: WorkerJob) -> WorkerJobView:
    """Map a persisted `WorkerJob` onto its HTTP view."""
    return WorkerJobView.model_validate(job, from_attributes=True)


def build_worker_router(state: ApiState) -> APIRouter:  # noqa: C901 - route count, not complexity
    """Build every ADR 0015 worker-dispatch route over `state`."""
    router = APIRouter()

    @router.post(
        "/workers", response_model=WorkerRegisterResponse, status_code=status.HTTP_201_CREATED
    )
    def register_worker(
        payload: WorkerRegisterRequest, authorization: str | None = Header(default=None)
    ) -> WorkerRegisterResponse:
        """Register a new desktop worker for the caller's own org.

        Raises:
            HTTPException: `401` if the session token is missing/invalid.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        secret = mint_worker_secret()
        worker = Worker(
            worker_id=_new_worker_id(),
            org_id=principal.org_id,
            secret_hash=_hash_worker_secret(secret),
            display_name=payload.display_name,
        )
        state.worker_store.create(worker)
        return WorkerRegisterResponse(
            worker_id=worker.worker_id, worker_secret=secret, org_id=worker.org_id
        )

    @router.get("/workers", response_model=WorkerListView)
    def list_workers(authorization: str | None = Header(default=None)) -> WorkerListView:
        """Every worker registered for the caller's org."""
        principal = require_principal(authorization, session_secret=state.session_secret)
        workers = state.worker_store.list_workers(principal.org_id)
        return WorkerListView(
            workers=[WorkerSummary.model_validate(w, from_attributes=True) for w in workers]
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
        worker = _owned_worker(state, worker_id, principal.org_id)
        safe_url = _validate_seed_url(state, payload.seed_url)

        token = state.worker_dispatch_store.mint_dispatch_preview(
            org_id=principal.org_id,
            worker_id=worker.worker_id,
            seed_url=safe_url,
            template_name=payload.template_name,
            correlation_id=payload.correlation_id,
            ttl_s=get_settings().worker_dispatch_preview_ttl_s,
        )
        return DispatchPreviewResponse(
            token=token.token,
            expires_at=token.expires_at,
            worker_id=worker.worker_id,
            seed_url=safe_url,
            template_name=payload.template_name,
            correlation_id=payload.correlation_id,
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
                invalid/expired/already used; `400` an unsafe URL; `503`
                the dispatch store is unreachable (fail closed — condition
                5's "approval silently fails, nothing runs").
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        worker = _owned_worker(state, worker_id, principal.org_id)
        safe_url = _validate_seed_url(state, payload.seed_url)

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

    @router.get("/workers/dispatch/poll", response_model=PollResponse)
    def poll_for_job(authorization: str | None = Header(default=None)) -> PollResponse:
        """A worker daemon's poll: claim its own oldest queued job, if any.

        `worker_id`/`org_id` come only from the verified credential
        (condition 2) — nothing in this request can name a different
        worker's queue.

        Raises:
            HTTPException: `401` unauthenticated; `503` the dispatch store
                is unreachable.
        """
        principal = require_worker_principal(authorization, worker_store=state.worker_store)
        try:
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
            ttl_s=get_settings().worker_dispatch_assignment_ttl_s,
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

        Raises:
            HTTPException: `401` unauthenticated; `404` unknown job; `403`
                a job belonging to a different worker or org (condition 2's
                IDOR rule, applied to the upload path); `400` the body is
                empty, over the size cap, or fails bundle validation
                (condition 9); `503` the dispatch store is unreachable.
        """
        principal = require_worker_principal(authorization, worker_store=state.worker_store)
        job = _owned_job(state, job_id, principal.worker_id, principal.org_id)

        body = await request.body()
        max_bytes = get_settings().worker_upload_max_bytes
        if not body:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="empty upload body")
        if len(body) > max_bytes:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"upload is over the {max_bytes // (1024 * 1024)} MB limit",
            )

        try:
            members = validate_and_extract_bundle(body, max_total_bytes=max_bytes)
        except BundleUploadError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        rebuilt = _rebuild_zip(members)
        encrypted = encrypt_bytes(rebuilt, secret=state.bundle_encryption_secret)
        try:
            state.worker_dispatch_store.store_upload(
                job.id,
                org_id=principal.org_id,
                worker_id=principal.worker_id,
                encrypted_bytes=encrypted,
                retention_days=get_settings().worker_bundle_retention_days,
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
        job = _owned_job(state, job_id, principal.worker_id, principal.org_id)
        try:
            updated = state.worker_dispatch_store.mark_failed(job.id, payload.error)
        except DispatchStoreUnavailableError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        return WorkerJobAccepted(id=updated.id, status=updated.status.value)

    @router.get("/workers/jobs", response_model=WorkerJobListView)
    def list_worker_jobs(authorization: str | None = Header(default=None)) -> WorkerJobListView:
        """Every dispatch job for the caller's org."""
        principal = require_principal(authorization, session_secret=state.session_secret)
        try:
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
        try:
            job = state.worker_dispatch_store.get_job(job_id)
        except WorkerJobNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no job {job_id}") from exc
        except DispatchStoreUnavailableError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        org_scoped_or_404(record=job, record_id=job_id, org_id=principal.org_id, kind="worker_job")
        return _to_view(job)

    return router


def _new_worker_id() -> str:
    """A short, URL-safe, `_IDENTIFIER_PATTERN`-shaped worker id."""
    return f"wkr-{uuid.uuid4().hex[:20]}"


def _hash_worker_secret(secret: str) -> str:
    return hash_password(secret)


def _owned_worker(state: ApiState, worker_id: str, org_id: str) -> Worker:
    """Look up a worker by id and confirm this org owns it.

    Raises:
        HTTPException: `404` unknown worker; `403` another org's worker.
    """
    try:
        worker = state.worker_store.get(worker_id)
    except WorkerNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no worker {worker_id}") from exc
    org_scoped_or_404(record=worker, record_id=worker_id, org_id=org_id, kind="worker")
    return worker


def _owned_job(state: ApiState, job_id: str, worker_id: str, org_id: str) -> WorkerJob:
    """Look up a job and confirm *this exact worker* owns it.

    ADR 0015 condition 2's IDOR rule, applied to the job outcome routes:
    org-scoping alone is not enough here, because two workers can share an
    org — a job pinned to worker A must be unclaimable, unreportable, and
    un-uploadable-to by worker B even inside the same organization
    (condition 6: pinned to one worker, never round-robined).

    Raises:
        HTTPException: `404` unknown job; `403` a job owned by a different
            org or a different worker.
    """
    try:
        job = state.worker_dispatch_store.get_job(job_id)
    except WorkerJobNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no job {job_id}") from exc
    org_scoped_or_404(record=job, record_id=job_id, org_id=org_id, kind="worker_job")
    if job.worker_id != worker_id:
        _logger.warning(
            "worker_job_access_denied_worker_mismatch",
            extra={"job_id": job_id, "claiming_worker": worker_id, "owning_worker": job.worker_id},
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="access denied")
    return job


def _validate_seed_url(state: ApiState, seed_url: str) -> str:
    """Admission-time `UrlSafetyPolicy` check, mirroring `server.py`'s own.

    Raises:
        HTTPException: `400` on an unsafe URL.
    """
    try:
        return state.url_policy.validate(seed_url).url
    except UnsafeUrlError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _rebuild_zip(members: dict[str, bytes]) -> bytes:
    """Repackage validated members into a fresh zip — never the caller's own bytes.

    Nothing downstream of `validate_and_extract_bundle` should ever handle
    the attacker-controlled archive again, even one that passed validation:
    a fresh archive built only from the extracted, allow-listed bytes is
    what gets encrypted and stored.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(members.items()):
            archive.writestr(name, data)
    return buffer.getvalue()
