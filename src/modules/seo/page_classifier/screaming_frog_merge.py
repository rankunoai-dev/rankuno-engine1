"""Fold the pages Screaming Frog reached, and this engine missed, into the tree.

`screaming_frog_reconciler` decides *what* the two crawlers disagree about and
why. This module acts on exactly one of its buckets — `MISSED_PAGE`, the live,
indexable, in-scope pages this engine never found — and leaves every other
disagreement alone.

Why only that bucket
--------------------
The other frog-side reasons are differences rather than defects: a redirect
source is not a page, an off-site URL is out of scope by design, and a media URL
is refused deliberately. Merging any of them would import the noise this engine
spent cycles 0020 and 0021 learning to reject, and would do it under the banner
of a fix.

The engine-side surplus is not merged either, in either direction. A sitemap
orphan is *already* in the tree; Screaming Frog's silence about it is the
finding, not a correction to apply.

Optional, and it stays optional
-------------------------------
Nothing on the crawl path imports this module. A crawl with no export behaves
exactly as it did before. Reconciliation is an explicit extra step that returns
a **new** result and never mutates the one it was given — the same contract as
`reparse_placement`, and for the same reason: an operator must be able to
compare before and after.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.logger import get_logger
from src.modules.seo.page_classifier.cascading_pipeline import classify_page
from src.modules.seo.page_classifier.schemas import (
    FullPageIntelligenceProfile,
    PrimaryPageType,
)
from src.modules.seo.page_classifier.screaming_frog_reconciler import (
    ReconciliationReport,
    ScreamingFrogRow,
    load_screaming_frog_export,
    normalise,
    reconcile,
)
from src.modules.seo.page_classifier.signal_parsers import PageEvidence
from src.modules.seo.page_classifier.tool import (
    CrawlSummary,
    PageClassificationOutput,
    reparse_placement,
)
from src.modules.seo.page_classifier.url_rules import normalize_url

__all__ = ["MergeOutcome", "merge_reconciled_urls"]

_logger = get_logger("modules.seo.screaming_frog_merge")


@dataclass(frozen=True, slots=True)
class MergeOutcome:
    """A merged result and the reconciliation that produced it.

    A dataclass rather than a `StrictModel`: it carries a whole
    `PageClassificationOutput`, and declaring that as a Pydantic field would
    revalidate every one of up to 500,000 profiles on construction for no
    benefit — nothing here crosses a process boundary.

    Attributes:
        output: The result with the missed pages placed. A new object, except
            when nothing merged, where it is the input unchanged.
        report: The full bi-directional reconciliation.
        merged: How many pages were added. Zero is a normal, common outcome.
    """

    output: PageClassificationOutput
    report: ReconciliationReport
    merged: int


def _profile_for(
    url: str,
    row: ScreamingFrogRow | None,
    total_pages: int,
) -> FullPageIntelligenceProfile:
    """Classify one missed URL through the cascade.

    Only the URL and Screaming Frog's own link counts are available: an export
    carries no HTML, so the five structural parsers that read a page body cannot
    contribute. The cascade already handles that — it returns `UNKNOWN` at low
    confidence rather than raising — and the resulting profile is honestly
    weaker than a crawled page's.

    That weakness is deliberately left visible in `final_confidence_score`
    instead of being papered over. A merged page and a crawled page must not be
    indistinguishable in the tree, because they are not equally well evidenced.

    `inbound_internal_links` is the one signal an export genuinely adds:
    Screaming Frog counted those links by following them, and this engine never
    saw the page at all.
    """
    return classify_page(
        PageEvidence(
            url=url,
            normalized_path=normalize_url(url),
            inbound_internal_links=row.unique_inlinks if row else 0,
            total_pages_in_crawl=total_pages,
        )
    )


def _resummarise(output: PageClassificationOutput) -> CrawlSummary:
    """Recount the headline numbers over a changed page set.

    Mirrors `PageClassificationTool._summarise`, which is a method bound to a
    live cost ledger and so cannot be called here. The fields a merge cannot
    change — LLM spend, and the orphan count that came from discovery — are
    carried through from the original rather than recomputed from data this
    module does not have.
    """
    pages = output.pages
    total = len(pages)
    escalated = sum(1 for page in pages if page.escalated_to_llm)
    return CrawlSummary(
        pages_classified=total,
        escalated_to_llm=escalated,
        escalation_rate=(escalated / total) if total else 0.0,
        unknown_pages=sum(1 for p in pages if p.primary_page_type is PrimaryPageType.UNKNOWN),
        low_confidence_pages=sum(1 for p in pages if not p.is_confidently_classified),
        orphan_pages=output.discovery.orphans,
        llm_spend_usd=output.summary.llm_spend_usd,
    )


def merge_reconciled_urls(output: PageClassificationOutput, export: bytes | str) -> MergeOutcome:
    """Reconcile an export against a crawl and merge the pages it genuinely missed.

    Placement is done by re-running `reparse_placement` over the combined page
    set rather than by inserting nodes into the tree directly. Placement is a
    contested decision between the header menu and each page's own breadcrumb
    (`_better_trail`), and re-running the real thing is the only way the new
    pages are placed under the same rules as the existing ones. Hand-inserting
    would put a second placement implementation in the codebase to disagree with
    the first — the failure this repository has already paid for twice.

    A merged page has no breadcrumb of its own, so the menu places it or nothing
    does; one that nothing places lands in `OTHERS`, which is the correct and
    visible outcome rather than a hidden one.

    Args:
        output: The crawl to merge into. Not modified.
        export: An `Internal → HTML` export — raw `.xlsx`/`.csv` bytes from an
            upload, or CSV text already decoded. The format is detected from the
            content, so a renamed file still reads correctly.

    Returns:
        The merged result, the reconciliation report, and the number added.
    """
    rows = load_screaming_frog_export(export)
    report = reconcile(output.base_url, tuple(page.url for page in output.pages), rows)

    missed = report.missed_pages
    if not missed:
        # Returned untouched rather than pushed through a reparse. A merge that
        # finds no gap must not alter the result it was asked only to check —
        # a reparse would rewrite `trail_source` across the whole crawl.
        _logger.info("frog_merge_noop", extra={"base_url": output.base_url})
        return MergeOutcome(output, report, 0)

    by_key = {normalise(row.address): row for row in rows}
    total_after = len(output.pages) + len(missed)
    additions = tuple(_profile_for(url, by_key.get(normalise(url)), total_after) for url in missed)

    # `homepage_html` is unavailable: a stored result keeps no HTML. The stored
    # menu is therefore reused, which is right — the menu did not change, only
    # the set of pages being placed under it.
    merged = reparse_placement(output.model_copy(update={"pages": (*output.pages, *additions)}))
    merged = merged.model_copy(update={"summary": _resummarise(merged)})

    _logger.info(
        "frog_merged",
        extra={"added": len(additions), "pages_after": len(merged.pages)},
    )
    return MergeOutcome(merged, report, len(additions))
