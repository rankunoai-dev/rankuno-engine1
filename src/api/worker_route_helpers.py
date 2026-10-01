"""Ownership, identity and body-handling helpers for the worker routes.

Split out of `worker_routes.py` when the bundle-download, heartbeat and
per-worker-template routes pushed that module past this codebase's 400-line
target — the same reasoning `worker_schemas.py` already records for pulling
the wire models out of it. Nothing here is a route; everything here is a
check a route performs before it does anything else.

The security-relevant functions are `_owned_worker`/`_owned_job` (renamed
`owned_worker`/`owned_job` on the way out of the private namespace) and
`read_capped_body`. All three are shared rather than copied, because the
failure mode these guard against is exactly the one ADR 0016 condition 2
retrofitted across fourteen routes: an ownership rule implemented per-route
drifts per-route.
"""

from __future__ import annotations

import io
import zipfile
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request, status

from src.api.auth import org_scoped_or_404
from src.api.worker_schemas import WorkerSummary
from src.core.errors import UnsafeUrlError
from src.core.logger import get_logger
from src.core.worker_auth import (
    Worker,
    WorkerNotFoundError,
    WorkerStoreUnavailableError,
    worker_is_online,
)
from src.core.worker_dispatch_schemas import WorkerJob
from src.core.worker_dispatch_store import WorkerJobNotFoundError
from src.modules.seo.screaming_frog_control.license_check import FREE_TIER_URL_CEILING

if TYPE_CHECKING:
    from src.api.server import ApiState

__all__ = [
    "owned_job",
    "owned_worker",
    "read_capped_body",
    "rebuild_zip",
    "screaming_frog_busy",
    "shortfall_note",
    "summarise_worker",
    "validate_seed_url",
    "worker_store_unavailable",
]

_logger = get_logger("api.worker_route_helpers")

_HTTP_CONTENT_TOO_LARGE = 413
"""Spelled as an integer rather than `status.HTTP_413_*`: Starlette renamed
that constant (`REQUEST_ENTITY_TOO_LARGE` -> `CONTENT_TOO_LARGE`) and emits a
deprecation warning for the old name, so either spelling pins this module to
one Starlette version. The number has not changed since RFC 2068."""


def worker_store_unavailable(exc: WorkerStoreUnavailableError) -> HTTPException:
    """Map an unreachable identity store onto `503`, never `401`.

    A `401` here would tell a correctly configured daemon that its
    credential had been revoked, and a daemon that believes that stops on
    purpose. A `503` is what makes it back off and return.
    """
    _logger.error("worker_store_unavailable", extra={"error": str(exc)})
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"worker store unavailable: {exc}"
    )


def owned_worker(state: ApiState, worker_id: str, org_id: str) -> Worker:
    """Look up a worker by id and confirm this org owns it.

    Raises:
        HTTPException: `404` unknown worker; `403` another org's worker;
            `503` the worker store is unreachable.
    """
    try:
        worker = state.worker_store.get(worker_id)
    except WorkerNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no worker {worker_id}") from exc
    except WorkerStoreUnavailableError as exc:
        raise worker_store_unavailable(exc) from exc
    org_scoped_or_404(record=worker, record_id=worker_id, org_id=org_id, kind="worker")
    return worker


def summarise_worker(worker: Worker, *, offline_after_s: float) -> WorkerSummary:
    """Map a `Worker` onto its HTTP view, adding the server's liveness verdict.

    Shared by the list route and the revoke route so both describe a worker
    identically; never includes `secret_hash`.
    """
    return WorkerSummary(
        worker_id=worker.worker_id,
        org_id=worker.org_id,
        display_name=worker.display_name,
        is_active=worker.is_active,
        created_at=worker.created_at,
        last_seen_at=worker.last_seen_at,
        is_online=worker_is_online(worker, offline_after_s=offline_after_s),
        templates=list(worker.templates),
        unrecognised_template_count=worker.unrecognised_template_count,
    )


def owned_job(state: ApiState, job_id: str, worker_id: str, org_id: str) -> WorkerJob:
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


def screaming_frog_busy(state: ApiState, active: WorkerJob) -> HTTPException:
    """Refuse a second dispatch while one is in flight, and say what is running.

    The `seo.screaming_frog` facet is capped at `max_concurrent = 1`, and the
    cap is not conservatism: Screaming Frog appends to a `trace.txt` shared by
    every invocation on the workstation, and the offset-scoped licence read
    this engine depends on is only correct while exactly one supervised
    process is writing to it (`license_check`'s module docstring). Two
    concurrent crawls would not merely queue badly — they would make the
    licence verdict wrong for both.

    A bare `429` would say none of that. This names the cap, the reason, and
    the specific job the operator is waiting on, because the only useful next
    action is "wait for that one, or cancel it".
    """
    facet = state.facet_router.get_facet_config("seo.screaming_frog")
    started = "not started yet" if active.dispatched_at is None else "already running"
    _logger.warning(
        "worker_dispatch_refused_busy",
        extra={"worker_id": active.worker_id, "active_job_id": active.id},
    )
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail=(
            f"Screaming Frog runs {facet.max_concurrent} crawl at a time on a worker, "
            f"because its licence log is shared across every invocation on that machine. "
            f"Job {active.id} ({active.envelope.seed_url}) is {started} and is "
            f"'{active.status.value}'. Wait for it to finish, then dispatch again."
        ),
    )


def shortfall_note(*, expected: int, crawled: int) -> str:
    """Explain a list-mode run that crawled fewer pages than it was given.

    Two different findings share one symptom, and an operator has to act on
    them differently, so they must not collapse into one sentence:

    * `crawled` landing exactly on Screaming Frog's 500-URL free-tier ceiling
      while more than 500 were supplied is the licence, not the site. It is
      the first time this system can say so — before a known list length,
      "exactly 500" was indistinguishable from a real 500-page job
      (`license_check.FREE_TIER_URL_CEILING`).
    * Any other shortfall is pages that were supplied and not fetched:
      redirects collapsed, hosts that stopped answering, a run that was cut
      short. Worth investigating, but not a licence problem.

    Returns an empty string when nothing is missing, so a caller can render
    the field's presence as "there is something to say here".
    """
    missing = expected - crawled
    if missing <= 0:
        return ""
    if crawled == FREE_TIER_URL_CEILING:
        return (
            f"This run was given {expected:,} URLs and crawled {crawled:,} — exactly "
            f"Screaming Frog's free-tier ceiling. That is the licence expiring, not the "
            f"site: the crawl keeps running and is silently capped. Check the licence on "
            f"the worker machine and run this again."
        )
    return (
        f"This run was given {expected:,} URLs and crawled {crawled:,}; {missing:,} were "
        f"not fetched. The export is real but incomplete — the missing URLs may have "
        f"redirected, stopped responding, or the run may have been cut short."
    )


def validate_seed_url(state: ApiState, seed_url: str) -> str:
    """Admission-time `UrlSafetyPolicy` check, mirroring `server.py`'s own.

    Raises:
        HTTPException: `400` on an unsafe URL.
    """
    try:
        return state.url_policy.validate(seed_url).url
    except UnsafeUrlError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


async def read_capped_body(request: Request, *, max_bytes: int) -> bytes:
    """Read the request body, refusing anything over `max_bytes`.

    Two checks, because either alone is insufficient:

    1. A declared `Content-Length` over the cap is refused before a single
       byte of the body is read. This is the one that matters for the
       honest-but-oversized client — a 400 MB bundle is rejected in one
       round trip instead of after 400 MB has been received and buffered.
    2. The stream is then read chunk by chunk and abandoned the moment the
       running total crosses the cap, because `Content-Length` is absent on
       a chunked request and is in any case a claim, not a fact. A cap
       enforced only after `await request.body()` has already materialised
       the whole thing in memory is not a cap.

    Raises:
        HTTPException: `413` if either check trips. The message names the
            limit, so an operator seeing it knows what to change.
    """
    limit_mb = max_bytes / (1024 * 1024)
    detail = f"upload exceeds the {limit_mb:.0f} MB limit"

    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > max_bytes:
        _logger.warning("worker_upload_rejected_content_length", extra={"declared": declared})
        raise HTTPException(_HTTP_CONTENT_TOO_LARGE, detail=detail)

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            _logger.warning("worker_upload_rejected_oversize_stream", extra={"read": total})
            raise HTTPException(_HTTP_CONTENT_TOO_LARGE, detail=detail)
        chunks.append(chunk)
    return b"".join(chunks)


def rebuild_zip(members: dict[str, bytes]) -> bytes:
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
