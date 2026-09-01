"""GSC metrics aggregation and enrichment.

Joins Google Search Console analytics to crawled pages by URL, enriching each page
with GSC signals (clicks, position, CTR, impressions). Handles URL normalization,
conflict resolution (multiple matches), and graceful degradation on errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from src.core.logger import get_logger
from src.integrations.gsc_property_validator import GscPropertyValidator
from src.integrations.gsc_schemas import GscAnalyticsResponse, GscPageMetrics
from src.modules.seo.page_classifier.schemas import FullPageIntelligenceProfile

__all__ = ["GscMetricsAggregator", "EnrichedPageWithMetrics", "AggregationResult"]

_logger = get_logger("page_classifier.gsc_aggregator")


@dataclass
class GscSignals:
    """GSC metrics attached to a crawled page."""

    clicks: int
    impressions: int
    avg_position: float
    ctr: float

    @classmethod
    def from_metrics(cls, metrics: GscPageMetrics) -> GscSignals:
        """Create from a single GSC page metric."""
        return cls(
            clicks=metrics.clicks,
            impressions=metrics.impressions,
            avg_position=metrics.avg_position,
            ctr=metrics.ctr,
        )

    @classmethod
    def aggregate(cls, metrics_list: list[GscPageMetrics]) -> GscSignals:
        """Aggregate multiple GSC metrics into one.

        When multiple GSC URLs match a single crawled page, sum clicks/impressions
        and compute weighted average position.
        """
        if not metrics_list:
            return cls(clicks=0, impressions=0, avg_position=1.0, ctr=0.0)

        total_clicks = sum(m.clicks for m in metrics_list)
        total_impressions = sum(m.impressions for m in metrics_list)
        total_ctr = total_clicks / total_impressions if total_impressions > 0 else 0.0

        # Weighted average position (by impressions)
        if total_impressions > 0:
            weighted_position = (
                sum(m.avg_position * m.impressions for m in metrics_list) / total_impressions
            )
        else:
            weighted_position = 1.0

        return cls(
            clicks=total_clicks,
            impressions=total_impressions,
            avg_position=weighted_position,
            ctr=total_ctr,
        )


@dataclass
class EnrichedPageWithMetrics:
    """A crawled page with attached GSC metrics."""

    page: FullPageIntelligenceProfile
    gsc_signals: GscSignals | None
    match_type: str  # "exact", "prefix", or ""
    matched_gsc_urls: list[str]  # URLs that matched this page


@dataclass
class AggregationResult:
    """Result of GSC-to-crawl aggregation."""

    matched_pages: list[EnrichedPageWithMetrics]
    unmatched_gsc_urls: list[str]
    unmatched_crawl_pages: list[FullPageIntelligenceProfile]
    validation_error: str | None = None


class GscMetricsAggregator:
    """Join GSC analytics to crawled pages by URL.

    Validates property-crawl compatibility using Phase 4 validator, matches GSC
    URLs to crawled pages (exact + prefix matching), aggregates conflicting metrics,
    and returns enriched pages with GSC signals.

    Design note: URL matching is greedy (first match wins) to prevent ambiguity.
    """

    def __init__(self) -> None:
        """Initialize aggregator with URL validator."""
        self._validator = GscPropertyValidator()

    def aggregate(
        self,
        gsc_property_url: str,
        crawl_base_url: str,
        gsc_response: GscAnalyticsResponse,
        crawled_pages: list[FullPageIntelligenceProfile],
    ) -> AggregationResult:
        """Aggregate GSC metrics to crawled pages.

        Args:
            gsc_property_url: GSC property being queried
            crawl_base_url: Base URL of the crawl
            gsc_response: Analytics response from Phase 3 API client
            crawled_pages: Pages from the classification pipeline

        Returns:
            AggregationResult with matched pages, unmatched URLs/pages, and any errors
        """
        # Step 1: Validate property matches crawl base
        validation = self._validator.validate(gsc_property_url, crawl_base_url)
        if not validation.is_valid:
            _logger.warning(
                "gsc_property_validation_failed",
                extra={"reason": validation.reason},
            )
            return AggregationResult(
                matched_pages=[],
                unmatched_gsc_urls=[m.url for m in gsc_response.rows],
                unmatched_crawl_pages=crawled_pages,
                validation_error=validation.reason,
            )

        # Step 2: Build URL -> Page index for fast lookup
        page_by_url = {page.url: page for page in crawled_pages}

        # Step 3: Match GSC URLs to pages
        matched_pages: dict[str, list[GscPageMetrics]] = {}
        unmatched_gsc_urls: list[str] = []

        for metric in gsc_response.rows:
            page = self._find_matching_page(metric.url, page_by_url)
            if page:
                page_url = page.url
                if page_url not in matched_pages:
                    matched_pages[page_url] = []
                matched_pages[page_url].append(metric)
            else:
                unmatched_gsc_urls.append(metric.url)

        # Step 4: Build enriched pages
        enriched_pages: list[EnrichedPageWithMetrics] = []
        matched_page_urls = set()

        for page in crawled_pages:
            if page.url in matched_pages:
                metrics_list = matched_pages[page.url]
                signals = GscSignals.aggregate(metrics_list)
                enriched = EnrichedPageWithMetrics(
                    page=page,
                    gsc_signals=signals,
                    match_type="exact",
                    matched_gsc_urls=[m.url for m in metrics_list],
                )
                enriched_pages.append(enriched)
                matched_page_urls.add(page.url)
            else:
                enriched = EnrichedPageWithMetrics(
                    page=page,
                    gsc_signals=None,
                    match_type="",
                    matched_gsc_urls=[],
                )
                enriched_pages.append(enriched)

        # Step 5: Identify unmatched crawl pages
        unmatched_crawl_pages = [
            page for page in crawled_pages if page.url not in matched_page_urls
        ]

        return AggregationResult(
            matched_pages=enriched_pages,
            unmatched_gsc_urls=unmatched_gsc_urls,
            unmatched_crawl_pages=unmatched_crawl_pages,
        )

    def _find_matching_page(
        self,
        gsc_url: str,
        page_by_url: dict[str, FullPageIntelligenceProfile],
    ) -> FullPageIntelligenceProfile | None:
        """Find a matching crawled page for a GSC URL.

        Matching strategy (in order):
        1. Exact match — GSC URL == page URL (after normalization)
        2. Prefix match — GSC URL is path prefix of page URL
        3. No match

        Args:
            gsc_url: URL from GSC metrics
            page_by_url: Crawled pages indexed by URL

        Returns:
            Matching page or None if no match found
        """
        # Try exact match first
        if gsc_url in page_by_url:
            return page_by_url[gsc_url]

        # Try normalized exact match (trailing slash)
        normalized_gsc = self._normalize_url(gsc_url)
        for page_url, page in page_by_url.items():
            if self._normalize_url(page_url) == normalized_gsc:
                return page

        # Try prefix match: GSC URL could be a parent path of crawled page
        gsc_normalized = self._normalize_path(normalized_gsc)
        for page_url, page in page_by_url.items():
            page_normalized = self._normalize_path(self._normalize_url(page_url))
            if page_normalized.startswith(gsc_normalized):
                return page

        return None

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize URL for comparison.

        - Strip fragment
        - Strip query parameters
        - Lowercase domain
        - Add trailing slash to path if missing
        """
        try:
            parsed = urlparse(url.lower())
        except Exception:
            return url

        # Reconstruct without fragment or query
        path = parsed.path or "/"
        if not path.endswith("/"):
            path = f"{path}/"

        return f"{parsed.scheme}://{parsed.netloc}{path}"

    @staticmethod
    def _normalize_path(url: str) -> str:
        """Extract and normalize path from URL."""
        try:
            parsed = urlparse(url)
            path = parsed.path or "/"
            if not path.endswith("/"):
                path = f"{path}/"
            return path
        except Exception:
            return "/"
