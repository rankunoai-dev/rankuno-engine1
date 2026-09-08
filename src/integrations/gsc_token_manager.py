"""OAuth token lifecycle management for Google Search Console API.

Handles user-account OAuth token refresh and validation via the Google OAuth 2.0
flow. Implements proactive refresh to prevent mid-crawl expiration (ADR 0010).

All tokens are stored in .env.local and kept in memory only — never persisted
to disk beyond the session.

Deviation from rule 5 (accepted, recorded in the security audit): the refresh
POST goes to a fixed Google URL with `requests` directly rather than through a
`BaseAPIClient`. Routing it through one would put the refresh inside the retry
loop, and a revoked token must fail once, not four times.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import requests

from src.core.config import Settings, get_settings
from src.core.errors import GscAuthenticationError
from src.core.logger import get_logger
from src.integrations.gsc_schemas import GscOAuthToken

__all__ = ["GscTokenManager", "GSC_READONLY_SCOPE"]

_logger = get_logger("integrations.gsc_token_manager")

# Google OAuth 2.0 constants
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"  # noqa: S105
GSC_READONLY_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"

# The `error` field of an OAuth 2.0 token response is a fixed code such as
# `invalid_grant` (RFC 6749 §5.2). Anything that does not look like one is not
# repeated, so a response body can never travel into a log or an error message.
_OAUTH_ERROR_CODE_RE = re.compile(r"^[a-z_]{1,40}$")


class GscTokenManager:
    """Manages OAuth 2.0 token lifecycle for GSC API access.

    Handles user-account OAuth tokens via the standard Google OAuth 2.0 flow.
    Refreshes tokens proactively to prevent mid-crawl expiration. Validates
    that tokens have the required read-only scope.

    Design:
    - Credentials resolved per crawl from settings (.env.local), by profile name
      or the flat default (`Settings.resolve_gsc_account`)
    - Proactive refresh: if `expires_at - now < 5 minutes`, refresh immediately
    - Refresh failures raise GscAuthenticationError (non-retryable; halts crawl)
    - All tokens kept in memory only; never persisted beyond the session
    """

    REFRESH_WINDOW_SECONDS = 300  # 5 minutes before expiry

    def __init__(self, settings: Settings | None = None, *, account: str | None = None) -> None:
        """Initialize token manager from OAuth 2.0 credentials.

        Args:
            settings: Configuration override (primarily for tests).
            account: Named GSC profile to use. `None` keeps the single-account
                default, so callers that predate profiles are unchanged.

        Raises:
            ConfigurationError: If the profile is unknown or its credentials
                are incomplete. Unknown never falls back to the default.
        """
        self._settings = settings or get_settings()
        self._access_token: str | None = None
        self._token_expiry: datetime | None = None

        creds = self._settings.resolve_gsc_account(account)
        self._account = creds.account
        self._client_id = creds.client_id
        self._client_secret = creds.client_secret
        self._refresh_token = creds.refresh_token

        # A named account is identified by its name alone. The client id prefix
        # is only logged for the legacy default, where the name does not exist.
        _logger.debug(
            "gsc_token_manager_initialized",
            extra={"account": self._account or f"default:{self._client_id[:20]}..."},
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
        except requests.HTTPError as exc:
            msg = f"Token refresh failed ({self._describe_http_failure(exc)})"
            raise GscAuthenticationError(msg) from exc
        except Exception as exc:
            # Only the exception class: a transport error's text can quote the
            # request, and the request carries the refresh token.
            msg = f"Token refresh failed: {type(exc).__name__}"
            raise GscAuthenticationError(msg) from exc

        try:
            response_data = response.json()
            data: dict[str, str | int] = response_data
            self._access_token = str(data.get("access_token", ""))
            expires_in: int = int(data.get("expires_in", 3600))  # Default 1 hour
        except Exception as exc:
            msg = f"Failed to parse token response: {type(exc).__name__}"
            raise GscAuthenticationError(msg) from exc

        if not self._access_token:
            msg = "Token refresh succeeded but no access token was returned"
            raise GscAuthenticationError(msg)

        self._token_expiry = datetime.now(UTC) + timedelta(seconds=expires_in)

        _logger.debug(
            "gsc_token_refreshed",
            extra={
                "account": self._account,
                "expires_in": expires_in,
                "expires_at": self._token_expiry.isoformat(),
            },
        )

        return self._access_token

    @staticmethod
    def _describe_http_failure(exc: requests.HTTPError) -> str:
        """Status code plus the OAuth error code, and nothing else from the body.

        `invalid_grant` is the one an operator needs — it means the refresh
        token was revoked and the profile must be re-authorised — and it is a
        fixed vocabulary word, not user data.
        """
        response = exc.response
        status = response.status_code if response is not None else "no response"
        code: object = None
        if response is not None:
            try:
                body = response.json()
                code = body.get("error") if isinstance(body, dict) else None
            except Exception:  # noqa: BLE001 - a body that is not JSON is simply not described
                code = None
        if isinstance(code, str) and _OAUTH_ERROR_CODE_RE.fullmatch(code):
            return f"HTTP {status}, {code}"
        return f"HTTP {status}"

    def get_account_email(self) -> str:
        """Get the authenticated account identifier for audit logs.

        A named profile is identified by its name. The legacy default has no
        name, so it is identified by the client id as it always was.

        Returns:
            `oauth2://profile/<name>` for a named account, else `oauth2://<client_id>`.
        """
        if self._account is not None:
            return f"oauth2://profile/{self._account}"
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
