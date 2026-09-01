"""End-to-end integration tests for GSC pipeline (Phase 7)."""

import time
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


def create_page(url: str, depth: int = 0) -> FullPageIntelligenceProfile:
    """Factory for creating test pages."""
    # Determine page type based on URL
    if depth == 0:
        page_type = PrimaryPageType.HOMEPAGE
    elif "product" in url:
        page_type = PrimaryPageType.PRODUCT_DETAIL_PAGE
    elif "blog" in url:
        page_type = PrimaryPageType.BLOG_ARTICLE
    else:
        page_type = PrimaryPageType.SERVICE_DETAIL_PAGE  # Valid at L3_LEAF_PAGE

    return FullPageIntelligenceProfile(
        url=url,
        canonical_url=url,
        normalized_path=url.replace("https://example.com", ""),
        hierarchy_level=HierarchyLevel.L0_HOMEPAGE if depth == 0 else HierarchyLevel.L3_LEAF_PAGE,
        primary_page_type=page_type,
        depth_from_l0=depth,
        search_intent=SearchIntent.COMMERCIAL_INVESTIGATION,
        signals_evaluated=(
            SignalScore(
                source=SignalSource.SCHEMA_JSONLD,
                suggested_level=HierarchyLevel.L3_LEAF_PAGE,
                suggested_page_type=page_type,
                confidence=0.9,
            ),
        ),
        final_confidence_score=0.9,
        consensus_method=ConsensusMethod.LAYER1_STRUCTURAL,
    )


def create_metric(url: str, clicks: int = 10, impressions: int = 100) -> GscPageMetrics:
    """Factory for creating GSC metrics."""
    return GscPageMetrics(
        url=url,
        clicks=clicks,
        impressions=impressions,
        avg_position=3.0,
        ctr=clicks / impressions if impressions > 0 else 0.0,
    )


@pytest.fixture
def tool() -> PageClassificationTool:
    """Create tool instance."""
    return PageClassificationTool()


@pytest.fixture
def minimal_crawl() -> list[FullPageIntelligenceProfile]:
    """Minimal crawl: 1 page."""
    return [create_page("https://example.com/")]


@pytest.fixture
def medium_crawl() -> list[FullPageIntelligenceProfile]:
    """Medium crawl: 10 pages."""
    urls = [
        "https://example.com/",
        "https://example.com/products/shoes",
        "https://example.com/products/shirts",
        "https://example.com/blog/article-1",
        "https://example.com/blog/article-2",
        "https://example.com/about",
        "https://example.com/contact",
        "https://example.com/privacy",
        "https://example.com/terms",
        "https://example.com/sitemap",
    ]
    return [create_page(url, depth=i) for i, url in enumerate(urls)]


@pytest.fixture
def large_crawl() -> list[FullPageIntelligenceProfile]:
    """Large crawl: 100 pages."""
    pages = [create_page("https://example.com/")]
    for i in range(1, 100):
        pages.append(create_page(f"https://example.com/page-{i}", depth=1))
    return pages


class TestGscE2eSuccessPaths:
    """Test complete success flows."""

    def test_minimal_crawl_enrichment(self, tool, minimal_crawl):
        """Minimal crawl (1 page) → enrich → all fields populated."""
        metric = create_metric("https://example.com/", clicks=50, impressions=500)
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

            enriched = tool._enrich_with_gsc(tuple(minimal_crawl), payload)

        assert len(enriched) == 1
        page = enriched[0]
        assert page.gsc_clicks == 50
        assert page.gsc_impressions == 500
        assert page.gsc_avg_position == 3.0
        assert page.gsc_ctr == 0.1

    def test_medium_crawl_mixed_matching(self, tool, medium_crawl):
        """Medium crawl with partial matching: 5 matched, 5 unmatched."""
        metrics = [
            create_metric("https://example.com/", clicks=100),
            create_metric("https://example.com/products/shoes", clicks=50),
            create_metric("https://example.com/products/shirts", clicks=40),
            create_metric("https://example.com/blog/article-1", clicks=30),
            create_metric("https://example.com/blog/article-2", clicks=20),
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

            enriched = tool._enrich_with_gsc(tuple(medium_crawl), payload)

        assert len(enriched) == 10

        # First 5 should be enriched
        assert enriched[0].gsc_clicks == 100
        assert enriched[1].gsc_clicks == 50
        assert enriched[2].gsc_clicks == 40
        assert enriched[3].gsc_clicks == 30
        assert enriched[4].gsc_clicks == 20

        # Last 5 should be unmatched (null signals)
        for i in range(5, 10):
            assert enriched[i].gsc_clicks is None

    def test_large_crawl_performance(self, tool, large_crawl):
        """Large crawl (100 pages) → enrichment completes in < 500ms."""
        metrics = [create_metric(f"https://example.com/page-{i}", clicks=i) for i in range(1, 51)]
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

            start = time.time()
            enriched = tool._enrich_with_gsc(tuple(large_crawl), payload)
            elapsed = time.time() - start

        assert len(enriched) == 100
        assert elapsed < 0.5, f"Enrichment took {elapsed:.3f}s, expected < 0.5s"
        assert enriched[0].gsc_clicks is None  # Homepage unmatched
        assert enriched[1].gsc_clicks == 1  # page-1 matched


class TestGscE2eErrorHandling:
    """Test error paths don't crash the crawl."""

    def test_gsc_api_403_forbidden(self, tool, medium_crawl):
        """GSC API returns 403 (forbidden) → pages returned unchanged."""
        payload = PageClassificationInput(
            base_url="https://example.com",
            gsc_property_url="https://example.com",
        )

        with patch("src.modules.seo.page_classifier.tool.GscApiClient") as mock_client:
            mock_instance = Mock()
            mock_instance.fetch_analytics.side_effect = Exception("403 Forbidden")
            mock_client.return_value = mock_instance

            enriched = tool._enrich_with_gsc(tuple(medium_crawl), payload)

        # All pages returned unchanged
        assert len(enriched) == 10
        for page in enriched:
            assert page.gsc_clicks is None

    def test_gsc_api_429_quota_exceeded(self, tool, medium_crawl):
        """GSC API returns 429 (quota exceeded) → pages returned unchanged."""
        payload = PageClassificationInput(
            base_url="https://example.com",
            gsc_property_url="https://example.com",
        )

        with patch("src.modules.seo.page_classifier.tool.GscApiClient") as mock_client:
            mock_instance = Mock()
            mock_instance.fetch_analytics.side_effect = Exception("429 Quota Exceeded")
            mock_client.return_value = mock_instance

            enriched = tool._enrich_with_gsc(tuple(medium_crawl), payload)

        assert len(enriched) == 10
        for page in enriched:
            assert page.gsc_clicks is None

    def test_gsc_api_timeout(self, tool, medium_crawl):
        """GSC API timeout → pages returned unchanged."""
        payload = PageClassificationInput(
            base_url="https://example.com",
            gsc_property_url="https://example.com",
        )

        with patch("src.modules.seo.page_classifier.tool.GscApiClient") as mock_client:
            mock_instance = Mock()
            mock_instance.fetch_analytics.side_effect = TimeoutError("Request timeout")
            mock_client.return_value = mock_instance

            enriched = tool._enrich_with_gsc(tuple(medium_crawl), payload)

        assert len(enriched) == 10
        for page in enriched:
            assert page.gsc_clicks is None

    def test_property_validation_failure(self, tool, medium_crawl):
        """Property validation fails (domain mismatch) → pages returned unchanged."""
        response = GscAnalyticsResponse(
            property_url="https://other.com",
            start_date="2026-01-01",
            end_date="2026-12-31",
            rows=[create_metric("https://other.com/")],
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
                    validation_error="Domain mismatch",
                    matched_pages=[],
                    unmatched_gsc_urls=[],
                )
                mock_agg.return_value = mock_agg_instance

                enriched = tool._enrich_with_gsc(tuple(medium_crawl), payload)

        assert len(enriched) == 10
        for page in enriched:
            assert page.gsc_clicks is None


class TestGscE2eEdgeCases:
    """Test edge cases."""

    def test_no_gsc_metrics_available(self, tool, medium_crawl):
        """No GSC metrics → pages have null signals but are returned."""
        response = GscAnalyticsResponse(
            property_url="https://example.com",
            start_date="2026-01-01",
            end_date="2026-12-31",
            rows=[],  # Empty metrics
        )
        payload = PageClassificationInput(
            base_url="https://example.com",
            gsc_property_url="https://example.com",
        )

        with patch("src.modules.seo.page_classifier.tool.GscApiClient") as mock_client:
            mock_instance = Mock()
            mock_instance.fetch_analytics.return_value = response
            mock_client.return_value = mock_instance

            enriched = tool._enrich_with_gsc(tuple(medium_crawl), payload)

        assert len(enriched) == 10
        for page in enriched:
            assert page.gsc_clicks is None

    def test_partial_matching_5_of_10(self, tool, medium_crawl):
        """Partial matching: 5 matched, 5 unmatched."""
        metrics = [
            create_metric("https://example.com/", clicks=100),
            create_metric("https://example.com/products/shoes", clicks=50),
            create_metric("https://example.com/products/shirts", clicks=40),
            create_metric("https://example.com/blog/article-1", clicks=30),
            create_metric("https://example.com/blog/article-2", clicks=20),
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

            enriched = tool._enrich_with_gsc(tuple(medium_crawl), payload)

        # Count enriched vs unmatched
        enriched_count = sum(1 for p in enriched if p.gsc_clicks is not None)
        unmatched_count = sum(1 for p in enriched if p.gsc_clicks is None)

        assert enriched_count == 5
        assert unmatched_count == 5
        assert len(enriched) == 10

    def test_duplicate_gsc_urls_aggregation(self, tool, medium_crawl):
        """Multiple GSC URLs for same page → aggregation merges signals."""
        metrics = [
            create_metric("https://example.com/products/shoes", clicks=20, impressions=200),
            create_metric(
                "https://example.com/products/shoes?color=blue", clicks=15, impressions=150
            ),
            create_metric(
                "https://example.com/products/shoes?color=red", clicks=10, impressions=100
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

            enriched = tool._enrich_with_gsc(tuple(medium_crawl), payload)

        # Find shoes product page (should be index 1)
        shoes_page = enriched[1]
        assert shoes_page.url == "https://example.com/products/shoes"

        # Should have aggregated all three metrics
        assert shoes_page.gsc_clicks == 45  # 20 + 15 + 10
        assert shoes_page.gsc_impressions == 450  # 200 + 150 + 100


class TestGscE2eDataIntegrity:
    """Test data integrity across phases."""

    def test_enrichment_preserves_page_data(self, tool, medium_crawl):
        """Enrichment doesn't mutate other page fields."""
        metric = create_metric("https://example.com/", clicks=50)
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

        original_urls = [p.url for p in medium_crawl]

        with patch("src.modules.seo.page_classifier.tool.GscApiClient") as mock_client:
            mock_instance = Mock()
            mock_instance.fetch_analytics.return_value = response
            mock_client.return_value = mock_instance

            enriched = tool._enrich_with_gsc(tuple(medium_crawl), payload)

        # URLs unchanged
        enriched_urls = [p.url for p in enriched]
        assert enriched_urls == original_urls

        # Hierarchy, page type, depth unchanged
        for original, enriched_page in zip(medium_crawl, enriched, strict=True):
            assert enriched_page.hierarchy_level == original.hierarchy_level
            assert enriched_page.primary_page_type == original.primary_page_type
            assert enriched_page.depth_from_l0 == original.depth_from_l0

    def test_all_7_phases_together(self, tool):
        """All 7 phases: schemas → token → client → validator → aggregator → tool → tests."""
        # This is more of a smoke test; detailed tests are per-phase
        pages = [
            create_page("https://example.com/"),
            create_page("https://example.com/test", depth=1),
        ]

        metric = create_metric("https://example.com/", clicks=100)
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

            enriched = tool._enrich_with_gsc(tuple(pages), payload)

        # Both pages returned
        assert len(enriched) == 2

        # First page (homepage) enriched
        assert enriched[0].gsc_clicks == 100
        assert enriched[0].gsc_impressions == 100

        # Second page (test) unmatched
        assert enriched[1].gsc_clicks is None
