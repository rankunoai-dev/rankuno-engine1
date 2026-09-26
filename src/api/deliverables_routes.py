"""HTTP surface for building and downloading client deliverable workbooks.

Closes the gap `scripts/build_deliverable.py` left open: everything that
script does - load a source, apply a rulebook, score, render a workbook - was
reachable only from a terminal. This module wires the same
`run_deliverable_pipeline` an operator would call by hand onto the local API
server, so it can be triggered and downloaded from the browser.

A separate file from `src/api/server.py`, not more routes bolted onto it: that
module is already well past this project's 400-line target, and a router
built from `ApiState` rather than importing it keeps the dependency one-way -
`server.py` imports `build_deliverables_router`, this module never imports
`server.py` (only its `ApiState` *type*, under `TYPE_CHECKING`, so the two
modules cannot form an import cycle).

Two things carry the actual risk here (Step 5 audit, cycle 0087) and both are
non-negotiable:

* **Org-scoping.** `AuditDataset` and everything under `deliverables/` has no
  concept of an owner. Every record this module creates carries the caller's
  `org_id`, and every read, status check or download enforces it with the
  same shape `get_job`/`get_result` already use in `server.py` - not a new
  invention, the same `record.org_id != org_id -> 403` after a `404` for "no
  such record at all".
* **Nothing blocks a request handler on `build_workbook`.** Measured up to
  26.3s at the 500k-page ceiling. Every build-triggering endpoint here creates
  a job, reserves a slot in `ApiState`'s own (crawl-independent) concurrency
  guard, dispatches the real work to a worker thread with `asyncio.to_thread`,
  and returns `202` immediately - the same shape `server.py` already uses for
  a crawl, applied to a different resource.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Final
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from pydantic import Field, ValidationError

from src.api.auth import org_scoped_or_404, require_principal
from src.api.worker_dashboard_routes import human_owned_job
from src.core.logger import get_logger
from src.core.schemas import StrictModel
from src.core.state_store import JobNotFoundError, JobRecord
from src.core.worker_bundle_crypto import BundleDecryptionError, decrypt_bytes
from src.core.worker_dispatch_schemas import WorkerJob
from src.core.worker_dispatch_store import DispatchStoreUnavailableError
from src.modules.seo.contracts.audit import AuditDataset
from src.modules.seo.deliverables.build_runner import run_build
from src.modules.seo.deliverables.masterfile_source import (
    MasterfileSource,
    source_for_bundle_bytes,
)
from src.modules.seo.deliverables.rulebook import RulebookError
from src.modules.seo.deliverables.rulebook_store import (
    MAX_RULEBOOK_LABEL_LENGTH,
    RulebookNotFoundError,
    RulebookRecord,
)
from src.modules.seo.deliverables.screaming_frog_adapter import load_screaming_frog_bundle
from src.modules.seo.page_classifier.audit_export import to_audit_dataset
from src.modules.seo.page_classifier.tool import PageClassificationOutput
from src.modules.seo.page_classifier.url_rules import normalize_url

if TYPE_CHECKING:
    from src.api.server import ApiState

__all__ = ["build_deliverables_router"]

_logger = get_logger("api.deliverables")

_XLSX_MEDIA_TYPE: Final[str] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DELIVERABLE_TOOL_NAME: Final[str] = "seo.deliverables.workbook"
DELIVERABLE_FACET_ID: Final[str] = "seo.deliverables"

MAX_RULEBOOK_UPLOAD_BYTES: Final[int] = 5 * 1024 * 1024
"""Rulebooks are pattern spreadsheets an operator authors, not crawl output."""

MAX_SCREAMING_FROG_BUNDLE_BYTES: Final[int] = 200 * 1024 * 1024
"""Compressed upload ceiling. `_bundle.py` bounds *decompressed* bytes (8 GiB)
separately once the zip is open; this bounds what a single request body may
cost before that guard ever runs."""


class DeliverableAccepted(StrictModel):
    """What a build-triggering endpoint returns: an id to poll, not a file."""

    id: str
    status: str
    label: str = ""


class DeliverableBuildRequest(StrictModel):
    """Optional theming input for a workbook built from an existing crawl."""

    rulebook_id: str | None = Field(
        default=None,
        description="Id of a previously uploaded rulebook to theme pages with. "
        "Omitted means no theming, matching `build_deliverable.py` without --rulebook.",
    )


def _resolve_rulebook(state: ApiState, rulebook_id: str | None, org_id: str) -> Path | None:
    """Look up an org-owned rulebook by id, or return `None` for "no theming".

    Raises:
        HTTPException: `404` if unknown, `403` if another org owns it.
    """
    if rulebook_id is None:
        return None
    try:
        record = state.rulebook_store.get(rulebook_id)
    except RulebookNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no rulebook {rulebook_id}") from exc
    org_scoped_or_404(record=record, record_id=rulebook_id, org_id=org_id, kind="rulebook")
    return state.rulebook_store.path_for(rulebook_id)


async def _dispatch_build(
    state: ApiState,
    deliverable_id: str,
    dataset_loader: Callable[[], AuditDataset],
    rulebook_path: Path | None,
    source: str,
    cleanup: Callable[[], None] | None,
) -> None:
    """Run a build on a worker thread, then always release its slot and cleanup."""
    try:
        await asyncio.to_thread(
            run_build,
            state.deliverable_store,
            deliverable_id,
            dataset_loader,
            normalize_url,
            rulebook_path,
            source,
        )
    finally:
        state.release_deliverable(deliverable_id)
        if cleanup is not None:
            cleanup()


def _start_build(
    state: ApiState,
    org_id: str,
    *,
    dataset_loader: Callable[[], AuditDataset],
    rulebook_path: Path | None,
    source: str,
    label: str,
    request: Mapping[str, object],
    cleanup: Callable[[], None] | None = None,
) -> DeliverableAccepted:
    """Admit a build, reserve a slot, and dispatch it.

    Mirrors `server.py`'s `_start`: capacity is claimed against a provisional
    id *before* a record exists, so a refusal never leaves a permanent
    `FAILED` row behind, and is re-keyed once the store mints the real id.

    Raises:
        HTTPException: `429` if the deliverable concurrency guard is saturated.
    """
    pending = f"pending:{uuid4().hex}"
    if not state.try_reserve_deliverable(pending):
        if cleanup is not None:
            cleanup()
        _logger.warning("deliverable_rejected_saturation", extra={"org": org_id})
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"deliverable builds are at capacity "
                f"({state.max_concurrent_deliverables} concurrent); please retry in a moment"
            ),
        )
    try:
        record = state.deliverable_store.create(
            DELIVERABLE_TOOL_NAME,
            dict(request),
            label=label,
            facet_id=DELIVERABLE_FACET_ID,
            org_id=org_id,
        )
    except Exception:
        # The store failed, so there is no job and nothing will ever release
        # this slot or run the cleanup.
        state.release_deliverable(pending)
        if cleanup is not None:
            cleanup()
        raise
    state.rekey_deliverable(pending, record.id)
    state.track(
        asyncio.create_task(
            _dispatch_build(state, record.id, dataset_loader, rulebook_path, source, cleanup)
        )
    )
    return DeliverableAccepted(id=record.id, status=record.status.value, label=record.label)


def build_deliverables_router(state: ApiState) -> APIRouter:
    """Build the `/deliverables` and `/jobs/{id}/deliverable` routes over `state`.

    A factory, matching `create_app`'s own stance: the routes close over
    `state` rather than receiving it through `Depends`, for the reason
    `server.py` documents at its own route definitions - `from __future__
    import annotations` turns every annotation into a string FastAPI resolves
    against the *module* namespace, where a factory-local alias is invisible.
    """
    router = APIRouter()

    @router.post(
        "/deliverables/rulebooks",
        response_model=RulebookRecord,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_rulebook(
        request: Request,
        label: str = Query(default="", max_length=MAX_RULEBOOK_LABEL_LENGTH),
        authorization: str | None = Header(default=None),
    ) -> RulebookRecord:
        """Store a client's URL-pattern rulebook `.xlsx` for reuse across builds.

        The body is the raw `.xlsx`, sent as `application/octet-stream` - the
        same reasoning `server.py` gives at `upload_gsc`: FastAPI's file
        upload needs `python-multipart`, which is not a dependency here.

        Raises:
            HTTPException: `400` if the body is empty, oversized, or not a
                readable rulebook workbook.
        """
        org_id = require_principal(authorization, session_secret=state.session_secret).org_id
        body = await request.body()
        if not body.strip():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="empty body: POST the rulebook .xlsx as the request body",
            )
        if len(body) > MAX_RULEBOOK_UPLOAD_BYTES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"upload is over the {MAX_RULEBOOK_UPLOAD_BYTES // (1024 * 1024)} MB limit",
            )
        try:
            record = state.rulebook_store.create(org_id, label, body)
        except RulebookError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return record

    @router.get("/deliverables/rulebooks", response_model=list[RulebookRecord])
    def list_rulebooks(authorization: str | None = Header(default=None)) -> list[RulebookRecord]:
        """Every rulebook this organization uploaded, newest first."""
        org_id = require_principal(authorization, session_secret=state.session_secret).org_id
        return [r for r in state.rulebook_store.list_all() if r.org_id == org_id]

    @router.delete("/deliverables/rulebooks/{rulebook_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_rulebook(
        rulebook_id: str, authorization: str | None = Header(default=None)
    ) -> Response:
        """Remove an uploaded rulebook.

        Raises:
            HTTPException: `404` if unknown, `403` if another org owns it.
        """
        org_id = require_principal(authorization, session_secret=state.session_secret).org_id
        try:
            record = state.rulebook_store.get(rulebook_id)
        except RulebookNotFoundError as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail=f"no rulebook {rulebook_id}"
            ) from exc
        org_scoped_or_404(record=record, record_id=rulebook_id, org_id=org_id, kind="rulebook")
        state.rulebook_store.delete(rulebook_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/jobs/{job_id}/deliverable",
        response_model=DeliverableAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def build_from_job(
        job_id: str,
        payload: DeliverableBuildRequest | None = None,
        authorization: str | None = Header(default=None),
    ) -> DeliverableAccepted:
        """Build a workbook from an already-finished crawl job.

        `202`, never `200`: nothing has been built when this returns - the
        same contract `POST /jobs` uses for a crawl, for the same reason
        (`build_workbook` alone measures up to 26.3s at the page ceiling).

        Raises:
            HTTPException: `404` if the source job is unknown, `403` if
                another org owns it, `409` if it has not finished or its
                result predates the current output contract, `429` if the
                deliverable concurrency guard is saturated.
        """
        org_id = require_principal(authorization, session_secret=state.session_secret).org_id
        body = payload if payload is not None else DeliverableBuildRequest()
        try:
            crawl_record = state.store.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no job {job_id}") from exc
        org_scoped_or_404(record=crawl_record, record_id=job_id, org_id=org_id, kind="deliverable")
        if not crawl_record.has_result:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"job {job_id} is {crawl_record.status.value} and has no result",
            )

        rulebook_path = _resolve_rulebook(state, body.rulebook_id, org_id)

        stored = state.store.read_result(job_id)
        try:
            crawl_output = PageClassificationOutput.model_validate(stored)
        except ValidationError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="this job's result predates the current output contract",
            ) from exc

        return _start_build(
            state,
            org_id,
            dataset_loader=lambda: to_audit_dataset(crawl_output.pages, produced_at=None),
            rulebook_path=rulebook_path,
            source="engine",
            label=f"{crawl_output.base_url} workbook",
            request={
                "source": "engine",
                "source_job_id": job_id,
                "rulebook_id": body.rulebook_id,
            },
        )

    @router.post(
        "/deliverables/from-screaming-frog",
        response_model=DeliverableAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def build_from_screaming_frog(
        request: Request,
        rulebook_id: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
    ) -> DeliverableAccepted:
        """Build a workbook from an uploaded Screaming Frog export bundle.

        The body is the raw bundle - a zip of the export directory, the same
        thing `scripts/build_deliverable.py sf-bundle` reads from disk - sent
        as `application/zip`, not `multipart/form-data`, for the reason every
        other upload endpoint in this API gives.

        Parsing and building both happen on the worker thread, never in this
        handler: a large export's own parse time is added to the measured
        `build_workbook` cost, and neither may block the event loop.

        Raises:
            HTTPException: `400` if the body is empty or oversized, `429` if
                the deliverable concurrency guard is saturated.
        """
        org_id = require_principal(authorization, session_secret=state.session_secret).org_id
        body = await request.body()
        if not body.strip():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="empty body: POST the Screaming Frog export bundle (zip) as the request "
                "body",
            )
        if len(body) > MAX_SCREAMING_FROG_BUNDLE_BYTES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"upload is over the "
                    f"{MAX_SCREAMING_FROG_BUNDLE_BYTES // (1024 * 1024)} MB limit"
                ),
            )

        rulebook_path = _resolve_rulebook(state, rulebook_id, org_id)

        # Saved to a temp file inside the deliverable store's own root: the
        # bundle must survive past this handler's return for the worker
        # thread to read, and `open_bundle` needs a real path, not bytes.
        handle, tmp_name = tempfile.mkstemp(
            dir=str(state.deliverable_store.root), suffix=".sfbundle.tmp"
        )
        bundle_path = Path(tmp_name)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(body)
        except BaseException:
            bundle_path.unlink(missing_ok=True)
            raise

        try:
            return _start_build(
                state,
                org_id,
                dataset_loader=lambda: load_screaming_frog_bundle(
                    bundle_path, normalize=normalize_url
                ),
                rulebook_path=rulebook_path,
                source="screaming_frog",
                label="Screaming Frog workbook",
                request={"source": "screaming_frog", "rulebook_id": rulebook_id},
                cleanup=lambda: bundle_path.unlink(missing_ok=True),
            )
        except HTTPException:
            bundle_path.unlink(missing_ok=True)
            raise

    @router.get("/deliverables", response_model=list[JobRecord])
    def list_deliverables(authorization: str | None = Header(default=None)) -> list[JobRecord]:
        """Every deliverable build for the organization, newest first."""
        org_id = require_principal(authorization, session_secret=state.session_secret).org_id
        return [r for r in state.deliverable_store.list_jobs() if r.org_id == org_id]

    @router.get("/deliverables/{deliverable_id}", response_model=JobRecord)
    def get_deliverable(
        deliverable_id: str, authorization: str | None = Header(default=None)
    ) -> JobRecord:
        """One deliverable build's status.

        Raises:
            HTTPException: `404` if unknown, `403` if another org owns it.
        """
        org_id = require_principal(authorization, session_secret=state.session_secret).org_id
        try:
            record = state.deliverable_store.get(deliverable_id)
        except JobNotFoundError as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail=f"no deliverable {deliverable_id}"
            ) from exc
        org_scoped_or_404(
            record=record, record_id=deliverable_id, org_id=org_id, kind="deliverable"
        )
        return record

    @router.get("/deliverables/{deliverable_id}/download")
    def download_deliverable(
        deliverable_id: str, authorization: str | None = Header(default=None)
    ) -> Response:
        """The finished workbook.

        The path-containment check mirrors `_bundle.py`'s
        `_DirectoryBundle.open_text`: a symlink is refused outright, and the
        candidate must resolve to a direct child of the deliverable's own
        output directory. `filename` comes from this deliverable's own stored
        result, itself built from `AuditDataset.site` - already hostname-
        validated - so this is defence in depth, not a live attack this
        record can currently produce.

        Raises:
            HTTPException: `404` if unknown or the file is missing, `403` if
                another org owns it, `409` if the build has not finished.
        """
        org_id = require_principal(authorization, session_secret=state.session_secret).org_id
        try:
            record = state.deliverable_store.get(deliverable_id)
        except JobNotFoundError as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail=f"no deliverable {deliverable_id}"
            ) from exc
        org_scoped_or_404(
            record=record, record_id=deliverable_id, org_id=org_id, kind="deliverable"
        )
        if not record.has_result:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"deliverable {deliverable_id} is {record.status.value} and has no file",
            )

        result = state.deliverable_store.read_result(deliverable_id)
        filename = str(result.get("filename") or "")
        job_dir = (state.deliverable_store.root / deliverable_id).resolve()
        candidate = job_dir / filename
        escapes = not filename or candidate.is_symlink() or candidate.resolve().parent != job_dir
        if escapes or not candidate.is_file():
            _logger.error("deliverable_file_missing", extra={"deliverable_id": deliverable_id})
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail=f"deliverable {deliverable_id} has no stored file"
            )

        return Response(
            content=candidate.read_bytes(),
            media_type=_XLSX_MEDIA_TYPE,
            headers={"Content-Disposition": f'attachment; filename="{candidate.name}"'},
        )

    async def _dispatch_masterfile(
        state: ApiState,
        deliverable_id: str,
        job_id: str,
        service_slug: str,
        source_factory: Callable[[], MasterfileSource],
        rulebook_path: Path | None,
    ) -> None:
        """Run a masterfile build on a worker thread, then always release its slot."""
        from src.modules.seo.deliverables.build_runner import run_masterfile

        try:
            await asyncio.to_thread(
                run_masterfile,
                state.deliverable_store,
                deliverable_id,
                job_id,
                service_slug,
                source_factory,
                rulebook_path,
            )
        finally:
            state.release_deliverable(deliverable_id)

    def _start_masterfile(
        state: ApiState,
        org_id: str,
        *,
        job_id: str,
        service_slug: str,
        source_factory: Callable[[], MasterfileSource],
        label: str,
    ) -> DeliverableAccepted:
        """Admit a masterfile build, reserve a slot, and dispatch it.

        The same admission sequence `_start_build` documents - a provisional
        id claimed before a record exists, re-keyed once the store mints the
        real one - so a refusal never leaves a permanent `FAILED` row behind.

        Raises:
            HTTPException: `429` if the deliverable concurrency guard is
                saturated.
        """
        pending = f"pending:{uuid4().hex}"
        if not state.try_reserve_deliverable(pending):
            _logger.warning("masterfile_rejected_saturation", extra={"org": org_id})
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"deliverable builds are at capacity "
                    f"({state.max_concurrent_deliverables} concurrent); please retry in a moment"
                ),
            )
        try:
            record = state.deliverable_store.create(
                DELIVERABLE_TOOL_NAME,
                {
                    "source": "masterfile",
                    "source_job_id": job_id,
                    "service_slug": service_slug,
                },
                label=label,
                facet_id=DELIVERABLE_FACET_ID,
                org_id=org_id,
            )
        except Exception:
            # The store failed, so there is no job and nothing will ever
            # release this slot.
            state.release_deliverable(pending)
            raise
        state.rekey_deliverable(pending, record.id)
        state.track(
            asyncio.create_task(
                _dispatch_masterfile(state, record.id, job_id, service_slug, source_factory, None)
            )
        )
        return DeliverableAccepted(id=record.id, status=record.status.value, label=record.label)

    def _reject_engine_job(job_id: str) -> None:
        """A native crawl job can never produce a masterfile. Say so precisely.

        Raises:
            HTTPException: always, `409`.
        """
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"job {job_id} is a native engine crawl: it produces a page-intelligence "
                f"result, not Screaming Frog CSV exports. Masterfiles are built from a "
                f"Screaming Frog export bundle - send a Screaming Frog worker job id here, "
                f"or POST /deliverables/from-screaming-frog to build from an upload"
            ),
        )

    async def _screaming_frog_bundle_bytes(state: ApiState, job: WorkerJob, org_id: str) -> bytes:
        """The decrypted export bundle for a finished Screaming Frog worker job.

        Read and decrypted on a worker thread, never on the event loop: a
        bundle is capped at `worker_upload_max_bytes`, and both the database
        read and the pass over the ciphertext are long enough at that size to
        stall every other request if they ran here.

        Three failures a caller must be able to tell apart, so they get three
        statuses rather than one message to parse:

        * `409` - no bundle was ever uploaded (the crawl is queued, running,
          or failed). `bundle_size_bytes` is the authority for that: it is
          set only by `mark_uploaded`.
        * `410` - a bundle existed and its retention window has closed.
          `read_upload` filters on `expires_at` in SQL, so an expired blob is
          simply not readable; that is a *gone* resource, not a missing one,
          and a `404` would have a caller looking for a job that is right
          there.
        * `500` - the blob is present and cannot be decrypted, naming the
          setting, exactly as `GET /workers/jobs/{id}/bundle` already does.

        Raises:
            HTTPException: as above, plus `503` if the dispatch store is
                unreachable.
        """
        if job.bundle_size_bytes is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=(
                    f"Screaming Frog job {job.id} is {job.status.value} and has uploaded no "
                    f"export bundle; a masterfile needs one"
                ),
            )
        try:
            blob = await asyncio.to_thread(
                state.worker_dispatch_store.read_upload, job.id, org_id=org_id
            )
        except DispatchStoreUnavailableError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        if blob is None:
            raise HTTPException(
                status.HTTP_410_GONE,
                detail=(
                    f"the export bundle for Screaming Frog job {job.id} has passed its "
                    f"retention window (worker_bundle_retention_days) and is no longer stored; "
                    f"re-run the crawl to rebuild this masterfile"
                ),
            )
        try:
            return await asyncio.to_thread(
                decrypt_bytes, blob, secret=state.bundle_encryption_secret
            )
        except BundleDecryptionError as exc:
            _logger.error(  # noqa: TRY400 - the traceback adds nothing; the cause is configuration
                "masterfile_bundle_decrypt_failed", extra={"job_id": job.id, "error": str(exc)}
            )
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "the stored bundle could not be decrypted; "
                    "WORKER_BUNDLE_ENCRYPTION_SECRET is missing or differs from the "
                    "value in force when this bundle was uploaded"
                ),
            ) from exc

    @router.post(
        "/jobs/{job_id}/masterfile/{service_slug}",
        response_model=DeliverableAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def build_masterfile(
        job_id: str,
        service_slug: str,
        authorization: str | None = Header(default=None),
    ) -> DeliverableAccepted:
        """Build one masterfile workbook from a job's Screaming Frog exports.

        `job_id` is resolved against both job namespaces this platform has,
        the engine store first: a caller has exactly one id to send here and
        one id - the returned deliverable - to poll, which is the reason this
        accepts both rather than shipping a second route over the dispatch
        store.

        * A native crawl job (`state.store`) is refused with `409`. It has no
          Screaming Frog CSVs and never will. The route used to build
          `state.store.root / job_id / "sf_export"` - a directory a flat file
          store cannot contain and which nothing in this repository ever
          wrote - so every request died there, whatever the id.
        * A Screaming Frog worker job (`state.worker_dispatch_store`) is
          built from its uploaded bundle, decrypted into memory and read as a
          zip. Nothing is written to disk: the bundle is encrypted at rest
          deliberately (ADR 0015 condition 11), and extracting it to a
          plaintext CSV directory to satisfy the old path-shaped signature
          would have undone that.

        `202`, never `200`: nothing has been built when this returns - the
        same contract `POST /jobs` uses for a crawl, for the same reason
        (`service.generate()` measures up to 26.3s at the page ceiling).

        Raises:
            HTTPException: `404` unknown service, or an id in neither
                namespace; `403` another org's job; `409` a native crawl job,
                or a Screaming Frog job with no uploaded bundle; `410` the
                bundle's retention window has closed; `429` the deliverable
                concurrency guard is saturated; `500` the bundle cannot be
                decrypted; `503` the dispatch store is unreachable, which is
                also what an unknown id becomes when the second namespace
                cannot be consulted at all.
        """
        from src.modules.seo.deliverables.masterfile_registry import AVAILABLE_SERVICES

        org_id = require_principal(authorization, session_secret=state.session_secret).org_id

        if service_slug not in AVAILABLE_SERVICES:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail=f"unknown masterfile service: {service_slug}",
            )

        try:
            crawl_record: JobRecord | None = state.store.get(job_id)
        except JobNotFoundError:
            crawl_record = None
        if crawl_record is not None:
            # Org-scoped before the refusal, so this route cannot be used to
            # probe which ids exist in another organization.
            org_scoped_or_404(record=crawl_record, record_id=job_id, org_id=org_id, kind="job")
            _reject_engine_job(job_id)

        job = human_owned_job(state, job_id, org_id)
        payload = await _screaming_frog_bundle_bytes(state, job, org_id)

        return _start_masterfile(
            state,
            org_id,
            job_id=job_id,
            service_slug=service_slug,
            # The plaintext lives in this closure alone, and only until the
            # build finishes and `run_masterfile` closes the source.
            source_factory=lambda: source_for_bundle_bytes(payload, job_id),
            label=f"{job.envelope.seed_url} — {service_slug}",
        )

    @router.get(
        "/masterfiles/available",
    )
    def list_available_masterfiles() -> dict[str, list[str]]:
        """List available masterfile service slugs.

        Returns:
            {"services": ["response_codes", "page_titles", ...]}
        """
        from src.modules.seo.deliverables.masterfile_registry import AVAILABLE_SERVICES

        return {"services": sorted(AVAILABLE_SERVICES)}

    return router
