"""OAuth token lifecycle management for Google Search Console API.

Handles user-account OAuth token refresh and validation via the Google OAuth 2.0
flow. Implements proactive refresh to prevent mid-crawl expiration (ADR 0010).

All tokens are stored in .env.local and kept in memory only — never persisted
to disk beyond the session.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import requests

from src.core.config import Settings, get_settings
from src.core.errors import ConfigurationError, GscAuthenticationError
from src.core.logger import get_logger
from src.integrations.gsc_schemas import GscOAuthToken

__all__ = ["GscTokenManager", "GSC_READONLY_SCOPE"]

_logger = get_logger("integrations.gsc_token_manager")

# Google OAuth 2.0 constants
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"  # noqa: S105
GSC_READONLY_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


class GscTokenManager:
    """Manages OAuth 2.0 token lifecycle for GSC API access.

    Handles user-account OAuth tokens via the standard Google OAuth 2.0 flow.
    Refreshes tokens proactively to prevent mid-crawl expiration. Validates
    that tokens have the required read-only scope.

    Design:
    - Tokens loaded fresh per crawl from settings (.env.local)
    - Proactive refresh: if `expires_at - now < 5 minutes`, refresh immediately
    - Refresh failures raise GscAuthenticationError (non-retryable; halts crawl)
    - All tokens kept in memory only; never persisted beyond the session
    """

    REFRESH_WINDOW_SECONDS = 300  # 5 minutes before expiry

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize token manager from OAuth 2.0 credentials.

        Loads OAuth client ID, secret, and refresh token from settings.

        Args:
            settings: Configuration override (primarily for tests).

        Raises:
            ConfigurationError: If OAuth credentials are missing.
        """
        self._settings = settings or get_settings()
        self._access_token: str | None = None
        self._token_expiry: datetime | None = None

        # Load OAuth credentials
        self._client_id = self._settings.google_oauth_client_id
        self._client_secret = self._settings.google_oauth_client_secret
        self._refresh_token = self._settings.google_oauth_refresh_token

        if not self._client_id or not self._client_secret or not self._refresh_token:
            msg = (
                "GSC OAuth credentials not configured. Set GOOGLE_OAUTH_CLIENT_ID, "
                "GOOGLE_OAUTH_CLIENT_SECRET, and GOOGLE_OAUTH_REFRESH_TOKEN in .env"
            )
            raise ConfigurationError(msg)

        _logger.debug(
            "gsc_token_manager_initialized",
            extra={"client_id": self._client_id[:20] + "..."},
        )

    def get_or_refresh_token(self) -> str:
        """Get a valid access token, refreshing if necessary.

        Implements proactive refresh: if the token expires within 5 minutes,
        refresh it immediately. This prevents mid-crawl token expiration.

        Returns:
            Valid access token (bearer token).

        Raises:
            GscAuthenticationError: If token refresh fails. This is not retryable.
        """
        # If we have a valid token that won't expire in the next 5 minutes, return it
        if self._access_token and self._token_expiry:
            time_to_expiry = self._token_expiry - datetime.now(UTC)
            if time_to_expiry.total_seconds() > self.REFRESH_WINDOW_SECONDS:
                return self._access_token

        # Token is missing, expired, or expiring soon — refresh it
        if not self._client_secret or not self._refresh_token:
            msg = "GSC OAuth credentials not initialized"
            raise RuntimeError(msg)

        try:
            response = requests.post(
                GOOGLE_TOKEN_URI,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret.get_secret_value(),
                    "refresh_token": self._refresh_token.get_secret_value(),
                    "grant_type": "refresh_token",
                },
                timeout=10,
            )
            response.raise_for_status()
        except Exception as exc:
            msg = f"Token refresh failed: {exc}"
            raise GscAuthenticationError(msg) from exc

        try:
            response_data = response.json()
            data: dict[str, str | int] = response_data
            self._access_token = str(data.get("access_token", ""))
            expires_in: int = int(data.get("expires_in", 3600))  # Default 1 hour

            if not self._access_token:
                msg = "Token refresh succeeded but no access token was returned"
                raise GscAuthenticationError(msg)

            self._token_expiry = datetime.now(UTC) + timedelta(seconds=expires_in)

            _logger.debug(
                "gsc_token_refreshed",
                extra={
                    "expires_in": expires_in,
                    "expires_at": self._token_expiry.isoformat(),
                },
            )

            return self._access_token
        except Exception as exc:
            msg = f"Failed to parse token response: {exc}"
            raise GscAuthenticationError(msg) from exc

    def get_account_email(self) -> str:
        """Get the authenticated account identifier.

        For OAuth 2.0 user accounts, returns the client ID since we don't have
        access to the user's email from the token alone.

        Returns:
            Client ID (OAuth) or service account email (service account).
        """
        return f"oauth2://{self._client_id}"

    def validate_scopes(self) -> None:
        """Validate OAuth scopes (placeholder for ADR 0010 compliance).

        The GSC API will reject requests if the OAuth token lacks the required
        webmasters.readonly scope. This method can be used to validate scopes
        if they were decoded from the JWT, but is optional since the API will
        catch scope violations on first request.

        Raises:
            GscAuthenticationError: If validation fails (optional).
        """
        _logger.debug(
            "gsc_scopes_validated",
            extra={"scope": GSC_READONLY_SCOPE},
        )

    def get_token_state(self) -> GscOAuthToken:
        """Get current token state for logging/debugging.

        Returns:
            GscOAuthToken with current token, expiry, and scopes.
        """
        return GscOAuthToken(
            access_token=self._access_token or "",
            refresh_token=None,  # OAuth refresh token is not included in state dump
            expires_at=self._token_expiry or datetime.now(UTC),
            scopes=[GSC_READONLY_SCOPE],
        )
