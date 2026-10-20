"""A partial page-level Search Console fetch is recorded, and its rows are still applied."""

from __future__ import annotations

from unittest.mock import Mock, patch

from src.integrations.gsc_schemas import GscAnalyticsResponse, GscPageMetrics
from src.modules.seo.page_classifier.schemas import FullPageIntelligenceProfile
from src.modules.seo.page_classifier.tool import (
    GscEnrichmentReport,
    PageClassificationInput,
    PageClassificationTool,
)
from tests.modules.seo.page_classifier.report_profile_factory import make_page


def _enrich(
    response: GscAnalyticsResponse,
) -> tuple[tuple[FullPageIntelligenceProfile, ...], GscEnrichmentReport]:
    tool = PageClassificationTool()
    page = make_page("https://example.com/products/shoes")
    payload = PageClassificationInput(
        base_url="https://example.com",
        gsc_property_url="https://example.com",
    )
    with patch("src.modules.seo.page_classifier.tool.GscApiClient") as mock_client:
        mock_client.return_value = Mock(fetch_analytics=Mock(return_value=response))
        return tool._enrich_with_gsc((page,), payload)


def _metric() -> GscPageMetrics:
    return GscPageMetrics(
        url="https://example.com/products/shoes",
        clicks=42,
        impressions=500,
        avg_position=3.5,
        ctr=0.084,
    )


def test_a_partial_fetch_keeps_its_rows_and_marks_the_report_incomplete() -> None:
    response = GscAnalyticsResponse(
        property_url="https://example.com/",
        start_date="2026-01-01",
        end_date="2026-12-31",
        rows=[_metric()],
        complete=False,
        stop_reason="fetch_failed",
    )

    pages, report = _enrich(response)

    assert pages[0].gsc_clicks == 42
    assert report.status == "succeeded"
    assert report.complete is False


def test_a_complete_fetch_is_marked_complete() -> None:
    response = GscAnalyticsResponse(
        property_url="https://example.com/",
        start_date="2026-01-01",
        end_date="2026-12-31",
        rows=[_metric()],
    )

    _pages, report = _enrich(response)

    assert report.complete is True
