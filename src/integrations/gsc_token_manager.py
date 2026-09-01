"""OAuth token lifecycle management for Google Search Console API.

Handles service account authentication, token generation, refresh, and validation.
All tokens are kept fresh proactively to avoid mid-crawl expiration.
"""

from __future__ import annotations

from datetime import UTC, datetime

from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials

from src.core.config import Settings, get_settings
from src.core.errors import ConfigurationError, GscAuthenticationError, GscAuthorizationError
from src.core.logger import get_logger
from src.integrations.gsc_schemas import GscOAuthToken

__all__ = ["GscTokenManager"]

_logger = get_logger("integrations.gsc_token_manager")

# Google Search Console API scope for read-only access
GSC_READONLY_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


class GscTokenManager:
    """Manages OAuth token lifecycle for GSC API access.

    Loads service account credentials, generates access tokens, and keeps them
    fresh. Validates that tokens have the correct scopes (read-only).

    Design:
    - Token refresh is proactive: if `expires_at - now < 5 minutes`, refresh
    - Refresh failures raise GscAuthenticationError (non-retryable by design;
      caller must handle or propagate)
    - All tokens are kept in memory; no persistence (loaded fresh per crawl)
    """

    # Minimum time before expiry to trigger proactive refresh
    REFRESH_WINDOW_SECONDS = 300  # 5 minutes

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize token manager from service account credentials.

        Args:
            settings: Configuration override, primarily for tests.

        Raises:
            ConfigurationError: If credentials are missing or malformed.
        """
        self._settings = settings or get_settings()
        self._credentials: Credentials | None = None
        self._account_email: str | None = None

        # Load service account credentials
        client_email = self._settings.google_search_console_client_email
        private_key = self._settings.google_search_console_private_key

        if not client_email or not private_key:
            msg = (
                "GSC credentials not configured. Set GOOGLE_SEARCH_CONSOLE_CLIENT_EMAIL "
                "and GOOGLE_SEARCH_CONSOLE_PRIVATE_KEY in .env"
            )
            raise ConfigurationError(msg)

        self._account_email = client_email

        try:
            # Create service account credentials with read-only scope
            self._credentials = Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
                {
                    "type": "service_account",
                    "project_id": "rankuno-gsc",
                    "private_key_id": "rankuno-gsc-key",
                    "private_key": private_key.get_secret_value(),
                    "client_email": client_email,
                    "client_id": "rankuno-gsc-client",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                },
                scopes=[GSC_READONLY_SCOPE],
            )
        except Exception as exc:
            msg = f"Failed to load GSC service account credentials: {exc}"
            raise ConfigurationError(msg) from exc

        _logger.debug(
            "gsc_token_manager_initialized",
            extra={"account": self._account_email},
        )

    def get_account_email(self) -> str:
        """Get the authenticated service account email.

        Returns:
            Email address of the service account.
        """
        if not self._account_email:
            msg = "Token manager not initialized"
            raise RuntimeError(msg)
        return self._account_email

    def get_or_refresh_token(self) -> str:
        """Get a valid access token, refreshing if necessary.

        Implements proactive refresh: if the token expires within 5 minutes,
        refresh immediately before returning it. This prevents mid-crawl
        token expiration.

        Returns:
            Valid access token (bearer token).

        Raises:
            GscAuthenticationError: If token refresh fails. This is not retryable;
                caller must handle or propagate to halt the crawl.
        """
        if not self._credentials:
            msg = "Token manager not initialized"
            raise RuntimeError(msg)

        # Check if token exists and is still valid beyond the refresh window
        if self._credentials.valid:
            expires_at = self._credentials.expiry
            if expires_at:
                time_to_expiry = expires_at - datetime.now(UTC)
                if time_to_expiry.total_seconds() > self.REFRESH_WINDOW_SECONDS:
                    # Token is fresh; return without refresh
                    token = self._credentials.token
                    if token:
                        return str(token)

        # Token is expired, expiring soon, or invalid; refresh it
        try:
            request = Request()
            self._credentials.refresh(request)  # type: ignore[no-untyped-call]
        except Exception as exc:
            # Wrap in GscAuthenticationError for unified error handling
            msg = f"Token refresh failed: {exc}"
            raise GscAuthenticationError(msg) from exc

        token = self._credentials.token
        if not token:
            msg = "Token refresh succeeded but no token was returned"
            raise GscAuthenticationError(msg)

        _logger.debug(
            "gsc_token_refreshed",
            extra={
                "account": self._account_email,
                "expires_at": self._credentials.expiry,
            },
        )

        return str(token)

    def validate_scopes(self) -> None:
        """Validate that the token has the required read-only scope.

        Raises:
            GscAuthorizationError: If the token lacks the required scope.
        """
        if not self._credentials:
            msg = "Token manager not initialized"
            raise RuntimeError(msg)

        scopes = self._credentials.scopes or []
        if GSC_READONLY_SCOPE not in scopes:
            msg = (
                f"GSC token is missing required scope '{GSC_READONLY_SCOPE}'. "
                f"Available scopes: {scopes}. "
                f"Credentials must be configured with read-only GSC access."
            )
            raise GscAuthorizationError(msg)

        _logger.debug(
            "gsc_scopes_validated",
            extra={
                "account": self._account_email,
                "scopes": scopes,
            },
        )

    def get_token_state(self) -> GscOAuthToken:
        """Get current token state for logging/debugging.

        Returns:
            GscOAuthToken with current token, expiry, scopes.
        """
        if not self._credentials:
            msg = "Token manager not initialized"
            raise RuntimeError(msg)

        return GscOAuthToken(
            access_token=self._credentials.token or "",
            refresh_token=None,  # Service accounts don't have refresh tokens
            expires_at=self._credentials.expiry or datetime.now(UTC),
            scopes=self._credentials.scopes or [],
        )
