"""Pydantic schemas for Google Search Console API request/response data.

All responses from GSC API are validated against these models. Strict mode
ensures no unexpected fields slip through, preventing silent data loss.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from src.core.schemas import StrictModel

__all__ = [
    "GscPageMetrics",
    "GscQueryMetrics",
    "GscAnalyticsRequest",
    "GscAnalyticsResponse",
    "GscOAuthToken",
    "GscProperty",
    "GscPropertyValidationResult",
]


class GscPageMetrics(StrictModel):
    """Page-level analytics from GSC: URL and aggregate search performance."""

    url: str = Field(..., description="Absolute URL of the page")
    impressions: int = Field(ge=0, description="Search impressions in the period")
    clicks: int = Field(ge=0, description="Clicks from search results")
    avg_position: float = Field(ge=1.0, description="Average position in search results")
    ctr: float = Field(
        ge=0.0,
        le=1.0,
        description="Click-through rate (clicks / impressions, clamped to [0, 1])",
    )


class GscQueryMetrics(StrictModel):
    """Query-level analytics: search term performance for a specific page.

    Maps to GSC "Search Analytics" with grouping by query.
    """

    query: str = Field(..., description="Search query text")
    url: str = Field(..., description="URL that the query led to")
    impressions: int = Field(ge=0, description="Impressions for this query-URL pair")
    clicks: int = Field(ge=0, description="Clicks for this query-URL pair")
    avg_position: float = Field(ge=1.0, description="Average position for this query")
    ctr: float = Field(
        ge=0.0,
        le=1.0,
        description="CTR for this query-URL pair",
    )
    country: str = Field(default="", description="2-letter country code, or empty if not filtered")


class GscProperty(StrictModel):
    """A GSC property (site) accessible to the authenticated account."""

    url: str = Field(
        ...,
        description="Property URL (e.g., https://example.com or https://example.com/path/)",
    )
    property_type: str = Field(
        ...,
        description="Type: 'DOMAIN' (entire domain), 'URL_PREFIX' (path-scoped)",
    )


class GscAnalyticsRequest(StrictModel):
    """Request parameters for GSC analytics query."""

    property_url: str = Field(
        ...,
        description="The GSC property URL to query (must be accessible to authenticated account)",
    )
    start_date: str = Field(
        ...,
        description="Start date (YYYY-MM-DD), inclusive",
    )
    end_date: str = Field(
        ...,
        description="End date (YYYY-MM-DD), inclusive",
    )
    row_limit: int = Field(
        default=10000,
        ge=1,
        le=25000,
        description="Max rows to return (GSC max is 25,000 per request)",
    )


class GscAnalyticsResponse(StrictModel):
    """Response from GSC analytics query: aggregated page metrics."""

    property_url: str = Field(..., description="The property queried")
    start_date: str = Field(..., description="Date range start (YYYY-MM-DD)")
    end_date: str = Field(..., description="Date range end (YYYY-MM-DD)")
    rows: list[GscPageMetrics] = Field(
        default_factory=list,
        description="Page-level metrics, sorted by impressions descending",
    )
    fetched_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When this response was fetched from GSC",
    )
    rows_available: int = Field(
        default=0,
        ge=0,
        description="Total rows available from GSC (may exceed len(rows) if row_limit was hit)",
    )


class GscOAuthToken(StrictModel):
    """OAuth 2.0 token state for GSC API access."""

    access_token: str = Field(..., description="Access token (bearer token for API calls)")
    refresh_token: str | None = Field(
        default=None,
        description="Refresh token (used to acquire new access token when expired)",
    )
    expires_at: datetime = Field(..., description="When the access token expires (UTC)")
    token_type: str = Field(default="Bearer", description="OAuth token type")
    scopes: list[str] = Field(
        default_factory=list,
        description="OAuth scopes granted (should contain 'https://www.googleapis.com/auth/webmasters.readonly')",
    )


class GscPropertyValidationResult(StrictModel):
    """Result of validating a GSC property against a crawl base URL."""

    is_valid: bool = Field(
        ...,
        description="True if property URL is compatible with crawl base URL",
    )
    match_type: str = Field(
        default="",
        description="Type of match: 'exact', 'subdomain', 'prefix', or empty if invalid",
    )
    reason: str = Field(
        ...,
        description="Human-readable explanation: why it matched or didn't match",
    )
