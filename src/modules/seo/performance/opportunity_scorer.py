"""Turn a crawl crossed with Search Console into ranked analyst recommendations.

What the data actually supports
-------------------------------
The four findings here were specified before the fields behind them were
measured, and two of the four could not be built as specified. Measured across
the 58 stored crawls with 200+ pages:

* **`discovery_sources` is absent on 98.1% of stored pages** (473,005 of
  482,190). "Sitemap orphan" cannot require a sitemap origin, because on almost
  every stored crawl there is nothing to read it from. The finding is built on
  zero inbound internal links instead, and says so.
* **`depth_from_l0` does not hold what its name and docstring claim.** It is
  URL path depth, not distance from the homepage, and it is offset by two
  because `cascading_pipeline` feeds `depth_of()` a `normalized_path` that holds
  a whole URL — so `/` counts `https:` and the host as segments and the homepage
  reads as depth 2. 90.4% of pages sit at exactly `segments + 2`. A "depth 4+"
  rule on that field selects two-segment URLs, which is most of a site.
  **Navigation trail depth is used instead**, which is real browsing depth.
* **`trail_source != "menu"` is true of 88.6% of pages** and is not a
  discriminator at all. Several crawls are at 100%.

A signal can be absent for a whole crawl
----------------------------------------
The share of pages with zero inbound internal links is not a site property, it
is a *crawl* property: across 58 crawls it runs 0%, 0.3%, … 38%, then jumps to
54%, 72%, a cluster at 80%, and 97/99/100%. The high ones are crawls that hit
their page ceiling, so most pages were listed but never fetched and no link
pointing at them was ever counted. Emitting 99,000 "orphans" from one of those
would be the loudest possible way to be wrong, so any crawl above
`MAX_ORPHAN_SHARE` has the inbound-link findings **skipped with a stated
reason** rather than answered. The threshold sits in the empirical gap between
38% and 54%.

On scoring
----------
`score` ranks **within one kind** and nothing else. Clicks already earned by an
orphan and impressions sitting at position 12 are not the same quantity, and
combining them into one number would be an invented exchange rate presented as
arithmetic. A caller wanting one list should sort within a kind and interleave
deliberately.

Absolute click and impression thresholds are period-dependent and this module
cannot see the period — a Search Console export carries no date range, so the
same site over 28 days and over 16 months produces very different numbers
against a fixed threshold. Ranking is trustworthy; the thresholds are a floor to
keep the list finite, not a judgement.

Pure domain logic: no I/O, no settings, no clock.
"""

from __future__ import annotations

from collections import defaultdict
from enum import StrEnum

from pydantic import Field

from src.core.schemas import StrictModel
from src.modules.seo.page_classifier.schemas import FullPageIntelligenceProfile
from src.modules.seo.page_classifier.url_rules import is_malformed_url, is_spider_trap
from src.modules.seo.performance.aggregator import PageMetricSet, section_path_of
from src.modules.seo.performance.schemas import GscPageMetrics
from src.modules.seo.performance.url_identity import UrlResolutionIndex

__all__ = [
    "BURIED_TRAIL_DEPTH",
    "MAX_ORPHAN_SHARE",
    "SITEWIDE_LINK_SHARE",
    "STRIKING_BAND",
    "Opportunity",
    "OpportunityKind",
    "OpportunityReport",
    "SignalGap",
    "score_opportunities",
]

MAX_ORPHAN_SHARE = 0.5
"""Above this share of zero-inbound pages, the link counts are not usable.

Placed in the empirical gap: 36 of 58 stored crawls sit at 38% or below, and the
next one up is 54%. The high group is crawls that hit their page ceiling, where
most pages were listed by a sitemap and never fetched, so nothing ever counted a
link pointing at them.
"""

BURIED_TRAIL_DEPTH = 3
"""Navigation trail depth at which a page counts as buried.

Trail depth, not `depth_from_l0` — see the module docstring. 26.9% of corpus
pages sit at depth 3 or deeper, so this is a filter rather than a finding on its
own; earning real clicks from down there is what makes it one.
"""

SITEWIDE_LINK_SHARE = 0.2
"""Above this share of the site linking to it, a page is navigation, not a hub.

The first real run made this necessary. Every "well-linked sibling" the
recommendation named on gep.com was a site-wide link: `/info-guide` at 78% of
the site, the homepage at 88%, the locale switchers at 85%. "Check whether that
page links here" was pointing at the footer.

Measured across the eight largest stored crawls, the 95th percentile of inbound
share is at most 0.9% and the 99th at most 20.6% — real content pages sit near
zero and navigation sits in the top one percent, with nothing in between. 20%
falls in that gap.
"""

STRIKING_BAND = (5.0, 20.0)
"""Average-position range where a ranking gain is plausibly worth chasing.

Roughly the bottom of page one to the end of page two. Above 5 the page is
already winning; past 20 a link change is not what stands between it and page
one.
"""


class OpportunityKind(StrEnum):
    """What kind of recommendation this is.

    Lowercase, following the `trail_source` precedent — provenance and
    classification metadata rather than domain taxonomy.
    """

    ORPHAN_WITH_TRAFFIC = "orphan_with_traffic"
    """Earns search clicks with no internal link pointing at it."""

    BURIED_WITH_TRAFFIC = "buried_with_traffic"
    """Earns search clicks from three or more navigation levels down."""

    INDEXED_CRAWL_TRAP = "indexed_crawl_trap"
    """Google has indexed a URL this crawler refuses as a trap or as malformed."""

    UNDERPERFORMING_SIBLING = "underperforming_sibling"
    """Draws impressions but ranks off page one, beside a well-linked sibling."""


class SignalGap(StrEnum):
    """Why a kind was not evaluated. Absence of a finding is not absence of one."""

    NO_SEARCH_DATA = "no_search_data"
    """No export row resolved to any crawled page, so nothing can be ranked."""

    INBOUND_LINKS_UNRELIABLE = "inbound_links_unreliable"
    """Too many pages report zero inbound links for the count to mean anything —
    the hallmark of a crawl that stopped at its page ceiling."""


class Opportunity(StrictModel):
    """One ranked recommendation about one page.

    Attributes:
        kind: Which finding this is.
        url: The crawled page the recommendation is about.
        section: That page's navigation trail.
        score: Rank within this kind, 0–100, where 100 is the largest in the
            kind. **Not comparable across kinds** and not a predicted uplift.
        clicks: Search Console clicks on this page.
        impressions: Search Console impressions on this page.
        position: Impression-weighted average position, or `None` when the page
            drew no impressions.
        inbound_internal_links: What the crawl counted pointing at this page.
        reference_url: The related page a recommendation refers to — the
            well-linked sibling for `UNDERPERFORMING_SIBLING`, `None` otherwise.
        reason: The finding in plain words, for a reader who will not open the
            schema.
    """

    kind: OpportunityKind
    url: str = Field(min_length=1)
    section: tuple[str, ...] = ()
    score: float = Field(default=0.0, ge=0.0, le=100.0)
    clicks: int = Field(default=0, ge=0)
    impressions: int = Field(default=0, ge=0)
    position: float | None = Field(default=None, ge=0.0)
    inbound_internal_links: int = Field(default=0, ge=0)
    reference_url: str | None = None
    reason: str = ""


class OpportunityReport(StrictModel):
    """Every recommendation this crawl and export support, and what was skipped.

    Attributes:
        opportunities: The ranked findings, highest score first within each
            kind, kinds in declaration order.
        found: How many of each kind were identified **before** the cap.
        truncated: How many of each kind the cap dropped. Reported rather than
            silently applied: a list that stops at 50 and says nothing reads as
            "there were 50".
        skipped: Kinds that were not evaluated, and why. A kind absent from both
            `found` and `skipped` was evaluated and found nothing.
        limit_per_kind: The cap that was applied.
    """

    opportunities: tuple[Opportunity, ...] = ()
    found: dict[OpportunityKind, int] = Field(default_factory=dict)
    truncated: dict[OpportunityKind, int] = Field(default_factory=dict)
    skipped: dict[OpportunityKind, SignalGap] = Field(default_factory=dict)
    limit_per_kind: int = Field(default=0, ge=0)


def _orphan_share(pages: tuple[FullPageIntelligenceProfile, ...]) -> float:
    """Fraction of pages the crawl counted no inbound internal link for."""
    if not pages:
        return 0.0
    zero = sum(1 for page in pages if page.inbound_internal_links_count == 0)
    return zero / len(pages)


_Measured = list[tuple[FullPageIntelligenceProfile, GscPageMetrics]]


def _measured(index: UrlResolutionIndex, metrics: PageMetricSet) -> _Measured:
    """Pages a Search Console row reached, paired with their merged metrics.

    The Search Console row is unpacked here rather than carried as an optional,
    so nothing downstream needs to re-assert that it is present.
    """
    out: _Measured = []
    for page in index.pages:
        held = metrics.pages.get(page.url)
        if held is not None and held.gsc is not None:
            out.append((page, held.gsc))
    return out


def _rank(items: list[tuple[float, Opportunity]], limit: int) -> tuple[int, list[Opportunity]]:
    """Score a kind's findings against its own largest, then cap.

    Returns the count found before capping alongside the survivors, because the
    cap is reported rather than applied silently.
    """
    if not items:
        return 0, []
    best = max(value for value, _ in items)
    ranked = sorted(items, key=lambda pair: -pair[0])
    scored = [
        opportunity.model_copy(update={"score": round(100.0 * value / best, 1) if best else 0.0})
        for value, opportunity in ranked[:limit]
    ]
    return len(items), scored


def score_opportunities(
    index: UrlResolutionIndex,
    metrics: PageMetricSet,
    *,
    limit_per_kind: int = 50,
    min_clicks: int = 1,
    min_impressions: int = 100,
) -> OpportunityReport:
    """Rank what this crawl and export together justify recommending.

    Args:
        index: The resolver for the crawl.
        metrics: Merged per-page metrics from `merge_page_metrics`.
        limit_per_kind: Most findings to return per kind. What the cap drops is
            counted in `truncated`.
        min_clicks: Floor for the click-driven kinds. Period-dependent — see the
            module docstring — and intended to keep the list finite rather than
            to express a judgement.
        min_impressions: Floor for `UNDERPERFORMING_SIBLING`.

    Returns:
        The ranked findings, with the kinds that could not be evaluated named
        alongside the reason.
    """
    measured = _measured(index, metrics)
    share = _orphan_share(index.pages)
    links_usable = share <= MAX_ORPHAN_SHARE

    found: dict[OpportunityKind, int] = {}
    truncated: dict[OpportunityKind, int] = {}
    skipped: dict[OpportunityKind, SignalGap] = {}
    out: list[Opportunity] = []

    def record(kind: OpportunityKind, items: list[tuple[float, Opportunity]]) -> None:
        total, kept = _rank(items, limit_per_kind)
        if total:
            found[kind] = total
        if total > len(kept):
            truncated[kind] = total - len(kept)
        out.extend(kept)

    if not measured:
        # Nothing resolved. Every click-driven kind is unanswerable, and saying
        # so is the whole point — an empty report with no explanation reads as
        # "your site has no opportunities".
        for kind in OpportunityKind:
            skipped[kind] = SignalGap.NO_SEARCH_DATA
        return OpportunityReport(skipped=skipped, limit_per_kind=limit_per_kind)

    # One finding per page, across every kind. Reporting a page as an orphan and
    # again as an underperforming sibling is the same instruction twice, and the
    # first real run produced seven such pairs between buried and sibling — the
    # third pairing, after 0041 and 0042 each caught one of the other two.
    reported: set[str] = set()
    if links_usable:
        items = []
        for page, gsc in measured:
            if page.inbound_internal_links_count or gsc.clicks < min_clicks:
                continue
            reported.add(page.url)
            items.append(
                (
                    float(gsc.clicks),
                    _opportunity(
                        OpportunityKind.ORPHAN_WITH_TRAFFIC,
                        page,
                        gsc,
                        reason=(
                            f"Earns {gsc.clicks} search clicks with no internal link "
                            f"pointing at it. Nothing on the site passes authority to "
                            f"this page, and a visitor cannot browse to it."
                        ),
                    ),
                )
            )
        record(OpportunityKind.ORPHAN_WITH_TRAFFIC, items)
    else:
        skipped[OpportunityKind.ORPHAN_WITH_TRAFFIC] = SignalGap.INBOUND_LINKS_UNRELIABLE

    items = []
    for page, gsc in measured:
        trail = section_path_of(page)
        if page.url in reported or len(trail) < BURIED_TRAIL_DEPTH:
            continue
        if gsc.clicks < min_clicks:
            continue
        reported.add(page.url)
        items.append(
            (
                float(gsc.clicks),
                _opportunity(
                    OpportunityKind.BURIED_WITH_TRAFFIC,
                    page,
                    gsc,
                    reason=(
                        f"Earns {gsc.clicks} search clicks from {len(trail)} levels down, "
                        f"under {' > '.join(trail)}. Demand is proven; the navigation "
                        f"makes it hard to reach."
                    ),
                ),
            )
        )
    record(OpportunityKind.BURIED_WITH_TRAFFIC, items)

    record(OpportunityKind.INDEXED_CRAWL_TRAP, _traps(metrics))

    if links_usable:
        record(
            OpportunityKind.UNDERPERFORMING_SIBLING,
            _siblings(measured, min_impressions, reported, len(index.pages)),
        )
    else:
        skipped[OpportunityKind.UNDERPERFORMING_SIBLING] = SignalGap.INBOUND_LINKS_UNRELIABLE

    order = list(OpportunityKind)
    out.sort(key=lambda item: (order.index(item.kind), -item.score))
    return OpportunityReport(
        opportunities=tuple(out),
        found=found,
        truncated=truncated,
        skipped=skipped,
        limit_per_kind=limit_per_kind,
    )


def _opportunity(
    kind: OpportunityKind,
    page: FullPageIntelligenceProfile,
    gsc: GscPageMetrics,
    *,
    reason: str,
    reference_url: str | None = None,
) -> Opportunity:
    """Build one finding from a page and its metrics."""
    return Opportunity(
        kind=kind,
        url=page.url,
        section=section_path_of(page),
        clicks=gsc.clicks,
        impressions=gsc.impressions,
        position=round(gsc.position, 2) if gsc.impressions else None,
        inbound_internal_links=page.inbound_internal_links_count,
        reference_url=reference_url,
        reason=reason,
    )


def _traps(metrics: PageMetricSet) -> list[tuple[float, Opportunity]]:
    """URLs Google has indexed that this crawler refuses.

    Read from the *export* side rather than from a stored refusal list, because
    no refusal list is stored — discovery counts refusals but does not keep the
    URLs. Working from the export is the stronger evidence anyway: a trap the
    crawler merely declined costs nothing, while one Google has indexed is
    already consuming crawl budget and competing with real pages.
    """
    items: list[tuple[float, Opportunity]] = []
    seen: set[str] = set()
    for row in metrics.unresolved_gsc:
        if row.url in seen or not (is_spider_trap(row.url) or is_malformed_url(row.url)):
            continue
        seen.add(row.url)
        kind = "a crawl loop" if is_spider_trap(row.url) else "a malformed address"
        items.append(
            (
                float(row.impressions),
                Opportunity(
                    kind=OpportunityKind.INDEXED_CRAWL_TRAP,
                    url=row.url,
                    clicks=row.clicks,
                    impressions=row.impressions,
                    position=round(row.position, 2) if row.impressions else None,
                    reason=(
                        f"Google has indexed this URL and shown it {row.impressions} "
                        f"times, but it is {kind} rather than a page. It spends crawl "
                        f"budget and competes with the real page it duplicates."
                    ),
                ),
            )
        )
    return items


def _siblings(
    measured: _Measured, min_impressions: int, reported: set[str], site_pages: int
) -> list[tuple[float, Opportunity]]:
    """Pages ranking off page one beside a well-linked sibling in their section.

    **This does not know whether the link already exists.** The crawl stores
    inbound and outbound link *counts*, not the edges, so no check for "does the
    hub already link here" is possible. The finding is therefore the
    underperformance, which stands on its own; the sibling is named as the
    obvious place to look first, not as a confirmed missing link.

    Pages already reported under another kind are excluded. "Nothing links here"
    and "a sibling with four links outranks you" are the same instruction twice,
    and the earlier finding says it with more force.

    **The hub must not be a site-wide link.** The first real run named
    `/info-guide` — in the footer of 78% of gep.com — as the page to link from,
    for every one of that section's findings. A page already linked from most of
    the site is navigation, and "check whether that page links here" is advice
    about the footer.

    **And the page must be converting worse than its own section.** `/gep.com/login`
    was reported as underperforming at position 5.3 while taking 89,220 clicks on
    589,390 impressions — a 15% click-through rate, which is a page winning a
    navigational query, not one starved of links. Comparing a page against its
    siblings' combined rate needs no assumed click-through curve: the benchmark
    is the client's own data.
    """
    by_section: dict[tuple[str, ...], _Measured] = defaultdict(list)
    for page, gsc in measured:
        by_section[section_path_of(page)].append((page, gsc))

    low, high = STRIKING_BAND
    items: list[tuple[float, Opportunity]] = []
    for section, members in by_section.items():
        if len(members) < 2:
            continue
        ceiling = site_pages * SITEWIDE_LINK_SHARE
        topical = [pair for pair in members if pair[0].inbound_internal_links_count <= ceiling]
        if not topical:
            continue
        hub = max(topical, key=lambda pair: pair[0].inbound_internal_links_count)
        if hub[0].inbound_internal_links_count == 0:
            continue

        clicks = sum(gsc.clicks for _, gsc in members)
        impressions = sum(gsc.impressions for _, gsc in members)
        section_ctr = clicks / impressions if impressions else 0.0

        for page, gsc in members:
            if page.url == hub[0].url or page.url in reported:
                continue
            if gsc.impressions < min_impressions or not low <= gsc.position <= high:
                continue
            if gsc.ctr >= section_ctr:
                continue
            items.append(
                (
                    float(gsc.impressions),
                    _opportunity(
                        OpportunityKind.UNDERPERFORMING_SIBLING,
                        page,
                        gsc,
                        reference_url=hub[0].url,
                        reason=(
                            f"Shown {gsc.impressions} times but averaging position "
                            f"{gsc.position:.1f}, while a sibling in "
                            f"{' > '.join(section)} carries "
                            f"{hub[0].inbound_internal_links_count} internal links. "
                            f"Check whether that page links here."
                        ),
                    ),
                )
            )
    return items
