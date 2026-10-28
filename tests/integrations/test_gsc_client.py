"""Tests for GSC API client."""

from collections.abc import Callable
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
    """The client hands the profile name and its org to the token manager.

    The org decides *whose* stored accounts the name may match, so forwarding it
    is not cosmetic: dropping it would resolve every crawl against the default
    organization's accounts.
    """

    def test_init_forwards_account_to_token_manager(self, mock_settings, mock_token_manager):
        with patch(
            "src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager
        ) as tm_class:
            GscApiClient(settings=mock_settings, account="acme")
        tm_class.assert_called_once_with(settings=mock_settings, account="acme", org_id=None)

    def test_init_default_account_is_none(self, mock_settings, mock_token_manager):
        with patch(
            "src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager
        ) as tm_class:
            GscApiClient(settings=mock_settings)
        tm_class.assert_called_once_with(settings=mock_settings, account=None, org_id=None)

    def test_init_forwards_the_org(self, mock_settings, mock_token_manager):
        with patch(
            "src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager
        ) as tm_class:
            GscApiClient(settings=mock_settings, account="acme", org_id="team-a")
        tm_class.assert_called_once_with(settings=mock_settings, account="acme", org_id="team-a")


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


class TestRefusalsPropagate:
    """A 403 or 404 is raised, not turned into an empty response.

    An empty response is indistinguishable from "this property has no search
    data", so the crawl reported success with 0 matched pages. The caller
    (`PageClassificationTool._enrich_with_gsc`) owns graceful degradation and
    reports the refusal as a failed step.
    """

    @pytest.fixture(autouse=True)
    def _no_backoff(self, monkeypatch) -> None:
        monkeypatch.setattr("tenacity.nap.time.sleep", lambda _seconds: None)

    @staticmethod
    def _http_error(status: int) -> Exception:
        import httplib2
        from googleapiclient.errors import HttpError

        return HttpError(httplib2.Response({"status": str(status)}), b"{}")

    def _fetch_raising(self, mock_settings, mock_token_manager, status: int) -> None:
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            query = mock_build.return_value.searchanalytics.return_value.query
            query.return_value.execute.side_effect = self._http_error(status)
            client = GscApiClient(settings=mock_settings)
            client.fetch_analytics("https://example.com", "2026-08-01", "2026-08-31")

    def test_a_403_raises_authorization_error(self, mock_settings, mock_token_manager):
        from src.core.errors import GscAuthorizationError

        with pytest.raises(GscAuthorizationError):
            self._fetch_raising(mock_settings, mock_token_manager, 403)

    def test_a_404_raises_property_not_found(self, mock_settings, mock_token_manager):
        from src.core.errors import GscPropertyNotFoundError

        with pytest.raises(GscPropertyNotFoundError):
            self._fetch_raising(mock_settings, mock_token_manager, 404)


class TestDomainProperty:
    """`sc-domain:` properties are sent exactly as Search Console lists them."""

    def test_sc_domain_property_is_sent_without_a_trailing_slash(
        self, mock_settings, mock_token_manager
    ):
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            analytics = mock_build.return_value.searchanalytics.return_value
            analytics.query.return_value.execute.return_value = {"rows": []}
            client = GscApiClient(settings=mock_settings)
            response = client.fetch_analytics("sc-domain:example.com", "2026-08-01", "2026-08-31")

        assert analytics.query.call_args[1]["siteUrl"] == "sc-domain:example.com"
        assert response.property_url == "sc-domain:example.com"

    def test_a_typed_trailing_slash_is_dropped_from_a_domain_property(
        self, mock_settings, mock_token_manager
    ):
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            analytics = mock_build.return_value.searchanalytics.return_value
            analytics.query.return_value.execute.return_value = {"rows": []}
            client = GscApiClient(settings=mock_settings)
            client.fetch_analytics("sc-domain:example.com/", "2026-08-01", "2026-08-31")

        assert analytics.query.call_args[1]["siteUrl"] == "sc-domain:example.com"

    def test_a_domain_property_is_recognised_whatever_its_case(
        self, mock_settings, mock_token_manager
    ):
        # The form and the validator accept `SC-DOMAIN:` case-insensitively, so the
        # client must too, or it would append "/" and name no property at all.
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            analytics = mock_build.return_value.searchanalytics.return_value
            analytics.query.return_value.execute.return_value = {"rows": []}
            client = GscApiClient(settings=mock_settings)
            client.fetch_analytics("SC-Domain:Example.com/", "2026-08-01", "2026-08-31")

        assert analytics.query.call_args[1]["siteUrl"] == "sc-domain:example.com"


def _serve(rows: list[dict[str, object]]) -> tuple[Callable[..., Mock], list[dict[str, object]]]:
    """A fake `searchanalytics.query` that pages a fixed dataset the way Search Console does.

    Each request returns the slice starting at its `startRow`, of its `rowLimit`
    length, so the cursor arithmetic under test is checked against real offsets
    rather than against a canned sequence of responses.
    """
    calls: list[dict[str, object]] = []

    def query(siteUrl: str, body: dict[str, object]) -> Mock:  # noqa: ARG001
        calls.append(body)
        start = body["startRow"]
        limit = body["rowLimit"]
        assert isinstance(start, int)
        assert isinstance(limit, int)
        request = Mock()
        request.execute.return_value = {"rows": rows[start : start + limit]}
        return request

    return query, calls


def _page_row(i: int) -> dict[str, object]:
    return {
        "keys": [f"https://example.com/p{i}"],
        "clicks": 1,
        "impressions": 10,
        "position": 3.0,
    }


def _query_row(i: int, query: str = "widgets") -> dict[str, object]:
    return {
        "keys": [f"https://example.com/p{i}", query],
        "clicks": 2,
        "impressions": 20,
        "position": 4.0,
    }


@pytest.fixture
def no_backoff(monkeypatch) -> None:
    """Retries sleep for real otherwise; a failing page would take seconds per test."""
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda _seconds: None)


def _http_error(status: int) -> Exception:
    import httplib2
    from googleapiclient.errors import HttpError

    return HttpError(httplib2.Response({"status": str(status)}), b"{}")


class TestPagedPageAnalytics:
    """`fetch_analytics` reads every page, not just the first 10,000 rows."""

    def test_pages_through_until_a_short_page(self, mock_settings, mock_token_manager):
        query, calls = _serve([_page_row(i) for i in range(25)])
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            mock_build.return_value.searchanalytics.return_value.query.side_effect = query
            client = GscApiClient(settings=mock_settings)
            response = client.fetch_analytics(
                "https://example.com", "2026-08-01", "2026-08-31", row_limit=10
            )

        assert [body["startRow"] for body in calls] == [0, 10, 20]
        assert len(response.rows) == 25
        assert response.complete is True
        assert response.stop_reason == "exhausted"

    def test_a_full_last_page_costs_one_more_request_to_prove_the_end(
        self, mock_settings, mock_token_manager
    ):
        query, calls = _serve([_page_row(i) for i in range(20)])
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            mock_build.return_value.searchanalytics.return_value.query.side_effect = query
            client = GscApiClient(settings=mock_settings)
            response = client.fetch_analytics(
                "https://example.com", "2026-08-01", "2026-08-31", row_limit=10
            )

        assert len(calls) == 3
        assert len(response.rows) == 20
        assert response.complete is True

    def test_stops_at_the_page_cap_and_says_so(self, mock_settings, mock_token_manager):
        from src.integrations.gsc_requests import MAX_PAGES

        query, calls = _serve([_page_row(i) for i in range(MAX_PAGES * 10 + 50)])
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            mock_build.return_value.searchanalytics.return_value.query.side_effect = query
            client = GscApiClient(settings=mock_settings)
            response = client.fetch_analytics(
                "https://example.com", "2026-08-01", "2026-08-31", row_limit=10
            )

        assert len(calls) == MAX_PAGES
        assert len(response.rows) == MAX_PAGES * 10
        assert response.complete is False
        assert response.stop_reason == "row_cap"

    def test_one_call_per_page_so_each_page_takes_a_rate_limit_slot(
        self, mock_settings, mock_token_manager
    ):
        query, _calls = _serve([_page_row(i) for i in range(25)])
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            mock_build.return_value.searchanalytics.return_value.query.side_effect = query
            client = GscApiClient(settings=mock_settings)
            with patch.object(
                GscApiClient, "call", autospec=True, side_effect=GscApiClient.call
            ) as spy:
                client.fetch_analytics(
                    "https://example.com", "2026-08-01", "2026-08-31", row_limit=10
                )

        assert spy.call_count == 3

    def test_token_is_fetched_once_not_per_page(self, mock_settings, mock_token_manager):
        query, _calls = _serve([_page_row(i) for i in range(25)])
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            mock_build.return_value.searchanalytics.return_value.query.side_effect = query
            client = GscApiClient(settings=mock_settings)
            client.fetch_analytics("https://example.com", "2026-08-01", "2026-08-31", row_limit=10)

        assert mock_token_manager.get_or_refresh_token.call_count == 1

    def test_a_failed_later_page_keeps_the_rows_before_it(
        self, mock_settings, mock_token_manager, no_backoff
    ):
        good, _calls = _serve([_page_row(i) for i in range(10)])

        def query(siteUrl: str, body: dict[str, object]) -> Mock:  # noqa: ARG001
            request = Mock()
            if body["startRow"] == 0:
                request.execute.return_value = good(siteUrl, body).execute.return_value
            else:
                request.execute.side_effect = RuntimeError("connection reset")
            return request

        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            mock_build.return_value.searchanalytics.return_value.query.side_effect = query
            client = GscApiClient(settings=mock_settings)
            response = client.fetch_analytics(
                "https://example.com", "2026-08-01", "2026-08-31", row_limit=10
            )

        assert len(response.rows) == 10
        assert response.complete is False
        assert response.stop_reason == "fetch_failed"

    def test_a_first_page_failure_is_an_empty_incomplete_response(
        self, mock_settings, mock_token_manager, no_backoff
    ):
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            request = mock_build.return_value.searchanalytics.return_value.query.return_value
            request.execute.side_effect = RuntimeError("down")
            client = GscApiClient(settings=mock_settings)
            response = client.fetch_analytics("https://example.com", "2026-08-01", "2026-08-31")

        assert response.rows == []
        assert response.complete is False
        assert response.stop_reason == "fetch_failed"

    def test_a_403_on_a_later_page_still_propagates(
        self, mock_settings, mock_token_manager, no_backoff
    ):
        from src.core.errors import GscAuthorizationError

        good, _calls = _serve([_page_row(i) for i in range(10)])

        def query(siteUrl: str, body: dict[str, object]) -> Mock:  # noqa: ARG001
            request = Mock()
            if body["startRow"] == 0:
                request.execute.return_value = good(siteUrl, body).execute.return_value
            else:
                request.execute.side_effect = _http_error(403)
            return request

        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            mock_build.return_value.searchanalytics.return_value.query.side_effect = query
            client = GscApiClient(settings=mock_settings)
            with pytest.raises(GscAuthorizationError):
                client.fetch_analytics(
                    "https://example.com", "2026-08-01", "2026-08-31", row_limit=10
                )

    @pytest.mark.parametrize("row_limit", [0, -1, 25001])
    def test_a_row_limit_outside_gsc_bounds_is_refused_before_any_request(
        self, mock_settings, mock_token_manager, row_limit
    ):
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            client = GscApiClient(settings=mock_settings)
            with pytest.raises(ValueError, match="row_limit"):
                client.fetch_analytics(
                    "https://example.com", "2026-08-01", "2026-08-31", row_limit=row_limit
                )

        mock_token_manager.get_or_refresh_token.assert_not_called()
        mock_build.assert_not_called()


class TestFetchTopQueries:
    """`fetch_top_queries` reads every (page, query) row, one page at a time."""

    def test_requests_both_dimensions_at_the_maximum_page_size(
        self, mock_settings, mock_token_manager
    ):
        query, calls = _serve([_query_row(0)])
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            mock_build.return_value.searchanalytics.return_value.query.side_effect = query
            client = GscApiClient(settings=mock_settings)
            client.fetch_top_queries("https://example.com", "2026-08-01", "2026-08-31")

        assert calls == [
            {
                "startDate": "2026-08-01",
                "endDate": "2026-08-31",
                "dimensions": ["page", "query"],
                "rowLimit": 25000,
                "startRow": 0,
            }
        ]

    def test_advances_the_cursor_by_rows_received_across_pages(
        self, mock_settings, mock_token_manager
    ):
        query, calls = _serve([_query_row(i) for i in range(7)])
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            mock_build.return_value.searchanalytics.return_value.query.side_effect = query
            client = GscApiClient(settings=mock_settings)
            result = client.fetch_top_queries(
                "https://example.com", "2026-08-01", "2026-08-31", row_limit=3
            )

        assert [body["startRow"] for body in calls] == [0, 3, 6]
        assert len(result.rows) == 7
        assert result.complete is True
        assert result.stop_reason == "exhausted"

    def test_row_cap_is_reported_as_incomplete(self, mock_settings, mock_token_manager):
        from src.integrations.gsc_requests import MAX_PAGES

        query, calls = _serve([_query_row(i) for i in range(MAX_PAGES + 10)])
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            mock_build.return_value.searchanalytics.return_value.query.side_effect = query
            client = GscApiClient(settings=mock_settings)
            result = client.fetch_top_queries(
                "https://example.com", "2026-08-01", "2026-08-31", row_limit=1
            )

        assert len(calls) == MAX_PAGES
        assert len(result.rows) == MAX_PAGES
        assert result.complete is False
        assert result.stop_reason == "row_cap"

    def test_one_call_per_page_and_the_token_fetched_once(self, mock_settings, mock_token_manager):
        query, _calls = _serve([_query_row(i) for i in range(5)])
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            mock_build.return_value.searchanalytics.return_value.query.side_effect = query
            client = GscApiClient(settings=mock_settings)
            with patch.object(
                GscApiClient, "call", autospec=True, side_effect=GscApiClient.call
            ) as spy:
                client.fetch_top_queries(
                    "https://example.com", "2026-08-01", "2026-08-31", row_limit=2
                )

        assert spy.call_count == 3
        assert mock_token_manager.get_or_refresh_token.call_count == 1

    def test_a_mid_paging_failure_keeps_the_rows_received(
        self, mock_settings, mock_token_manager, no_backoff
    ):
        good, _calls = _serve([_query_row(i) for i in range(4)])

        def query(siteUrl: str, body: dict[str, object]) -> Mock:  # noqa: ARG001
            request = Mock()
            if body["startRow"] == 0:
                request.execute.return_value = good(siteUrl, body).execute.return_value
            else:
                request.execute.side_effect = RuntimeError("timeout")
            return request

        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            mock_build.return_value.searchanalytics.return_value.query.side_effect = query
            client = GscApiClient(settings=mock_settings)
            result = client.fetch_top_queries(
                "https://example.com", "2026-08-01", "2026-08-31", row_limit=2
            )

        assert len(result.rows) == 2
        assert result.complete is False
        assert result.stop_reason == "fetch_failed"

    def test_a_row_without_both_keys_is_skipped(self, mock_settings, mock_token_manager):
        rows: list[dict[str, object]] = [
            {"keys": ["https://example.com/p1"], "clicks": 1, "impressions": 1, "position": 1.0},
            _query_row(2),
        ]
        query, _calls = _serve(rows)
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            mock_build.return_value.searchanalytics.return_value.query.side_effect = query
            client = GscApiClient(settings=mock_settings)
            result = client.fetch_top_queries("https://example.com", "2026-08-01", "2026-08-31")

        assert [row.page for row in result.rows] == ["https://example.com/p2"]

    @pytest.mark.parametrize("row_limit", [0, 25001])
    def test_a_row_limit_outside_1_to_25000_raises_value_error(
        self, mock_settings, mock_token_manager, row_limit
    ):
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            client = GscApiClient(settings=mock_settings)
            with pytest.raises(ValueError, match="between 1 and 25000"):
                client.fetch_top_queries(
                    "https://example.com", "2026-08-01", "2026-08-31", row_limit=row_limit
                )

        mock_token_manager.get_or_refresh_token.assert_not_called()
        mock_build.assert_not_called()

    def test_a_403_raises_authorization_error(self, mock_settings, mock_token_manager, no_backoff):
        from src.core.errors import GscAuthorizationError

        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            request = mock_build.return_value.searchanalytics.return_value.query.return_value
            request.execute.side_effect = _http_error(403)
            client = GscApiClient(settings=mock_settings)
            with pytest.raises(GscAuthorizationError):
                client.fetch_top_queries("https://example.com", "2026-08-01", "2026-08-31")


class TestFailedPageClass:
    """A failed fetch says what kind of failure it was, and never what the message said.

    The message can quote the property and the search phrase, so the result carries
    a closed class label and nothing else from the exception.
    """

    SECRET = "private search phrase for example.com"

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (TimeoutError(SECRET), "timeout"),
            (ConnectionResetError(SECRET), "connection"),
            (_http_error(503), "server_error"),
            (_http_error(429), "quota"),
            (RuntimeError(SECRET), "unexpected"),
        ],
    )
    def test_the_class_is_recorded_and_the_message_is_not(
        self, mock_settings, mock_token_manager, no_backoff, error, expected
    ):
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            request = mock_build.return_value.searchanalytics.return_value.query.return_value
            request.execute.side_effect = error
            client = GscApiClient(settings=mock_settings)
            result = client.fetch_top_queries("https://example.com", "2026-08-01", "2026-08-31")

        assert result.stop_reason == "fetch_failed"
        assert result.rows == []
        assert result.failure_class == expected
        assert self.SECRET not in result.model_dump_json()

    def test_a_successful_fetch_has_no_failure_class(self, mock_settings, mock_token_manager):
        with (
            patch("src.integrations.gsc_client.GscTokenManager", return_value=mock_token_manager),
            patch("src.integrations.gsc_client.build") as mock_build,
        ):
            request = mock_build.return_value.searchanalytics.return_value.query.return_value
            request.execute.return_value = {"rows": []}
            client = GscApiClient(settings=mock_settings)
            result = client.fetch_top_queries("https://example.com", "2026-08-01", "2026-08-31")

        assert result.stop_reason == "exhausted"
        assert result.failure_class is None
