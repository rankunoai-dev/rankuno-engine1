"""Pydantic schemas for Google Search Console API request/response data.

All responses from GSC API are validated against these models. Strict mode
ensures no unexpected fields slip through, preventing silent data loss.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, SecretStr, model_validator

from src.core.schemas import StrictModel

__all__ = [
    "GscAnalyticsRequest",
    "GscAnalyticsResponse",
    "GscOAuthToken",
    "GscPageMetrics",
    "GscPageQueries",
    "GscPropertyValidationResult",
    "GscProperty",
    "GscQueryMetrics",
    "GscQueryRow",
    "GscStopReason",
]

GscStopReason = Literal["exhausted", "row_cap", "fetch_failed"]
"""Why a paged Search Console fetch stopped.

`exhausted` is the only answer that means every row was read: the last page came
back short. `row_cap` means the page limit was reached while full pages were still
arriving, so rows past it exist and were never asked for. `fetch_failed` means a
page request failed after retries; the rows received before it are kept, never
discarded, and the result is marked incomplete.
"""


def _complete_matches_reason(complete: bool, stop_reason: GscStopReason) -> None:
    """Reject a result that says it is complete while stopping for any other reason.

    The flag and the reason are two fields for one fact. Letting them disagree
    would let a consumer show "complete" over a fetch that stopped at its cap.
    """
    if complete != (stop_reason == "exhausted"):
        msg = f"complete={complete} contradicts stop_reason={stop_reason!r}"
        raise ValueError(msg)


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
        description="Rows received across every page fetched (len(rows) before parsing)",
    )
    complete: bool = Field(
        default=True,
        description="False when paging stopped before the last short page; rows are partial",
    )
    stop_reason: GscStopReason = Field(
        default="exhausted",
        description="Why paging stopped; see GscStopReason",
    )

    @model_validator(mode="after")
    def _flag_matches_reason(self) -> GscAnalyticsResponse:
        """Keep `complete` and `stop_reason` from disagreeing."""
        _complete_matches_reason(self.complete, self.stop_reason)
        return self


class GscQueryRow(StrictModel):
    """One (page, query) pair from a Search Console query-by-page fetch."""

    page: str = Field(
        ..., description="Absolute URL the query led to, as Search Console reports it"
    )
    query: str = Field(..., description="Search query text, as Search Console reports it")
    clicks: int = Field(ge=0, description="Clicks for this query on this page")
    impressions: int = Field(ge=0, description="Impressions for this query on this page")
    avg_position: float = Field(
        ge=0.0,
        description="Average position for this query on this page. Not clamped to 1.0: a "
        "malformed row must reach the export as-is rather than be quietly corrected.",
    )


class GscPageQueries(StrictModel):
    """Every (page, query) row a Search Console fetch received, with how it ended.

    Stored on the job sidecar and read by the URL exports. The rows are kept as
    received; ranking the top queries per URL happens at export, so this model
    is a record of what was fetched, not a view of it.
    """

    property_url: str = Field(..., description="The property queried, as sent to the API")
    start_date: str = Field(..., description="Date range start (YYYY-MM-DD), inclusive")
    end_date: str = Field(..., description="Date range end (YYYY-MM-DD), inclusive")
    rows: list[GscQueryRow] = Field(
        default_factory=list,
        description="Every row received, across all pages, in the order received",
    )
    complete: bool = Field(..., description="True only when the last page came back short")
    stop_reason: GscStopReason = Field(..., description="Why paging stopped")
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the fetch finished (UTC)",
    )

    @model_validator(mode="after")
    def _flag_matches_reason(self) -> GscPageQueries:
        """Keep `complete` and `stop_reason` from disagreeing."""
        _complete_matches_reason(self.complete, self.stop_reason)
        return self


class GscOAuthToken(StrictModel):
    """OAuth 2.0 token state for GSC API access."""

    access_token: SecretStr = Field(
        ...,
        description=(
            "Access token (bearer token for API calls). SecretStr so a state dump "
            "written to a log masks it."
        ),
    )
    refresh_token: SecretStr | None = Field(
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
        description="Type of match: 'exact', 'subdomain', 'prefix', 'domain', or empty if invalid",
    )
    reason: str = Field(
        ...,
        description="Human-readable explanation: why it matched or didn't match",
    )
