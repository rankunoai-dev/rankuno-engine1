"""Which `--crawl-list` sources one finished crawl can actually offer.

Split out of `url_list_routes.py` when pasted lists were added: that module
now owns "generate the bytes and persist them", which is the same job for
every origin, and this one owns "can this particular crawl supply a list at
all", which is only ever asked of a crawl. Keeping them apart is what let the
route module stay inside this codebase's 400-line target while gaining a
second origin, and it puts every sentence an operator reads about an
unavailable option in one file.

Why "Orphans Only" is conditional
---------------------------------
An orphan is defined by comparison: a URL this engine found that Screaming
Frog's own link-following crawl did not (`EngineGapReason.SITEMAP_ORPHAN`).
That comparison only exists once an operator has uploaded a Screaming Frog
export for the crawl, so the option is genuinely unavailable until then. The
API says which sources are available, with a reason for each that is not, so
a UI never has to guess and never offers a choice that would fail.

Every reason string here is user-facing and is never empty when an option is
unavailable. "The option is greyed out and nobody knows why" is the failure
`unavailable_reason` exists to prevent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.api.url_list_schemas import UrlListSourceOption, UrlListSourcesView
from src.core.errors import RankunoError
from src.core.logger import get_logger
from src.core.state_store import JobNotFoundError, JobRecord
from src.modules.seo.screaming_frog_control.url_list import UrlListSource

if TYPE_CHECKING:
    from collections.abc import Iterator

    from src.api.server import ApiState

__all__ = [
    "NO_RECONCILIATION",
    "NO_RESULT",
    "base_url_of",
    "orphan_urls",
    "sources_view",
]

_logger = get_logger("api.url_list_sources")


NO_RECONCILIATION = (
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
NO_RESULT = "This crawl has not finished, so it has no URLs to send."
_ALL_DESCRIPTION = (
    "Every URL this crawl discovered. Mostly pages Screaming Frog would reach "
    "by itself; large, and it spends the licence's throughput on them."
)
_ORPHANS_DESCRIPTION = (
    "Only the pages no internal link reaches. This is what a link-following "
    "crawl can never audit, and the reason list mode exists."
)


def base_url_of(record: JobRecord) -> str:
    """The crawl's own root, from the request it was created with.

    Read from `JobRecord.request` rather than from the result: the result is
    the 93 MB file this feature exists to avoid opening, and the seed URL a
    crawl was started with is already on the record. An absent or non-string
    value yields `""`, which `build_url_list` treats as "no domain filter" —
    visible in the returned counts rather than silently emptying the list.
    """
    seed = record.request.get("base_url") or record.request.get("seed_url")
    return seed if isinstance(seed, str) else ""


def sources_view(state: ApiState, record: JobRecord, ceiling: int) -> UrlListSourcesView:
    """Both options for one crawl, each with the server's own verdict.

    Counts here are **candidates, before filtering** — the preview call is
    what reports the truthful post-filter numbers a modal shows ("excluded 18
    external URLs"). Counting stops one past the ceiling, so an oversized
    crawl answers in a fraction of a second instead of streaming a 93 MB file
    to the end.
    """
    return UrlListSourcesView(
        job_id=record.id,
        label=record.label,
        base_url=base_url_of(record),
        max_urls=ceiling,
        sources=[
            _orphans_option(state, record, ceiling),
            _all_option(state, record, ceiling),
        ],
    )


def orphan_urls(state: ApiState, job_id: str) -> tuple[str, ...] | None:
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


def _orphans_option(state: ApiState, record: JobRecord, ceiling: int) -> UrlListSourceOption:
    """Availability of the recommended source, with the reason when it is not."""
    orphans = orphan_urls(state, record.id)
    if orphans is None:
        return UrlListSourceOption(
            source=UrlListSource.ORPHANS,
            label="Orphans Only (Recommended)",
            description=_ORPHANS_DESCRIPTION,
            available=False,
            unavailable_reason=NO_RECONCILIATION,
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
            unavailable_reason=NO_RESULT,
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
            unavailable_reason=NO_RESULT,
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
