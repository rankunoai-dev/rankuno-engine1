"""Tests for GSC API schemas and data validation."""

from datetime import datetime, timedelta

import pytest
from src.integrations.gsc_schemas import (
    GscAnalyticsResponse,
    GscOAuthToken,
    GscPageMetrics,
    GscProperty,
    GscQueryMetrics,
)


class TestGscPageMetrics:
    """Validate GscPageMetrics schema."""

    def test_valid_page_metrics(self):
        """Valid page metrics are accepted."""
        metrics = GscPageMetrics(
            url="https://example.com/about",
            impressions=150,
            clicks=12,
            avg_position=5.2,
            ctr=0.08,
        )
        assert metrics.url == "https://example.com/about"
        assert metrics.impressions == 150
        assert metrics.clicks == 12
        assert metrics.avg_position == 5.2
        assert metrics.ctr == 0.08

    def test_zero_impressions(self):
        """Zero impressions is valid (no search traffic)."""
        metrics = GscPageMetrics(
            url="https://example.com/page",
            impressions=0,
            clicks=0,
            avg_position=1.0,
            ctr=0.0,
        )
        assert metrics.impressions == 0
        assert metrics.ctr == 0.0

    def test_ctr_clamped_to_range(self):
        """CTR must be in [0, 1]."""
        # Valid: exactly at boundaries
        GscPageMetrics(
            url="https://example.com/",
            impressions=100,
            clicks=0,
            avg_position=1.0,
            ctr=0.0,
        )
        GscPageMetrics(
            url="https://example.com/",
            impressions=100,
            clicks=100,
            avg_position=1.0,
            ctr=1.0,
        )

        # Invalid: outside range
        with pytest.raises(ValueError):
            GscPageMetrics(
                url="https://example.com/",
                impressions=100,
                clicks=150,
                avg_position=1.0,
                ctr=1.5,
            )

    def test_avg_position_ge_1(self):
        """Position must be >= 1.0 (you can't rank 0th)."""
        with pytest.raises(ValueError):
            GscPageMetrics(
                url="https://example.com/",
                impressions=10,
                clicks=1,
                avg_position=0.5,
                ctr=0.1,
            )

    def test_negative_impressions_rejected(self):
        """Impressions cannot be negative."""
        with pytest.raises(ValueError):
            GscPageMetrics(
                url="https://example.com/",
                impressions=-5,
                clicks=0,
                avg_position=1.0,
                ctr=0.0,
            )


class TestGscQueryMetrics:
    """Validate GscQueryMetrics schema."""

    def test_valid_query_metrics(self):
        """Valid query metrics are accepted."""
        metrics = GscQueryMetrics(
            query="best seo tools",
            url="https://example.com/tools",
            impressions=50,
            clicks=5,
            avg_position=8.5,
            ctr=0.1,
            country="US",
        )
        assert metrics.query == "best seo tools"
        assert metrics.country == "US"

    def test_country_optional(self):
        """Country code defaults to empty string."""
        metrics = GscQueryMetrics(
            query="seo",
            url="https://example.com/",
            impressions=100,
            clicks=10,
            avg_position=2.0,
            ctr=0.1,
        )
        assert metrics.country == ""


class TestGscProperty:
    """Validate GscProperty schema."""

    def test_domain_property(self):
        """Domain property type."""
        prop = GscProperty(
            url="https://example.com",
            property_type="DOMAIN",
        )
        assert prop.url == "https://example.com"
        assert prop.property_type == "DOMAIN"

    def test_url_prefix_property(self):
        """URL-prefix property type."""
        prop = GscProperty(
            url="https://example.com/blog/",
            property_type="URL_PREFIX",
        )
        assert prop.property_type == "URL_PREFIX"


class TestGscOAuthToken:
    """Validate GscOAuthToken schema."""

    def test_valid_token(self):
        """Valid OAuth token is accepted."""
        expires = datetime.utcnow() + timedelta(hours=1)
        token = GscOAuthToken(
            access_token="ya29.a0AfH6SMB...",  # noqa: S106
            refresh_token="1//0gF...",  # noqa: S106
            expires_at=expires,
            scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
        )
        assert token.token_type == "Bearer"  # noqa: S105
        assert token.scopes[0].endswith("webmasters.readonly")

    def test_token_type_defaults_to_bearer(self):
        """Token type defaults to Bearer."""
        token = GscOAuthToken(
            access_token="token",  # noqa: S106
            expires_at=datetime.utcnow(),
        )
        assert token.token_type == "Bearer"  # noqa: S105

    def test_refresh_token_optional(self):
        """Refresh token is optional (can be None)."""
        token = GscOAuthToken(
            access_token="token",  # noqa: S106
            expires_at=datetime.utcnow(),
        )
        assert token.refresh_token is None


class TestGscAnalyticsResponse:
    """Validate GscAnalyticsResponse schema."""

    def test_empty_response(self):
        """Empty response (no rows) is valid."""
        response = GscAnalyticsResponse(
            property_url="https://example.com",
            start_date="2026-08-01",
            end_date="2026-08-31",
        )
        assert response.rows == []
        assert response.rows_available == 0

    def test_response_with_metrics(self):
        """Response with multiple page metrics."""
        response = GscAnalyticsResponse(
            property_url="https://example.com",
            start_date="2026-08-01",
            end_date="2026-08-31",
            rows=[
                GscPageMetrics(
                    url="https://example.com/",
                    impressions=500,
                    clicks=50,
                    avg_position=2.1,
                    ctr=0.1,
                ),
                GscPageMetrics(
                    url="https://example.com/about",
                    impressions=200,
                    clicks=20,
                    avg_position=3.5,
                    ctr=0.1,
                ),
            ],
            rows_available=2,
        )
        assert len(response.rows) == 2
        assert response.rows_available == 2
        assert response.rows[0].impressions == 500

    def test_fetched_at_defaults_to_now(self):
        """fetched_at defaults to current UTC time."""
        before = datetime.utcnow()
        response = GscAnalyticsResponse(
            property_url="https://example.com",
            start_date="2026-08-01",
            end_date="2026-08-31",
        )
        after = datetime.utcnow()

        assert before <= response.fetched_at <= after
