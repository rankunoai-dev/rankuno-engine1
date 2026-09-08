"""Tests for GSC OAuth token manager."""

from unittest.mock import Mock, patch

import pytest
import requests
from pydantic import SecretStr
from src.core.config import Settings
from src.core.errors import ConfigurationError, GscAuthenticationError
from src.integrations.gsc_token_manager import GSC_READONLY_SCOPE, GscTokenManager


def _settings(**overrides: object) -> Settings:
    """Real settings, never a Mock.

    The manager resolves credentials through `Settings.resolve_gsc_account`,
    which a spec'd Mock would silently stub.
    """
    base = {
        "_env_file": None,
        "google_oauth_client_id": "test-client-id",
        "google_oauth_client_secret": SecretStr("test-client-secret"),
        "google_oauth_refresh_token": SecretStr("test-refresh-token"),
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def mock_oauth_settings() -> Settings:
    """Provide test settings with OAuth 2.0 credentials."""
    return _settings()


@pytest.fixture
def profile_settings() -> Settings:
    """Shared OAuth app, two authorised accounts, one with its own client."""
    return _settings(
        gsc_accounts={
            "acme": {"refresh_token": "rt-acme"},
            "globex": {
                "refresh_token": "rt-globex",
                "client_id": "globex-id",
                "client_secret": "globex-secret",
            },
        }
    )


def _token_response(token: str = "ya29.test-token-123", expires_in: int = 3600) -> Mock:  # noqa: S107 - fake
    response = Mock()
    response.json.return_value = {"access_token": token, "expires_in": expires_in}
    return response


def _http_error(status: int, body: object) -> requests.HTTPError:
    response = Mock()
    response.status_code = status
    response.json.return_value = body
    return requests.HTTPError(response=response)


class TestGscTokenManagerInitialization:
    """Test token manager initialization."""

    def test_init_with_valid_oauth_credentials(self, mock_oauth_settings):
        """Token manager initializes with valid OAuth credentials."""
        manager = GscTokenManager(settings=mock_oauth_settings)
        assert manager is not None

    def test_init_without_client_id(self):
        """ConfigurationError if client ID is missing."""
        with pytest.raises(ConfigurationError, match="credentials not configured"):
            GscTokenManager(settings=_settings(google_oauth_client_id=None))

    def test_init_without_client_secret(self):
        """ConfigurationError if client secret is missing."""
        with pytest.raises(ConfigurationError, match="credentials not configured"):
            GscTokenManager(settings=_settings(google_oauth_client_secret=None))

    def test_init_without_refresh_token(self):
        """ConfigurationError if refresh token is missing."""
        with pytest.raises(ConfigurationError, match="credentials not configured"):
            GscTokenManager(settings=_settings(google_oauth_refresh_token=None))


class TestNamedAccounts:
    """Selecting a profile by name."""

    def test_named_account_posts_its_own_refresh_token(self, profile_settings):
        """The refresh POST carries the profile's token, and the shared client."""
        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.return_value = _token_response()
            GscTokenManager(settings=profile_settings, account="acme").get_or_refresh_token()

        sent = mock_post.call_args.kwargs["data"]
        assert sent["refresh_token"] == "rt-acme"  # noqa: S105
        assert sent["client_id"] == "test-client-id"
        assert sent["client_secret"] == "test-client-secret"  # noqa: S105

    def test_named_account_client_override(self, profile_settings):
        """A profile with its own OAuth app does not use the shared one."""
        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.return_value = _token_response()
            GscTokenManager(settings=profile_settings, account="globex").get_or_refresh_token()

        sent = mock_post.call_args.kwargs["data"]
        assert sent["refresh_token"] == "rt-globex"  # noqa: S105
        assert sent["client_id"] == "globex-id"
        assert sent["client_secret"] == "globex-secret"  # noqa: S105

    def test_no_account_keeps_default_behaviour(self, profile_settings):
        """Profiles being configured does not change what `None` selects."""
        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.return_value = _token_response()
            GscTokenManager(settings=profile_settings).get_or_refresh_token()

        assert mock_post.call_args.kwargs["data"]["refresh_token"] == "test-refresh-token"  # noqa: S105

    def test_unknown_account_raises_configuration_error(self, profile_settings):
        """Unknown name fails at construction; never falls back to the default."""
        with (
            pytest.raises(ConfigurationError, match="Unknown GSC account 'nobody'"),
            patch("src.integrations.gsc_token_manager.requests.post") as mock_post,
        ):
            GscTokenManager(settings=profile_settings, account="nobody")
        mock_post.assert_not_called()

    def test_account_email_names_the_profile_only(self, profile_settings):
        """Audit identity for a named account is the name, never the client id (F5)."""
        manager = GscTokenManager(settings=profile_settings, account="globex")
        assert manager.get_account_email() == "oauth2://profile/globex"
        assert "globex-id" not in manager.get_account_email()


class TestTokenRetrieval:
    """Test getting and refreshing tokens."""

    def test_get_token_first_call_requires_refresh(self, mock_oauth_settings):
        """First call to get_or_refresh_token triggers a refresh."""
        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.return_value = _token_response()
            manager = GscTokenManager(settings=mock_oauth_settings)

            token = manager.get_or_refresh_token()
            assert token == "ya29.test-token-123"  # noqa: S105
            mock_post.assert_called_once()

    def test_reuse_valid_token_without_refresh(self, mock_oauth_settings):
        """Valid token is reused without refreshing."""
        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.return_value = _token_response()
            manager = GscTokenManager(settings=mock_oauth_settings)

            token1 = manager.get_or_refresh_token()
            assert mock_post.call_count == 1

            token2 = manager.get_or_refresh_token()
            assert token1 == token2
            assert mock_post.call_count == 1

    def test_proactive_refresh_when_expiring_soon(self, mock_oauth_settings):
        """Token is refreshed if it expires within 5 minutes."""
        responses = [
            _token_response("token-1", expires_in=100),
            _token_response("token-2", expires_in=3600),
        ]

        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.side_effect = responses
            manager = GscTokenManager(settings=mock_oauth_settings)

            assert manager.get_or_refresh_token() == "token-1"  # noqa: S105
            assert mock_post.call_count == 1

            assert manager.get_or_refresh_token() == "token-2"  # noqa: S105
            assert mock_post.call_count == 2

    def test_refresh_failure_raises_authentication_error(self, mock_oauth_settings):
        """Refresh failure raises GscAuthenticationError."""
        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.side_effect = Exception("Network error")
            manager = GscTokenManager(settings=mock_oauth_settings)

            with pytest.raises(GscAuthenticationError, match="Token refresh failed"):
                manager.get_or_refresh_token()

    def test_transport_error_text_is_not_repeated(self, mock_oauth_settings):
        """A transport error can quote the request, which carries the refresh token."""
        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.side_effect = requests.ConnectionError(
                "POST ... refresh_token=test-refresh-token"
            )
            manager = GscTokenManager(settings=mock_oauth_settings)

            with pytest.raises(GscAuthenticationError) as info:
                manager.get_or_refresh_token()
        assert "test-refresh-token" not in str(info.value)
        assert "ConnectionError" in str(info.value)

    def test_invalid_grant_names_the_code_and_nothing_else(self, mock_oauth_settings):
        """A revoked token surfaces `invalid_grant`; the body's prose never does."""
        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.return_value.raise_for_status.side_effect = _http_error(
                400, {"error": "invalid_grant", "error_description": "Token has been revoked"}
            )
            manager = GscTokenManager(settings=mock_oauth_settings)

            with pytest.raises(GscAuthenticationError, match=r"HTTP 400, invalid_grant"):
                manager.get_or_refresh_token()
            assert mock_post.call_count == 1

    def test_unexpected_error_body_is_not_repeated(self, mock_oauth_settings):
        """An `error` field that is not an OAuth code is treated as untrusted text."""
        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.return_value.raise_for_status.side_effect = _http_error(
                500, {"error": "<html>stack trace with secrets</html>"}
            )
            manager = GscTokenManager(settings=mock_oauth_settings)

            with pytest.raises(GscAuthenticationError) as info:
                manager.get_or_refresh_token()
        assert str(info.value).endswith("(HTTP 500)")
        assert "stack" not in str(info.value)

    def test_refresh_succeeds_but_no_token_returned(self, mock_oauth_settings):
        """GscAuthenticationError if refresh succeeds but returns no token."""
        mock_response = Mock()
        mock_response.json.return_value = {"expires_in": 3600}

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
        manager.validate_scopes()

    def test_get_account_email_returns_oauth_identifier(self, mock_oauth_settings):
        """The legacy default is still identified by client id."""
        manager = GscTokenManager(settings=mock_oauth_settings)
        email = manager.get_account_email()
        assert email == "oauth2://test-client-id"

    def test_get_token_state_masks_the_access_token(self, mock_oauth_settings):
        """The state dump carries the scope, and hides the token (F6)."""
        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.return_value = _token_response()
            manager = GscTokenManager(settings=mock_oauth_settings)
            manager.get_or_refresh_token()

            state = manager.get_token_state()
            assert GSC_READONLY_SCOPE in state.scopes
            assert state.access_token.get_secret_value() == "ya29.test-token-123"  # noqa: S105
            assert "ya29.test-token-123" not in repr(state)
            assert "ya29.test-token-123" not in state.model_dump_json()
