"""Tests for GSC API client."""

from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest
from src.core.config import Settings
from src.integrations.gsc_client import GscApiClient
from src.integrations.gsc_schemas import GscAnalyticsResponse


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
    settings.default_timeout_s = 30.0
    settings.default_requests_per_minute = 60
    settings.default_max_retries = 3
    return settings


@pytest.fixture
def mock_token_manager():
    """Provide a mock token manager."""
    manager = Mock()
    manager.get_or_refresh_token.return_value = "ya29.test-token"
    manager.validate_scopes.return_value = None  # No exception = validation passed
    manager.get_account_email.return_value = "test@example.iam.gserviceaccount.com"
    return manager


class TestGscClientInitialization:
    """Test GSC client initialization."""

    def test_init_success(self, mock_settings):
        """Client initializes and authenticates successfully."""
        with patch("src.integrations.gsc_client.GscTokenManager") as mock_tm_class:
            mock_tm = Mock()
            mock_tm_class.return_value = mock_tm
            mock_tm.validate_scopes.return_value = None

            client = GscApiClient(settings=mock_settings)

            assert client.service_name == "google.search_console"
            assert client.rate_limit_key == "gsc_quota"
            assert client.requests_per_minute == 60

    def test_init_validates_scopes(self, mock_settings):
        """Initialization calls scope validation."""
        with patch("src.integrations.gsc_client.GscTokenManager") as mock_tm_class:
            mock_tm = Mock()
            mock_tm_class.return_value = mock_tm
            mock_tm.validate_scopes.return_value = None

            GscApiClient(settings=mock_settings)

            mock_tm.validate_scopes.assert_called_once()


class TestListProperties:
    """Test listing accessible GSC properties."""

    def test_list_properties_success(self, mock_settings, mock_token_manager):
        """Successfully list GSC properties."""
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch(  # noqa: SIM117
                "src.integrations.gsc_client.build"
            ) as mock_build,
        ):
            mock_service = Mock()
            mock_build.return_value = mock_service

            mock_sites = Mock()
            mock_service.sites.return_value = mock_sites
            mock_request = Mock()
            mock_sites.list.return_value = mock_request

            # Mock API response
            mock_request.execute.return_value = {
                "siteEntry": [
                    {
                        "siteUrl": "https://example.com/",
                        "permissionLevel": "siteOwner",
                    },
                    {
                        "siteUrl": "https://blog.example.com/",
                        "permissionLevel": "siteOwner",
                    },
                ]
            }

            client = GscApiClient(settings=mock_settings)
            properties = client.list_accessible_properties()

            assert len(properties) == 2
            assert properties[0].url == "https://example.com/"
            assert properties[1].url == "https://blog.example.com/"

    def test_list_properties_empty(self, mock_settings, mock_token_manager):
        """List properties returns empty list when no properties exist."""
        with patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager):  # noqa: SIM117
            with patch("src.integrations.gsc_client.build") as mock_build:
                mock_service = Mock()
                mock_build.return_value = mock_service
                mock_sites = Mock()
                mock_service.sites.return_value = mock_sites
                mock_request = Mock()
                mock_sites.list.return_value = mock_request
                mock_request.execute.return_value = {"siteEntry": []}

                client = GscApiClient(settings=mock_settings)
                properties = client.list_accessible_properties()

                assert properties == []

    def test_list_properties_error_returns_empty(self, mock_settings, mock_token_manager):
        """List properties returns empty list on error (graceful degradation)."""
        with patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager):  # noqa: SIM117
            with patch("src.integrations.gsc_client.build") as mock_build:
                mock_service = Mock()
                mock_build.return_value = mock_service
                mock_sites = Mock()
                mock_service.sites.return_value = mock_sites
                mock_request = Mock()
                mock_sites.list.return_value = mock_request
                mock_request.execute.side_effect = Exception("Network error")

                client = GscApiClient(settings=mock_settings)
                properties = client.list_accessible_properties()

                # Error handling: return empty list instead of raising
                assert properties == []


class TestFetchAnalytics:
    """Test fetching GSC analytics.

    Note: HttpError handling and retry logic are tested in BaseAPIClient tests.
    These tests focus on the GscApiClient's mapping and data transformation.
    """

    def test_fetch_analytics_success(self, mock_settings, mock_token_manager):
        """Successfully fetch analytics for a property."""
        with patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager):  # noqa: SIM117
            with patch("src.integrations.gsc_client.build") as mock_build:
                with patch("src.integrations.gsc_client.datetime") as mock_datetime:
                    now = datetime.now(UTC)
                    mock_datetime.now.return_value = now
                    mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

                    mock_service = Mock()
                    mock_build.return_value = mock_service
                    mock_analytics = Mock()
                    mock_service.searchanalytics.return_value = mock_analytics
                    mock_request = Mock()
                    mock_analytics.query.return_value = mock_request

                    # Mock API response
                    mock_request.execute.return_value = {
                        "rows": [
                            {
                                "keys": ["https://example.com/"],
                                "clicks": 10,
                                "impressions": 100,
                                "position": 5.2,
                            },
                            {
                                "keys": ["https://example.com/about"],
                                "clicks": 5,
                                "impressions": 50,
                                "position": 8.1,
                            },
                        ]
                    }

                    client = GscApiClient(settings=mock_settings)
                    response = client.fetch_analytics(
                        "https://example.com",
                        "2026-08-01",
                        "2026-08-31",
                    )

                    assert isinstance(response, GscAnalyticsResponse)
                    assert len(response.rows) == 2
                    assert response.rows[0].url == "https://example.com/"
                    assert response.rows[0].clicks == 10
                    assert response.rows[0].impressions == 100
                    assert response.rows[0].avg_position == 5.2
                    assert abs(response.rows[0].ctr - 0.1) < 0.001

    def test_fetch_analytics_empty(self, mock_settings, mock_token_manager):
        """Fetch analytics returns empty rows when no data."""
        with patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager):  # noqa: SIM117
            with patch("src.integrations.gsc_client.build") as mock_build:
                mock_service = Mock()
                mock_build.return_value = mock_service
                mock_analytics = Mock()
                mock_service.searchanalytics.return_value = mock_analytics
                mock_request = Mock()
                mock_analytics.query.return_value = mock_request
                mock_request.execute.return_value = {"rows": []}

                client = GscApiClient(settings=mock_settings)
                response = client.fetch_analytics(
                    "https://example.com",
                    "2026-08-01",
                    "2026-08-31",
                )

                assert len(response.rows) == 0

    def test_fetch_analytics_ctr_calculation(self, mock_settings, mock_token_manager):
        """CTR is calculated correctly and clamped to [0, 1]."""
        with patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager):  # noqa: SIM117
            with patch("src.integrations.gsc_client.build") as mock_build:
                mock_service = Mock()
                mock_build.return_value = mock_service
                mock_analytics = Mock()
                mock_service.searchanalytics.return_value = mock_analytics
                mock_request = Mock()
                mock_analytics.query.return_value = mock_request

                # Test various CTR scenarios
                mock_request.execute.return_value = {
                    "rows": [
                        {
                            "keys": ["https://example.com/high-ctr"],
                            "clicks": 50,
                            "impressions": 100,
                            "position": 1.0,
                        },
                        {
                            "keys": ["https://example.com/zero-ctr"],
                            "clicks": 0,
                            "impressions": 100,
                            "position": 10.0,
                        },
                    ]
                }

                client = GscApiClient(settings=mock_settings)
                response = client.fetch_analytics(
                    "https://example.com",
                    "2026-08-01",
                    "2026-08-31",
                )

                # 50/100 = 0.5
                assert abs(response.rows[0].ctr - 0.5) < 0.001
                # 0/100 = 0.0
                assert response.rows[1].ctr == 0.0

    def test_fetch_analytics_property_url_trailing_slash(self, mock_settings, mock_token_manager):
        """Property URL is normalized to include trailing slash."""
        with patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager):  # noqa: SIM117
            with patch("src.integrations.gsc_client.build") as mock_build:
                mock_service = Mock()
                mock_build.return_value = mock_service
                mock_analytics = Mock()
                mock_service.searchanalytics.return_value = mock_analytics
                mock_request = Mock()
                mock_analytics.query.return_value = mock_request
                mock_request.execute.return_value = {"rows": []}

                client = GscApiClient(settings=mock_settings)

                # Call without trailing slash
                client.fetch_analytics(
                    "https://example.com",
                    "2026-08-01",
                    "2026-08-31",
                )

                # Verify API was called with trailing slash
                call_args = mock_analytics.query.call_args
                assert call_args[1]["siteUrl"] == "https://example.com/"

    def test_fetch_analytics_graceful_degradation_on_error(self, mock_settings, mock_token_manager):
        """Unexpected errors return empty response (graceful degradation)."""
        with patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager):  # noqa: SIM117
            with patch("src.integrations.gsc_client.build") as mock_build:
                mock_service = Mock()
                mock_build.return_value = mock_service
                mock_analytics = Mock()
                mock_service.searchanalytics.return_value = mock_analytics
                mock_request = Mock()
                mock_analytics.query.return_value = mock_request
                mock_request.execute.side_effect = RuntimeError("Unexpected error")

                client = GscApiClient(settings=mock_settings)
                response = client.fetch_analytics(
                    "https://example.com",
                    "2026-08-01",
                    "2026-08-31",
                )

                # Should return empty response, not raise
                assert isinstance(response, GscAnalyticsResponse)
                assert len(response.rows) == 0


class TestNamedAccountSelection:
    """The client hands the profile name to the token manager and nothing else."""

    def test_init_forwards_account_to_token_manager(self, mock_settings, mock_token_manager):
        with patch(
            "src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager
        ) as tm_class:
            GscApiClient(settings=mock_settings, account="acme")
        tm_class.assert_called_once_with(settings=mock_settings, account="acme")

    def test_init_default_account_is_none(self, mock_settings, mock_token_manager):
        with patch(
            "src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager
        ) as tm_class:
            GscApiClient(settings=mock_settings)
        tm_class.assert_called_once_with(settings=mock_settings, account=None)


class TestAuthenticationIsNotRetried:
    """Regression for audit finding F2.

    `GscAuthenticationError` subclasses `IntegrationError`, which the retry
    policy treats as transient. With the refresh inside `call()`, a revoked
    refresh token POSTed `invalid_grant` once per attempt.
    """

    @pytest.fixture
    def real_settings(self):
        from pydantic import SecretStr
        from src.core.config import Settings

        return Settings(
            _env_file=None,
            google_oauth_client_id="cid",
            google_oauth_client_secret=SecretStr("sec"),
            google_oauth_refresh_token=SecretStr("revoked"),
        )

    @staticmethod
    def _invalid_grant() -> Exception:
        import requests

        response = Mock()
        response.status_code = 400
        response.json.return_value = {"error": "invalid_grant"}
        return requests.HTTPError(response=response)

    def test_fetch_analytics_posts_token_endpoint_once(self, real_settings):
        from src.core.errors import GscAuthenticationError

        with (
            patch("src.integrations.gsc_token_manager.requests.post") as mock_post,
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            mock_post.return_value.raise_for_status.side_effect = self._invalid_grant()
            client = GscApiClient(settings=real_settings)
            with pytest.raises(GscAuthenticationError, match="invalid_grant"):
                client.fetch_analytics("https://example.com", "2026-08-01", "2026-08-31")

        assert mock_post.call_count == 1
        mock_build.assert_not_called()

    def test_list_properties_posts_token_endpoint_once(self, real_settings):
        from src.core.errors import GscAuthenticationError

        with (
            patch("src.integrations.gsc_token_manager.requests.post") as mock_post,
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            mock_post.return_value.raise_for_status.side_effect = self._invalid_grant()
            client = GscApiClient(settings=real_settings)
            with pytest.raises(GscAuthenticationError, match="invalid_grant"):
                client.list_accessible_properties()

        assert mock_post.call_count == 1
        mock_build.assert_not_called()
