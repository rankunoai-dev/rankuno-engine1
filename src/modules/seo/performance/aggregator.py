"""Roll page-level Google metrics up the navigation tree.

Why this is not a `groupby`
---------------------------
Four things in this data punish the obvious implementation, and all four were
measured on the 70 stored crawls rather than imagined:

**Section labels are not unique.** Up to 68 labels per crawl appear under more
than one parent — an `Overview` under Products and another under Company. Keying
a rollup by label merges two unrelated sections into one row that is wrong in a
way nobody can see. The key here is the whole trail.

**A section is often a page as well.** 1,220 distinct trails are a strict prefix
of a deeper trail, so `Products` holds both its own page and everything beneath
it. A single total cannot answer "is this section big, or is its landing page
big", so `direct_*` is reported beside the subtree total.

**Rates do not roll up.** A section's CTR is not the mean of its pages' CTRs,
and its average position is not the mean of their positions — it is the
impression-weighted mean. Both are recomputed from counters that survive
addition, never averaged.

**Several Google URLs can name one page.** That is what canonical tags are for,
so the resolver maps them onto one crawled page and the rows must be *summed*.
Assigning instead of adding silently discards clicks, and the total still looks
plausible.

The number that makes the rest trustworthy
------------------------------------------
Some export rows resolve to no page at all. If those are dropped, the sum of the
sections is quietly smaller than the total in the Search Console UI, and the
first thing an analyst does is compare the two. `unattributed` holds them, and
`attributed_share` says how much of the export reached a section.

Pure domain logic: no I/O, no settings, no clock.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from src.modules.seo.page_classifier.logical_hierarchy import OTHERS_LABEL
from src.modules.seo.page_classifier.schemas import FullPageIntelligenceProfile
from src.modules.seo.performance.schemas import (
    Ga4PageMetrics,
    GscPageMetrics,
    PerformanceRollup,
    SectionPerformance,
    UnattributedTotals,
)
from src.modules.seo.performance.url_identity import UrlResolutionIndex

__all__ = ["aggregate", "section_path_of"]


def section_path_of(page: FullPageIntelligenceProfile) -> tuple[str, ...]:
    """The section trail a page rolls up under.

    An empty `breadcrumb_path` becomes `(OTHERS,)` rather than staying empty.
    Four of the 58 stored crawls with a usable page count express "nothing
    placed this" as an empty trail and the other 53 express it as
    `(OTHERS, <page type>)`; no crawl uses both. Folding the older spelling into
    the visible bucket keeps those pages counted somewhere a reader can find
    them, instead of appearing only in the site total and in no section.
    """
    return page.breadcrumb_path or (OTHERS_LABEL,)


@dataclass
class _Acc:
    """Running totals for one section. Counters only — no rates."""

    pages: int = 0
    pages_with_data: int = 0
    direct_pages: int = 0
    direct_clicks: int = 0
    clicks: int = 0
    impressions: int = 0
    # Sum of `position × impressions`. The numerator of the impression-weighted
    # mean, kept because it is the only form of position that survives addition.
    position_weight: float = 0.0
    sessions: int = 0
    engaged_sessions: int = 0
    engagement_time_sec: float = 0.0
    conversions: float = 0.0
    revenue: float = 0.0

    def add(self, other: _Acc) -> None:
        """Fold another accumulator in. Used to lift a page onto its ancestors."""
        self.clicks += other.clicks
        self.impressions += other.impressions
        self.position_weight += other.position_weight
        self.sessions += other.sessions
        self.engaged_sessions += other.engaged_sessions
        self.engagement_time_sec += other.engagement_time_sec
        self.conversions += other.conversions
        self.revenue += other.revenue


@dataclass
class _PageAcc:
    """One crawled page's merged metrics, before it is lifted onto sections."""

    acc: _Acc = field(default_factory=_Acc)
    seen_gsc: bool = False
    seen_ga4: bool = False


def _position(weight: float, impressions: int) -> float | None:
    """Impression-weighted average position, or `None` when nothing was seen.

    `None`, never `0.0`. Position zero is not a neutral value — it reads as
    better than rank 1, so a section with no impressions would sort to the top
    of a "best performing" list on the strength of having no data at all.
    """
    if impressions <= 0:
        return None
    return round(weight / impressions, 2)


def _prefixes(path: tuple[str, ...]) -> list[tuple[str, ...]]:
    """Every ancestor of a trail, site root first, the trail itself last.

    Trails run 0–6 deep across the stored corpus, so this is iterative and
    bounded rather than recursive; a cycle in the tree cannot hang it because
    there is no tree traversal here, only prefixes of one page's own trail.
    """
    return [path[:n] for n in range(len(path) + 1)]


def aggregate(
    index: UrlResolutionIndex,
    gsc_rows: Iterable[GscPageMetrics] = (),
    ga4_rows: Iterable[Ga4PageMetrics] = (),
) -> PerformanceRollup:
    """Attach Google metrics to crawled pages and roll them up the nav tree.

    Args:
        index: Built from the crawl whose sections are being totalled. Its
            deduplicated page set is used directly, so the rollup counts exactly
            the pages the resolver can map onto.
        gsc_rows: Search Console page rows. Several rows may name one page;
            they are summed.
        ga4_rows: GA4 `pagePath` rows, on the same terms.

    Returns:
        The rollup: one `SectionPerformance` per trail prefix, a site row, the
        metrics that reached no page, and the resolution report for each source.
    """
    pages = index.pages
    by_page: dict[str, _PageAcc] = {}
    unresolved = _Acc()
    unresolved_rows = 0

    gsc_list = list(gsc_rows)
    for row in gsc_list:
        target = index.resolve_url(row.url)
        if target is None:
            unresolved_rows += 1
            unresolved.clicks += row.clicks
            unresolved.impressions += row.impressions
            continue
        held = by_page.setdefault(target, _PageAcc())
        held.seen_gsc = True
        held.acc.clicks += row.clicks
        held.acc.impressions += row.impressions
        # Weighted, not assigned. Two rows for one page hold two averages over
        # different impression volumes, and the mean of the two is not the
        # average position of the page.
        held.acc.position_weight += row.position * row.impressions

    ga4_list = list(ga4_rows)
    for ga4 in ga4_list:
        target = index.resolve_url(ga4.path)
        if target is None:
            unresolved_rows += 1
            unresolved.sessions += ga4.sessions
            continue
        held = by_page.setdefault(target, _PageAcc())
        held.seen_ga4 = True
        held.acc.sessions += ga4.sessions
        held.acc.engaged_sessions += ga4.engaged_sessions
        held.acc.engagement_time_sec += ga4.engagement_time_sec
        held.acc.conversions += ga4.conversions
        held.acc.revenue += ga4.revenue

    sections = _roll_up(pages, by_page)
    site = sections.pop(())
    return PerformanceRollup(
        site=_render((), site),
        sections=tuple(_render(path, acc) for path, acc in sorted(sections.items())),
        unattributed=UnattributedTotals(
            rows=unresolved_rows,
            clicks=unresolved.clicks,
            impressions=unresolved.impressions,
            sessions=unresolved.sessions,
        ),
        gsc_resolution=index.build_resolution_report(row.url for row in gsc_list),
        ga4_resolution=index.build_resolution_report(row.path for row in ga4_list),
        duplicate_profiles=index.duplicate_profiles,
    )


def _roll_up(
    pages: Sequence[FullPageIntelligenceProfile], by_page: dict[str, _PageAcc]
) -> dict[tuple[str, ...], _Acc]:
    """Lift each page's metrics onto its own trail and every ancestor of it.

    Every page has exactly one trail, so a page is counted once per ancestor
    level and the top-level sections sum to the site row. That property is what
    makes the totals reconcilable, and it depends on the trail being single —
    if a page ever gained a second placement, this would double-count it.
    """
    sections: dict[tuple[str, ...], _Acc] = {}
    for page in pages:
        path = section_path_of(page)
        held = by_page.get(page.url)
        measured = held.acc if held is not None else _Acc()
        # A row of zeroes still counts as measured. Search Console exports
        # pages with no clicks, and "reported with nothing" is a different fact
        # from "never reported" — collapsing them here would undo the reason
        # `PagePerformance.gsc` is optional rather than a row of zeroes.
        has_data = held is not None and (held.seen_gsc or held.seen_ga4)

        for prefix in _prefixes(path):
            acc = sections.setdefault(prefix, _Acc())
            acc.pages += 1
            if has_data:
                acc.pages_with_data += 1
            acc.add(measured)

        own = sections[path]
        own.direct_pages += 1
        own.direct_clicks += measured.clicks
    sections.setdefault((), _Acc())
    return sections


def _render(path: tuple[str, ...], acc: _Acc) -> SectionPerformance:
    """Turn counters into the reported contract, deriving the rates last."""
    return SectionPerformance(
        path=path,
        label=path[-1] if path else "",
        depth=len(path),
        pages=acc.pages,
        pages_with_data=acc.pages_with_data,
        direct_pages=acc.direct_pages,
        direct_clicks=acc.direct_clicks,
        clicks=acc.clicks,
        impressions=acc.impressions,
        position=_position(acc.position_weight, acc.impressions),
        sessions=acc.sessions,
        engaged_sessions=acc.engaged_sessions,
        engagement_time_sec=round(acc.engagement_time_sec, 3),
        conversions=acc.conversions,
        revenue=acc.revenue,
    )
