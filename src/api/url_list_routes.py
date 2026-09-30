"""Generating and offering the `--crawl-list` URL lists a dispatch may use.

ADR 0023. Split out of `worker_dashboard_routes.py` rather than added to it:
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
from src.api.url_list_schemas import (
    PastedUrlPlanRequest,
    PastedUrlPlanView,
    UrlListSourcesView,
)
from src.api.url_list_sources import (
    NO_RECONCILIATION,
    NO_RESULT,
    base_url_of,
    orphan_urls,
    sources_view,
)
from src.core.config import get_settings
from src.core.logger import get_logger
from src.core.state_store import JobNotFoundError, JobRecord
from src.modules.seo.screaming_frog_control.pasted_url_list import (
    PasteCounts,
    PastedUrlPlan,
    parse_pasted_urls,
    plan_pasted_urls,
)
from src.modules.seo.screaming_frog_control.url_list import (
    EmptyUrlListError,
    UrlListManifest,
    UrlListSource,
    UrlListTooLargeError,
    build_url_list,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from src.api.server import ApiState

__all__ = [
    "build_url_list_router",
    "generate_and_store_pasted_url_list",
    "generate_and_store_url_list",
    "owned_crawl_job",
]

_logger = get_logger("api.url_list_routes")

_HTTP_UNPROCESSABLE_CONTENT = 422
"""Spelled as an integer for the same reason `worker_route_helpers` spells 413
that way: Starlette renamed the constant (`UNPROCESSABLE_ENTITY` ->
`UNPROCESSABLE_CONTENT`) and warns on the old name, so either spelling pins
this module to one Starlette version. The number has not changed since RFC
4918."""

_PASTED_LABEL = "a list you pasted"
"""What the approval summary calls a pasted list where it would otherwise name
the source crawl. Server-owned wording, like every `UrlListSourceOption.label`,
so the phrase an operator approves under has one definition and not one per
client."""


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


def _build_and_store(
    state: ApiState,
    *,
    org_id: str,
    urls: Iterable[str],
    source: UrlListSource,
    source_job_id: str,
    source_label: str,
    base_url: str,
) -> UrlListManifest:
    """Filter, freeze and persist one list, whatever produced the URLs.

    The single place a `--crawl-list` file comes into existence. Both origins
    — a finished crawl and a block of pasted text — land here, so the ceiling,
    the off-domain filter, the per-host SSRF check and the digest are applied
    by one body of code and cannot drift apart. Persisting at preview time
    rather than at download time is the whole design: the bytes an operator
    approves a fingerprint of must already exist, so that deleting, re-running
    or extending a source afterwards cannot change what the worker fetches.

    Raises:
        HTTPException: `422` filtering left nothing, or the list is over the
            ceiling. Both carry the full explanation, because both are
            decisions an operator has to make differently, not transient
            failures to retry.
    """
    settings = get_settings()
    try:
        manifest, body = build_url_list(
            urls,
            source=source,
            source_job_id=source_job_id,
            source_label=source_label,
            base_url=base_url,
            max_urls=settings.screaming_frog_url_list_max_urls,
            policy=state.url_policy,
        )
    except (EmptyUrlListError, UrlListTooLargeError) as exc:
        _logger.warning(
            "sf_url_list_refused",
            extra={"job_id": source_job_id, "source": source.value, "reason": str(exc)},
        )
        raise HTTPException(_HTTP_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    state.worker_dispatch_store.store_url_list(
        org_id=org_id,
        sha256=manifest.sha256,
        body=body,
        url_count=manifest.url_count,
        source_job_id=source_job_id,
        retention_days=settings.worker_url_list_retention_days,
    )
    return manifest


def generate_and_store_url_list(
    state: ApiState,
    *,
    org_id: str,
    record: JobRecord,
    source: UrlListSource,
) -> UrlListManifest:
    """Build a list from one of this org's finished crawls, and persist it.

    Raises:
        HTTPException: `409` the crawl has no result, or "Orphans Only" was
            asked for on a crawl with no cross-check; `422` from
            `_build_and_store`.
    """
    return _build_and_store(
        state,
        org_id=org_id,
        urls=_source_urls(state, record=record, source=source),
        source=source,
        source_job_id=record.id,
        source_label=record.label or record.id,
        base_url=base_url_of(record),
    )


def generate_and_store_pasted_url_list(
    state: ApiState,
    *,
    org_id: str,
    text: str,
    seed_url: str,
) -> tuple[UrlListManifest, PasteCounts]:
    """Read pasted text into a list, persist it, and return the parse account.

    The text is parsed **here**, server-side, and never accepted as an array a
    client already split. The counts an operator approves and the bytes a
    worker fetches then come from one execution of one parser, so "400 URLs"
    in the dialog is arithmetic over the file that exists rather than a
    browser's opinion of the same text.

    `seed_url` is the already-validated dispatch seed, and its registrable
    domain is the in-scope rule — the same rule a crawl-sourced list takes
    from the crawl's own root. A paste covering two sites therefore keeps one
    and reports the rest as `counts.off_domain_dropped`, rather than being
    refused outright: which site was meant is a question `PastedUrlPlanView`
    already put to the operator before they got here.

    Args:
        state: API state, for the SSRF policy and the dispatch store.
        org_id: The authenticated principal's org. Scopes the stored bytes.
        text: Exactly what the operator pasted.
        seed_url: The validated seed URL, whose domain scopes the list.

    Returns:
        The manifest and the parse account, which the preview reports beside
        the filtering counts so an operator sees both halves of what their
        text turned into.

    Raises:
        HTTPException: `422` from `_build_and_store` — nothing readable
            survived, or the list is over the ceiling.
    """
    parsed = parse_pasted_urls(text)
    manifest = _build_and_store(
        state,
        org_id=org_id,
        urls=parsed.urls,
        source=UrlListSource.PASTED,
        source_job_id="",
        source_label=_PASTED_LABEL,
        base_url=seed_url,
    )
    return manifest, parsed.counts


def _source_urls(state: ApiState, *, record: JobRecord, source: UrlListSource) -> Iterator[str]:
    """The raw URLs for one source, streamed where streaming is possible."""
    if source is UrlListSource.ORPHANS:
        orphans = orphan_urls(state, record.id)
        if orphans is None:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=NO_RECONCILIATION)
        return iter(orphans)
    if not record.has_result:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NO_RESULT)
    try:
        return state.store.iter_result_page_urls(record.id)
    except JobNotFoundError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NO_RESULT) from exc


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
        cross-checked, and a UI cannot know that without asking. The verdicts
        and the wording are `url_list_sources`'.

        Raises:
            HTTPException: `401` unauthenticated; `404` unknown crawl;
                `403` a crawl belonging to another org.
        """
        principal = require_principal(authorization, session_secret=state.session_secret)
        record = owned_crawl_job(state, job_id, principal.org_id)
        return sources_view(state, record, get_settings().screaming_frog_url_list_max_urls)

    @router.post("/url-list/paste/plan", response_model=PastedUrlPlanView)
    def plan_pasted_url_list(
        payload: PastedUrlPlanRequest, authorization: str | None = Header(default=None)
    ) -> PastedUrlPlanView:
        """Read pasted text and report what it would crawl. Nothing is stored.

        The paste-mode counterpart of `.../url-list/sources`, and it exists
        for the same reason: a dispatch form must not offer a choice that
        would fail, and it cannot work out on its own which site a block of
        text is about. A pasted list still needs a `seed_url` — its
        registrable domain is what the list is filtered against — and with no
        source crawl there is nothing to take one from, so this call proposes
        one and names every other domain the text covers.

        Parsing happens here rather than in the browser so that the rule has
        one owner: the counts shown before approval and the bytes generated at
        preview come from the same parser on the same text.

        No list is generated, no digest minted and nothing persisted. This is
        a reading of text the caller already holds, so it grants no access to
        anything, and the bytes are still frozen at preview time (ADR 0023).

        Raises:
            HTTPException: `401` unauthenticated.
        """
        require_principal(authorization, session_secret=state.session_secret)
        return _plan_view(
            plan_pasted_urls(payload.urls, max_urls=get_settings().screaming_frog_url_list_max_urls)
        )

    return router


def _plan_view(plan: PastedUrlPlan) -> PastedUrlPlanView:
    """Map the module's plan onto its wire shape, which is a `list` not a tuple."""
    return PastedUrlPlanView(
        counts=plan.counts,
        domains=list(plan.domains),
        suggested_seed_url=plan.suggested_seed_url,
        max_urls=plan.max_urls,
        exceeds_ceiling=plan.exceeds_ceiling,
    )
