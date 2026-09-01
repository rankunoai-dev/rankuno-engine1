"""Tests for GSC metrics aggregation."""

from unittest.mock import Mock, patch

import pytest
from src.integrations.gsc_schemas import GscAnalyticsResponse, GscPageMetrics
from src.modules.seo.page_classifier.gsc_aggregator import GscMetricsAggregator, GscSignals
from src.modules.seo.page_classifier.schemas import (
    ConsensusMethod,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)


@pytest.fixture
def sample_page() -> FullPageIntelligenceProfile:
    """Create a sample crawled page profile."""
    return FullPageIntelligenceProfile(
        url="https://example.com/products/shoes",
        canonical_url="https://example.com/products/shoes",
        normalized_path="/products/shoes/",
        hierarchy_level=HierarchyLevel.L3_LEAF_PAGE,
        primary_page_type=PrimaryPageType.PRODUCT_DETAIL_PAGE,
        depth_from_l0=2,
        search_intent=SearchIntent.COMMERCIAL_INVESTIGATION,
        signals_evaluated=(
            SignalScore(
                source=SignalSource.SCHEMA_JSONLD,
                suggested_level=HierarchyLevel.L3_LEAF_PAGE,
                suggested_page_type=PrimaryPageType.PRODUCT_DETAIL_PAGE,
                confidence=0.95,
            ),
        ),
        final_confidence_score=0.95,
        consensus_method=ConsensusMethod.LAYER1_STRUCTURAL,
    )


@pytest.fixture
def sample_metric() -> GscPageMetrics:
    """Create a sample GSC metric."""
    return GscPageMetrics(
        url="https://example.com/products/shoes",
        clicks=42,
        impressions=500,
        avg_position=3.5,
        ctr=0.084,
    )


@pytest.fixture
def aggregator() -> GscMetricsAggregator:
    """Create aggregator instance."""
    return GscMetricsAggregator()


class TestGscSignals:
    """Test GscSignals dataclass."""

    def test_signals_from_single_metric(self, sample_metric):
        """GscSignals.from_metrics creates signals from one metric."""
        signals = GscSignals.from_metrics(sample_metric)

        assert signals.clicks == 42
        assert signals.impressions == 500
        assert signals.avg_position == 3.5
        assert signals.ctr == 0.084

    def test_signals_aggregate_multiple_metrics(self):
        """GscSignals.aggregate combines multiple metrics."""
        metrics = [
            GscPageMetrics(
                url="https://example.com/shoes",
                clicks=10,
                impressions=100,
                avg_position=4.0,
                ctr=0.1,
            ),
            GscPageMetrics(
                url="https://example.com/shoes?variant=blue",
                clicks=20,
                impressions=200,
                avg_position=2.0,
                ctr=0.1,
            ),
        ]

        signals = GscSignals.aggregate(metrics)

        assert signals.clicks == 30
        assert signals.impressions == 300
        assert signals.ctr == 0.1  # 30 / 300
        # Position: (4.0 * 100 + 2.0 * 200) / 300 = 2.666...
        assert abs(signals.avg_position - 2.6667) < 0.01

    def test_signals_aggregate_empty_list(self):
        """GscSignals.aggregate handles empty list."""
        signals = GscSignals.aggregate([])

        assert signals.clicks == 0
        assert signals.impressions == 0
        assert signals.avg_position == 1.0
        assert signals.ctr == 0.0

    def test_signals_aggregate_zero_impressions(self):
        """GscSignals.aggregate handles zero impressions."""
        metrics = [
            GscPageMetrics(
                url="https://example.com/no-clicks",
                clicks=0,
                impressions=0,
                avg_position=1.0,
                ctr=0.0,
            ),
        ]

        signals = GscSignals.aggregate(metrics)

        assert signals.ctr == 0.0
        assert signals.avg_position == 1.0


class TestExactMatching:
    """Test exact URL matching."""

    def test_exact_match_same_url(self, aggregator, sample_page, sample_metric):
        """Exact match when GSC URL == page URL."""
        response = GscAnalyticsResponse(
            property_url="https://example.com",
            start_date="2026-01-01",
            end_date="2026-01-31",
            rows=[sample_metric],
        )

        with patch.object(aggregator._validator, "validate") as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)

            result = aggregator.aggregate(
                gsc_property_url="https://example.com",
                crawl_base_url="https://example.com",
                gsc_response=response,
                crawled_pages=[sample_page],
            )

        assert len(result.matched_pages) == 1
        assert result.matched_pages[0].page.url == sample_page.url
        assert result.matched_pages[0].gsc_signals is not None
        assert result.matched_pages[0].gsc_signals.clicks == 42
        assert len(result.unmatched_gsc_urls) == 0

    def test_exact_match_with_query_params(self, aggregator, sample_page):
        """Exact match ignores query parameters in GSC URL."""
        metric_with_query = GscPageMetrics(
            url="https://example.com/products/shoes?utm_campaign=summer",
            clicks=10,
            impressions=100,
            avg_position=2.0,
            ctr=0.1,
        )
        response = GscAnalyticsResponse(
            property_url="https://example.com",
            start_date="2026-01-01",
            end_date="2026-01-31",
            rows=[metric_with_query],
        )

        with patch.object(aggregator._validator, "validate") as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)

            result = aggregator.aggregate(
                gsc_property_url="https://example.com",
                crawl_base_url="https://example.com",
                gsc_response=response,
                crawled_pages=[sample_page],
            )

        assert len(result.matched_pages) == 1
        assert result.matched_pages[0].gsc_signals is not None
        assert result.matched_pages[0].gsc_signals.clicks == 10


class TestPrefixMatching:
    """Test prefix path matching."""

    def test_prefix_match_gsc_parent_path(self, aggregator):
        """Prefix match when GSC URL is parent of page URL."""
        page = FullPageIntelligenceProfile(
            url="https://example.com/products/shoes/blue",
            canonical_url="https://example.com/products/shoes/blue",
            normalized_path="/products/shoes/blue/",
            hierarchy_level=HierarchyLevel.L3_LEAF_PAGE,
            primary_page_type=PrimaryPageType.PRODUCT_DETAIL_PAGE,
            depth_from_l0=3,
            search_intent=SearchIntent.COMMERCIAL_INVESTIGATION,
            signals_evaluated=(
                SignalScore(
                    source=SignalSource.SCHEMA_JSONLD,
                    suggested_level=HierarchyLevel.L3_LEAF_PAGE,
                    suggested_page_type=PrimaryPageType.PRODUCT_DETAIL_PAGE,
                    confidence=0.9,
                ),
            ),
            final_confidence_score=0.9,
            consensus_method=ConsensusMethod.LAYER1_STRUCTURAL,
        )

        metric = GscPageMetrics(
            url="https://example.com/products",
            clicks=50,
            impressions=600,
            avg_position=2.5,
            ctr=0.083,
        )
        response = GscAnalyticsResponse(
            property_url="https://example.com",
            start_date="2026-01-01",
            end_date="2026-01-31",
            rows=[metric],
        )

        with patch.object(aggregator._validator, "validate") as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)

            result = aggregator.aggregate(
                gsc_property_url="https://example.com",
                crawl_base_url="https://example.com",
                gsc_response=response,
                crawled_pages=[page],
            )

        assert len(result.matched_pages) == 1
        assert result.matched_pages[0].gsc_signals is not None
        assert result.matched_pages[0].gsc_signals.clicks == 50


class TestConflictResolution:
    """Test conflict resolution when multiple GSC URLs match one page."""

    def test_multiple_gsc_urls_same_page(self, aggregator, sample_page):
        """Multiple GSC URLs matching one page are aggregated."""
        metrics = [
            GscPageMetrics(
                url="https://example.com/products/shoes",
                clicks=20,
                impressions=300,
                avg_position=3.0,
                ctr=0.067,
            ),
            GscPageMetrics(
                url="https://example.com/products/shoes?sku=12345",
                clicks=15,
                impressions=150,
                avg_position=3.0,
                ctr=0.1,
            ),
        ]
        response = GscAnalyticsResponse(
            property_url="https://example.com",
            start_date="2026-01-01",
            end_date="2026-01-31",
            rows=metrics,
        )

        with patch.object(aggregator._validator, "validate") as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)

            result = aggregator.aggregate(
                gsc_property_url="https://example.com",
                crawl_base_url="https://example.com",
                gsc_response=response,
                crawled_pages=[sample_page],
            )

        assert len(result.matched_pages) == 1
        enriched = result.matched_pages[0]
        assert enriched.gsc_signals is not None
        assert enriched.gsc_signals.clicks == 35  # 20 + 15
        assert enriched.gsc_signals.impressions == 450  # 300 + 150


class TestURLNormalization:
    """Test URL normalization edge cases."""

    def test_normalize_trailing_slash_missing(self, aggregator, sample_page):
        """Normalization adds trailing slash to path."""
        metric = GscPageMetrics(
            url="https://example.com/products/shoes",
            clicks=5,
            impressions=50,
            avg_position=2.0,
            ctr=0.1,
        )
        response = GscAnalyticsResponse(
            property_url="https://example.com",
            start_date="2026-01-01",
            end_date="2026-01-31",
            rows=[metric],
        )

        with patch.object(aggregator._validator, "validate") as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)

            result = aggregator.aggregate(
                gsc_property_url="https://example.com",
                crawl_base_url="https://example.com",
                gsc_response=response,
                crawled_pages=[sample_page],
            )

        # Should still match despite trailing slash difference
        assert len(result.matched_pages) == 1
        assert result.matched_pages[0].gsc_signals is not None

    def test_normalize_case_insensitive_domain(self, aggregator):
        """Normalization is case-insensitive for domains."""
        page = FullPageIntelligenceProfile(
            url="https://Example.Com/Products/Shoes",
            canonical_url="https://Example.Com/Products/Shoes",
            normalized_path="/Products/Shoes/",
            hierarchy_level=HierarchyLevel.L3_LEAF_PAGE,
            primary_page_type=PrimaryPageType.PRODUCT_DETAIL_PAGE,
            depth_from_l0=2,
            search_intent=SearchIntent.COMMERCIAL_INVESTIGATION,
            signals_evaluated=(
                SignalScore(
                    source=SignalSource.SCHEMA_JSONLD,
                    suggested_level=HierarchyLevel.L3_LEAF_PAGE,
                    suggested_page_type=PrimaryPageType.PRODUCT_DETAIL_PAGE,
                    confidence=0.9,
                ),
            ),
            final_confidence_score=0.9,
            consensus_method=ConsensusMethod.LAYER1_STRUCTURAL,
        )

        metric = GscPageMetrics(
            url="https://example.com/products/shoes",
            clicks=8,
            impressions=80,
            avg_position=2.5,
            ctr=0.1,
        )
        response = GscAnalyticsResponse(
            property_url="https://example.com",
            start_date="2026-01-01",
            end_date="2026-01-31",
            rows=[metric],
        )

        with patch.object(aggregator._validator, "validate") as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)

            result = aggregator.aggregate(
                gsc_property_url="https://example.com",
                crawl_base_url="https://example.com",
                gsc_response=response,
                crawled_pages=[page],
            )

        assert len(result.matched_pages) == 1
        assert result.matched_pages[0].gsc_signals is not None


class TestPropertyValidation:
    """Test property validation failures."""

    def test_property_validation_fails(self, aggregator, sample_page, sample_metric):
        """When property validation fails, all GSC URLs are unmatched."""
        response = GscAnalyticsResponse(
            property_url="https://other.com",
            start_date="2026-01-01",
            end_date="2026-01-31",
            rows=[sample_metric],
        )

        with patch.object(aggregator._validator, "validate") as mock_validate:
            mock_validate.return_value = Mock(
                is_valid=False,
                reason="Domain mismatch: other.com vs example.com",
            )

            result = aggregator.aggregate(
                gsc_property_url="https://other.com",
                crawl_base_url="https://example.com",
                gsc_response=response,
                crawled_pages=[sample_page],
            )

        assert result.validation_error is not None
        assert "Domain mismatch" in result.validation_error
        assert len(result.matched_pages) == 0
        assert len(result.unmatched_gsc_urls) == 1
        assert len(result.unmatched_crawl_pages) == 1


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_gsc_metrics(self, aggregator, sample_page):
        """Empty GSC metrics returns all pages unmatched."""
        response = GscAnalyticsResponse(
            property_url="https://example.com",
            start_date="2026-01-01",
            end_date="2026-01-31",
            rows=[],
        )

        with patch.object(aggregator._validator, "validate") as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)

            result = aggregator.aggregate(
                gsc_property_url="https://example.com",
                crawl_base_url="https://example.com",
                gsc_response=response,
                crawled_pages=[sample_page],
            )

        assert len(result.matched_pages) == 1
        assert result.matched_pages[0].gsc_signals is None
        assert len(result.unmatched_crawl_pages) == 1

    def test_empty_crawl(self, aggregator, sample_metric):
        """Empty crawl returns all GSC URLs unmatched."""
        response = GscAnalyticsResponse(
            property_url="https://example.com",
            start_date="2026-01-01",
            end_date="2026-01-31",
            rows=[sample_metric],
        )

        with patch.object(aggregator._validator, "validate") as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)

            result = aggregator.aggregate(
                gsc_property_url="https://example.com",
                crawl_base_url="https://example.com",
                gsc_response=response,
                crawled_pages=[],
            )

        assert len(result.matched_pages) == 0
        assert len(result.unmatched_gsc_urls) == 1

    def test_no_matches_at_all(self, aggregator, sample_page):
        """No matches: all pages unmatched, all GSC URLs unmatched."""
        metric = GscPageMetrics(
            url="https://other.com/different/path",
            clicks=10,
            impressions=100,
            avg_position=2.0,
            ctr=0.1,
        )
        response = GscAnalyticsResponse(
            property_url="https://example.com",
            start_date="2026-01-01",
            end_date="2026-01-31",
            rows=[metric],
        )

        with patch.object(aggregator._validator, "validate") as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)

            result = aggregator.aggregate(
                gsc_property_url="https://example.com",
                crawl_base_url="https://example.com",
                gsc_response=response,
                crawled_pages=[sample_page],
            )

        assert len(result.matched_pages) == 1
        assert result.matched_pages[0].gsc_signals is None
        assert len(result.unmatched_gsc_urls) == 1
        assert len(result.unmatched_crawl_pages) == 1

    def test_mixed_matched_unmatched(self, aggregator):
        """Mix of matched and unmatched pages/URLs."""
        page1 = FullPageIntelligenceProfile(
            url="https://example.com/products",
            canonical_url="https://example.com/products",
            normalized_path="/products/",
            hierarchy_level=HierarchyLevel.L1_PRIMARY_NAV_HUB,
            primary_page_type=PrimaryPageType.PRODUCT_CATEGORY_HUB,
            depth_from_l0=1,
            search_intent=SearchIntent.COMMERCIAL_INVESTIGATION,
            signals_evaluated=(
                SignalScore(
                    source=SignalSource.SCHEMA_JSONLD,
                    suggested_level=HierarchyLevel.L1_PRIMARY_NAV_HUB,
                    suggested_page_type=PrimaryPageType.PRODUCT_CATEGORY_HUB,
                    confidence=0.9,
                ),
            ),
            final_confidence_score=0.9,
            consensus_method=ConsensusMethod.LAYER1_STRUCTURAL,
        )
        page2 = FullPageIntelligenceProfile(
            url="https://example.com/blog",
            canonical_url="https://example.com/blog",
            normalized_path="/blog/",
            hierarchy_level=HierarchyLevel.L1_PRIMARY_NAV_HUB,
            primary_page_type=PrimaryPageType.BLOG_HUB,
            depth_from_l0=1,
            search_intent=SearchIntent.INFORMATIONAL,
            signals_evaluated=(
                SignalScore(
                    source=SignalSource.ARIA_NAV_TREE,
                    suggested_level=HierarchyLevel.L1_PRIMARY_NAV_HUB,
                    suggested_page_type=PrimaryPageType.BLOG_HUB,
                    confidence=0.85,
                ),
            ),
            final_confidence_score=0.85,
            consensus_method=ConsensusMethod.LAYER1_STRUCTURAL,
        )

        metrics = [
            GscPageMetrics(
                url="https://example.com/products",
                clicks=100,
                impressions=1000,
                avg_position=2.0,
                ctr=0.1,
            ),
            GscPageMetrics(
                url="https://example.com/unknown",
                clicks=5,
                impressions=50,
                avg_position=5.0,
                ctr=0.1,
            ),
        ]
        response = GscAnalyticsResponse(
            property_url="https://example.com",
            start_date="2026-01-01",
            end_date="2026-01-31",
            rows=metrics,
        )

        with patch.object(aggregator._validator, "validate") as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)

            result = aggregator.aggregate(
                gsc_property_url="https://example.com",
                crawl_base_url="https://example.com",
                gsc_response=response,
                crawled_pages=[page1, page2],
            )

        # page1 matched, page2 unmatched
        assert len(result.matched_pages) == 2
        matched_with_signals = [p for p in result.matched_pages if p.gsc_signals]
        assert len(matched_with_signals) == 1
        assert matched_with_signals[0].page.url == "https://example.com/products"

        # One GSC URL unmatched
        assert len(result.unmatched_gsc_urls) == 1
        assert "unknown" in result.unmatched_gsc_urls[0]

        # One crawl page unmatched
        assert len(result.unmatched_crawl_pages) == 1
        assert result.unmatched_crawl_pages[0].url == "https://example.com/blog"


class TestEnrichedPageMetadata:
    """Test metadata on enriched pages."""

    def test_matched_gsc_urls_tracked(self, aggregator, sample_page):
        """Enriched pages track which GSC URLs matched them."""
        metrics = [
            GscPageMetrics(
                url="https://example.com/products/shoes",
                clicks=20,
                impressions=200,
                avg_position=2.0,
                ctr=0.1,
            ),
            GscPageMetrics(
                url="https://example.com/products/shoes?color=blue",
                clicks=10,
                impressions=100,
                avg_position=3.0,
                ctr=0.1,
            ),
        ]
        response = GscAnalyticsResponse(
            property_url="https://example.com",
            start_date="2026-01-01",
            end_date="2026-01-31",
            rows=metrics,
        )

        with patch.object(aggregator._validator, "validate") as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)

            result = aggregator.aggregate(
                gsc_property_url="https://example.com",
                crawl_base_url="https://example.com",
                gsc_response=response,
                crawled_pages=[sample_page],
            )

        enriched = result.matched_pages[0]
        assert len(enriched.matched_gsc_urls) == 2
        assert "https://example.com/products/shoes" in enriched.matched_gsc_urls
