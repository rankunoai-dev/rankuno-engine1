"""Tests for GSC OAuth token manager."""

from typing import cast
from unittest.mock import Mock, patch

import pytest
import requests
from pydantic import SecretStr
from src.core.config import DEFAULT_ORG_ID, Settings
from src.core.errors import ConfigurationError, GscAuthenticationError
from src.core.schemas import GscAccountCredential, OrgConfig
from src.core.state_store import OrgConfigStore
from src.integrations.gsc_token_manager import GSC_READONLY_SCOPE, GscTokenManager


class _OrgStore:
    """The `get()` half of `OrgConfigStore`, which is all resolution reads.

    Present in every settings object these tests build, so that no test reads
    the real `.orgs/org_configs.json`: accounts an operator added on this
    workstation would otherwise leak into the fixture.
    """

    def __init__(self, accounts: dict[str, GscAccountCredential] | None = None) -> None:
        self._accounts = accounts or {}

    def get(self, org_id: str) -> OrgConfig:
        if org_id != DEFAULT_ORG_ID:
            raise KeyError(org_id)
        return OrgConfig(
            org_id=DEFAULT_ORG_ID,
            display_name="Default Organization",
            gsc_accounts=dict(self._accounts),
        )


def _settings(org_accounts: dict[str, str] | None = None, **overrides: object) -> Settings:
    """Real settings, never a Mock.

    The manager resolves credentials through `Settings.resolve_gsc_account`,
    which a spec'd Mock would silently stub.

    Args:
        org_accounts: Accounts to place in the default org's store, as
            name -> refresh token. Empty unless a test asks for them.
        **overrides: Settings fields.
    """
    base = {
        "_env_file": None,
        "google_oauth_client_id": "test-client-id",
        "google_oauth_client_secret": SecretStr("test-client-secret"),
        "google_oauth_refresh_token": SecretStr("test-refresh-token"),
    }
    base.update(overrides)
    settings = Settings(**base)
    stored = {
        name: GscAccountCredential(refresh_token=SecretStr(token))
        for name, token in (org_accounts or {}).items()
    }
    settings._org_config_store = cast(OrgConfigStore, _OrgStore(stored))  # noqa: SLF001 - see above
    return settings


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


class TestOrgStoredAccounts:
    """Accounts an operator added in the UI, held per organization.

    The defect these cover: the store was write-only. A crawl naming an account
    that existed only there could not start, because resolution looked at
    `.env.local` and nowhere else.
    """

    def test_an_org_stored_account_resolves_at_crawl_time(self):
        settings = _settings(org_accounts={"initech": "rt-initech-org"})
        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.return_value = _token_response()
            GscTokenManager(settings=settings, account="initech").get_or_refresh_token()

        sent = mock_post.call_args.kwargs["data"]
        assert sent["refresh_token"] == "rt-initech-org"  # noqa: S105
        assert sent["client_id"] == "test-client-id"

    def test_an_env_only_account_still_resolves(self):
        """Backwards compatibility: the `.env.local` table predates the store."""
        settings = _settings(
            org_accounts={"initech": "rt-initech-org"},
            gsc_accounts={"acme": {"refresh_token": "rt-acme"}},
        )
        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.return_value = _token_response()
            GscTokenManager(settings=settings, account="acme").get_or_refresh_token()

        assert mock_post.call_args.kwargs["data"]["refresh_token"] == "rt-acme"  # noqa: S105

    def test_another_orgs_account_does_not_resolve(self):
        """One organization's refresh token is not another's to spend."""
        settings = _settings(org_accounts={"initech": "rt-initech-org"})
        with pytest.raises(ConfigurationError, match="Unknown GSC account 'initech'"):
            GscTokenManager(settings=settings, account="initech", org_id="team-a")

    def test_the_account_email_is_the_name_for_an_org_account(self):
        """No credential in the audit identity, same rule as an `.env` profile."""
        settings = _settings(org_accounts={"initech": "rt-initech-org"})
        manager = GscTokenManager(settings=settings, account="initech")
        assert manager.get_account_email() == "oauth2://profile/initech"
        assert "rt-initech-org" not in manager.get_account_email()


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


class TestCircuitBreaker:
    """Tests for circuit breaker resilience in token refresh."""

    def test_circuit_breaker_initialized(self, mock_oauth_settings):
        """Token manager initializes with a circuit breaker."""
        manager = GscTokenManager(settings=mock_oauth_settings)
        assert manager._circuit_breaker is not None
        assert not manager._circuit_breaker.is_open()

    def test_circuit_breaker_records_failures(self, mock_oauth_settings):
        """Refresh failures record in circuit breaker."""
        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.side_effect = Exception("Network error")
            manager = GscTokenManager(settings=mock_oauth_settings)

            for _ in range(3):
                try:
                    manager.get_or_refresh_token()
                except GscAuthenticationError:
                    pass

            assert manager._circuit_breaker._failure_count == 3

    def test_circuit_breaker_opens_after_threshold(self, mock_oauth_settings):
        """Circuit breaker opens after failure threshold."""
        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.side_effect = Exception("Endpoint down")
            manager = GscTokenManager(settings=mock_oauth_settings)

            # Trigger failures to open circuit
            for _ in range(5):
                try:
                    manager.get_or_refresh_token()
                except GscAuthenticationError:
                    pass

            assert manager._circuit_breaker.is_open()

    def test_circuit_breaker_uses_stale_token(self, mock_oauth_settings):
        """When circuit is open, uses stale token if not expired."""
        from datetime import UTC, datetime, timedelta

        manager = GscTokenManager(settings=mock_oauth_settings)

        # Manually set a non-expired stale token
        manager._access_token = "stale-valid-token"
        manager._token_expiry = datetime.now(UTC) + timedelta(hours=1)

        # Force circuit breaker open
        for _ in range(5):
            manager._circuit_breaker.record_failure(Exception("endpoint down"))

        # Should return stale token without calling endpoint
        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            token = manager.get_or_refresh_token()
            assert token == "stale-valid-token"
            mock_post.assert_not_called()

    def test_circuit_breaker_fails_with_expired_stale_token(self, mock_oauth_settings):
        """When circuit is open and stale token expired, raises error."""
        from datetime import UTC, datetime, timedelta

        manager = GscTokenManager(settings=mock_oauth_settings)

        # Set an expired stale token
        manager._access_token = "expired-token"
        manager._token_expiry = datetime.now(UTC) - timedelta(seconds=1)

        # Force circuit breaker open
        for _ in range(5):
            manager._circuit_breaker.record_failure(Exception("endpoint down"))

        # Should raise error instead of using expired token
        with pytest.raises(GscAuthenticationError, match="Token endpoint unreachable"):
            manager.get_or_refresh_token()

    def test_circuit_breaker_recovers_after_success(self, mock_oauth_settings):
        """Circuit breaker closes after successful refresh."""
        with patch("src.integrations.gsc_token_manager.requests.post") as mock_post:
            mock_post.return_value = _token_response()
            manager = GscTokenManager(settings=mock_oauth_settings)

            # Open the circuit
            for _ in range(5):
                manager._circuit_breaker.record_failure(Exception("test"))

            assert manager._circuit_breaker.is_open()

            # Successful refresh should close it
            manager.get_or_refresh_token()
            assert not manager._circuit_breaker.is_open()
