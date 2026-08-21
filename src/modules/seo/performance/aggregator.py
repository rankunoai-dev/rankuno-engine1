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

from pydantic import Field

from src.core.schemas import StrictModel
from src.modules.seo.page_classifier.logical_hierarchy import OTHERS_LABEL
from src.modules.seo.page_classifier.schemas import FullPageIntelligenceProfile
from src.modules.seo.performance.schemas import (
    Ga4PageMetrics,
    GscPageMetrics,
    PagePerformance,
    PerformanceRollup,
    ResolutionOutcome,
    SectionPerformance,
    UnattributedTotals,
    UrlFailure,
    UrlMatch,
)
from src.modules.seo.performance.url_identity import UrlResolutionIndex

__all__ = [
    "PageMetricSet",
    "aggregate",
    "merge_page_metrics",
    "rollup_of",
    "section_path_of",
]


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


class PageMetricSet(StrictModel):
    """Google metrics merged onto crawled pages, before any rollup.

    The shared middle step. Both the section rollup and the opportunity scorer
    need "what did Google say about each page", and computing it twice would be
    two implementations of the merge rule — including the impression weighting,
    which is exactly the part that would end up subtly wrong in one copy and not
    the other.

    Attributes:
        pages: Crawled page URL to its merged metrics. A page absent from this
            map appeared in no export row at all, which is not the same as a
            page with zero clicks.
        unattributed: Metrics from rows that reached no page.
        unresolved_gsc: The Search Console rows that reached no page, kept
            whole rather than as bare URLs. Some of them are findings in their
            own right — a URL Google has indexed and this crawler refuses is a
            crawl-budget defect, only visible from this side — and ranking those
            needs the clicks and impressions, not just the address.
        unresolved_ga4: The GA4 rows that reached no page, on the same terms.
        gsc_resolution: How much of the Search Console export landed.
        ga4_resolution: The same for GA4.
    """

    pages: dict[str, PagePerformance] = Field(default_factory=dict)
    unattributed: UnattributedTotals = UnattributedTotals()
    unresolved_gsc: tuple[GscPageMetrics, ...] = ()
    unresolved_ga4: tuple[Ga4PageMetrics, ...] = ()
    gsc_resolution: ResolutionOutcome = ResolutionOutcome(total=0)
    ga4_resolution: ResolutionOutcome = ResolutionOutcome(total=0)


def merge_page_metrics(
    index: UrlResolutionIndex,
    gsc_rows: Iterable[GscPageMetrics] = (),
    ga4_rows: Iterable[Ga4PageMetrics] = (),
) -> PageMetricSet:
    """Resolve every export row onto a page and merge the rows that share one.

    Args:
        index: The resolver for the crawl these rows describe.
        gsc_rows: Search Console page rows.
        ga4_rows: GA4 `pagePath` rows.

    Returns:
        The merged per-page metrics, what reached no page, and a resolution
        report per source.
    """
    by_page: dict[str, _PageAcc] = {}
    unresolved = _Acc()
    unresolved_rows = 0
    missed_gsc: list[GscPageMetrics] = []
    missed_ga4: list[Ga4PageMetrics] = []

    gsc_matches: list[UrlMatch] = []
    gsc_failures: list[UrlFailure] = []
    gsc_total = 0
    for row in gsc_rows:
        gsc_total += 1
        outcome = index.resolve(row.url)
        if isinstance(outcome, UrlFailure):
            gsc_failures.append(outcome)
            missed_gsc.append(row)
            unresolved_rows += 1
            unresolved.clicks += row.clicks
            unresolved.impressions += row.impressions
            continue
        gsc_matches.append(outcome)
        held = by_page.setdefault(outcome.page_url, _PageAcc())
        held.seen_gsc = True
        held.acc.clicks += row.clicks
        held.acc.impressions += row.impressions
        # Weighted, not assigned. Two rows for one page hold two averages over
        # different impression volumes, and the mean of the two is not the
        # average position of the page.
        held.acc.position_weight += row.position * row.impressions

    ga4_matches: list[UrlMatch] = []
    ga4_failures: list[UrlFailure] = []
    ga4_total = 0
    for ga4 in ga4_rows:
        ga4_total += 1
        outcome = index.resolve(ga4.path)
        if isinstance(outcome, UrlFailure):
            ga4_failures.append(outcome)
            missed_ga4.append(ga4)
            unresolved_rows += 1
            unresolved.sessions += ga4.sessions
            continue
        ga4_matches.append(outcome)
        held = by_page.setdefault(outcome.page_url, _PageAcc())
        held.seen_ga4 = True
        held.acc.sessions += ga4.sessions
        held.acc.engaged_sessions += ga4.engaged_sessions
        held.acc.engagement_time_sec += ga4.engagement_time_sec
        held.acc.conversions += ga4.conversions
        held.acc.revenue += ga4.revenue

    return PageMetricSet(
        pages={url: _page_performance(url, held) for url, held in by_page.items()},
        unattributed=UnattributedTotals(
            rows=unresolved_rows,
            clicks=unresolved.clicks,
            impressions=unresolved.impressions,
            sessions=unresolved.sessions,
        ),
        unresolved_gsc=tuple(missed_gsc),
        unresolved_ga4=tuple(missed_ga4),
        gsc_resolution=ResolutionOutcome(
            total=gsc_total, matches=tuple(gsc_matches), failures=tuple(gsc_failures)
        ),
        ga4_resolution=ResolutionOutcome(
            total=ga4_total, matches=tuple(ga4_matches), failures=tuple(ga4_failures)
        ),
    )


def _page_performance(url: str, held: _PageAcc) -> PagePerformance:
    """Render one page's accumulator, keeping "absent" distinct from "zero".

    `gsc` stays `None` when no Search Console row named this page. A row of
    zeroes produces a `GscPageMetrics` of zeroes instead, because "indexed and
    earning nothing" and "never reported" are different findings.

    The position is deliberately **not** rounded here. Rounding at this level
    and then multiplying back by impressions to roll a section up would
    reintroduce the error the weighting exists to remove; rounding happens once,
    at the section boundary.
    """
    acc = held.acc
    gsc = None
    if held.seen_gsc:
        gsc = GscPageMetrics(
            url=url,
            clicks=acc.clicks,
            impressions=acc.impressions,
            position=acc.position_weight / acc.impressions if acc.impressions else 0.0,
        )
    ga4 = None
    if held.seen_ga4:
        ga4 = Ga4PageMetrics(
            path=url,
            sessions=acc.sessions,
            engaged_sessions=acc.engaged_sessions,
            engagement_time_sec=acc.engagement_time_sec,
            conversions=acc.conversions,
            revenue=acc.revenue,
        )
    return PagePerformance(page_url=url, gsc=gsc, ga4=ga4)


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
    return rollup_of(index, merge_page_metrics(index, gsc_rows, ga4_rows))


def rollup_of(index: UrlResolutionIndex, metrics: PageMetricSet) -> PerformanceRollup:
    """Roll already-merged page metrics up the navigation tree.

    Split from `aggregate` so a caller that has already merged — the opportunity
    scorer has — does not resolve the whole export a second time.
    """
    sections = _roll_up(index.pages, metrics.pages)
    site = sections.pop(())
    return PerformanceRollup(
        site=_render((), site),
        sections=tuple(_render(path, acc) for path, acc in sorted(sections.items())),
        unattributed=metrics.unattributed,
        gsc_resolution=metrics.gsc_resolution,
        ga4_resolution=metrics.ga4_resolution,
        duplicate_profiles=index.duplicate_profiles,
    )


def _roll_up(
    pages: Sequence[FullPageIntelligenceProfile], by_page: dict[str, PagePerformance]
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
        measured = _measured(held)
        # Presence in the map is what counts as measured, not whether the
        # numbers are non-zero. Search Console exports pages with no clicks, and
        # "reported with nothing" is a different fact from "never reported" —
        # collapsing them here would undo the reason `PagePerformance.gsc` is
        # optional rather than a row of zeroes.
        has_data = held is not None

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


def _measured(held: PagePerformance | None) -> _Acc:
    """Unpack a page's reported metrics back into addable counters."""
    acc = _Acc()
    if held is None:
        return acc
    if held.gsc is not None:
        acc.clicks = held.gsc.clicks
        acc.impressions = held.gsc.impressions
        acc.position_weight = held.gsc.position * held.gsc.impressions
    if held.ga4 is not None:
        acc.sessions = held.ga4.sessions
        acc.engaged_sessions = held.ga4.engaged_sessions
        acc.engagement_time_sec = held.ga4.engagement_time_sec
        acc.conversions = held.ga4.conversions
        acc.revenue = held.ga4.revenue
    return acc


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
