"""Google Search Console API client.

Wraps the Google Search Console API with rate limiting, error handling, and
audit logging. All calls are protected by the BaseAPIClient framework.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import partial
from typing import Any

from googleapiclient.discovery import build  # type: ignore[import-untyped]
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

from src.core.config import Settings
from src.core.errors import (
    GscAuthorizationError,
    GscPropertyNotFoundError,
    GscQuotaExceededError,
    GuardrailViolationError,
)
from src.core.logger import get_logger
from src.integrations.base_client import BaseAPIClient
from src.integrations.gsc_requests import (
    MAX_PAGES,
    ROW_LIMIT_MAX,
    api_property_url,
    check_row_limit,
    page_metrics,
    query_rows,
    raise_mapped_http_error,
)
from src.integrations.gsc_schemas import (
    GscAnalyticsResponse,
    GscFailureClass,
    GscPageQueries,
    GscProperty,
    GscStopReason,
)
from src.integrations.gsc_token_manager import GscTokenManager

__all__ = ["GscApiClient"]

_logger = get_logger("integrations.gsc_client")


def _failure_class(exc: Exception) -> GscFailureClass:
    """Name the kind of failure a page raised, from a closed list.

    `call()` wraps a failed request in `IntegrationError` with the transport error as
    `__cause__`, so the class is read from there. The message is never read: it can
    quote the property and the search phrase.
    """
    if isinstance(exc, GscQuotaExceededError):
        return "quota"
    cause = exc.__cause__ if exc.__cause__ is not None else exc
    if isinstance(cause, HttpError):
        return "server_error" if 500 <= cause.resp.status <= 599 else "unexpected"
    if isinstance(cause, TimeoutError):
        return "timeout"
    if isinstance(cause, ConnectionError):
        return "connection"
    return "unexpected"


class GscApiClient(BaseAPIClient):
    """Google Search Console API connector.

    Mandatory class vars (from BaseAPIClient):
    - `service_name` — audit log identity
    - `rate_limit_key` — shared quota bucket key
    - `requests_per_minute` — vendor's documented sustained limit

    Design:
    - All requests go through BaseAPIClient.call() which enforces rate limiting
    - Token refresh is handled by GscTokenManager and happens *before* `call()`,
      never inside it. `GscAuthenticationError` is an `IntegrationError`, which
      the retry policy treats as transient, so a refresh inside the loop turned
      one revoked token into four `invalid_grant` POSTs.
    - Paged fetches make one `call()` per page, so every page takes a rate-limit
      slot and a page that fails after its retries does not discard the pages
      before it. The result says it is incomplete and why.
    - Errors are mapped to specific exception types for upstream handling
    - Graceful degradation: a transient fetch error keeps the rows already
      received and reports `fetch_failed`, rather than raising. Authentication,
      authorization (403) and property-not-found (404) errors are the exception
      to that: an empty result would read as "no search data" rather than
      "re-authorise this account" or "this account cannot see this property", so
      they propagate to the caller.
    """

    service_name = "google.search_console"
    rate_limit_key = "gsc_quota"
    requests_per_minute = 60  # 2x headroom per property (120 QPM per property, 1200 total)

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        account: str | None = None,
        org_id: str | None = None,
    ) -> None:
        """Initialize GSC API client.

        Args:
            settings: Configuration override, primarily for tests.
            account: Named GSC profile. `None` is the single-account default.
            org_id: Organization whose stored accounts `account` may name.
                `None` means the default org.

        Raises:
            ConfigurationError: If the profile is unknown or credentials are missing.
        """
        super().__init__(settings=settings)

        self._token_manager = GscTokenManager(
            settings=self._settings, account=account, org_id=org_id
        )

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

    def _get_service(self, token: str) -> Any:
        """Build the GSC API service around an already-refreshed access token.

        Takes the token as an argument rather than fetching it so the refresh
        stays outside `call()`'s retry loop. Service is created fresh each call
        so a token refreshed between calls is always the one used.

        Args:
            token: Bearer token from `GscTokenManager.get_or_refresh_token()`.

        Returns:
            Google Webmasters (Search Console) API service object.
        """
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
            GscAuthenticationError: If the refresh token is revoked or invalid.
                Raised once; never retried.
        """
        token = self._token_manager.get_or_refresh_token()

        def attempt() -> list[GscProperty]:
            service = self._get_service(token)
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

    def _query_page(
        self, token: str, api_url: str, body: dict[str, object]
    ) -> list[dict[str, Any]]:
        """Run one `searchAnalytics.query` request and return its raw rows.

        The retry wrapper calls this again with the same body on a transient
        failure, so `startRow` is fixed by the caller and a retry cannot skip or
        repeat a row.

        Raises:
            GscPropertyNotFoundError: On a 404.
            GscAuthorizationError: On a 403.
            GscQuotaExceededError: On a 429.
        """
        try:
            service = self._get_service(token)
            request = service.searchanalytics().query(siteUrl=api_url, body=body)
            response = request.execute()
        except HttpError as exc:
            raise_mapped_http_error(exc, api_url)
        return list(response.get("rows", []))

    def _page_through(
        self,
        operation: str,
        token: str,
        api_url: str,
        body: dict[str, object],
        row_limit: int,
    ) -> tuple[list[dict[str, Any]], GscStopReason, GscFailureClass | None]:
        """Read pages of `searchAnalytics.query` until one comes back short.

        Each page is one `self.call()`, so each takes a rate-limit slot. The
        cursor advances by the rows *received*, not the rows parsed, because a
        row skipped at parse time still occupies a position in the API's
        ordering. A short page is the end of the data; a full page at the cap is
        `row_cap`.

        Args:
            operation: Audit-log label for each page request.
            token: Bearer token, fetched once by the caller before this loop.
            api_url: The `siteUrl` to query.
            body: Request body shared by every page (dates and dimensions).
            row_limit: Rows requested per page.

        Returns:
            The raw rows received, in order, why paging stopped, and the class of
            the failure when it stopped on one. Rows received before a failed page
            are returned, never dropped.

        Raises:
            GscPropertyNotFoundError: On a 404 on any page; refusals propagate.
            GscAuthorizationError: On a 403 on any page; refusals propagate.
            GuardrailViolationError: Propagated unchanged, as `call()` does.
        """
        collected: list[dict[str, Any]] = []
        for _ in range(MAX_PAGES):
            page_body = {**body, "rowLimit": row_limit, "startRow": len(collected)}
            try:
                page = self.call(operation, partial(self._query_page, token, api_url, page_body))
            except (GscPropertyNotFoundError, GscAuthorizationError, GuardrailViolationError):
                raise
            except Exception as exc:  # noqa: BLE001 - a failed page keeps the rows before it
                # Class name only. The exception text can quote the request, and
                # the request names a property and a search phrase.
                _logger.warning(
                    "gsc_page_fetch_failed",
                    extra={
                        "operation": operation,
                        "error": type(exc).__name__,
                        "rows_kept": len(collected),
                    },
                )
                return collected, "fetch_failed", _failure_class(exc)

            collected.extend(page)
            if len(page) < row_limit:
                return collected, "exhausted", None

        _logger.warning(
            "gsc_row_cap_reached",
            extra={"operation": operation, "pages": MAX_PAGES, "rows": len(collected)},
        )
        return collected, "row_cap", None

    def fetch_analytics(
        self,
        property_url: str,
        start_date: str,
        end_date: str,
        row_limit: int = 10000,
    ) -> GscAnalyticsResponse:
        """Fetch page-level search analytics for a GSC property, across every page.

        Reads `dimensions=["page"]` one `row_limit` page at a time until a page
        comes back short. Without paging, a property with more pages than one
        request returns is silently truncated, and every total built from it is
        wrong for exactly the sites with the most pages.

        Args:
            property_url: GSC property, either a URL prefix
                ("https://example.com/") or a domain ("sc-domain:example.com").
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            row_limit: Rows requested per page (1 to 25,000; GSC's maximum).

        Returns:
            GscAnalyticsResponse with page metrics. `complete` is False and
            `stop_reason` says why when the rows are partial.

        Raises:
            ValueError: If `row_limit` is outside 1 to 25,000. Raised before any
                network call.
            GscAuthenticationError: If the refresh token is revoked or invalid.
                Raised once, before any analytics request; never retried.
            GscAuthorizationError: On a 403 — this account cannot access the
                property.
            GscPropertyNotFoundError: On a 404 — no such property.
        """
        check_row_limit(row_limit)
        token = self._token_manager.get_or_refresh_token()
        api_url = api_property_url(property_url)
        body: dict[str, object] = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": ["page"],
        }

        raw, stop_reason, _failure = self._page_through(
            "fetch_analytics", token, api_url, body, row_limit
        )
        rows = page_metrics(raw)
        return GscAnalyticsResponse(
            property_url=api_url,
            start_date=start_date,
            end_date=end_date,
            rows=rows,
            rows_available=len(rows),
            fetched_at=datetime.now(UTC),
            complete=stop_reason == "exhausted",
            stop_reason=stop_reason,
        )

    def fetch_top_queries(
        self,
        property_url: str,
        start_date: str,
        end_date: str,
        row_limit: int = ROW_LIMIT_MAX,
    ) -> GscPageQueries:
        """Fetch every (page, query) row for a GSC property, across pages.

        The query dimension multiplies the rows, which is why the default page is
        Search Console's maximum rather than the page-level default. The rows are
        returned as received; choosing the top queries per URL is the export's
        job, so no ranking decision is baked in here.

        Args:
            property_url: GSC property, as for `fetch_analytics`.
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).
            row_limit: Rows requested per page (1 to 25,000).

        Returns:
            GscPageQueries carrying every row received, `complete`, and
            `stop_reason`.

        Raises:
            ValueError: If `row_limit` is outside 1 to 25,000. Raised before the
                token is fetched.
            GscAuthenticationError: If the refresh token is revoked or invalid.
                Raised once, before any query request.
            GscAuthorizationError: On a 403 on any page.
            GscPropertyNotFoundError: On a 404 on any page.
        """
        check_row_limit(row_limit)
        token = self._token_manager.get_or_refresh_token()
        api_url = api_property_url(property_url)
        body: dict[str, object] = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": ["page", "query"],
        }

        raw, stop_reason, failure_class = self._page_through(
            "fetch_top_queries", token, api_url, body, row_limit
        )
        result = GscPageQueries(
            property_url=api_url,
            start_date=start_date,
            end_date=end_date,
            rows=query_rows(raw),
            complete=stop_reason == "exhausted",
            stop_reason=stop_reason,
            failure_class=failure_class,
        )
        _logger.info(
            "gsc_top_queries_fetched",
            extra={"rows": len(result.rows), "stop_reason": stop_reason},
        )
        return result
