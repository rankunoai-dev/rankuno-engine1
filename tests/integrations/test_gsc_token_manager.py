"""Tests for GSC OAuth token manager."""

from unittest.mock import Mock, patch

import pytest
from src.core.config import Settings
from src.core.errors import ConfigurationError, GscAuthenticationError
from src.integrations.gsc_token_manager import GSC_READONLY_SCOPE, GscTokenManager


@pytest.fixture
def mock_oauth_settings() -> Settings:
    """Provide test settings with OAuth 2.0 credentials."""
    from pydantic import SecretStr

    settings = Mock(spec=Settings)
    settings.google_oauth_client_id = "test-client-id"
    settings.google_oauth_client_secret = SecretStr("test-client-secret")
    settings.google_oauth_refresh_token = SecretStr("test-refresh-token")
    return settings


class TestGscTokenManagerInitialization:
    """Test token manager initialization."""

    def test_init_with_valid_oauth_credentials(self, mock_oauth_settings):
        """Token manager initializes with valid OAuth credentials."""
        manager = GscTokenManager(settings=mock_oauth_settings)
        assert manager is not None

    def test_init_without_client_id(self):
        """ConfigurationError if client ID is missing."""
        settings = Mock(spec=Settings)
        settings.google_oauth_client_id = None
        settings.google_oauth_client_secret = "secret"  # noqa: S105
        settings.google_oauth_refresh_token = "token"  # noqa: S105

        with pytest.raises(ConfigurationError, match="credentials not configured"):
            GscTokenManager(settings=settings)

    def test_init_without_client_secret(self):
        """ConfigurationError if client secret is missing."""
        settings = Mock(spec=Settings)
        settings.google_oauth_client_id = "client-id"
        settings.google_oauth_client_secret = None
        settings.google_oauth_refresh_token = "token"  # noqa: S105  # noqa: S105

        with pytest.raises(ConfigurationError, match="credentials not configured"):
            GscTokenManager(settings=settings)

    def test_init_without_refresh_token(self):
        """ConfigurationError if refresh token is missing."""
        settings = Mock(spec=Settings)
        settings.google_oauth_client_id = "client-id"
        settings.google_oauth_client_secret = "secret"  # noqa: S105
        settings.google_oauth_refresh_token = None

        with pytest.raises(ConfigurationError, match="credentials not configured"):
            GscTokenManager(settings=settings)


class TestTokenRetrieval:
    """Test getting and refreshing tokens."""

    def test_get_token_first_call_requires_refresh(self, mock_oauth_settings):
        """First call to get_or_refresh_token triggers a refresh."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "access_token": "ya29.test-token-123",
            "expires_in": 3600,
        }

        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.return_value = mock_response
            manager = GscTokenManager(settings=mock_oauth_settings)

            token = manager.get_or_refresh_token()
            assert token == "ya29.test-token-123"  # noqa: S105
            mock_post.assert_called_once()

    def test_reuse_valid_token_without_refresh(self, mock_oauth_settings):
        """Valid token is reused without refreshing."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "access_token": "ya29.test-token-123",
            "expires_in": 3600,
        }

        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.return_value = mock_response
            manager = GscTokenManager(settings=mock_oauth_settings)

            # First call triggers refresh
            token1 = manager.get_or_refresh_token()
            assert mock_post.call_count == 1

            # Second call (token still valid) should not refresh
            token2 = manager.get_or_refresh_token()
            assert token1 == token2
            assert mock_post.call_count == 1  # Still only 1 call

    def test_proactive_refresh_when_expiring_soon(self, mock_oauth_settings):
        """Token is refreshed if it expires within 5 minutes."""
        responses = [
            Mock(json=lambda: {"access_token": "token-1", "expires_in": 100}),  # 100 sec
            Mock(json=lambda: {"access_token": "token-2", "expires_in": 3600}),  # 1 hour
        ]

        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.side_effect = responses
            manager = GscTokenManager(settings=mock_oauth_settings)

            # First call: gets token-1 (expires in 100 sec = within 5 min window)
            token1 = manager.get_or_refresh_token()
            assert token1 == "token-1"
            assert mock_post.call_count == 1

            # Second call: should refresh because token-1 expires in 100 sec < 300 sec window
            token2 = manager.get_or_refresh_token()
            assert token2 == "token-2"
            assert mock_post.call_count == 2

    def test_refresh_failure_raises_authentication_error(self, mock_oauth_settings):
        """Refresh failure raises GscAuthenticationError."""
        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.side_effect = Exception("Network error")
            manager = GscTokenManager(settings=mock_oauth_settings)

            with pytest.raises(GscAuthenticationError, match="Token refresh failed"):
                manager.get_or_refresh_token()

    def test_refresh_succeeds_but_no_token_returned(self, mock_oauth_settings):
        """GscAuthenticationError if refresh succeeds but returns no token."""
        mock_response = Mock()
        mock_response.json.return_value = {"expires_in": 3600}  # Missing access_token

        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.return_value = mock_response
            manager = GscTokenManager(settings=mock_oauth_settings)

            with pytest.raises(GscAuthenticationError, match="no access token"):
                manager.get_or_refresh_token()

    def test_refresh_response_parse_error(self, mock_oauth_settings):
        """GscAuthenticationError if token response is malformed."""
        mock_response = Mock()
        mock_response.json.side_effect = ValueError("Invalid JSON")

        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.return_value = mock_response
            manager = GscTokenManager(settings=mock_oauth_settings)

            with pytest.raises(GscAuthenticationError, match="parse token response"):
                manager.get_or_refresh_token()


class TestScopeValidation:
    """Test OAuth scope validation."""

    def test_validate_scopes_succeeds(self, mock_oauth_settings):
        """validate_scopes completes without error."""
        manager = GscTokenManager(settings=mock_oauth_settings)
        manager.validate_scopes()  # Should not raise

    def test_get_account_email_returns_oauth_identifier(self, mock_oauth_settings):
        """get_account_email returns OAuth client identifier."""
        manager = GscTokenManager(settings=mock_oauth_settings)
        email = manager.get_account_email()
        assert "oauth2://" in email
        assert "test-client-id" in email

    def test_get_token_state_includes_scope(self, mock_oauth_settings):
        """get_token_state includes the GSC read-only scope."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "access_token": "ya29.test-token-123",
            "expires_in": 3600,
        }

        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.return_value = mock_response
            manager = GscTokenManager(settings=mock_oauth_settings)
            manager.get_or_refresh_token()

            state = manager.get_token_state()
            assert GSC_READONLY_SCOPE in state.scopes
            assert state.access_token == "ya29.test-token-123"  # noqa: S105
