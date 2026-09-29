"""Generating and offering the `--crawl-list` URL lists a dispatch may use.

ADR 0022. Split out of `worker_dashboard_routes.py` rather than added to it:
that module was already at this codebase's 400-line target, and this is a
separable concern — everything here answers "which URLs, and are they even
available", while everything there answers "may this operator dispatch to this
worker". `build_url_list_router` is included by `build_worker_dashboard_router`
so `server.py` still mounts one router.

The route worth the most scrutiny is `GET /jobs/{id}/url-list/sources`. It
reads a crawl belonging to the caller's own org and nobody else's: the source
crawl is the data being exfiltrated to an external binary, so the ownership
check here is the same class of control as the one on the bundle download.

Why "Orphans Only" is conditional
---------------------------------
An orphan is defined by comparison: a URL this engine found that Screaming
Frog's own link-following crawl did not (`EngineGapReason.SITEMAP_ORPHAN`).
That comparison only exists once an operator has uploaded a Screaming Frog
export for the crawl, so the option is genuinely unavailable until then. The
API says which sources are available, with a reason for each that is not, so
a UI never has to guess and never offers a choice that would fail.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Header, HTTPException, status

from src.api.auth import org_scoped_or_404, require_principal
from src.api.worker_schemas import UrlListSourceOption, UrlListSourcesView
from src.core.config import get_settings
from src.core.errors import RankunoError
from src.core.logger import get_logger
from src.core.state_store import JobNotFoundError, JobRecord
from src.modules.seo.screaming_frog_control.url_list import (
    EmptyUrlListError,
    UrlListManifest,
    UrlListSource,
    UrlListTooLargeError,
    build_url_list,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from src.api.server import ApiState

__all__ = ["build_url_list_router", "generate_and_store_url_list", "owned_crawl_job"]

_logger = get_logger("api.url_list_routes")

_HTTP_UNPROCESSABLE_CONTENT = 422
"""Spelled as an integer for the same reason `worker_route_helpers` spells 413
that way: Starlette renamed the constant (`UNPROCESSABLE_ENTITY` ->
`UNPROCESSABLE_CONTENT`) and warns on the old name, so either spelling pins
this module to one Starlette version. The number has not changed since RFC
4918."""

_NO_RECONCILIATION = (
    "No Screaming Frog cross-check has been run against this crawl yet, and an "
    "orphan is defined by that comparison — a URL this engine found that a "
    "link-following crawl did not. Upload a Screaming Frog export for this crawl "
    "first, then this option becomes available."
)
_NO_ORPHANS = (
    "The cross-check for this crawl found no orphans: every URL this engine "
    "discovered was also reachable by following links. There is nothing for a "
    "list crawl to add."
)
_NO_RESULT = "This crawl has not finished, so it has no URLs to send."
_ALL_DESCRIPTION = (
    "Every URL this crawl discovered. Mostly pages Screaming Frog would reach "
    "by itself; large, and it spends the licence's throughput on them."
)
_ORPHANS_DESCRIPTION = (
    "Only the pages no internal link reaches. This is what a link-following "
    "crawl can never audit, and the reason list mode exists."
)


def owned_crawl_job(state: ApiState, job_id: str, org_id: str) -> JobRecord:
    """Fetch a Rankuno crawl record and confirm this org owns it.

    The IDOR control for this whole feature. A crawl's URL list is a complete
    map of a customer's site; being able to generate one from a `job_id` a
    caller merely guessed would hand one customer another's site map, and
    hand it to an external binary on a third party's desktop besides.

    Raises:
        HTTPException: `404` unknown crawl; `403` a crawl owned by another
            org, via the same shared `org_scoped_or_404` every other
            job-family route uses (ADR 0016 condition 2).
    """
    try:
        record = state.store.get(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no job {job_id}") from exc
    org_scoped_or_404(record=record, record_id=job_id, org_id=org_id, kind="crawl_job")
    return record


def _orphan_urls(state: ApiState, job_id: str) -> tuple[str, ...] | None:
    """The saved cross-check's orphan list, or `None` if no cross-check exists."""
    saved = state.store.read_reconciliation(job_id)
    if saved is None:
        return None
    raw = saved.get("orphans")
    if not isinstance(raw, list):
        return ()
    return tuple(str(url) for url in raw)


def _count_to_ceiling(urls: Iterator[str], *, ceiling: int) -> tuple[int, bool]:
    """Count, but stop one past the ceiling.

    A 100,687-page crawl takes ~3 s to stream in full; stopping at
    `ceiling + 1` turns that into ~0.4 s while still answering the only two
    questions this endpoint has — how many, and is it too many. The count is
    exact whenever it matters (a list that can actually be dispatched) and
    deliberately approximate when it does not.
    """
    count = 0
    for _ in urls:
        count += 1
        if count > ceiling:
            return count, True
    return count, False


def generate_and_store_url_list(
    state: ApiState,
    *,
    org_id: str,
    record: JobRecord,
    source: UrlListSource,
) -> UrlListManifest:
    """Build the list, persist its bytes, and return what names them.

    Called at preview time. Persisting here rather than at download time is
    the whole design: the bytes an operator approves a fingerprint of must
    already exist, so that deleting, re-running or extending the source crawl
    afterwards cannot change what the worker fetches.

    Raises:
        HTTPException: `409` the crawl has no result, or "Orphans Only" was
            asked for on a crawl with no cross-check; `422` filtering left
            nothing, or the list is over the ceiling — both carry the full
            explanation, because both are decisions an operator has to make
            differently, not transient failures to retry.
    """
    settings = get_settings()
    urls = _source_urls(state, record=record, source=source)
    try:
        manifest, body = build_url_list(
            urls,
            source=source,
            source_job_id=record.id,
            source_label=record.label or record.id,
            base_url=_base_url_of(record),
            max_urls=settings.screaming_frog_url_list_max_urls,
            policy=state.url_policy,
        )
    except (EmptyUrlListError, UrlListTooLargeError) as exc:
        _logger.warning(
            "sf_url_list_refused",
            extra={"job_id": record.id, "source": source.value, "reason": str(exc)},
        )
        raise HTTPException(_HTTP_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    state.worker_dispatch_store.store_url_list(
        org_id=org_id,
        sha256=manifest.sha256,
        body=body,
        url_count=manifest.url_count,
        source_job_id=record.id,
        retention_days=settings.worker_url_list_retention_days,
    )
    return manifest


def _base_url_of(record: JobRecord) -> str:
    """The crawl's own root, from the request it was created with.

    Read from `JobRecord.request` rather than from the result: the result is
    the 93 MB file this feature exists to avoid opening, and the seed URL a
    crawl was started with is already on the record. An absent or non-string
    value yields `""`, which `build_url_list` treats as "no domain filter" —
    visible in the returned counts rather than silently emptying the list.
    """
    seed = record.request.get("base_url") or record.request.get("seed_url")
    return seed if isinstance(seed, str) else ""


def _source_urls(state: ApiState, *, record: JobRecord, source: UrlListSource) -> Iterator[str]:
    """The raw URLs for one source, streamed where streaming is possible."""
    if source is UrlListSource.ORPHANS:
        orphans = _orphan_urls(state, record.id)
        if orphans is None:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=_NO_RECONCILIATION)
        return iter(orphans)
    if not record.has_result:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=_NO_RESULT)
    try:
        return state.store.iter_result_page_urls(record.id)
    except JobNotFoundError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=_NO_RESULT) from exc


def build_url_list_router(state: ApiState) -> APIRouter:
    """Build the URL-list source-discovery route over `state`."""
    router = APIRouter()

    @router.get("/jobs/{job_id}/url-list/sources", response_model=UrlListSourcesView)
    def list_url_list_sources(
        job_id: str, authorization: str | None = Header(default=None)
    ) -> UrlListSourcesView:
        """Which `--crawl-list` sources this finished crawl can actually offer.

        Served rather than inferred so a dispatch form never offers a choice
        that would fail: "Orphans Only" exists only for a crawl that has been
        cross-checked, and a UI cannot know that without asking.

        Counts here are **candidates, before filtering** — the preview call is
        what reports the truthful post-filter numbers a modal shows ("excluded
        18 external URLs"). Counting stops one past the ceiling, so an
        oversized crawl answers in a fraction of a second instead of streaming
        a 93 MB file to the end.

        Raises:
            HTTPException: `401` unauthenticated; `404` unknown crawl;
                `403` a crawl belonging to another org.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        record = owned_crawl_job(state, job_id, principal.org_id)
        ceiling = get_settings().screaming_frog_url_list_max_urls
        return UrlListSourcesView(
            job_id=record.id,
            label=record.label,
            base_url=_base_url_of(record),
            max_urls=ceiling,
            sources=[
                _orphans_option(state, record, ceiling),
                _all_option(state, record, ceiling),
            ],
        )

    return router


def _orphans_option(state: ApiState, record: JobRecord, ceiling: int) -> UrlListSourceOption:
    """Availability of the recommended source, with the reason when it is not."""
    orphans = _orphan_urls(state, record.id)
    if orphans is None:
        return UrlListSourceOption(
            source=UrlListSource.ORPHANS,
            label="Orphans Only (Recommended)",
            description=_ORPHANS_DESCRIPTION,
            available=False,
            unavailable_reason=_NO_RECONCILIATION,
        )
    if not orphans:
        return UrlListSourceOption(
            source=UrlListSource.ORPHANS,
            label="Orphans Only (Recommended)",
            description=_ORPHANS_DESCRIPTION,
            available=False,
            unavailable_reason=_NO_ORPHANS,
            candidate_url_count=0,
        )
    count, exceeds = _count_to_ceiling(iter(orphans), ceiling=ceiling)
    return UrlListSourceOption(
        source=UrlListSource.ORPHANS,
        label="Orphans Only (Recommended)",
        description=_ORPHANS_DESCRIPTION,
        available=not exceeds,
        unavailable_reason=_over_ceiling_reason(ceiling) if exceeds else "",
        candidate_url_count=count,
        exceeds_ceiling=exceeds,
    )


def _all_option(state: ApiState, record: JobRecord, ceiling: int) -> UrlListSourceOption:
    """Availability of the whole discovered set."""
    if not record.has_result:
        return UrlListSourceOption(
            source=UrlListSource.ALL,
            label="All Discovered URLs",
            description=_ALL_DESCRIPTION,
            available=False,
            unavailable_reason=_NO_RESULT,
        )
    try:
        count, exceeds = _count_to_ceiling(
            state.store.iter_result_page_urls(record.id), ceiling=ceiling
        )
    except (JobNotFoundError, RankunoError, OSError) as exc:
        _logger.warning(
            "sf_url_list_source_unreadable", extra={"job_id": record.id, "error": str(exc)}
        )
        return UrlListSourceOption(
            source=UrlListSource.ALL,
            label="All Discovered URLs",
            description=_ALL_DESCRIPTION,
            available=False,
            unavailable_reason=_NO_RESULT,
        )
    return UrlListSourceOption(
        source=UrlListSource.ALL,
        label="All Discovered URLs",
        description=_ALL_DESCRIPTION,
        available=not exceeds,
        unavailable_reason=_over_ceiling_reason(ceiling) if exceeds else "",
        candidate_url_count=count,
        exceeds_ceiling=exceeds,
    )


def _over_ceiling_reason(ceiling: int) -> str:
    """Why an oversized source is offered as unavailable rather than trimmed."""
    return (
        f"This crawl holds more than {ceiling:,} URLs, the ceiling for one list "
        f"(SCREAMING_FROG_URL_LIST_MAX_URLS). The list is not trimmed to fit, "
        f"because a trimmed list audits fewer pages than the approval says it "
        f"does. Use 'Orphans Only', which is smaller and is the recommended "
        f"source."
    )
