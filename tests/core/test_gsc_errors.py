"""Tests for GSC-specific error types."""

from src.core.errors import (
    GscApiDeprecatedError,
    GscAuthenticationError,
    GscAuthorizationError,
    GscPropertyNotFoundError,
    GscQuotaExceededError,
    IntegrationError,
)


class TestGscAuthenticationError:
    """Validate GscAuthenticationError."""

    def test_creates_integration_error(self):
        """GscAuthenticationError is an IntegrationError."""
        error = GscAuthenticationError("Token expired")
        assert isinstance(error, IntegrationError)
        assert error.service == "google.search_console"
        assert "Token expired" in str(error)

    def test_invalid_grant_scenario(self):
        """Capture invalid_grant (revoked consent)."""
        error = GscAuthenticationError("invalid_grant: user revoked consent")
        assert error.reason == "invalid_grant: user revoked consent"
        assert "revoked" in str(error)

    def test_token_refresh_failure(self):
        """Capture token refresh failures."""
        error = GscAuthenticationError("Refresh token is stale or invalid")
        assert "Refresh token" in str(error)


class TestGscAuthorizationError:
    """Validate GscAuthorizationError."""

    def test_property_not_accessible(self):
        """User lacks access to requested property."""
        error = GscAuthorizationError("User is not owner of property https://example.com")
        assert isinstance(error, IntegrationError)
        assert "owner" in str(error).lower()

    def test_scope_mismatch(self):
        """Token lacks required scopes."""
        error = GscAuthorizationError(
            "Token missing scope: https://www.googleapis.com/auth/webmasters.readonly"
        )
        assert "scope" in str(error).lower()


class TestGscPropertyNotFoundError:
    """Validate GscPropertyNotFoundError."""

    def test_property_deleted(self):
        """Property was deleted from GSC."""
        error = GscPropertyNotFoundError("https://example.com")
        assert isinstance(error, IntegrationError)
        assert error.property_url == "https://example.com"
        assert "deleted" in str(error).lower()

    def test_property_url_preserved(self):
        """Property URL is accessible for logging."""
        error = GscPropertyNotFoundError("https://shop.example.com/products")
        assert error.property_url == "https://shop.example.com/products"


class TestGscQuotaExceededError:
    """Validate GscQuotaExceededError."""

    def test_quota_exceeded_no_retry_after(self):
        """Quota exceeded without retry-after header."""
        error = GscQuotaExceededError()
        assert isinstance(error, IntegrationError)
        assert "quota exhausted" in str(error).lower()
        assert error.retry_after_s is None

    def test_quota_exceeded_with_retry_after(self):
        """Quota exceeded with server-provided retry window."""
        error = GscQuotaExceededError(retry_after_s=30.0)
        assert error.retry_after_s == 30.0
        assert "30.0s" in str(error)

    def test_short_retry_window(self):
        """Very short retry window (sub-second)."""
        error = GscQuotaExceededError(retry_after_s=0.5)
        assert "0.5s" in str(error)


class TestGscApiDeprecatedError:
    """Validate GscApiDeprecatedError."""

    def test_gone_endpoint(self):
        """Endpoint returns 410 Gone (deprecated)."""
        error = GscApiDeprecatedError(410, "This API version is no longer supported")
        assert isinstance(error, IntegrationError)
        assert error.http_status == 410
        assert "410" in str(error)
        assert "no longer supported" in str(error)

    def test_not_implemented(self):
        """Endpoint returns 501 Not Implemented."""
        error = GscApiDeprecatedError(501, "Endpoint not implemented in this version")
        assert error.http_status == 501
        assert "501" in str(error)

    def test_http_status_preserved(self):
        """HTTP status is accessible."""
        error = GscApiDeprecatedError(410, "Gone")
        assert error.http_status == 410
