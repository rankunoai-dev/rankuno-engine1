"""Google Search Console API client.

Wraps the Google Search Console API with rate limiting, error handling, and
audit logging. All calls are protected by the BaseAPIClient framework.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from googleapiclient.discovery import build  # type: ignore[import-untyped]
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

from src.core.config import Settings
from src.core.errors import (
    GscApiDeprecatedError,
    GscAuthorizationError,
    GscPropertyNotFoundError,
    GscQuotaExceededError,
)
from src.core.logger import get_logger
from src.integrations.base_client import BaseAPIClient
from src.integrations.gsc_schemas import GscAnalyticsResponse, GscPageMetrics, GscProperty
from src.integrations.gsc_token_manager import GscTokenManager

__all__ = ["GscApiClient"]

_logger = get_logger("integrations.gsc_client")


class GscApiClient(BaseAPIClient):
    """Google Search Console API connector.

    Mandatory class vars (from BaseAPIClient):
    - `service_name` — audit log identity
    - `rate_limit_key` — shared quota bucket key
    - `requests_per_minute` — vendor's documented sustained limit

    Design:
    - All requests go through BaseAPIClient.call() which enforces rate limiting
    - Token refresh is handled by GscTokenManager; tokens are kept fresh before each call
    - Errors are mapped to specific exception types for upstream handling
    - Graceful degradation: property/fetch errors return empty data, not exceptions
    """

    service_name = "google.search_console"
    rate_limit_key = "gsc_quota"
    requests_per_minute = 60  # 2x headroom per property (120 QPM per property, 1200 total)

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize GSC API client.

        Args:
            settings: Configuration override, primarily for tests.

        Raises:
            ConfigurationError: If GSC credentials are missing.
        """
        super().__init__(settings=settings)

        self._token_manager = GscTokenManager(settings=self._settings)

        # Validate authentication immediately
        self.authenticate()

    def authenticate(self) -> None:
        """Acquire credentials and validate scope.

        Builds the Google Search Console service using credentials from the
        token manager. Validates that the authenticated account has the
        required read-only scope.

        Raises:
            GscAuthenticationError: If credentials cannot be loaded or validated.
            GscAuthorizationError: If scopes are incorrect.
        """
        # Validate that token manager has correct scopes
        self._token_manager.validate_scopes()

        # Build the Google API discovery service (lazy loads at first API call)
        # We'll build it on-demand in each API call to ensure token is fresh
        _logger.debug(
            "gsc_authenticated",
            extra={"account": self._token_manager.get_account_email()},
        )

    def _get_service(self) -> Any:
        """Get or create the GSC API service.

        Builds the Google API discovery service using credentials from the token manager.
        Service is created fresh each call to ensure token is always current.

        Returns:
            Google Webmasters (Search Console) API service object.
        """
        # Don't cache service; build fresh each time to ensure token is current
        token = self._token_manager.get_or_refresh_token()

        # Build credentials that wrap our token
        from google.oauth2.credentials import Credentials as OAuth2Credentials

        credentials = OAuth2Credentials(  # type: ignore[no-untyped-call]
            token=token,
            refresh_token=None,
            token_uri="https://oauth2.googleapis.com/token",  # noqa: S106
            client_id=None,
            client_secret=None,
        )

        return build(
            "webmasters",
            "v3",
            credentials=credentials,
            cache_discovery=False,
        )

    def list_accessible_properties(self) -> list[GscProperty]:
        """Fetch list of GSC properties accessible to the authenticated account.

        Returns:
            List of GscProperty objects (URL and type).

        Raises:
            GscAuthenticationError: If token is invalid (401).
            GscAuthorizationError: If user lacks access (403).
        """

        def attempt() -> list[GscProperty]:
            service = self._get_service()
            request = service.sites().list()
            response = request.execute()

            properties = []
            for site in response.get("siteEntry", []):
                properties.append(
                    GscProperty(
                        url=site.get("siteUrl", ""),
                        property_type=site.get("permissionLevel", "siteOwner"),
                    )
                )
            return properties

        try:
            return self.call("list_properties", attempt)
        except Exception as exc:
            _logger.exception(
                "gsc_list_properties_failed",
                extra={"error": str(exc)},
            )
            # Return empty list on error (graceful degradation)
            return []

    def fetch_analytics(
        self,
        property_url: str,
        start_date: str,
        end_date: str,
        row_limit: int = 10000,
    ) -> GscAnalyticsResponse:
        """Fetch search analytics for a GSC property.

        Queries the GSC API for page-level analytics (impressions, clicks, position, CTR)
        for the specified date range.

        Args:
            property_url: GSC property URL (e.g., "https://example.com/")
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            row_limit: Max rows to return (GSC max is 25,000 per request)

        Returns:
            GscAnalyticsResponse with page metrics, or empty response on error.

        Raises:
            GscPropertyNotFoundError: If property doesn't exist (404)
            GscAuthorizationError: If user lacks access (403)
            GscQuotaExceededError: If rate limited (429)
            GscApiDeprecatedError: If endpoint is deprecated (410, 501)
        """

        def attempt() -> GscAnalyticsResponse:
            try:
                service = self._get_service()

                # Ensure property URL ends with / for API call
                api_property_url = (
                    property_url if property_url.endswith("/") else f"{property_url}/"
                )

                request = service.searchanalytics().query(
                    siteUrl=api_property_url,
                    body={
                        "startDate": start_date,
                        "endDate": end_date,
                        "dimensions": ["page"],
                        "rowLimit": row_limit,
                    },
                )

                response = request.execute()

                # Parse response into GscAnalyticsResponse
                rows: list[GscPageMetrics] = []
                for row in response.get("rows", []):
                    keys = row.get("keys", [])
                    if not keys:
                        continue

                    url = keys[0]
                    impressions = int(row.get("impressions", 0))
                    clicks = int(row.get("clicks", 0))
                    position = float(row.get("position", 1.0))

                    # Calculate CTR, clamped to [0, 1]
                    ctr = (clicks / impressions) if impressions > 0 else 0.0
                    ctr = min(1.0, max(0.0, ctr))

                    rows.append(
                        GscPageMetrics(
                            url=url,
                            impressions=impressions,
                            clicks=clicks,
                            avg_position=position,
                            ctr=ctr,
                        )
                    )

                return GscAnalyticsResponse(
                    property_url=api_property_url,
                    start_date=start_date,
                    end_date=end_date,
                    rows=rows,
                    rows_available=len(rows),
                    fetched_at=datetime.now(UTC),
                )
            except HttpError as exc:
                # Map HTTP errors to specific exception types before retry logic catches them
                status_code = exc.resp.status
                reason = exc.resp.reason or "Unknown"

                if status_code == 404:
                    raise GscPropertyNotFoundError(property_url) from exc
                if status_code == 403:
                    raise GscAuthorizationError(
                        f"Property not accessible or verification pending: {reason}"
                    ) from exc
                if status_code == 429:
                    retry_after = None
                    if "retry-after" in exc.resp:
                        with suppress(ValueError, TypeError):
                            retry_after = float(exc.resp["retry-after"])
                    raise GscQuotaExceededError(retry_after_s=retry_after) from exc
                if status_code == 410:
                    raise GscApiDeprecatedError(410, f"Endpoint deprecated: {reason}") from exc
                if status_code == 501:
                    raise GscApiDeprecatedError(501, f"Endpoint not implemented: {reason}") from exc
                # Re-raise HttpError for other status codes (retry will handle)
                raise

        try:
            return self.call("fetch_analytics", attempt)
        except (
            GscPropertyNotFoundError,
            GscAuthorizationError,
            GscQuotaExceededError,
            GscApiDeprecatedError,
        ):
            # These are mapped errors; return empty response (graceful degradation)
            # They're raised from within attempt(), so they come out of self.call()
            _logger.warning(
                "gsc_fetch_analytics_error",
                extra={"property": property_url},
                exc_info=True,
            )
            # Return empty response (graceful degradation)
            return GscAnalyticsResponse(
                property_url=property_url,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as exc:
            _logger.exception(
                "gsc_fetch_analytics_failed",
                extra={"property": property_url, "error": str(exc)},
            )
            # Return empty response (graceful degradation)
            return GscAnalyticsResponse(
                property_url=property_url,
                start_date=start_date,
                end_date=end_date,
            )
