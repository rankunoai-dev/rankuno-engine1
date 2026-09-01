"""Tests for GSC integration in the crawl tool (Phase 6)."""

from unittest.mock import Mock, patch

import pytest
from src.integrations.gsc_schemas import GscAnalyticsResponse, GscPageMetrics
from src.modules.seo.page_classifier.schemas import (
    ConsensusMethod,
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
    SearchIntent,
    SignalScore,
    SignalSource,
)
from src.modules.seo.page_classifier.tool import PageClassificationInput, PageClassificationTool


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
def tool() -> PageClassificationTool:
    """Create tool instance."""
    return PageClassificationTool()


class TestGscEnrichmentSuccess:
    """Test successful GSC enrichment."""

    def test_enrichment_populates_gsc_fields(self, tool, sample_page):
        """GSC enrichment populates gsc_* fields on matched pages."""
        metric = GscPageMetrics(
            url="https://example.com/products/shoes",
            clicks=42,
            impressions=500,
            avg_position=3.5,
            ctr=0.084,
        )
        response = GscAnalyticsResponse(
            property_url="https://example.com",
            start_date="2026-01-01",
            end_date="2026-12-31",
            rows=[metric],
        )

        payload = PageClassificationInput(
            base_url="https://example.com",
            gsc_property_url="https://example.com",
        )

        with patch("src.modules.seo.page_classifier.tool.GscApiClient") as mock_client:
            mock_instance = Mock()
            mock_instance.fetch_analytics.return_value = response
            mock_client.return_value = mock_instance

            enriched_pages = tool._enrich_with_gsc((sample_page,), payload)

        assert len(enriched_pages) == 1
        page = enriched_pages[0]
        assert page.gsc_clicks == 42
        assert page.gsc_impressions == 500
        assert page.gsc_avg_position == 3.5
        assert page.gsc_ctr == 0.084

    def test_unmatched_pages_have_null_signals(self, tool, sample_page):
        """Pages without GSC matches have null GSC fields."""
        response = GscAnalyticsResponse(
            property_url="https://example.com",
            start_date="2026-01-01",
            end_date="2026-12-31",
            rows=[],  # No metrics
        )

        payload = PageClassificationInput(
            base_url="https://example.com",
            gsc_property_url="https://example.com",
        )

        with patch("src.modules.seo.page_classifier.tool.GscApiClient") as mock_client:
            mock_instance = Mock()
            mock_instance.fetch_analytics.return_value = response
            mock_client.return_value = mock_instance

            enriched_pages = tool._enrich_with_gsc((sample_page,), payload)

        assert len(enriched_pages) == 1
        page = enriched_pages[0]
        assert page.gsc_clicks is None
        assert page.gsc_impressions is None
        assert page.gsc_avg_position is None
        assert page.gsc_ctr is None


class TestGscEnrichmentDisabled:
    """Test behavior when GSC enrichment is disabled."""

    def test_no_enrichment_without_property_url(self, tool, sample_page):
        """Without gsc_property_url, pages returned unchanged."""
        payload = PageClassificationInput(
            base_url="https://example.com",
            gsc_property_url=None,
        )

        enriched_pages = tool._enrich_with_gsc((sample_page,), payload)

        assert len(enriched_pages) == 1
        assert enriched_pages[0] is sample_page  # Same object
        assert enriched_pages[0].gsc_clicks is None


class TestGscEnrichmentErrorHandling:
    """Test graceful degradation on GSC errors."""

    def test_api_client_error_returns_unchanged_pages(self, tool, sample_page):
        """If GscApiClient raises, return pages unchanged with warning logged."""
        payload = PageClassificationInput(
            base_url="https://example.com",
            gsc_property_url="https://example.com",
        )

        with patch("src.modules.seo.page_classifier.tool.GscApiClient") as mock_client:
            mock_instance = Mock()
            mock_instance.fetch_analytics.side_effect = RuntimeError("Network error")
            mock_client.return_value = mock_instance

            enriched_pages = tool._enrich_with_gsc((sample_page,), payload)

        # Pages returned unchanged
        assert len(enriched_pages) == 1
        assert enriched_pages[0].gsc_clicks is None

    def test_validation_failure_returns_unchanged_pages(self, tool, sample_page):
        """If property validation fails, return pages unchanged with warning logged."""
        response = GscAnalyticsResponse(
            property_url="https://other.com",
            start_date="2026-01-01",
            end_date="2026-12-31",
            rows=[],
        )

        payload = PageClassificationInput(
            base_url="https://example.com",
            gsc_property_url="https://other.com",
        )

        with patch("src.modules.seo.page_classifier.tool.GscApiClient") as mock_client:
            mock_instance = Mock()
            mock_instance.fetch_analytics.return_value = response
            mock_client.return_value = mock_instance

            with patch("src.modules.seo.page_classifier.tool.GscMetricsAggregator") as mock_agg:
                mock_agg_instance = Mock()
                mock_agg_instance.aggregate.return_value = Mock(
                    validation_error="Domain mismatch: other.com vs example.com",
                    matched_pages=[],
                    unmatched_gsc_urls=[],
                    unmatched_crawl_pages=[sample_page],
                )
                mock_agg.return_value = mock_agg_instance

                enriched_pages = tool._enrich_with_gsc((sample_page,), payload)

        # Pages returned unchanged due to validation error
        assert len(enriched_pages) == 1
        assert enriched_pages[0].gsc_clicks is None


class TestGscEnrichmentMultiplePages:
    """Test enrichment with multiple pages."""

    def test_enrichment_mixed_matched_unmatched(self, tool):
        """Enrichment handles both matched and unmatched pages."""
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

        metric = GscPageMetrics(
            url="https://example.com/products",
            clicks=100,
            impressions=1000,
            avg_position=2.0,
            ctr=0.1,
        )
        response = GscAnalyticsResponse(
            property_url="https://example.com",
            start_date="2026-01-01",
            end_date="2026-12-31",
            rows=[metric],
        )

        payload = PageClassificationInput(
            base_url="https://example.com",
            gsc_property_url="https://example.com",
        )

        with patch("src.modules.seo.page_classifier.tool.GscApiClient") as mock_client:
            mock_instance = Mock()
            mock_instance.fetch_analytics.return_value = response
            mock_client.return_value = mock_instance

            enriched_pages = tool._enrich_with_gsc((page1, page2), payload)

        assert len(enriched_pages) == 2

        # page1 matched
        assert enriched_pages[0].url == "https://example.com/products"
        assert enriched_pages[0].gsc_clicks == 100

        # page2 unmatched
        assert enriched_pages[1].url == "https://example.com/blog"
        assert enriched_pages[1].gsc_clicks is None


class TestGscEnrichmentAggregation:
    """Test metric aggregation during enrichment."""

    def test_multiple_gsc_urls_aggregated(self, tool, sample_page):
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
            end_date="2026-12-31",
            rows=metrics,
        )

        payload = PageClassificationInput(
            base_url="https://example.com",
            gsc_property_url="https://example.com",
        )

        with patch("src.modules.seo.page_classifier.tool.GscApiClient") as mock_client:
            mock_instance = Mock()
            mock_instance.fetch_analytics.return_value = response
            mock_client.return_value = mock_instance

            enriched_pages = tool._enrich_with_gsc((sample_page,), payload)

        assert len(enriched_pages) == 1
        page = enriched_pages[0]
        assert page.gsc_clicks == 35  # 20 + 15
        assert page.gsc_impressions == 450  # 300 + 150
