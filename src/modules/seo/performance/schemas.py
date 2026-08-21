"""Contracts for performance data joined onto a crawl.

Two rules shape every model here.

**Rates are never stored, only derived.** Search Console reports a CTR and an
average position per row, and both are traps under aggregation: the CTR of a
section is not the mean of its pages' CTRs, and its position is not the mean of
their positions. Summing clicks and impressions and dividing is the only correct
answer, so `ctr` is a property over the two counters that survive addition, and
`position` is stored per page but documented as un-summable.

**A missing metric is not a zero.** `PagePerformance` holds `gsc` and `ga4` as
optional, because "this page got no clicks" and "this page was not in the
export" produce identical rollups if both are written as `0` — and the second
one means the join failed, which is a defect in us rather than in the client's
site.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, computed_field

from src.core.schemas import StrictModel

__all__ = [
    "RELIABLE_MATCH_RATE",
    "Ga4PageMetrics",
    "GscPageMetrics",
    "MatchFailure",
    "MatchTier",
    "PagePerformance",
    "ResolutionOutcome",
    "UrlFailure",
    "UrlMatch",
]

RELIABLE_MATCH_RATE = 90.0
"""Percentage of Google URLs that must resolve before a rollup is trustworthy.

Below this, section totals understate traffic by an unknown amount that is not
evenly spread — an unresolved URL is usually unresolved for a structural reason
(one template redirects, one silo is client-rendered), so the loss concentrates
in whichever section the analyst is least expecting it in.
"""


class MatchTier(StrEnum):
    """How a Google URL was tied to a crawled page, strongest evidence first.

    Recorded per match because the tiers are not equally trustworthy and a
    reader who cannot tell them apart cannot audit the join. Lowercase per the
    `trail_source` precedent — this is provenance metadata, not domain taxonomy.
    """

    CRAWLED_URL = "crawled_url"
    """The address the crawler holds. Unambiguous by construction."""

    REDIRECT_TARGET = "redirect_target"
    """Where a crawled page's fetch landed. Google reports destinations."""

    CANONICAL_TAG = "canonical_tag"
    """A page declared this URL as its canonical. A claim, not a verdict."""

    BARE_PATH = "bare_path"
    """Matched only after dropping the query string, and only because exactly
    one crawled page has that path. GA4 property filters frequently strip
    queries the crawl kept."""


class MatchFailure(StrEnum):
    """Why a Google URL could not be tied to a crawled page.

    The breakdown is the point. A match rate on its own says the join is bad;
    these say *who* is at fault, and the four answers need four different fixes.
    """

    UNPARSEABLE = "unparseable"
    """Not a URL. A malformed export cell, or a header row read as data."""

    OFF_SITE = "off_site"
    """A host the crawl never covered — a different subdomain or property."""

    AMBIGUOUS = "ambiguous"
    """Several crawled pages claim this address. Attributing it to one of them
    would be a guess, and a guess here moves real traffic to the wrong section."""

    NOT_CRAWLED = "not_crawled"
    """On this site, but absent from the crawl. Either a page we failed to
    reach, or one Google still holds that the site has removed."""


class UrlMatch(StrictModel):
    """One Google URL successfully tied to one crawled page."""

    google_url: str = Field(min_length=1)
    page_url: str = Field(min_length=1)
    via: MatchTier


class UrlFailure(StrictModel):
    """One Google URL that could not be tied to a crawled page."""

    google_url: str
    reason: MatchFailure


class ResolutionOutcome(StrictModel):
    """The result of resolving a whole export against one crawl.

    Produced before any metric is aggregated, and deliberately so: the analyst
    is told how much of the export landed *before* being shown numbers derived
    from it.
    """

    total: int = Field(ge=0)
    matches: tuple[UrlMatch, ...] = ()
    failures: tuple[UrlFailure, ...] = ()
    threshold_pct: float = Field(default=RELIABLE_MATCH_RATE, ge=0.0, le=100.0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def matched_count(self) -> int:
        """How many Google URLs resolved to a crawled page."""
        return len(self.matches)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def match_rate_pct(self) -> float:
        """Percentage of the export that resolved, or 0.0 for an empty export."""
        if self.total == 0:
            return 0.0
        return round(100.0 * len(self.matches) / self.total, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_reliable(self) -> bool:
        """Whether rollups built on this join should be shown without a warning.

        An empty export is **not** reliable. Vacuous truth is the wrong answer
        for a caller asking "can I trust the totals": there are no totals, and
        returning True here would present an empty dashboard as a healthy one.
        """
        return self.total > 0 and self.match_rate_pct >= self.threshold_pct

    @computed_field  # type: ignore[prop-decorator]
    @property
    def by_tier(self) -> dict[MatchTier, int]:
        """Match count per evidence tier, for auditing how the join was made."""
        counts = dict.fromkeys(MatchTier, 0)
        for match in self.matches:
            counts[match.via] += 1
        return counts

    @computed_field  # type: ignore[prop-decorator]
    @property
    def by_failure(self) -> dict[MatchFailure, int]:
        """Failure count per reason. The actionable half of a poor match rate."""
        counts = dict.fromkeys(MatchFailure, 0)
        for failure in self.failures:
            counts[failure.reason] += 1
        return counts


class GscPageMetrics(StrictModel):
    """Search Console metrics for one page. Pre-click demand.

    Attributes:
        url: The URL as Search Console reported it, kept verbatim so a
            reconciliation can show what was uploaded rather than what we made
            of it.
        clicks: Sessions Google sent. Sums correctly.
        impressions: Times the page appeared in a result set. Sums correctly.
        position: Average position **as reported for this row**. Does not sum,
            and does not average unweighted — a section's position is the
            impression-weighted mean, computed where the weights are known.
    """

    url: str = Field(min_length=1)
    clicks: int = Field(default=0, ge=0)
    impressions: int = Field(default=0, ge=0)
    position: float = Field(default=0.0, ge=0.0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ctr(self) -> float:
        """Clicks per impression, derived rather than stored.

        Zero impressions gives 0.0 rather than raising: a Search Console export
        can contain such a row, and it is not an error condition.
        """
        if self.impressions == 0:
            return 0.0
        return self.clicks / self.impressions


class Ga4PageMetrics(StrictModel):
    """GA4 metrics for one page path. Post-click behaviour.

    GA4 reports a `pagePath`, not a URL — the host is a property setting, not
    part of the row. That asymmetry with Search Console is the reason the
    resolution index carries a path map at all.

    Attributes:
        path: `pagePath` exactly as exported, including any query string.
        sessions: Sessions that included a view of this page.
        engaged_sessions: Sessions GA4 counted as engaged.
        engagement_time_sec: Total engagement seconds, not an average — an
            average cannot be re-aggregated into a section.
        conversions: Key events. A float because GA4 permits fractional values
            on some event-count models, not because a count can be fractional.
        revenue: Attributed revenue in the property's reporting currency, which
            this model does not carry and therefore must not be summed across
            properties.
    """

    path: str = Field(min_length=1)
    sessions: int = Field(default=0, ge=0)
    engaged_sessions: int = Field(default=0, ge=0)
    engagement_time_sec: float = Field(default=0.0, ge=0.0)
    conversions: float = Field(default=0.0, ge=0.0)
    revenue: float = Field(default=0.0, ge=0.0)


class PagePerformance(StrictModel):
    """Everything known about one crawled page's performance.

    Attributes:
        page_url: The crawled address, which is the key the site graph already
            uses. No new page identity is invented here — inventing one is how
            two halves of a dashboard start disagreeing about a page count.
        gsc: Search Console metrics, or `None` when no export row resolved to
            this page. Distinct from a row of zeroes.
        ga4: GA4 metrics, or `None` on the same terms.
    """

    page_url: str = Field(min_length=1)
    gsc: GscPageMetrics | None = None
    ga4: Ga4PageMetrics | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_data(self) -> bool:
        """Whether any source resolved to this page."""
        return self.gsc is not None or self.ga4 is not None
