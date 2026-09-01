"""Tests for GSC OAuth token manager."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from src.core.config import Settings
from src.core.errors import ConfigurationError, GscAuthenticationError, GscAuthorizationError
from src.integrations.gsc_token_manager import GSC_READONLY_SCOPE, GscTokenManager


@pytest.fixture
def mock_settings() -> Settings:
    """Provide test settings with GSC credentials."""
    from pydantic import SecretStr

    settings = Mock(spec=Settings)
    settings.google_search_console_client_email = "test@example.iam.gserviceaccount.com"
    settings.google_search_console_private_key = SecretStr(
        "-----BEGIN PRIVATE KEY-----\n"
        "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7W0O..."
        "\n-----END PRIVATE KEY-----\n"
    )
    return settings


@pytest.fixture
def mock_credentials():
    """Provide a mock Google credentials object."""
    creds = Mock()
    creds.token = "ya29.test-token-abc123"  # noqa: S105
    creds.valid = True
    creds.expiry = datetime.now(UTC) + timedelta(hours=1)
    creds.scopes = [GSC_READONLY_SCOPE]
    return creds


class TestGscTokenManagerInitialization:
    """Test token manager initialization."""

    def test_init_with_valid_credentials(self, mock_settings):
        """Token manager initializes with valid credentials."""
        with patch(
            "src.integrations.gsc_token_manager.Credentials.from_service_account_info"
        ) as mock_creds:
            mock_creds.return_value = Mock()
            manager = GscTokenManager(settings=mock_settings)

            assert manager.get_account_email() == "test@example.iam.gserviceaccount.com"

    def test_init_without_client_email(self):
        """ConfigurationError if client email is missing."""
        settings = Mock(spec=Settings)
        settings.google_search_console_client_email = None
        settings.google_search_console_private_key = "key"

        with pytest.raises(ConfigurationError, match="credentials not configured"):
            GscTokenManager(settings=settings)

    def test_init_without_private_key(self):
        """ConfigurationError if private key is missing."""
        settings = Mock(spec=Settings)
        settings.google_search_console_client_email = "test@example.com"
        settings.google_search_console_private_key = None

        with pytest.raises(ConfigurationError, match="credentials not configured"):
            GscTokenManager(settings=settings)

    def test_init_with_malformed_key(self, mock_settings):
        """ConfigurationError if private key is malformed."""
        with patch(
            "src.integrations.gsc_token_manager.Credentials.from_service_account_info"
        ) as mock_creds:
            mock_creds.side_effect = ValueError("Invalid key format")

            with pytest.raises(ConfigurationError, match="Failed to load.*credentials"):
                GscTokenManager(settings=mock_settings)


class TestTokenRetrieval:
    """Test getting and refreshing tokens."""

    def test_get_valid_token(self, mock_settings, mock_credentials):
        """get_or_refresh_token returns valid token without refresh."""
        with patch(
            "src.integrations.gsc_token_manager.Credentials.from_service_account_info"
        ) as mock_creds:
            mock_creds.return_value = mock_credentials
            manager = GscTokenManager(settings=mock_settings)

            token = manager.get_or_refresh_token()
            assert token == "ya29.test-token-abc123"  # noqa: S105

    def test_proactive_refresh_when_expiring(self, mock_settings, mock_credentials):
        """Token is refreshed proactively if expiring within 5 minutes."""
        # Set token to expire in 2 minutes (within 5-minute window)
        mock_credentials.expiry = datetime.now(UTC) + timedelta(minutes=2)
        mock_credentials.valid = True

        with patch(
            "src.integrations.gsc_token_manager.Credentials.from_service_account_info"
        ) as mock_creds:
            mock_creds.return_value = mock_credentials

            manager = GscTokenManager(settings=mock_settings)

            # First call should trigger refresh
            with patch("google.auth.transport.requests.Request"):
                mock_credentials.token = "ya29.refreshed-token"  # noqa: S105
                token = manager.get_or_refresh_token()

            # Token was refreshed
            assert token == "ya29.refreshed-token"  # noqa: S105
            mock_credentials.refresh.assert_called_once()

    def test_no_refresh_if_token_valid_long_term(self, mock_settings, mock_credentials):
        """Token is not refreshed if it's valid for > 5 minutes."""
        # Token expires in 30 minutes (outside refresh window)
        mock_credentials.expiry = datetime.now(UTC) + timedelta(minutes=30)
        mock_credentials.valid = True

        with patch(
            "src.integrations.gsc_token_manager.Credentials.from_service_account_info"
        ) as mock_creds:
            mock_creds.return_value = mock_credentials
            manager = GscTokenManager(settings=mock_settings)

            token = manager.get_or_refresh_token()

            # Refresh should NOT have been called
            mock_credentials.refresh.assert_not_called()
            assert token == "ya29.test-token-abc123"  # noqa: S105

    def test_refresh_failure_raises_authentication_error(self, mock_settings, mock_credentials):
        """Refresh failure raises GscAuthenticationError."""
        mock_credentials.valid = False
        mock_credentials.expiry = datetime.now(UTC) + timedelta(minutes=2)
        mock_credentials.refresh.side_effect = Exception("Network error")

        with patch(
            "src.integrations.gsc_token_manager.Credentials.from_service_account_info"
        ) as mock_creds:
            mock_creds.return_value = mock_credentials

            manager = GscTokenManager(settings=mock_settings)

            with patch("google.auth.transport.requests.Request"):  # noqa: SIM117
                with pytest.raises(GscAuthenticationError, match="Token refresh failed"):
                    manager.get_or_refresh_token()

    def test_no_token_after_refresh_raises_error(self, mock_settings, mock_credentials):
        """If refresh succeeds but returns no token, raise GscAuthenticationError."""
        mock_credentials.valid = False
        mock_credentials.token = None  # No token after refresh
        mock_credentials.expiry = datetime.now(UTC) + timedelta(minutes=2)

        with patch(
            "src.integrations.gsc_token_manager.Credentials.from_service_account_info"
        ) as mock_creds:
            mock_creds.return_value = mock_credentials

            manager = GscTokenManager(settings=mock_settings)

            with patch("google.auth.transport.requests.Request"):  # noqa: SIM117
                with pytest.raises(GscAuthenticationError, match="no token was returned"):
                    manager.get_or_refresh_token()


class TestScopeValidation:
    """Test OAuth scope validation."""

    def test_validate_scopes_success(self, mock_settings, mock_credentials):
        """Scope validation succeeds with correct scopes."""
        mock_credentials.scopes = [GSC_READONLY_SCOPE]

        with patch(
            "src.integrations.gsc_token_manager.Credentials.from_service_account_info"
        ) as mock_creds:
            mock_creds.return_value = mock_credentials
            manager = GscTokenManager(settings=mock_settings)

            # Should not raise
            manager.validate_scopes()

    def test_validate_scopes_missing_required_scope(self, mock_settings, mock_credentials):
        """GscAuthorizationError if required scope is missing."""
        # Token has wrong scope
        mock_credentials.scopes = ["https://www.googleapis.com/auth/webmasters"]

        with patch(
            "src.integrations.gsc_token_manager.Credentials.from_service_account_info"
        ) as mock_creds:
            mock_creds.return_value = mock_credentials
            manager = GscTokenManager(settings=mock_settings)

            with pytest.raises(GscAuthorizationError, match="missing required scope"):
                manager.validate_scopes()

    def test_validate_scopes_with_multiple_scopes(self, mock_settings, mock_credentials):
        """Scope validation succeeds if required scope is in list."""
        mock_credentials.scopes = [
            "https://www.googleapis.com/auth/drive",
            GSC_READONLY_SCOPE,
            "https://www.googleapis.com/auth/gmail.readonly",
        ]

        with patch(
            "src.integrations.gsc_token_manager.Credentials.from_service_account_info"
        ) as mock_creds:
            mock_creds.return_value = mock_credentials
            manager = GscTokenManager(settings=mock_settings)

            # Should not raise; required scope is present
            manager.validate_scopes()

    def test_validate_scopes_empty_scopes(self, mock_settings, mock_credentials):
        """GscAuthorizationError if scopes list is empty."""
        mock_credentials.scopes = []

        with patch(
            "src.integrations.gsc_token_manager.Credentials.from_service_account_info"
        ) as mock_creds:
            mock_creds.return_value = mock_credentials
            manager = GscTokenManager(settings=mock_settings)

            with pytest.raises(GscAuthorizationError, match="missing required scope"):
                manager.validate_scopes()


class TestAccountEmail:
    """Test account email retrieval."""

    def test_get_account_email(self, mock_settings, mock_credentials):
        """get_account_email returns the service account email."""
        with patch(
            "src.integrations.gsc_token_manager.Credentials.from_service_account_info"
        ) as mock_creds:
            mock_creds.return_value = mock_credentials
            manager = GscTokenManager(settings=mock_settings)

            email = manager.get_account_email()
            assert email == "test@example.iam.gserviceaccount.com"


class TestTokenState:
    """Test token state inspection."""

    def test_get_token_state(self, mock_settings, mock_credentials):
        """get_token_state returns GscOAuthToken with current state."""
        expires = datetime.now(UTC) + timedelta(hours=1)
        mock_credentials.expiry = expires
        mock_credentials.scopes = [GSC_READONLY_SCOPE]
        mock_credentials.token = "ya29.test-token"  # noqa: S105

        with patch(
            "src.integrations.gsc_token_manager.Credentials.from_service_account_info"
        ) as mock_creds:
            mock_creds.return_value = mock_credentials
            manager = GscTokenManager(settings=mock_settings)

            state = manager.get_token_state()

            assert state.access_token == "ya29.test-token"  # noqa: S105,S106
            assert state.refresh_token is None  # Service accounts don't have refresh tokens
            assert state.expires_at == expires
            assert GSC_READONLY_SCOPE in state.scopes
